import io
import os
import sqlite3
import uuid

from fastapi.testclient import TestClient
from PIL import Image

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.auth import hash_password
from backend.app.config import settings
from backend.app.database import Base, get_db
from backend.app.data_portability import create_backup, restore_backup
from backend.app.hotwords import hotword_registry
from backend.app.main import app
from backend.app.models import AdminUser, Student
from backend.app.name_resolver import canonicalize_student_names, normalized_pinyin, resolve_students


def login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": os.getenv("ADMIN_PASSWORD", "change-me")})
    assert response.status_code == 200


def test_spaced_transcript_name_correction():
    names = ["陈颢霖", "陈梓恒", "董佳鹄", "黄麒", "李晟睿", "李易恒", "梁晋", "林子昂", "刘一铭", "罗浩玮", "潘卓辰"]
    students = [Student(id=str(index), student_no=str(index), name=name, pinyin=normalized_pinyin(name), aliases="", status="active") for index, name in enumerate(names)]
    transcript = "今 天 陈 浩 霖 和 陈 子 恒 找 董 家 湖 玩，遇 到 黄 琦、李 晟 瑞、李 毅 恒、梁 静、林 子 昂、刘 一 鸣、罗 浩 伟 和 潘 卓 辰。"
    corrected, corrections = canonicalize_student_names(transcript, students)
    assert corrected == "今天陈颢霖和陈梓恒找董佳鹄玩，遇到黄麒、李晟睿、李易恒、梁晋、林子昂、刘一铭、罗浩玮和潘卓辰。"
    assert len(corrections) == 9
    resolution = resolve_students(corrected, students)
    assert len(resolution.candidates) == 11
    assert len(resolution.auto_selected_ids) == 11
    assert all(candidate.confidence == 1 for candidate in resolution.candidates)


def test_first_run_setup(tmp_path):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)
    Base.metadata.create_all(test_engine)

    def test_db():
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    try:
        with TestClient(app) as client:
            assert client.get("/api/auth/status").json() == {"initialized": False}
            too_short = client.post("/api/auth/setup", json={"username": "teacher", "password": "short"})
            assert too_short.status_code == 422
            setup = client.post("/api/auth/setup", json={"username": "teacher", "password": "safe-password"})
            assert setup.status_code == 200
            assert client.get("/api/auth/me").json() == {"username": "teacher"}
            assert client.get("/api/auth/status").json() == {"initialized": True}
            duplicate = client.post("/api/auth/setup", json={"username": "other", "password": "other-password"})
            assert duplicate.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_phase1_multi_student_event_and_avatar(tmp_path):
    original_data_dir = settings.data_dir
    settings.data_dir = tmp_path
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)
    Base.metadata.create_all(test_engine)
    with TestSession() as seed:
        seed.add(AdminUser(username="admin", password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "change-me"))))
        seed.commit()

    def test_db():
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    token = uuid.uuid4().hex[:8]
    try:
        with TestClient(app) as client:
            assert client.get("/api/students").status_code == 401
            login(client)
            first = client.post("/api/students", json={"student_no": f"A{token}", "name": "测试甲", "aliases": []})
            second = client.post("/api/students", json={"student_no": f"B{token}", "name": "测试乙", "aliases": []})
            target = client.post("/api/students", json={"student_no": f"C{token}", "name": "杨煜洆", "aliases": []})
            near_homophone = client.post("/api/students", json={"student_no": f"D{token}", "name": "方宁", "aliases": []})
            assert first.status_code == second.status_code == target.status_code == near_homophone.status_code == 200
            ids = [first.json()["id"], second.json()["id"]]
            with TestSession() as session:
                assert "杨煜洆" in hotword_registry.get(session)
                active = list(session.query(Student).all())
                corrected, corrections = canonicalize_student_names("今天杨育成和方林在午休时讲话。", active)
                assert corrected == "今天杨煜洆和方宁在午休时讲话。"
                assert [(item.original, item.corrected) for item in corrections] == [("杨育成", "杨煜洆"), ("方林", "方宁")]

            status = client.get("/api/asr/status")
            assert status.status_code == 200
            assert status.json()["provider"] == "paraformer"
            assert status.json()["hotword_count"] >= 14
            switched = client.put("/api/settings/asr", json={"provider": "sensevoice"})
            assert switched.status_code == 200
            assert switched.json()["provider"] == "sensevoice"
            assert (tmp_path / "config.json").exists()

            image = Image.new("RGB", (800, 600), "#d85f2f")
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            uploaded = client.post(f"/api/students/{ids[0]}/avatar", files={"file": ("portrait.png", buffer.getvalue(), "image/png")})
            assert uploaded.status_code == 200
            assert uploaded.json()["avatar_url"].endswith(".webp")

            event = client.post("/api/events", json={
                "student_ids": ids,
                "occurred_at": "2026-09-24T13:45:00",
                "location": "教室",
                "category": "午休纪律",
                "event_description": "午休期间交谈，提醒后停止。",
                "teacher_action": "教师口头提醒。",
                "tags": ["午休", "谈话"],
            })
            assert event.status_code == 200
            assert {student["id"] for student in event.json()["students"]} == set(ids)
            fetched = client.get(f"/api/events/{event.json()['id']}")
            assert fetched.status_code == 200
            assert fetched.json()["event_description"] == "午休期间交谈，提醒后停止。"
            assert fetched.json()["attachments"] == []

            attachment_image = Image.new("RGB", (2400, 1200), "#28584d")
            attachment_buffer = io.BytesIO()
            attachment_image.save(attachment_buffer, "JPEG")
            attached = client.post(
                f"/api/events/{event.json()['id']}/attachments",
                files={"file": ("课堂 照片.jpg", attachment_buffer.getvalue(), "image/jpeg")},
            )
            assert attached.status_code == 200
            attachment_path = tmp_path / "attachments" / attached.json()["url"].rsplit("/", 1)[-1]
            assert attachment_path.is_file()
            assert Image.open(attachment_path).width <= 1920
            assert client.get(f"/api/events/{event.json()['id']}").json()["attachments"][0]["original_filename"] == "课堂 照片.jpg"

            assert any(item["id"] == event.json()["id"] for item in client.get("/api/events?q=测试甲").json())
            assert any(item["id"] == event.json()["id"] for item in client.get("/api/events?tag=午休").json())
            assert any(item["id"] == event.json()["id"] for item in client.get(f"/api/events?student_id={ids[0]}").json())
            assert client.get("/api/events?date_from=2030-01-01T00:00:00").json() == []

            exported_json = client.get("/api/export/json")
            assert exported_json.status_code == 200
            assert any(item["id"] == event.json()["id"] for item in exported_json.json()["events"])
            exported_csv = client.get("/api/export/csv")
            assert exported_csv.status_code == 200
            assert "测试甲" in exported_csv.content.decode("utf-8-sig")
            summary = client.post(f"/api/students/{ids[0]}/summary", json={"date_from": "2026-09-01T00:00:00", "date_to": "2026-09-30T23:59:59"})
            assert summary.status_code == 200
            assert summary.json()["source_event_count"] == 1
            assert summary.json()["provider"] == "mock"
            assert summary.json()["sections"]["discipline_records"] == ["2026-09-24：午休期间交谈，提醒后停止。"]
            empty_summary = client.post(f"/api/students/{ids[0]}/summary", json={"date_from": "2030-01-01T00:00:00", "date_to": "2030-01-31T23:59:59"})
            assert empty_summary.status_code == 400
            for student_id in ids:
                timeline = client.get(f"/api/events?student_id={student_id}")
                assert timeline.status_code == 200
                assert any(item["id"] == event.json()["id"] for item in timeline.json())

            structured = client.post("/api/ai/structure", json={"transcript": "今天中午杨育成和方林在教室午休时讲话。"})
            assert structured.status_code == 200
            assert structured.json()["transcript"] == "今天中午杨煜洆和方宁在教室午休时讲话。"
            assert structured.json()["draft"]["event_description"] == "今天中午杨煜洆和方宁在教室午休时讲话。"
            target_candidate = next(item for item in structured.json()["candidates"] if item["student_id"] == target.json()["id"])
            assert target_candidate["confidence"] >= 0.9
            assert target.json()["id"] in structured.json()["draft"]["student_ids"]
            assert near_homophone.json()["id"] in structured.json()["draft"]["student_ids"]

            voice_event_payload = {
                **structured.json()["draft"],
                "raw_transcript": "今天中午杨育成和方林在教室午休时讲话。",
                "record_method": "voice",
                "ai_processed": True,
            }
            voice_event = client.post("/api/events", json=voice_event_payload)
            assert voice_event.status_code == 200
            assert {item["id"] for item in voice_event.json()["students"]} == {
                target.json()["id"],
                near_homophone.json()["id"],
            }
            for student_id in voice_event_payload["student_ids"]:
                timeline = client.get(f"/api/events?student_id={student_id}")
                assert any(item["id"] == voice_event.json()["id"] for item in timeline.json())
            assert client.delete(f"/api/events/{voice_event.json()['id']}").status_code == 200

            cleared = client.delete("/api/students/clear")
            assert cleared.status_code == 200
            assert cleared.json() == {"ok": True, "deleted": 2, "archived": 2}
            assert client.get("/api/students").json() == []
            with TestSession() as session:
                assert "杨煜洆" not in hotword_registry.get(session)
            assert client.delete(f"/api/events/{event.json()['id']}").status_code == 200
            assert not attachment_path.exists()
    finally:
        app.dependency_overrides.clear()
        hotword_registry.invalidate()
        settings.data_dir = original_data_dir


def _create_portable_database(path, student_name: str) -> None:
    test_engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        Base.metadata.create_all(test_engine)
        with sessionmaker(bind=test_engine)() as session:
            session.add(Student(id='s1', student_no='01', name=student_name))
            session.commit()
    finally:
        test_engine.dispose()


def test_phase3_complete_backup_and_restore(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    for root in (source, target):
        for folder in ("avatars", "attachments", "backups"):
            (root / folder).mkdir(parents=True, exist_ok=True)
    _create_portable_database(source / "app.db", "备份学生")
    (source / "avatars" / "avatar.webp").write_bytes(b"avatar-content")
    (source / "attachments" / "proof.webp").write_bytes(b"attachment-content")
    (source / "config.json").write_text('{"asr_provider":"paraformer"}', encoding="utf-8")
    backup = create_backup(source)
    assert backup.is_file()

    _create_portable_database(target / "app.db", "恢复前学生")
    (target / "avatars" / "old.webp").write_bytes(b"old")
    safety_backup = restore_backup(backup.read_bytes(), target)
    assert safety_backup and safety_backup.is_file()
    connection = sqlite3.connect(target / "app.db")
    try:
        assert connection.execute("SELECT name FROM students WHERE id='s1'").fetchone()[0] == "备份学生"
    finally:
        connection.close()
    assert (target / "avatars" / "avatar.webp").read_bytes() == b"avatar-content"
    assert not (target / "avatars" / "old.webp").exists()
    assert (target / "attachments" / "proof.webp").read_bytes() == b"attachment-content"
    assert (target / "config.json").read_text(encoding="utf-8") == '{"asr_provider":"paraformer"}'
