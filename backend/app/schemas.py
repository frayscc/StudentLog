from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StudentBase(BaseModel):
    student_no: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    pinyin: str | None = None
    aliases: list[str] = []
    status: str = "active"

    @field_validator("status")
    @classmethod
    def valid_status(cls, value: str) -> str:
        if value not in {"active", "inactive"}:
            raise ValueError("status must be active or inactive")
        return value


class StudentCreate(StudentBase):
    pass


class StudentUpdate(BaseModel):
    student_no: str | None = None
    name: str | None = None
    pinyin: str | None = None
    aliases: list[str] | None = None
    status: str | None = None


class StudentOut(StudentBase):
    id: str
    avatar_url: str | None = None
    event_count: int = 0
    last_event_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EventCreate(BaseModel):
    student_ids: list[str] = Field(min_length=1)
    occurred_at: datetime
    location: str | None = None
    category: str = "其他"
    event_description: str = Field(min_length=1)
    student_response: str | None = None
    teacher_action: str | None = None
    follow_up: str | None = None
    raw_transcript: str | None = None
    record_method: str = "text"
    tags: list[str] = []
    ai_processed: bool = False
    ai_confidence: float | None = None


class EventUpdate(EventCreate):
    pass


class StudentBrief(BaseModel):
    id: str
    student_no: str
    name: str
    avatar_url: str | None = None


class EventOut(BaseModel):
    id: str
    occurred_at: datetime
    recorded_at: datetime
    location: str | None
    category: str
    event_description: str
    student_response: str | None
    teacher_action: str | None
    follow_up: str | None
    raw_transcript: str | None
    record_method: str
    ai_processed: bool
    ai_confidence: float | None
    students: list[StudentBrief]
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class NameCandidate(BaseModel):
    student_id: str
    student_no: str
    name: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class StructuredEventDraft(BaseModel):
    student_ids: list[str] = []
    occurred_at: datetime
    location: str | None = None
    category: str = "其他"
    event_description: str
    student_response: str | None = None
    teacher_action: str | None = None
    follow_up: str | None = None
    tags: list[str] = []


class StructureRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=10000)
    preset_student_id: str | None = None


class StructureResponse(BaseModel):
    transcript: str
    draft: StructuredEventDraft
    candidates: list[NameCandidate]
    provider: str
    requires_student_confirmation: bool


class TranscriptResponse(BaseModel):
    transcript: str
    original_transcript: str
    provider: str
    elapsed_ms: int
    hotword_count: int
    name_corrections: list[dict[str, str]] = []


class ASRSettingsUpdate(BaseModel):
    provider: Literal["paraformer", "sensevoice"]


class ASRSettingsOut(BaseModel):
    provider: Literal["paraformer", "sensevoice"]


class ASRProviderStatus(BaseModel):
    name: Literal["paraformer", "sensevoice"]
    installed: bool
    loaded: bool


class ASRStatus(BaseModel):
    provider: Literal["paraformer", "sensevoice"]
    hotword_count: int
    providers: list[ASRProviderStatus]
