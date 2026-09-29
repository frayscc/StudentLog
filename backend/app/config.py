from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_secret: str = "dev-only-change-me"
    studentlog_port: int = 8765
    llm_provider: str = "mock"
    asr_provider: str = "paraformer"
    asr_cpu_threads: int = 6
    asr_allow_model_download: bool = False
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    data_dir: Path = ROOT_DIR / "data"
    models_dir: Path = ROOT_DIR / "models"
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"


settings = Settings()


def ensure_data_dirs() -> None:
    for name in ("", "avatars", "attachments", "backups", "temp_audio"):
        (settings.data_dir / name).mkdir(parents=True, exist_ok=True)
    for name in ("paraformer", "sensevoice"):
        (settings.models_dir / name).mkdir(parents=True, exist_ok=True)
