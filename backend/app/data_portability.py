import csv
import hashlib
import io
import json
import shutil
import sqlite3
import uuid
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from .config import settings
from .database import Base, engine
from . import models  # Register the complete schema even in standalone backup tests.
from sqlalchemy import create_engine

BACKUP_VERSION = 2
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_BACKUP_MEMBERS = 20000
ALLOWED_BACKUP_ROOTS = {"app.db", "avatars", "attachments", "config.json", "metadata.json"}


def json_export(students: list[dict], events: list[dict]) -> bytes:
    payload = {
        "format": "StudentLog JSON export",
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "students": students,
        "events": events,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def csv_export(events: list[dict]) -> bytes:
    output = io.StringIO()
    fields = ["event_id", "occurred_at", "recorded_at", "student_no", "student_name", "category", "location", "event_description", "student_response", "teacher_action", "follow_up", "tags", "record_method"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for event in events:
        students = event.get("students") or [{"student_no": "", "name": ""}]
        for student in students:
            writer.writerow({
                "event_id": event["id"],
                "occurred_at": event["occurred_at"],
                "recorded_at": event["recorded_at"],
                "student_no": student.get("student_no", ""),
                "student_name": student.get("name", ""),
                "category": event.get("category", ""),
                "location": event.get("location") or "",
                "event_description": event.get("event_description", ""),
                "student_response": event.get("student_response") or "",
                "teacher_action": event.get("teacher_action") or "",
                "follow_up": event.get("follow_up") or "",
                "tags": "|".join(event.get("tags") or []),
                "record_method": event.get("record_method", ""),
            })
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _copy_database(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def create_backup(data_dir: Path | None = None) -> Path:
    root = (data_dir or settings.data_dir).resolve()
    backups = root / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    if not (root / "app.db").is_file():
        raise HTTPException(status_code=409, detail="数据库尚未创建，无法备份")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"studentlog-backup-{stamp}-{uuid.uuid4().hex[:6]}.zip"
    output = backups / filename
    snapshot = backups / f".snapshot-{uuid.uuid4().hex}.db"
    metadata = {"format": "StudentLog backup", "version": BACKUP_VERSION, "created_at": datetime.now().isoformat()}
    try:
        _copy_database(root / "app.db", snapshot)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            checksums = {"app.db": _sha256(snapshot)}
            archive.write(snapshot, "app.db")
            for folder in ("avatars", "attachments"):
                base = root / folder
                if not base.exists():
                    continue
                for path in base.rglob("*"):
                    if path.is_file():
                        name = f"{folder}/{path.relative_to(base).as_posix()}"
                        archive.write(path, name)
                        checksums[name] = _sha256(path)
            config = root / "config.json"
            if config.is_file():
                archive.write(config, "config.json")
                checksums["config.json"] = _sha256(config)
            metadata["checksums"] = checksums
            archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            if len(archive.infolist()) > MAX_BACKUP_MEMBERS or sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise HTTPException(status_code=413, detail="数据超过完整 ZIP 备份上限（2GB / 20,000 个文件），请先导出数据")
        output.chmod(0o600)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    finally:
        snapshot.unlink(missing_ok=True)
    return output


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    seen = set()
    expanded = 0
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        if (path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] not in ALLOWED_BACKUP_ROOTS
                or '\\' in item.filename or ':' in item.filename
                or (path.parts[0] in {'avatars', 'attachments'} and len(path.parts) == 1 and not item.is_dir())
                or (path.parts[0] in {"app.db", "config.json", "metadata.json"} and (len(path.parts) != 1 or item.is_dir()))
                or path.as_posix() in seen or item.flag_bits & 1):
            raise HTTPException(status_code=400, detail="备份包含不安全或不支持的路径")
        seen.add(path.as_posix())
        expanded += item.file_size
        if expanded > MAX_EXPANDED_BYTES or len(seen) > MAX_BACKUP_MEMBERS:
            raise HTTPException(status_code=400, detail="备份展开后超过 2GB 或文件数量过多")
        if (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise HTTPException(status_code=400, detail="备份不能包含符号链接")
        members.append(item)
    file_names = {PurePosixPath(item.filename).as_posix() for item in members if not item.is_dir()}
    for item in members:
        if any(parent.as_posix() in file_names for parent in PurePosixPath(item.filename).parents):
            raise HTTPException(status_code=400, detail="备份中存在文件与目录路径冲突")
    if not {"app.db", "metadata.json"}.issubset({item.filename for item in members}):
        raise HTTPException(status_code=400, detail="备份中缺少 app.db 或 metadata.json")
    return members


def _validate_database(path: Path) -> None:
    try:
        connection = sqlite3.connect(path)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in Base.metadata.sorted_tables:
            if table.name == "attachments" and table.name not in tables:
                continue  # Phase 1/2 backups predate event attachments.
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table.name}")')}
            if not set(table.columns.keys()).issubset(columns):
                raise HTTPException(status_code=400, detail="备份数据库结构与当前版本不兼容")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise HTTPException(status_code=400, detail="备份中的学生或事件关联已损坏")
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=400, detail="备份中的 SQLite 数据库无效") from exc
    finally:
        if "connection" in locals():
            connection.close()
    if integrity != "ok" or not {"students", "events", "admin_users"}.issubset(tables):
        raise HTTPException(status_code=400, detail="备份数据库不完整或已损坏")
    if "attachments" not in tables:
        temporary_engine = create_engine(f"sqlite:///{path.as_posix()}")
        try:
            Base.metadata.tables["attachments"].create(temporary_engine)
        finally:
            temporary_engine.dispose()


def _validate_payload(staging: Path) -> None:
    try:
        metadata = json.loads((staging / "metadata.json").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("format") != "StudentLog backup" or metadata.get("version") not in {1, 2}:
            raise ValueError()
        if metadata["version"] == 2:
            checksums = metadata.get("checksums")
            files = {p.relative_to(staging).as_posix(): p for p in staging.rglob('*') if p.is_file() and p.relative_to(staging).as_posix() != 'metadata.json'}
            if not isinstance(checksums, dict) or set(checksums) != set(files):
                raise ValueError()
            if any(checksums[name] != _sha256(path) for name, path in files.items()):
                raise ValueError()
        config = staging / 'config.json'
        if config.exists():
            values = json.loads(config.read_text(encoding='utf-8'))
            if not isinstance(values, dict):
                raise ValueError()
            if values.get('llm_provider', 'mock') not in {'mock', 'deepseek'} or values.get('asr_provider', 'paraformer') not in {'paraformer', 'sensevoice'}:
                raise ValueError()
            if not isinstance(values.get('deepseek_api_key', ''), str):
                raise ValueError()
    except (ValueError, UnicodeError, OSError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="备份版本、配置或文件校验失败，请使用完整的 StudentLog 备份") from exc
    _validate_database(staging / 'app.db')
    with closing(sqlite3.connect(staging / 'app.db')) as connection:
        for folder, query in (('avatars', 'SELECT avatar_path FROM students WHERE avatar_path IS NOT NULL'),
                              ('attachments', 'SELECT stored_filename FROM attachments')):
            for (filename,) in connection.execute(query):
                if (not filename or '/' in filename or '\\' in filename or ':' in filename
                        or filename in {'.', '..'} or not (staging / folder / filename).is_file()):
                    raise HTTPException(status_code=400, detail="备份缺少数据库引用的头像或附件")


def _install_restore(staging: Path, root: Path) -> None:
    """Swap prepared components; retain originals until every swap succeeds."""
    previous = staging / '.previous'
    touched = []
    installed = set()
    journal = {'touched': [], 'had_original': {}, 'committed': False}

    def save_journal():
        temporary = staging / '.journal.tmp'
        temporary.write_text(json.dumps(journal), encoding='utf-8')
        temporary.replace(staging / '.restore-journal.json')

    save_journal()
    previous.mkdir()
    try:
        for name in ('app.db', 'avatars', 'attachments', 'config.json'):
            source, target, old = staging / name, root / name, previous / name
            if target.is_symlink() or target.resolve().parent != root:
                raise OSError('Invalid restore target')
            touched.append(name)
            journal['touched'].append(name)
            journal['had_original'][name] = target.exists()
            save_journal()
            if target.exists():
                target.replace(old)
            if source.exists():
                source.replace(target)
                installed.add(name)
        journal['committed'] = True
        save_journal()
    except OSError as exc:
        try:
            for name in reversed(touched):
                target, old = root / name, previous / name
                # A failed move of the old component leaves it in place.
                if old.exists() or name in installed:
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink(missing_ok=True)
                    if old.exists():
                        old.replace(target)
        except OSError as rollback_error:
            raise HTTPException(status_code=500, detail="恢复和回滚失败，原文件保留在恢复暂存目录；请使用恢复前安全备份") from rollback_error
        previous.rmdir()
        raise HTTPException(status_code=500, detail="恢复失败，已回滚到恢复前的数据，请检查磁盘空间或文件权限") from exc
    shutil.rmtree(previous, ignore_errors=True)


def recover_interrupted_restores(data_dir: Path | None = None) -> None:
    """Called before opening the database on startup; finish or undo a swap."""
    root = (data_dir or settings.data_dir).resolve()
    for staging in (root / 'backups').glob('.restore-*'):
        previous = staging / '.previous'
        if not previous.exists():
            continue
        journal_file = staging / '.restore-journal.json'
        try:
            journal = json.loads(journal_file.read_text(encoding='utf-8'))
            names = journal['touched']
            if (not isinstance(names, list) or len(names) != len(set(names))
                    or any(name not in {'app.db', 'avatars', 'attachments', 'config.json'} for name in names)
                    or not isinstance(journal.get('committed'), bool)
                    or any(not isinstance(journal['had_original'].get(name), bool) for name in names)):
                raise ValueError('Invalid recovery journal')
            if not journal['committed']:
                for name in reversed(names):
                    target, old = root / name, previous / name
                    if target.is_symlink() or target.resolve().parent != root:
                        raise ValueError('Invalid recovery target')
                    if old.exists() or not journal['had_original'][name]:
                        if target.is_dir():
                            shutil.rmtree(target)
                        else:
                            target.unlink(missing_ok=True)
                        if old.exists():
                            old.replace(target)
            shutil.rmtree(staging)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError('发现未完成的数据恢复，无法自动回滚。原文件保留在 data/backups 的恢复暂存目录中。') from exc


def restore_backup(content: bytes, data_dir: Path | None = None) -> Path:
    root = (data_dir or settings.data_dir).resolve()
    backups = root / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    staging = backups / f".restore-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="上传文件不是有效的 ZIP 备份") from exc
        with archive:
            members = _safe_members(archive)
            for item in members:
                if item.is_dir():
                    continue
                destination = staging.joinpath(*PurePosixPath(item.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with archive.open(item) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
                except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                    raise HTTPException(status_code=400, detail="备份 ZIP 已损坏或压缩格式不受支持") from exc
        _validate_payload(staging)
        for folder in ('avatars', 'attachments'):
            (staging / folder).mkdir(exist_ok=True)
        if (staging / 'config.json').exists():
            (staging / 'config.json').chmod(0o600)
        safety_backup = create_backup(root) if (root / "app.db").is_file() else None
        engine.dispose()
        if (root / 'app.db').exists():
            with closing(sqlite3.connect(root / 'app.db')) as connection:
                result = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                if result[0]:
                    raise HTTPException(status_code=409, detail="数据库仍被占用，请稍后恢复")
        for suffix in ("-wal", "-shm"):
            Path(f"{root / 'app.db'}{suffix}").unlink(missing_ok=True)
        _install_restore(staging, root)
        return safety_backup
    finally:
        # Keep originals if rollback itself failed. Never delete that recovery copy.
        if staging.exists() and not (staging / '.previous').exists():
            shutil.rmtree(staging)
