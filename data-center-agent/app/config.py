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
    demo_llm_provider: str = Field(default="mimo", alias="DEMO_LLM_PROVIDER")
    demo_llm_base_url: str = Field(default="https://api.mimo-v2.com/v1", alias="DEMO_LLM_BASE_URL")
    demo_llm_model: str = Field(default="mimo-v2.5", alias="DEMO_LLM_MODEL")
    demo_llm_api_key: str | None = Field(default=None, alias="DEMO_LLM_API_KEY")
    demo_llm_timeout_seconds: int = Field(default=30, alias="DEMO_LLM_TIMEOUT_SECONDS")
    demo_llm_max_output_tokens: int = Field(default=900, alias="DEMO_LLM_MAX_OUTPUT_TOKENS")
    auth_session_secret: str | None = Field(default=None, alias="AUTH_SESSION_SECRET")
    auth_cookie_secure: bool = Field(default=False, alias="AUTH_COOKIE_SECURE")
    auth_session_ttl_seconds: int = Field(default=60 * 60 * 24 * 14, alias="AUTH_SESSION_TTL_SECONDS")
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
