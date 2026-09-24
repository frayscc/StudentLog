import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from .config import settings
from .providers import ProviderError


@dataclass(frozen=True)
class ASRResult:
    transcript: str
    elapsed_ms: int


class LocalASRProvider(ABC):
    name = "unknown"
    model_folder = ""
    remote_model = ""

    def __init__(self) -> None:
        self._model = None
        self._load_lock = Lock()

    @property
    def model_dir(self) -> Path:
        return settings.models_dir / self.model_folder

    @property
    def installed(self) -> bool:
        return self.model_dir.exists() and any(path.name != ".gitkeep" for path in self.model_dir.iterdir())

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _model_reference(self) -> str:
        if self.installed:
            return str(self.model_dir)
        if settings.asr_allow_model_download:
            return self.remote_model
        raise ProviderError(f"{self.name} 模型尚未安装。请先运行 launcher/download_asr_models.py {self.name}")

    def _get_model(self):
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is None:
                try:
                    import torch
                    from funasr import AutoModel
                except ImportError as exc:
                    raise ProviderError("本地语音组件未安装，请安装 backend/requirements-asr.txt") from exc
                torch.set_num_threads(max(1, settings.asr_cpu_threads))
                os.environ.setdefault("OMP_NUM_THREADS", str(max(1, settings.asr_cpu_threads)))
                try:
                    self._model = self._build_model(AutoModel, self._model_reference())
                except ProviderError:
                    raise
                except Exception as exc:
                    raise ProviderError(f"{self.name} 模型初始化失败：{exc}") from exc
        return self._model

    @abstractmethod
    def _build_model(self, auto_model, model_reference: str): ...

    @abstractmethod
    def _generate(self, model, audio_path: Path, hotwords: list[str] | None, language: str) -> str: ...

    async def transcribe(self, audio_path: Path, hotwords: list[str] | None = None, language: str = "zh") -> ASRResult:
        started = time.perf_counter()

        def run() -> str:
            model = self._get_model()
            return self._generate(model, audio_path, hotwords, language)

        try:
            transcript = await asyncio.to_thread(run)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"{self.name} 本地识别失败：{exc}") from exc
        transcript = transcript.strip()
        if not transcript:
            raise ProviderError(f"{self.name} 未识别到文字")
        return ASRResult(transcript=transcript, elapsed_ms=round((time.perf_counter() - started) * 1000))


def _first_text(result) -> str:
    if isinstance(result, list) and result:
        result = result[0]
    if isinstance(result, dict):
        return str(result.get("text", ""))
    return str(result or "")


class ParaformerProvider(LocalASRProvider):
    name = "paraformer"
    model_folder = "paraformer"
    remote_model = "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"

    def _build_model(self, auto_model, model_reference: str):
        return auto_model(model=model_reference, device="cpu", disable_update=True)

    def _generate(self, model, audio_path: Path, hotwords: list[str] | None, language: str) -> str:
        result = model.generate(input=str(audio_path), hotword=" ".join(hotwords or []), language=language)
        return _first_text(result)


class SenseVoiceProvider(LocalASRProvider):
    name = "sensevoice"
    model_folder = "sensevoice"
    remote_model = "iic/SenseVoiceSmall"

    def _build_model(self, auto_model, model_reference: str):
        return auto_model(model=model_reference, device="cpu", disable_update=True)

    def _generate(self, model, audio_path: Path, hotwords: list[str] | None, language: str) -> str:
        result = _first_text(model.generate(input=str(audio_path), language=language, use_itn=True, batch_size_s=60))
        try:
            from funasr.utils.postprocess_utils import rich_transcription_postprocess

            return rich_transcription_postprocess(result)
        except ImportError:
            return result


_providers: dict[str, LocalASRProvider] = {
    "paraformer": ParaformerProvider(),
    "sensevoice": SenseVoiceProvider(),
}


def get_asr_provider(name: str) -> LocalASRProvider:
    try:
        return _providers[name.lower()]
    except KeyError as exc:
        raise ProviderError("不支持的本地语音识别模型") from exc
