from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import create_session, hash_password, require_login, verify_password
from .config import ensure_data_dirs, settings
from .database import Base, engine, get_db
from .models import AdminUser, Event, Student
from .schemas import EventCreate, EventOut, EventUpdate, LoginRequest, StudentCreate, StudentOut, StudentUpdate
from .services import apply_event, event_out, event_query, parse_student_import, save_avatar, student_out


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_data_dirs()
    Base.metadata.create_all(engine)
    db = next(get_db())
    try:
        if not db.scalar(select(AdminUser).where(AdminUser.username == settings.admin_username)):
            db.add(AdminUser(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
            db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title="StudentLog", lifespan=lifespan)
app.mount("/files/avatars", StaticFiles(directory=settings.data_dir / "avatars"), name="avatars")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    create_session(response, payload.username)
    return {"username": payload.username}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("studentlog_session")
    return {"ok": True}


@app.get("/api/auth/me")
def me(username: str = Depends(require_login)):
    return {"username": username}


@app.get("/api/students", response_model=list[StudentOut], dependencies=[Depends(require_login)])
def list_students(q: str = "", include_inactive: bool = False, recent: bool = False, db: Session = Depends(get_db)):
    query = select(Student).options(selectinload(Student.events))
    if not include_inactive:
        query = query.where(Student.status == "active")
    if q:
        query = query.where(or_(Student.name.contains(q), Student.student_no.contains(q), Student.aliases.contains(q)))
    students = list(db.scalars(query))
    result = [student_out(item) for item in students]
    if recent:
        return sorted(result, key=lambda item: item.last_event_at.timestamp() if item.last_event_at else 0, reverse=True)
    return sorted(result, key=lambda item: item.student_no)


@app.post("/api/students", response_model=StudentOut, dependencies=[Depends(require_login)])
def create_student(payload: StudentCreate, db: Session = Depends(get_db)):
    student = Student(**payload.model_dump(exclude={"aliases"}), aliases="|".join(payload.aliases))
    db.add(student)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="学号已存在") from exc
    db.refresh(student)
    return student_out(student)


@app.post("/api/students/import", response_model=list[StudentOut], dependencies=[Depends(require_login)])
async def import_students(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename or "").lower().endswith((".txt", ".csv")):
        raise HTTPException(status_code=400, detail="仅支持 TXT 或 CSV")
    content = await file.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise HTTPException(status_code=400, detail="名单文件不能超过 1MB")
    try:
        rows = parse_student_import(content.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="请使用 UTF-8 编码") from exc
    existing = set(db.scalars(select(Student.student_no).where(Student.student_no.in_([r.student_no for r in rows]))))
    if existing:
        raise HTTPException(status_code=409, detail=f"学号已存在：{', '.join(sorted(existing))}")
    students = [Student(**row.model_dump(exclude={"aliases"}), aliases="") for row in rows]
    db.add_all(students)
    db.commit()
    return [student_out(item) for item in students]


@app.get("/api/students/{student_id}", response_model=StudentOut, dependencies=[Depends(require_login)])
def get_student(student_id: str, db: Session = Depends(get_db)):
    student = db.scalar(select(Student).options(selectinload(Student.events)).where(Student.id == student_id))
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    return student_out(student)


@app.patch("/api/students/{student_id}", response_model=StudentOut, dependencies=[Depends(require_login)])
def update_student(student_id: str, payload: StudentUpdate, db: Session = Depends(get_db)):
    student = db.scalar(select(Student).options(selectinload(Student.events)).where(Student.id == student_id))
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    data = payload.model_dump(exclude_unset=True)
    if "aliases" in data:
        data["aliases"] = "|".join(data["aliases"] or [])
    for key, value in data.items():
        setattr(student, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="学号已存在") from exc
    return student_out(student)


@app.delete("/api/students/{student_id}", dependencies=[Depends(require_login)])
def deactivate_student(student_id: str, db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    student.status = "inactive"
    db.commit()
    return {"ok": True}


@app.post("/api/students/{student_id}/avatar", response_model=StudentOut, dependencies=[Depends(require_login)])
async def upload_avatar(student_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    student = db.scalar(select(Student).options(selectinload(Student.events)).where(Student.id == student_id))
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    student.avatar_path = await save_avatar(student, file)
    db.commit()
    return student_out(student)


@app.get("/api/events", response_model=list[EventOut], dependencies=[Depends(require_login)])
def list_events(student_id: str | None = None, category: str | None = None, q: str = "", db: Session = Depends(get_db)):
    query = event_query().order_by(Event.occurred_at.desc())
    if student_id:
        query = query.where(Event.students.any(Student.id == student_id))
    if category:
        query = query.where(Event.category == category)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Event.event_description.like(like), Event.student_response.like(like), Event.teacher_action.like(like), Event.follow_up.like(like)))
    return [event_out(item) for item in db.scalars(query)]


@app.post("/api/events", response_model=EventOut, dependencies=[Depends(require_login)])
def create_event(payload: EventCreate, db: Session = Depends(get_db)):
    event = apply_event(db, Event(), payload)
    db.add(event)
    db.commit()
    db.refresh(event)
    event = db.scalar(event_query().where(Event.id == event.id))
    return event_out(event)


@app.get("/api/events/{event_id}", response_model=EventOut, dependencies=[Depends(require_login)])
def get_event(event_id: str, db: Session = Depends(get_db)):
    event = db.scalar(event_query().where(Event.id == event_id))
    if not event:
        raise HTTPException(status_code=404, detail="记录不存在")
    return event_out(event)


@app.put("/api/events/{event_id}", response_model=EventOut, dependencies=[Depends(require_login)])
def update_event(event_id: str, payload: EventUpdate, db: Session = Depends(get_db)):
    event = db.scalar(event_query().where(Event.id == event_id))
    if not event:
        raise HTTPException(status_code=404, detail="记录不存在")
    apply_event(db, event, payload)
    db.commit()
    return event_out(event)


@app.delete("/api/events/{event_id}", dependencies=[Depends(require_login)])
def delete_event(event_id: str, db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(event)
    db.commit()
    return {"ok": True}


if settings.frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (settings.frontend_dist / path).resolve()
        root = settings.frontend_dist.resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(settings.frontend_dist / "index.html")
