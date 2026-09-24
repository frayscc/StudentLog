import json
from abc import ABC, abstractmethod
from datetime import datetime

import httpx
from pydantic import ValidationError

from .config import settings
from .schemas import NameCandidate, StructuredEventDraft


class ProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    name = "unknown"

    @abstractmethod
    async def structure(self, transcript: str, candidates: list[NameCandidate], selected_ids: list[str]) -> StructuredEventDraft: ...


class MockLLMProvider(LLMProvider):
    name = "mock"

    async def structure(self, transcript: str, candidates: list[NameCandidate], selected_ids: list[str]) -> StructuredEventDraft:
        category = "午休纪律" if "午休" in transcript else "课堂表现" if "课堂" in transcript else "其他"
        location = next((place for place in ("教室", "操场", "办公室", "食堂", "宿舍") if place in transcript), None)
        return StructuredEventDraft(
            student_ids=selected_ids,
            occurred_at=datetime.now().replace(second=0, microsecond=0),
            location=location,
            category=category,
            event_description=transcript.strip(),
            tags=[word for word in ("午休", "纪律", "课堂", "表扬", "谈话") if word in transcript],
        )


SYSTEM_PROMPT = """你是学生事件记录整理助手。只整理教师明确表达的事实，不评价学生，不推断心理、人格、学习意愿或家庭情况，不添加原文没有的事实。把口语去重并调整语序。教师的主观判断不能被改写成客观事实；没有可验证事实时应标明“教师主观观察”或省略该判断。学生只能从候选 student_id 中选择，禁止创造姓名或 ID；不确定时返回空数组。输出严格 JSON，字段为 student_ids、occurred_at、location、category、event_description、student_response、teacher_action、follow_up、tags。occurred_at 使用 ISO 8601；无法确定具体时间时使用当前时间。空值使用 null。"""


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    async def structure(self, transcript: str, candidates: list[NameCandidate], selected_ids: list[str]) -> StructuredEventDraft:
        if not settings.deepseek_api_key:
            raise ProviderError("DeepSeek API Key 尚未配置")
        allowed_ids = {item.student_id for item in candidates}
        strong_local_match = bool(selected_ids) and all(item.confidence >= 0.9 for item in candidates if item.student_id in selected_ids)
        candidate_payload = [{"student_id": item.student_id, **({} if strong_local_match else {"name": item.name})} for item in candidates]
        minimized_transcript = transcript
        if strong_local_match:
            for item in candidates:
                minimized_transcript = minimized_transcript.replace(item.name, item.student_id)
        user_content = json.dumps({"current_time": datetime.now().isoformat(), "transcript": minimized_transcript, "candidate_students": candidate_payload, "locally_selected_student_ids": selected_ids}, ensure_ascii=False)
        body = {"model": settings.deepseek_model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content}], "response_format": {"type": "json_object"}, "temperature": 0.1, "max_tokens": 1200, "stream": False}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(f"{settings.deepseek_base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"}, json=body)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            draft = StructuredEventDraft.model_validate_json(content)
        except (httpx.HTTPError, KeyError, IndexError, ValidationError, ValueError) as exc:
            raise ProviderError(f"DeepSeek 整理失败，原始内容未保存：{exc}") from exc
        if any(student_id not in allowed_ids for student_id in draft.student_ids):
            raise ProviderError("DeepSeek 返回了候选名单之外的学生，已拒绝该结果")
        return draft


def get_llm_provider() -> LLMProvider:
    return DeepSeekProvider() if settings.llm_provider.lower() == "deepseek" else MockLLMProvider()
