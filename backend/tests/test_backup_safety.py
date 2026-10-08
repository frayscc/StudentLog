import asyncio
import io
import json
import sqlite3
import zipfile
from contextlib import closing, nullcontext
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import Student
from backend.app.data_portability import create_backup, restore_backup, recover_interrupted_restores
from backend.app.maintenance import DataAccessGate


def make_data(root, name):
    root.mkdir(parents=True)
    for folder in ('avatars', 'attachments', 'backups'):
        (root / folder).mkdir()
    engine = create_engine(f"sqlite:///{(root / 'app.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Student(id='s1', student_no='01', name=name, avatar_path='avatar.webp'))
            session.commit()
    finally:
        engine.dispose()
    (root / 'avatars/avatar.webp').write_bytes(name.encode())
    (root / 'config.json').write_text(json.dumps({'llm_provider': 'mock'}), encoding='utf-8')


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob('*')
            if path.is_file() and 'backups' not in path.relative_to(root).parts}


def rewrite(content, edits=None, additions=None, drop=()):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(output, 'w') as target:
        for member in source.infolist():
            if member.filename not in drop:
                target.writestr(member, (edits or {}).get(member.filename, source.read(member)))
        for name, data in (additions or {}).items():
            target.writestr(name, data)
    return output.getvalue()


@pytest.mark.parametrize('problem', ['checksum', 'missing_avatar', 'missing_db', 'metadata', 'version',
                                     'traversal', 'backslash', 'duplicate', 'invalid_config', 'schema', 'foreign_key'])
def test_invalid_backup_preserves_current_data(tmp_path, problem):
    source, target = tmp_path / 'source', tmp_path / 'target'
    make_data(source, '备份学生')
    make_data(target, '当前学生')
    content = create_backup(source).read_bytes()
    metadata = {'format': 'StudentLog backup', 'version': 1}
    if problem == 'checksum':
        content = rewrite(content, {'avatars/avatar.webp': b'changed'})
    elif problem == 'missing_avatar':
        content = rewrite(content, {'metadata.json': json.dumps(metadata).encode()}, drop=('avatars/avatar.webp',))
    elif problem == 'missing_db':
        content = rewrite(content, drop=('app.db',))
    elif problem == 'metadata':
        content = rewrite(content, {'metadata.json': b'not-json'})
    elif problem == 'version':
        content = rewrite(content, {'metadata.json': b'{"format":"StudentLog backup","version":999}'})
    elif problem in {'traversal', 'backslash', 'duplicate'}:
        filename = {'traversal': 'avatars/../../outside', 'backslash': 'avatars/..\\outside', 'duplicate': 'app.db'}[problem]
        with pytest.warns(UserWarning) if problem == 'duplicate' else nullcontext():
            content = rewrite(content, additions={filename: b'bad'})
    elif problem == 'invalid_config':
        content = rewrite(content, {'metadata.json': json.dumps(metadata).encode(), 'config.json': b'[]'})
    else:
        with closing(sqlite3.connect(source / 'app.db')) as connection, connection:
            if problem == 'schema':
                connection.execute('ALTER TABLE students RENAME COLUMN name TO broken_name')
            else:
                connection.execute("INSERT INTO event_students VALUES ('missing-event', 'missing-student')")
        content = create_backup(source).read_bytes()
    before = snapshot(target)
    with pytest.raises(HTTPException) as error:
        restore_backup(content, target)
    assert error.value.status_code == 400
    assert snapshot(target) == before
    assert not list((target / 'backups').glob('.restore-*'))


def test_restore_rolls_back_after_partial_swap(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    make_data(source, '备份学生')
    make_data(target, '当前学生')
    content = create_backup(source).read_bytes()
    before = snapshot(target)
    original = Path.replace

    def fail_attachment_swap(path, destination):
        if path.name == 'attachments' and path.parent.name.startswith('.restore-'):
            raise OSError('simulated disk error')
        return original(path, destination)

    monkeypatch.setattr(Path, 'replace', fail_attachment_swap)
    with pytest.raises(HTTPException) as error:
        restore_backup(content, target)
    assert error.value.status_code == 500
    assert snapshot(target) == before
    assert list((target / 'backups').glob('*.zip'))
    assert not list((target / 'backups').glob('.restore-*'))


def test_legacy_backup_without_attachments_table_is_upgraded(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    make_data(source, '旧版本学生')
    make_data(target, '当前学生')
    with closing(sqlite3.connect(source / 'app.db')) as connection, connection:
        connection.execute('DROP TABLE attachments')
    content = create_backup(source).read_bytes()
    content = rewrite(content, {'metadata.json': b'{"format":"StudentLog backup","version":1}'})
    restore_backup(content, target)
    with closing(sqlite3.connect(target / 'app.db')) as connection:
        assert connection.execute('SELECT name FROM students').fetchone()[0] == '旧版本学生'
        assert connection.execute('SELECT COUNT(*) FROM attachments').fetchone()[0] == 0


def test_interrupted_restore_is_rolled_back_on_next_start(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    make_data(source, '备份学生')
    make_data(target, '当前学生')
    content = create_backup(source).read_bytes()
    before = snapshot(target)
    original = Path.replace

    def interrupt_swap(path, destination):
        if path.name == 'avatars' and path.parent.name.startswith('.restore-'):
            raise KeyboardInterrupt('simulated process interruption')
        return original(path, destination)

    monkeypatch.setattr(Path, 'replace', interrupt_swap)
    with pytest.raises(KeyboardInterrupt):
        restore_backup(content, target)
    assert snapshot(target) != before
    monkeypatch.setattr(Path, 'replace', original)
    recover_interrupted_restores(target)
    assert snapshot(target) == before
    assert not list((target / 'backups').glob('.restore-*'))


def test_maintenance_waits_for_existing_requests_and_rejects_new_ones():
    async def scenario():
        gate = DataAccessGate()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def restore():
            async with gate.enter(exclusive=True) as acquired:
                assert acquired
                entered.set()
                await release.wait()

        async with gate.enter() as acquired:
            assert acquired
            task = asyncio.create_task(restore())
            while not gate.maintenance:
                await asyncio.sleep(0)
            assert not entered.is_set()
            async with gate.enter() as blocked:
                assert not blocked
        await entered.wait()
        async with gate.enter() as blocked:
            assert not blocked
        release.set()
        await task
        async with gate.enter() as acquired:
            assert acquired

    asyncio.run(scenario())
