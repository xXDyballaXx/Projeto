from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Divulgaí IA"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    admin_email: str = ""
    database_url: str = "sqlite:///./divulgai.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False
    external_services_enabled: bool = False
    secret_key: str = "development-only-change-me"
    jwt_secret_key: str = "development-jwt-change-me"
    encryption_key: str = ""
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    allowed_origins: str = "http://localhost:8000"
    base_url: str = "http://localhost:8000"
    max_upload_mb: int = 15
    max_company_upload_mb: int = 250
    daily_message_limit: int = 1000
    minute_message_limit: int = 30
    hourly_message_limit: int = 300
    large_campaign_threshold: int = 500
    daily_ai_generation_limit: int = 100
    minute_ai_generation_limit: int = 5
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
    ai_max_output_tokens: int = 1200

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug_value(cls, value):
        """Avoid collisions with tools that export DEBUG=release/debug globally."""
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production", "prod"}:
                return False
            if normalized in {"debug", "development", "dev"}:
                return True
        return value

    @model_validator(mode="after")
    def isolate_test_environment(self):
        if self.environment == "test":
            self.celery_task_always_eager = True
            self.external_services_enabled = False
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def simulation_mode(self) -> bool:
        return self.environment == "test" or not self.external_services_enabled

    def assert_production_secrets(self) -> None:
        if self.environment != "production":
            return
        insecure_values = {"", "development-only-change-me", "development-jwt-change-me"}
        if (
            self.secret_key in insecure_values
            or self.jwt_secret_key in insecure_values
            or len(self.secret_key) < 32
            or len(self.jwt_secret_key) < 32
            or self.secret_key == self.jwt_secret_key
        ):
            raise RuntimeError("Configure SECRET_KEY e JWT_SECRET_KEY distintos e seguros em produção.")
        if not self.encryption_key:
            raise RuntimeError("Configure ENCRYPTION_KEY em produção.")
        try:
            Fernet(self.encryption_key.encode())
        except (TypeError, ValueError) as exc:
            raise RuntimeError("ENCRYPTION_KEY não é uma chave Fernet válida.") from exc
        if not self.allowed_origins_list or "*" in self.allowed_origins_list:
            raise RuntimeError("Configure origens CORS explícitas em produção.")
        base_url = urlsplit(self.base_url)
        if base_url.scheme != "https" or not base_url.netloc:
            raise RuntimeError("BASE_URL deve usar HTTPS em produção.")
        if any(urlsplit(origin).scheme != "https" or not urlsplit(origin).netloc for origin in self.allowed_origins_list):
            raise RuntimeError("Todas as origens CORS devem usar HTTPS em produção.")
        database_url = self.database_url.casefold()
        if database_url.startswith("sqlite"):
            raise RuntimeError("Use PostgreSQL em produção; SQLite é destinado a desenvolvimento e testes.")
        if "://divulgai:divulgai@" in database_url:
            raise RuntimeError("Troque a senha padrão do PostgreSQL antes de iniciar em produção.")
        if self.debug:
            raise RuntimeError("DEBUG deve permanecer desativado em produção.")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_production_secrets()
    return settings


settings = get_settings()
