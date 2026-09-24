import io
import os
import uuid

from fastapi.testclient import TestClient
from PIL import Image

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.config import settings
from app.database import Base, get_db
from app.hotwords import hotword_registry
from app.main import app
from app.models import AdminUser, Student
from app.name_resolver import canonicalize_student_names


def login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": os.getenv("ADMIN_PASSWORD", "change-me")})
    assert response.status_code == 200


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

            cleared = client.delete("/api/students/clear")
            assert cleared.status_code == 200
            assert cleared.json() == {"ok": True, "deleted": 2, "archived": 2}
            assert client.get("/api/students").json() == []
            with TestSession() as session:
                assert "杨煜洆" not in hotword_registry.get(session)
            assert client.delete(f"/api/events/{event.json()['id']}").status_code == 200
    finally:
        app.dependency_overrides.clear()
        hotword_registry.invalidate()
        settings.data_dir = original_data_dir
