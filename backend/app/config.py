from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_secret: str = "dev-only-change-me"
    admin_username: str = "admin"
    admin_password: str = "change-me"
    studentlog_port: int = 8765
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
