from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import create_session, hash_password, require_login, verify_password
from .asr import get_asr_provider
from .audio import browser_audio_to_wav
from .config import ensure_data_dirs, settings
from .data_portability import create_backup, csv_export, json_export, restore_backup
from .database import Base, engine, get_db
from .hotwords import hotword_registry
from .local_config import get_asr_provider_name, save_asr_provider_name
from .models import AdminUser, Attachment, Event, Student, Tag
from .name_resolver import canonicalize_student_names, normalized_pinyin, resolve_students
from .providers import ProviderError, get_llm_provider
from .schemas import ASRSettingsOut, ASRSettingsUpdate, ASRStatus, AuthStatus, EventCreate, EventOut, EventUpdate, LoginRequest, SetupRequest, StructureRequest, StructureResponse, StudentCreate, StudentOut, StudentUpdate, TranscriptResponse
from .services import apply_event, attachment_out, delete_attachment_file, event_out, event_query, parse_student_import, save_attachment, save_avatar, student_out


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_data_dirs()
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="StudentLog", lifespan=lifespan)
app.mount("/files/avatars", StaticFiles(directory=settings.data_dir / "avatars"), name="avatars")
app.mount("/files/attachments", StaticFiles(directory=settings.data_dir / "attachments"), name="attachments")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/status", response_model=AuthStatus)
def auth_status(db: Session = Depends(get_db)):
    return AuthStatus(initialized=db.scalar(select(AdminUser.id).limit(1)) is not None)


@app.post("/api/auth/setup")
def setup(payload: SetupRequest, response: Response, db: Session = Depends(get_db)):
    if db.scalar(select(AdminUser.id).limit(1)) is not None:
        raise HTTPException(status_code=409, detail="管理员账号已经创建，请直接登录")
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    db.add(AdminUser(username=username, password_hash=hash_password(payload.password)))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="管理员账号已经创建，请直接登录") from exc
    create_session(response, username)
    return {"username": username}


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
    values = payload.model_dump(exclude={"aliases"})
    values["pinyin"] = values.get("pinyin") or normalized_pinyin(payload.name)
    student = Student(**values, aliases="|".join(payload.aliases))
    db.add(student)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="学号已存在") from exc
    db.refresh(student)
    hotword_registry.invalidate()
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
    students = [Student(**{**row.model_dump(exclude={"aliases"}), "pinyin": row.pinyin or normalized_pinyin(row.name)}, aliases="") for row in rows]
    db.add_all(students)
    db.commit()
    hotword_registry.invalidate()
    return [student_out(item) for item in students]


@app.delete("/api/students/clear", dependencies=[Depends(require_login)])
def clear_active_students(db: Session = Depends(get_db)):
    students = list(db.scalars(select(Student).options(selectinload(Student.events)).where(Student.status == "active")))
    deleted = 0
    archived = 0
    for student in students:
        if student.events:
            student.status = "inactive"
            archived += 1
        else:
            if student.avatar_path:
                avatar = settings.data_dir / "avatars" / Path(student.avatar_path).name
                avatar.unlink(missing_ok=True)
            db.delete(student)
            deleted += 1
    db.commit()
    hotword_registry.invalidate()
    return {"ok": True, "deleted": deleted, "archived": archived}


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
    if "name" in data and "pinyin" not in data:
        student.pinyin = normalized_pinyin(student.name)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="学号已存在") from exc
    hotword_registry.invalidate()
    return student_out(student)


@app.delete("/api/students/{student_id}", dependencies=[Depends(require_login)])
def deactivate_student(student_id: str, db: Session = Depends(get_db)):
    student = db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    student.status = "inactive"
    db.commit()
    hotword_registry.invalidate()
    return {"ok": True}


@app.post("/api/students/{student_id}/avatar", response_model=StudentOut, dependencies=[Depends(require_login)])
async def upload_avatar(student_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    student = db.scalar(select(Student).options(selectinload(Student.events)).where(Student.id == student_id))
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")
    student.avatar_path = await save_avatar(student, file)
    db.commit()
    return student_out(student)


@app.post("/api/asr/transcribe", response_model=TranscriptResponse, dependencies=[Depends(require_login)])
async def transcribe_audio(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await file.read(25 * 1024 * 1024 + 1)
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="录音不能超过 25MB")
    hotwords = hotword_registry.get(db)
    provider_name = get_asr_provider_name()
    wav_path = None
    try:
        wav_path = browser_audio_to_wav(content)
        provider = get_asr_provider(provider_name)
        result = await provider.transcribe(wav_path, hotwords=hotwords, language="zh")
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if wav_path is not None:
            wav_path.unlink(missing_ok=True)
    students = list(db.scalars(select(Student).where(Student.status == "active")))
    transcript, corrections = canonicalize_student_names(result.transcript, students)
    return TranscriptResponse(
        transcript=transcript,
        original_transcript=result.transcript,
        provider=provider.name,
        elapsed_ms=result.elapsed_ms,
        hotword_count=len(hotwords),
        name_corrections=[{"original": item.original, "corrected": item.corrected} for item in corrections],
    )


@app.get("/api/asr/status", response_model=ASRStatus, dependencies=[Depends(require_login)])
def asr_status(db: Session = Depends(get_db)):
    provider_name = get_asr_provider_name()
    providers = [get_asr_provider(name) for name in ("paraformer", "sensevoice")]
    return ASRStatus(
        provider=provider_name,
        hotword_count=len(hotword_registry.get(db)),
        providers=[{"name": item.name, "installed": item.installed, "loaded": item.loaded} for item in providers],
    )


@app.get("/api/settings/asr", response_model=ASRSettingsOut, dependencies=[Depends(require_login)])
def get_asr_settings():
    return ASRSettingsOut(provider=get_asr_provider_name())


@app.put("/api/settings/asr", response_model=ASRSettingsOut, dependencies=[Depends(require_login)])
def update_asr_settings(payload: ASRSettingsUpdate):
    save_asr_provider_name(payload.provider)
    return ASRSettingsOut(provider=payload.provider)


@app.post("/api/ai/structure", response_model=StructureResponse, dependencies=[Depends(require_login)])
async def structure_event(payload: StructureRequest, db: Session = Depends(get_db)):
    students = list(db.scalars(select(Student).where(Student.status == "active")))
    if payload.preset_student_id and not any(student.id == payload.preset_student_id for student in students):
        raise HTTPException(status_code=400, detail="预选学生不存在或已停用")
    transcript, corrections = canonicalize_student_names(payload.transcript, students)
    resolution = resolve_students(transcript, students, payload.preset_student_id)
    provider = get_llm_provider()
    try:
        draft = await provider.structure(transcript, resolution.candidates, resolution.auto_selected_ids)
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # Local exact/alias/high-confidence matches are deterministic and must not
    # be dropped by a cloud model. The teacher can still deselect them in review.
    draft.student_ids = list(dict.fromkeys([*resolution.auto_selected_ids, *draft.student_ids]))
    confidence_by_id = {item.student_id: item.confidence for item in resolution.candidates}
    requires_confirmation = not draft.student_ids or any(confidence_by_id.get(student_id, 0) < 0.9 for student_id in draft.student_ids)
    return StructureResponse(
        transcript=transcript,
        draft=draft,
        candidates=resolution.candidates,
        provider=provider.name,
        requires_student_confirmation=requires_confirmation,
        name_corrections=[{"original": item.original, "corrected": item.corrected} for item in corrections],
    )


@app.get("/api/events", response_model=list[EventOut], dependencies=[Depends(require_login)])
def list_events(
    student_id: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    q: str = "",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
):
    query = event_query().order_by(Event.occurred_at.desc())
    if student_id:
        query = query.where(Event.students.any(Student.id == student_id))
    if category:
        query = query.where(Event.category == category)
    if tag:
        query = query.where(Event.tags.any(Tag.name == tag))
    if date_from:
        query = query.where(Event.occurred_at >= date_from)
    if date_to:
        query = query.where(Event.occurred_at <= date_to)
    if q:
        like = f"%{q}%"
        query = query.where(or_(
            Event.event_description.like(like),
            Event.raw_transcript.like(like),
            Event.student_response.like(like),
            Event.teacher_action.like(like),
            Event.follow_up.like(like),
            Event.students.any(or_(Student.name.like(like), Student.student_no.like(like))),
            Event.tags.any(Tag.name.like(like)),
        ))
    return [event_out(item) for item in db.scalars(query)]


@app.get("/api/tags", response_model=list[str], dependencies=[Depends(require_login)])
def list_tags(db: Session = Depends(get_db)):
    return list(db.scalars(select(Tag.name).order_by(Tag.name)))


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
    event = db.scalar(event_query().where(Event.id == event_id))
    if not event:
        raise HTTPException(status_code=404, detail="记录不存在")
    for attachment in event.attachments:
        delete_attachment_file(attachment)
    db.delete(event)
    db.commit()
    return {"ok": True}


@app.post("/api/events/{event_id}/attachments", dependencies=[Depends(require_login)])
async def upload_event_attachment(event_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="记录不存在")
    attachment = await save_attachment(event, file)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment_out(attachment)


@app.delete("/api/attachments/{attachment_id}", dependencies=[Depends(require_login)])
def delete_event_attachment(attachment_id: str, db: Session = Depends(get_db)):
    attachment = db.get(Attachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="附件不存在")
    delete_attachment_file(attachment)
    db.delete(attachment)
    db.commit()
    return {"ok": True}


@app.get("/api/export/json", dependencies=[Depends(require_login)])
def export_json(db: Session = Depends(get_db)):
    students = [item.model_dump(mode="json") for item in (student_out(student) for student in db.scalars(select(Student).options(selectinload(Student.events)).order_by(Student.student_no)))]
    events = [event_out(event) for event in db.scalars(event_query().order_by(Event.occurred_at.desc()))]
    content = json_export(students, events)
    filename = f"studentlog-export-{datetime.now():%Y%m%d}.json"
    return Response(content, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/export/csv", dependencies=[Depends(require_login)])
def export_csv(db: Session = Depends(get_db)):
    events = [event_out(event) for event in db.scalars(event_query().order_by(Event.occurred_at.desc()))]
    content = csv_export(events)
    filename = f"studentlog-export-{datetime.now():%Y%m%d}.csv"
    return Response(content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/backups/export", dependencies=[Depends(require_login)])
def export_backup():
    path = create_backup()
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/backups/restore", dependencies=[Depends(require_login)])
async def import_backup(response: Response, file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请选择 StudentLog ZIP 备份")
    content = await file.read(512 * 1024 * 1024 + 1)
    if len(content) > 512 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="备份文件不能超过 512MB")
    safety_backup = restore_backup(content)
    hotword_registry.invalidate()
    response.delete_cookie("studentlog_session")
    return {"ok": True, "safety_backup": safety_backup.name if safety_backup else None, "message": "恢复完成，请重新登录并刷新页面"}


if settings.frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (settings.frontend_dist / path).resolve()
        root = settings.frontend_dist.resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(settings.frontend_dist / "index.html")
