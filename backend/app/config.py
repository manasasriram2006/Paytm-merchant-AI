from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Paytm Business AI"
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"
    llm_provider: str = "mock"
    llm_api_key: str | None = None
    ai_provider: str | None = Field(default=None, alias="AI_PROVIDER")
    ai_api_key: str | None = Field(default=None, alias="AI_API_KEY")
    ocr_provider: str = "unconfigured"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    sarvam_api_key: str | None = Field(default=None, alias="SARVAM_API_KEY")
    sarvam_base_url: str = Field(default="https://api.sarvam.ai", alias="SARVAM_BASE_URL")
    sarvam_timeout_seconds: int = Field(default=30, alias="SARVAM_TIMEOUT_SECONDS")

    class Config:
        env_file = (Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[1] / ".env")
        env_file_encoding = "utf-8"

    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError(
                "DATABASE_URL is missing. Set DATABASE_URL=postgresql+psycopg2://USER@HOST/DATABASE "
                "before starting the FastAPI application."
            )
        if self.database_url.startswith("sqlite"):
            raise RuntimeError("SQLite is not supported. DATABASE_URL must point to PostgreSQL.")
        if not self.database_url.startswith(("postgresql+psycopg2://", "postgresql+psycopg://", "postgresql://")):
            raise RuntimeError("DATABASE_URL must be a PostgreSQL SQLAlchemy URL.")
        database_name = urlparse(self.database_url).path.lstrip("/")
        if database_name != "paytm_business_ai":
            raise RuntimeError("DATABASE_URL must connect to the paytm_business_ai PostgreSQL database only.")
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
