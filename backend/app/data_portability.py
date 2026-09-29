import csv
import io
import json
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from .config import settings
from .database import engine

BACKUP_VERSION = 1
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
    _copy_database(root / "app.db", snapshot)
    metadata = {"format": "StudentLog backup", "version": BACKUP_VERSION, "created_at": datetime.now().isoformat()}
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(snapshot, "app.db")
            archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            for folder in ("avatars", "attachments"):
                base = root / folder
                if not base.exists():
                    continue
                for path in base.rglob("*"):
                    if path.is_file():
                        archive.write(path, f"{folder}/{path.relative_to(base).as_posix()}")
            config = root / "config.json"
            if config.is_file():
                archive.write(config, "config.json")
    finally:
        snapshot.unlink(missing_ok=True)
    return output


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] not in ALLOWED_BACKUP_ROOTS:
            raise HTTPException(status_code=400, detail="备份包含不安全或不支持的路径")
        if (item.external_attr >> 16) & 0o170000 == 0o120000:
            raise HTTPException(status_code=400, detail="备份不能包含符号链接")
        members.append(item)
    if "app.db" not in {item.filename for item in members}:
        raise HTTPException(status_code=400, detail="备份中缺少 app.db")
    return members


def _validate_database(path: Path) -> None:
    try:
        connection = sqlite3.connect(path)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=400, detail="备份中的 SQLite 数据库无效") from exc
    finally:
        if "connection" in locals():
            connection.close()
    if integrity != "ok" or not {"students", "events", "admin_users"}.issubset(tables):
        raise HTTPException(status_code=400, detail="备份数据库不完整或已损坏")


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
                with archive.open(item) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
        _validate_database(staging / "app.db")
        safety_backup = create_backup(root) if (root / "app.db").is_file() else None
        engine.dispose()
        for suffix in ("-wal", "-shm"):
            Path(f"{root / 'app.db'}{suffix}").unlink(missing_ok=True)
        replacement = root / ".restored-app.db"
        shutil.copy2(staging / "app.db", replacement)
        replacement.replace(root / "app.db")
        for folder in ("avatars", "attachments"):
            target = (root / folder).resolve()
            if target.parent != root:
                raise HTTPException(status_code=500, detail="恢复目标路径异常")
            if target.exists():
                shutil.rmtree(target)
            source = staging / folder
            shutil.copytree(source, target) if source.exists() else target.mkdir()
        config = staging / "config.json"
        if config.is_file():
            shutil.copy2(config, root / "config.json")
        else:
            (root / "config.json").unlink(missing_ok=True)
        return safety_backup
    finally:
        if staging.exists():
            shutil.rmtree(staging)
