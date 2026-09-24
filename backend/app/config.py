from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_secret: str = "dev-only-change-me"
    admin_username: str = "admin"
    admin_password: str = "change-me"
    studentlog_port: int = 8765
    llm_provider: str = "mock"
    asr_provider: str = "mock"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    ali_asr_access_key_id: str = ""
    ali_asr_access_key_secret: str = ""
    ali_asr_app_key: str = ""
    ali_asr_token: str = ""
    ali_asr_endpoint: str = ""
    data_dir: Path = ROOT_DIR / "data"
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'app.db').as_posix()}"


settings = Settings()


def ensure_data_dirs() -> None:
    for name in ("", "avatars", "attachments", "backups"):
        (settings.data_dir / name).mkdir(parents=True, exist_ok=True)
