import re
from dataclasses import dataclass

from pypinyin import lazy_pinyin
from rapidfuzz.fuzz import ratio

from .models import Student
from .schemas import NameCandidate


def normalized_pinyin(value: str) -> str:
    return "".join(lazy_pinyin(value)).lower().replace(" ", "")


def chinese_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for size in range(2, 5):
            chunks.extend(run[index:index + size] for index in range(max(0, len(run) - size + 1)))
    return chunks


@dataclass
class Resolution:
    candidates: list[NameCandidate]
    auto_selected_ids: list[str]


def resolve_students(transcript: str, students: list[Student], preset_student_id: str | None = None) -> Resolution:
    if preset_student_id:
        selected = next((student for student in students if student.id == preset_student_id), None)
        if selected:
            candidate = NameCandidate(student_id=selected.id, student_no=selected.student_no, name=selected.name, confidence=1, reason="当前学生档案")
            return Resolution([candidate], [selected.id])

    chunks = chinese_chunks(transcript)
    candidates: list[NameCandidate] = []
    for student in students:
        aliases = [item for item in student.aliases.split("|") if item]
        if student.name in transcript:
            score, reason = 1.0, "姓名完全匹配"
        elif any(alias in transcript for alias in aliases):
            score, reason = 0.98, "姓名别名匹配"
        else:
            target_pinyin = student.pinyin.replace(" ", "").lower() if student.pinyin else normalized_pinyin(student.name)
            pinyin_score = max((ratio(target_pinyin, normalized_pinyin(chunk)) for chunk in chunks), default=0) / 100
            text_score = max((ratio(student.name, chunk) for chunk in chunks), default=0) / 100
            score = max(pinyin_score * 0.96, text_score * 0.9)
            reason = "拼音匹配" if pinyin_score >= text_score else "近似文字匹配"
        if score >= 0.6:
            candidates.append(NameCandidate(student_id=student.id, student_no=student.student_no, name=student.name, confidence=round(score, 3), reason=reason))

    candidates.sort(key=lambda item: item.confidence, reverse=True)
    strong = [candidate.student_id for candidate in candidates if candidate.confidence >= 0.9]
    return Resolution(candidates[:8], strong)
