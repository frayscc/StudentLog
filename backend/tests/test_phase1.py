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
from app.main import app
from app.models import AdminUser


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
            assert first.status_code == second.status_code == 200
            ids = [first.json()["id"], second.json()["id"]]

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

            assert client.delete(f"/api/events/{event.json()['id']}").status_code == 200
            for student_id in ids:
                assert client.delete(f"/api/students/{student_id}").status_code == 200
    finally:
        app.dependency_overrides.clear()
        settings.data_dir = original_data_dir
