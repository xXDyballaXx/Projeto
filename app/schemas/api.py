from datetime import datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    refresh_token: str | None = None


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
    tags: list[str] = Field(default_factory=list, max_length=50)
    source: Annotated[str, Field(min_length=2, max_length=120)] = "manual"
    is_active: bool = True
    consents: list[ConsentInput] = Field(default_factory=list, max_length=10)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = "+" + "".join(filter(str.isdigit, value))
        if not 11 <= len(normalized) - 1 <= 15:
            raise ValueError("Informe o telefone com código do país.")
        return normalized

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            tag = value.strip()
            if not tag or len(tag) > 40:
                raise ValueError("Cada etiqueta deve ter entre 1 e 40 caracteres.")
            if tag not in normalized:
                normalized.append(tag)
        return normalized


class ContactUpdate(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)] | None = None
    phone: str | None = None
    email: EmailStr | None = None
    tags: Annotated[list[str], Field(max_length=50)] | None = None
    source: Annotated[str, Field(min_length=2, max_length=120)] | None = None
    is_active: bool | None = None
    permanently_blocked: bool | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        return ContactCreate.validate_phone(value) if value is not None else None

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str] | None) -> list[str] | None:
        return ContactCreate.validate_tags(values) if values is not None else None

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("name", "phone", "tags", "source", "is_active", "permanently_blocked"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"O campo {field} não pode ser nulo.")
        return self


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
    description: Annotated[str, Field(max_length=255)] | None = None
    contact_ids: list[int] = Field(default_factory=list, max_length=10000)

    @field_validator("contact_ids")
    @classmethod
    def validate_contact_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("Os contatos informados são inválidos.")
        return list(dict.fromkeys(values))


class ContactListUpdate(BaseModel):
    name: Annotated[str, Field(min_length=2, max_length=120)] | None = None
    description: Annotated[str, Field(max_length=255)] | None = None
    contact_ids: list[int] | None = Field(None, max_length=10000)

    @field_validator("contact_ids")
    @classmethod
    def validate_contact_ids(cls, values: list[int] | None) -> list[int] | None:
        return ContactListCreate.validate_contact_ids(values) if values is not None else None

    @model_validator(mode="after")
    def reject_null_name(self):
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("O nome da lista não pode ser nulo.")
        return self


class CampaignCreate(BaseModel):
    internal_name: Annotated[str, Field(min_length=2, max_length=160)]
    title: Annotated[str, Field(min_length=2, max_length=200)]
    body: Annotated[str, Field(min_length=2, max_length=4096)]
    call_to_action: Annotated[str, Field(max_length=120)] | None = None
    link_url: HttpUrl | None = None
    channel: Channel
    contact_list_id: int | None = None
    message_template_id: int | None = Field(None, gt=0)
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "America/Sao_Paulo"
    scheduled_at: datetime | None = None
    status: CampaignStatus = CampaignStatus.draft
    confirm_large_campaign: bool = False

    @field_validator("link_url")
    @classmethod
    def require_secure_url(cls, value):
        if value and value.scheme != "https" and value.host not in {"localhost", "127.0.0.1"}:
            raise ValueError("Use uma URL HTTPS.")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Informe um fuso horário IANA válido.") from exc
        return value

    @field_validator("scheduled_at")
    @classmethod
    def validate_schedule(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        comparable = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if comparable <= datetime.now(timezone.utc):
            raise ValueError("Escolha uma data futura para o agendamento.")
        return comparable.astimezone(timezone.utc)

    @field_validator("status")
    @classmethod
    def validate_initial_status(cls, value: CampaignStatus) -> CampaignStatus:
        if value not in {CampaignStatus.draft, CampaignStatus.review}:
            raise ValueError("Uma nova campanha deve iniciar como rascunho ou revisão.")
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
    message_template_id: int | None
    timezone: str
    status: CampaignStatus
    scheduled_at: datetime | None
    requires_confirmation: bool
    created_at: datetime


class CampaignUpdate(BaseModel):
    internal_name: Annotated[str, Field(min_length=2, max_length=160)] | None = None
    title: Annotated[str, Field(min_length=2, max_length=200)] | None = None
    body: Annotated[str, Field(min_length=2, max_length=4096)] | None = None
    call_to_action: Annotated[str, Field(max_length=120)] | None = None
    link_url: HttpUrl | None = None
    channel: Channel | None = None
    contact_list_id: int | None = None
    message_template_id: int | None = Field(None, gt=0)
    timezone: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    scheduled_at: datetime | None = None

    @field_validator("link_url")
    @classmethod
    def require_secure_url(cls, value):
        if value and value.scheme != "https" and value.host not in {"localhost", "127.0.0.1"}:
            raise ValueError("Use uma URL HTTPS.")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return CampaignCreate.validate_timezone(value) if value is not None else None

    @field_validator("scheduled_at")
    @classmethod
    def validate_schedule(cls, value: datetime | None) -> datetime | None:
        return CampaignCreate.validate_schedule(value)

    @model_validator(mode="after")
    def reject_null_required_fields(self):
        for field in ("internal_name", "title", "body", "channel", "timezone"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"O campo {field} não pode ser nulo.")
        return self


class GenerateContentRequest(BaseModel):
    product: Annotated[str, Field(min_length=2, max_length=500)]
    audience: Annotated[str, Field(min_length=2, max_length=500)]
    objective: Annotated[str, Field(min_length=2, max_length=500)]
    tone: Annotated[str, Field(min_length=2, max_length=80)] = "profissional"
    required_information: Annotated[str, Field(max_length=3000)] = ""
    channel: Channel


class ContentApprovalRequest(BaseModel):
    content: Annotated[str, Field(min_length=2, max_length=12000)] | None = None


class IntegrationCreate(BaseModel):
    provider: Annotated[str, Field(pattern="^(whatsapp|facebook|instagram|ai)$")]
    external_account_id: Annotated[str, Field(max_length=255)] | None = None
    credentials: dict[str, str] = Field(default_factory=dict, max_length=10)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=10)

    @field_validator("credentials")
    @classmethod
    def validate_credentials(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if not key or len(key) > 80 or len(value) > 5000:
                raise ValueError("Uma credencial informada é inválida.")
        return values

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if not key or len(key) > 80 or len(value) > 500:
                raise ValueError("Um identificador adicional informado é inválido.")
        return values
