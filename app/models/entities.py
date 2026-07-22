import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    user = "user"
    admin = "admin"


class Channel(str, enum.Enum):
    whatsapp = "whatsapp"
    facebook = "facebook"
    instagram = "instagram"


class CampaignStatus(str, enum.Enum):
    draft = "draft"
    review = "review"
    scheduled = "scheduled"
    sending = "sending"
    sent = "sent"
    simulated = "simulated"
    cancelled = "cancelled"
    failed = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


contact_list_members = Table(
    "contact_list_members",
    Base.metadata,
    Column("contact_id", ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
    Column("contact_list_id", ForeignKey("contact_lists.id", ondelete="CASCADE"), primary_key=True),
)


class Company(TimestampMixin, Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    daily_limit: Mapped[int] = mapped_column(Integer, default=1000)
    sending_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    unsubscribe_policy: Mapped[str] = mapped_column(Text, default="Cancelar imediatamente ao receber solicitação do titular.")
    users: Mapped[list["User"]] = relationship(back_populates="company")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    company: Mapped[Company] = relationship(back_populates="users")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("company_id", "phone", name="uq_contact_company_phone"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(24), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(120), default="manual")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    permanently_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    lists: Mapped[list["ContactList"]] = relationship(secondary=contact_list_members, back_populates="contacts")
    consents: Mapped[list["Consent"]] = relationship(back_populates="contact", cascade="all, delete-orphan")


class ContactList(TimestampMixin, Base):
    __tablename__ = "contact_lists"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(255))
    contacts: Mapped[list[Contact]] = relationship(secondary=contact_list_members, back_populates="lists")


class Consent(TimestampMixin, Base):
    __tablename__ = "consents"
    __table_args__ = (Index("ix_consent_contact_channel_active", "contact_id", "channel", "is_granted"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    channel: Mapped[Channel] = mapped_column(Enum(Channel))
    is_granted: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(120))
    proof: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[Contact] = relationship(back_populates="consents")


class Campaign(TimestampMixin, Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    contact_list_id: Mapped[int | None] = mapped_column(ForeignKey("contact_lists.id"))
    message_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("message_templates.id", ondelete="SET NULL", name="fk_campaign_message_template")
    )
    internal_name: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    call_to_action: Mapped[str | None] = mapped_column(String(120))
    link_url: Mapped[str | None] = mapped_column(String(2048))
    image_path: Mapped[str | None] = mapped_column(String(500))
    video_path: Mapped[str | None] = mapped_column(String(500))
    channel: Mapped[Channel] = mapped_column(Enum(Channel), index=True)
    status: Mapped[CampaignStatus] = mapped_column(Enum(CampaignStatus), default=CampaignStatus.draft, index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipients: Mapped[list["CampaignRecipient"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class CampaignChannel(TimestampMixin, Base):
    __tablename__ = "campaign_channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    channel: Mapped[Channel] = mapped_column(Enum(Channel))
    external_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="pending")


class CampaignRecipient(TimestampMixin, Base):
    __tablename__ = "campaign_recipients"
    __table_args__ = (UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_contact"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    external_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid.uuid4().hex)
    error_message: Mapped[str | None] = mapped_column(String(500))
    campaign: Mapped[Campaign] = relationship(back_populates="recipients")
    contact: Mapped[Contact] = relationship()


class ScheduledTask(TimestampMixin, Base):
    __tablename__ = "scheduled_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    execute_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)


class MessageTemplate(TimestampMixin, Base):
    __tablename__ = "message_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    language: Mapped[str] = mapped_column(String(16), default="pt_BR")
    meta_template_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    body: Mapped[str] = mapped_column(Text)


class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("company_id", "provider", name="uq_integration_company_provider"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    external_account_id: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class ApiCredential(TimestampMixin, Base):
    __tablename__ = "api_credentials"
    __table_args__ = (UniqueConstraint("integration_id", "key_name", name="uq_credential_integration_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    integration_id: Mapped[int] = mapped_column(ForeignKey("integrations.id", ondelete="CASCADE"), index=True)
    key_name: Mapped[str] = mapped_column(String(80))
    encrypted_value: Mapped[str] = mapped_column(Text)
    masked_hint: Mapped[str] = mapped_column(String(32))


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"
    __table_args__ = (UniqueConstraint("external_id", "event_type", name="uq_delivery_external_event"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("campaign_recipients.id", ondelete="SET NULL"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class UnsubscribeRequest(Base):
    __tablename__ = "unsubscribe_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    channel: Mapped[Channel] = mapped_column(Enum(Channel))
    source: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(String(255))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GeneratedContent(TimestampMixin, Base):
    __tablename__ = "generated_contents"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    prompt_data: Mapped[dict] = mapped_column(JSON)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    provider: Mapped[str] = mapped_column(String(40), default="simulation")
