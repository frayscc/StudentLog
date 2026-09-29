import csv
import io
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .config import settings
from .models import Attachment, Event, Student, Tag
from .schemas import AttachmentOut, EventCreate, StudentCreate, StudentOut

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def student_out(student: Student) -> StudentOut:
    dates = [event.occurred_at for event in student.events]
    return StudentOut(
        id=student.id,
        student_no=student.student_no,
        name=student.name,
        pinyin=student.pinyin,
        aliases=[item for item in student.aliases.split("|") if item],
        status=student.status,
        avatar_url=f"/files/avatars/{student.avatar_path}" if student.avatar_path else None,
        event_count=len(student.events),
        last_event_at=max(dates) if dates else None,
        created_at=student.created_at,
        updated_at=student.updated_at,
    )


def event_query():
    return select(Event).options(selectinload(Event.students), selectinload(Event.tags), selectinload(Event.attachments))


def attachment_out(attachment: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=attachment.id,
        original_filename=attachment.original_filename,
        mime_type=attachment.mime_type,
        file_size=attachment.file_size,
        url=f"/files/attachments/{attachment.stored_filename}",
        created_at=attachment.created_at,
    )


def event_out(event: Event) -> dict:
    return {
        "id": event.id,
        "occurred_at": event.occurred_at,
        "recorded_at": event.recorded_at,
        "location": event.location,
        "category": event.category,
        "event_description": event.event_description,
        "student_response": event.student_response,
        "teacher_action": event.teacher_action,
        "follow_up": event.follow_up,
        "raw_transcript": event.raw_transcript,
        "record_method": event.record_method,
        "ai_processed": event.ai_processed,
        "ai_confidence": event.ai_confidence,
        "students": [
            {"id": s.id, "student_no": s.student_no, "name": s.name, "avatar_url": f"/files/avatars/{s.avatar_path}" if s.avatar_path else None}
            for s in event.students
        ],
        "tags": [tag.name for tag in event.tags],
        "attachments": [attachment_out(item).model_dump(mode="json") for item in event.attachments],
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def apply_event(db: Session, event: Event, payload: EventCreate) -> Event:
    students = list(db.scalars(select(Student).where(Student.id.in_(set(payload.student_ids)))))
    if len(students) != len(set(payload.student_ids)):
        raise HTTPException(status_code=400, detail="包含不存在的学生")
    tags = []
    for raw_name in payload.tags:
        name = raw_name.strip()
        if not name:
            continue
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
        tags.append(tag)
    for field in ("occurred_at", "location", "category", "event_description", "student_response", "teacher_action", "follow_up", "raw_transcript", "record_method"):
        setattr(event, field, getattr(payload, field))
    event.ai_processed = payload.ai_processed
    event.ai_confidence = payload.ai_confidence
    event.students = students
    event.tags = tags
    return event


async def save_avatar(student: Student, upload: UploadFile) -> str:
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPG、PNG、WEBP 图片")
    content = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 8MB")
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image).convert("RGB")
        size = min(image.size)
        left = (image.width - size) // 2
        top = (image.height - size) // 2
        image = image.crop((left, top, left + size, top + size)).resize((512, 512), Image.Resampling.LANCZOS)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="图片文件无效") from exc
    filename = f"{uuid.uuid4().hex}.webp"
    image.save(settings.data_dir / "avatars" / filename, "WEBP", quality=84, method=6)
    if student.avatar_path:
        old_path = settings.data_dir / "avatars" / Path(student.avatar_path).name
        old_path.unlink(missing_ok=True)
    return filename


async def save_attachment(event: Event, upload: UploadFile) -> Attachment:
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="附件仅支持 JPG、PNG、WEBP 图片")
    content = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="附件图片不能超过 8MB")
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert("RGB")
        image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="附件图片文件无效") from exc
    filename = f"{uuid.uuid4().hex}.webp"
    target = settings.data_dir / "attachments" / filename
    image.save(target, "WEBP", quality=84, method=6)
    return Attachment(
        event_id=event.id,
        original_filename=Path(upload.filename or "image").name[:255],
        stored_filename=filename,
        mime_type="image/webp",
        file_size=target.stat().st_size,
    )


def delete_attachment_file(attachment: Attachment) -> None:
    (settings.data_dir / "attachments" / Path(attachment.stored_filename).name).unlink(missing_ok=True)


def parse_student_import(text: str) -> list[StudentCreate]:
    rows: list[StudentCreate] = []
    for raw in text.replace("\ufeff", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        columns = next(csv.reader([line])) if "," in line else re.split(r"\s+", line, maxsplit=1)
        if len(columns) < 2:
            raise HTTPException(status_code=400, detail=f"无法识别这一行：{line}")
        student_no, name = columns[0].strip(), columns[1].strip()
        if student_no.lower() in {"student_no", "学号"}:
            continue
        rows.append(StudentCreate(student_no=student_no, name=name))
    return rows
