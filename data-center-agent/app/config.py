from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/data_center_agent",
        alias="DATABASE_URL",
    )
    storage_root: Path = Field(default=Path("data"), alias="STORAGE_ROOT")
    http_timeout_seconds: int = Field(default=30, alias="HTTP_TIMEOUT_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_batch_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_BATCH_MODEL")
    openai_batch_review_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_BATCH_REVIEW_MODEL")
    openai_batch_max_input_tokens_per_report: int = Field(
        default=45000,
        alias="OPENAI_BATCH_MAX_INPUT_TOKENS_PER_REPORT",
    )
    openai_batch_prompt_version: str = Field(default="codebook_extraction_v1", alias="OPENAI_BATCH_PROMPT_VERSION")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
