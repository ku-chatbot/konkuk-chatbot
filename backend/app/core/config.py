from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    upstage_api_key: str | None = None
    upstage_parse_url: str = "https://api.upstage.ai/v1/document-digitization"
    local_embedding_model: str = "BAAI/bge-m3"
    embedding_server_url: str = "http://127.0.0.1:9000"
    embedding_request_timeout_seconds: float = 60.0
    tavily_api_key: str | None = None
    tavily_search_url: str = "https://api.tavily.com/search"
    tavily_request_timeout_seconds: float = 15.0
    enable_web_search: bool = False
    web_search_domains: str = "konkuk.ac.kr,www.konkuk.ac.kr,cse.konkuk.ac.kr,kupis.konkuk.ac.kr,kuis.konkuk.ac.kr,grad.konkuk.ac.kr,ipsi.konkuk.ac.kr,dorm.konkuk.ac.kr,library.konkuk.ac.kr,startup.konkuk.ac.kr"
    database_url: str = "sqlite:///./kubot.db"
    secret_key: str = "change-this-secret"
    access_token_expire_minutes: int = 120
    frontend_origin: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
