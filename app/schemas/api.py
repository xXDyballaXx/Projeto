from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator

from app.models import CampaignStatus, Channel


class RegisterRequest(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    company_name: Annotated[str, Field(min_length=2, max_length=160)]
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=72)]
    password_confirmation: str
    accept_terms: bool

    @model_validator(mode="after")
    def validate_registration(self):
        if self.password != self.password_confirmation:
            raise ValueError("As senhas não coincidem.")
        if not self.accept_terms:
            raise ValueError("É necessário aceitar os termos.")
        if not any(c.isdigit() for c in self.password) or not any(c.isalpha() for c in self.password):
            raise ValueError("A senha deve conter letras e números.")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ConsentInput(BaseModel):
    channel: Channel
    is_granted: bool = True
    source: Annotated[str, Field(min_length=2, max_length=120)]
    proof: str | None = None


class ContactCreate(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    phone: str
    email: EmailStr | None = None
    tags: list[str] = []
    source: str = "manual"
    is_active: bool = True
    consents: list[ConsentInput] = []

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = "+" + "".join(filter(str.isdigit, value))
        if not 11 <= len(normalized) - 1 <= 15:
            raise ValueError("Informe o telefone com código do país.")
        return normalized


class ContactUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    tags: list[str] | None = None
    is_active: bool | None = None
    permanently_blocked: bool | None = None


class ConsentOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    channel: Channel
    is_granted: bool
    granted_at: datetime
    revoked_at: datetime | None
    source: str


class ContactOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str
    email: str | None
    tags: list
    source: str
    is_active: bool
    permanently_blocked: bool
    consents: list[ConsentOutput] = []
    created_at: datetime


class ContactListCreate(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    description: str | None = None
    contact_ids: list[int] = []


class CampaignCreate(BaseModel):
    internal_name: Annotated[str, Field(min_length=2, max_length=160)]
    title: Annotated[str, Field(min_length=2, max_length=200)]
    body: Annotated[str, Field(min_length=2, max_length=4096)]
    call_to_action: str | None = None
    link_url: HttpUrl | None = None
    channel: Channel
    contact_list_id: int | None = None
    timezone: str = "America/Sao_Paulo"
    scheduled_at: datetime | None = None
    status: CampaignStatus = CampaignStatus.draft
    confirm_large_campaign: bool = False

    @field_validator("link_url")
    @classmethod
    def require_secure_url(cls, value):
        if value and value.scheme != "https" and value.host not in {"localhost", "127.0.0.1"}:
            raise ValueError("Use uma URL HTTPS.")
        return value


class CampaignOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    internal_name: str
    title: str
    body: str
    call_to_action: str | None
    link_url: str | None
    image_path: str | None
    video_path: str | None
    channel: Channel
    contact_list_id: int | None
    timezone: str
    status: CampaignStatus
    scheduled_at: datetime | None
    requires_confirmation: bool
    created_at: datetime


class CampaignUpdate(BaseModel):
    internal_name: Annotated[str, Field(min_length=2, max_length=160)] | None = None
    title: Annotated[str, Field(min_length=2, max_length=200)] | None = None
    body: Annotated[str, Field(min_length=2, max_length=4096)] | None = None
    call_to_action: str | None = None
    link_url: HttpUrl | None = None
    channel: Channel | None = None
    contact_list_id: int | None = None
    timezone: str | None = None
    scheduled_at: datetime | None = None

    @field_validator("link_url")
    @classmethod
    def require_secure_url(cls, value):
        if value and value.scheme != "https" and value.host not in {"localhost", "127.0.0.1"}:
            raise ValueError("Use uma URL HTTPS.")
        return value


class GenerateContentRequest(BaseModel):
    product: str
    audience: str
    objective: str
    tone: str = "profissional"
    required_information: str = ""
    channel: Channel


class IntegrationCreate(BaseModel):
    provider: Annotated[str, Field(pattern="^(whatsapp|facebook|instagram|ai)$")]
    external_account_id: str | None = None
    credentials: dict[str, str] = {}
