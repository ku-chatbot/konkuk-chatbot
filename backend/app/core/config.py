from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    upstage_api_key: str | None = None
    upstage_parse_url: str = "https://api.upstage.ai/v1/document-digitization"
    local_embedding_model: str = "nlpai-lab/KURE-v1"
    database_url: str = "sqlite:///./kubot.db"
    secret_key: str = "change-this-secret"
    access_token_expire_minutes: int = 120
    frontend_origin: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
