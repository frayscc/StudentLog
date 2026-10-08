import json
from abc import ABC, abstractmethod
from datetime import datetime

import httpx
from pydantic import ValidationError

from .config import settings
from .local_config import get_llm_config
from .schemas import NameCandidate, StructuredEventDraft, SummarySections


class ProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    name = "unknown"

    @abstractmethod
    async def structure(self, transcript: str, candidates: list[NameCandidate], selected_ids: list[str]) -> StructuredEventDraft: ...

    @abstractmethod
    async def summarize(self, events: list[dict]) -> SummarySections: ...


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

    async def summarize(self, events: list[dict]) -> SummarySections:
        learning, discipline, teacher, family, actions, follow_up = [], [], [], [], [], []
        for event in events:
            fact = f"{event['occurred_at'][:10]}：{event['event_description']}"
            category = event.get("category", "")
            if category in {"课堂表现", "作业", "表扬"}:
                learning.append(fact)
            if "纪律" in category:
                discipline.append(fact)
            if category == "师生沟通":
                teacher.append(fact)
            if category == "家校沟通":
                family.append(fact)
            if event.get("teacher_action"):
                actions.append(f"{event['occurred_at'][:10]}：{event['teacher_action']}")
            if event.get("follow_up"):
                follow_up.append(f"{event['occurred_at'][:10]}：{event['follow_up']}")
        return SummarySections(
            learning_records=learning,
            discipline_records=discipline,
            teacher_communication=teacher,
            family_communication=family,
            actions_taken=actions,
            follow_up_items=follow_up,
        )


SYSTEM_PROMPT = """你是学生事件记录整理助手。只整理教师明确表达的事实，不评价学生，不推断心理、人格、学习意愿或家庭情况，不添加原文没有的事实。把口语去重并调整语序。教师的主观判断不能被改写成客观事实；没有可验证事实时应标明“教师主观观察”或省略该判断。学生只能从候选 student_id 中选择，禁止创造姓名或 ID；不确定时返回空数组。输出严格 JSON，字段为 student_ids、occurred_at、location、category、event_description、student_response、teacher_action、follow_up、tags。occurred_at 使用 ISO 8601；无法确定具体时间时使用当前时间。空值使用 null。"""
SUMMARY_SYSTEM_PROMPT = """你是学生事件档案的事实摘要助手。只能根据输入事件归纳，不得补充事实，不得推断心理、人格、能力、学习意愿、家庭情况，不得评分、排名或生成学生画像。保持日期和具体行为，合并明显重复内容。输出严格 JSON，字段为 learning_records、discipline_records、teacher_communication、family_communication、actions_taken、follow_up_items，每个字段都是简短事实字符串数组；没有内容时返回空数组。"""


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    async def _complete(self, body: dict) -> str:
        api_key = get_llm_config()["api_key"]
        if not api_key:
            raise ProviderError("DeepSeek API Key 尚未配置，请在系统设置中填写")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("Expected text content")
                return content
        except httpx.TimeoutException as exc:
            raise ProviderError("DeepSeek 请求超时，原始内容已保留，请重试") from exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            message = ("API Key 无效或没有访问权限，请检查系统设置" if code in {401, 403}
                       else "请求过于频繁或账户额度不足，请稍后重试" if code == 429
                       else "服务暂时不可用，请稍后重试")
            raise ProviderError(f"DeepSeek {message}") from exc
        except httpx.RequestError as exc:
            raise ProviderError("无法连接 DeepSeek，请检查网络后重试") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("DeepSeek 返回格式异常，请重试") from exc

    async def structure(self, transcript: str, candidates: list[NameCandidate], selected_ids: list[str]) -> StructuredEventDraft:
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
            content = await self._complete(body)
            draft = StructuredEventDraft.model_validate_json(content)
        except ValidationError as exc:
            raise ProviderError("DeepSeek 整理结果格式不正确，原始内容已保留，请重试") from exc
        if any(student_id not in allowed_ids for student_id in draft.student_ids):
            raise ProviderError("DeepSeek 返回了候选名单之外的学生，已拒绝该结果")
        for field in ("location", "category", "event_description", "student_response", "teacher_action", "follow_up"):
            value = getattr(draft, field)
            if value:
                for item in candidates:
                    value = value.replace(item.student_id, item.name)
                setattr(draft, field, value)
        draft.tags = [self._restore_names(tag, candidates) for tag in draft.tags]
        return draft

    @staticmethod
    def _restore_names(value: str, candidates: list[NameCandidate]) -> str:
        for item in candidates:
            value = value.replace(item.student_id, item.name)
        return value

    async def summarize(self, events: list[dict]) -> SummarySections:
        body = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"events": events}, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 1800,
            "stream": False,
        }
        try:
            content = await self._complete(body)
            return SummarySections.model_validate_json(content)
        except ValidationError as exc:
            raise ProviderError("阶段性摘要格式不正确，未修改任何档案，请重试") from exc


def get_llm_provider() -> LLMProvider:
    return DeepSeekProvider() if str(get_llm_config()["provider"]).lower() == "deepseek" else MockLLMProvider()
