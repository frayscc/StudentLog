import json
from pathlib import Path
from threading import Lock

from .config import settings


VALID_ASR_PROVIDERS = {"paraformer", "sensevoice"}
_lock = Lock()


def _config_path() -> Path:
    return settings.data_dir / "config.json"


def read_local_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def get_asr_provider_name() -> str:
    configured = str(read_local_config().get("asr_provider", settings.asr_provider)).lower()
    return configured if configured in VALID_ASR_PROVIDERS else "paraformer"


def save_asr_provider_name(provider: str) -> None:
    provider = provider.lower()
    if provider not in VALID_ASR_PROVIDERS:
        raise ValueError("仅支持 paraformer 或 sensevoice")
    update_local_config({"asr_provider": provider})


def update_local_config(values: dict) -> None:
    with _lock:
        payload = read_local_config()
        payload.update(values)
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)


def get_llm_config() -> dict:
    local = read_local_config()
    provider = str(local.get("llm_provider", settings.llm_provider)).lower()
    api_key = local.get("deepseek_api_key", settings.deepseek_api_key)
    return {
        "provider": provider if provider in {"mock", "deepseek"} else "mock",
        "api_key": api_key if isinstance(api_key, str) else "",
    }
