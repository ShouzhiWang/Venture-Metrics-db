from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/data_center_agent",
        alias="DATABASE_URL",
    )
    demo_read_database_url: str | None = Field(default=None, alias="DEMO_READ_DATABASE_URL")
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
    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")
    openai_embedding_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL")
    local_embedding_model: str = Field(default="Qwen/Qwen3-Embedding-0.6B", alias="LOCAL_EMBEDDING_MODEL")
    local_embedding_fallback_model: str = Field(default="BAAI/bge-m3", alias="LOCAL_EMBEDDING_FALLBACK_MODEL")
    embedding_dimension: int = Field(default=1024, alias="EMBEDDING_DIMENSION")
    embedding_normalize: bool = Field(default=True, alias="EMBEDDING_NORMALIZE")
    embedding_device: str = Field(default="auto", alias="EMBEDDING_DEVICE")
    embedding_model_cache_dir: Path | None = Field(default=None, alias="EMBEDDING_MODEL_CACHE_DIR")
    search_index_batch_size: int = Field(default=100, alias="SEARCH_INDEX_BATCH_SIZE")
    search_index_max_text_chars: int = Field(default=6000, alias="SEARCH_INDEX_MAX_TEXT_CHARS")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("embedding_model_cache_dir", mode="before")
    @classmethod
    def empty_path_as_none(cls, value: str | Path | None) -> str | Path | None:
        if value == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
