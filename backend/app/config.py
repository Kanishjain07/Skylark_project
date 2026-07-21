"""Application configuration loaded from environment variables / .env file."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Monday.com
    monday_api_token: str = ""
    monday_work_orders_board_id: str = ""
    monday_deals_board_id: str = ""
    monday_api_url: str = "https://api.monday.com/v2"

    # Groq (OpenAI-compatible API)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # App
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    board_cache_ttl_seconds: int = 120

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def monday_configured(self) -> bool:
        return bool(
            self.monday_api_token
            and self.monday_work_orders_board_id
            and self.monday_deals_board_id
        )

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
