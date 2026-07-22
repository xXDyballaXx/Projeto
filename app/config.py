from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Divulgaí IA"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    admin_email: str = ""
    database_url: str = "sqlite:///./divulgai.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False
    secret_key: str = "development-only-change-me"
    jwt_secret_key: str = "development-jwt-change-me"
    encryption_key: str = ""
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    allowed_origins: str = "http://localhost:8000"
    base_url: str = "http://localhost:8000"
    max_upload_mb: int = 15
    daily_message_limit: int = 1000
    minute_message_limit: int = 30
    hourly_message_limit: int = 300
    large_campaign_threshold: int = 500
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    meta_graph_version: str = "v22.0"
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_access_token: str = ""
    facebook_page_id: str = ""
    facebook_page_access_token: str = ""
    instagram_account_id: str = ""
    ai_api_key: str = ""
    ai_api_url: str = "https://api.openai.com/v1/responses"
    ai_model: str = "gpt-4.1-mini"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def simulation_mode(self) -> bool:
        return self.environment != "production"

    def assert_production_secrets(self) -> None:
        if self.environment == "production" and (
            self.secret_key.startswith("development") or self.jwt_secret_key.startswith("development")
        ):
            raise RuntimeError("Configure SECRET_KEY e JWT_SECRET_KEY seguros em produção.")
        if self.environment == "production" and not self.encryption_key:
            raise RuntimeError("Configure ENCRYPTION_KEY em produção.")
        if self.environment == "production" and "*" in self.allowed_origins_list:
            raise RuntimeError("CORS curinga não é permitido em produção.")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_production_secrets()
    return settings


settings = get_settings()
