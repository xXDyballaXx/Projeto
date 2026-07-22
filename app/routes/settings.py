from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, User
from app.repositories.audit import audit
from app.security.auth import get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/settings", tags=["Configurações"])


class ProfileUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    company: str | None = Field(None, min_length=2, max_length=160)
    email: EmailStr | None = None
    timezone: str | None = None
    daily_limit: int | None = Field(None, ge=1, le=100000)
    unsubscribe_policy: str | None = Field(None, max_length=2000)
    sending_preferences: dict | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Informe um fuso horário IANA válido.") from exc
        return value


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


@router.get("/profile")
def get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company = db.get(Company, user.company_id)
    return {
        "name": user.name,
        "email": user.email,
        "company": company.name,
        "timezone": company.timezone,
        "daily_limit": company.daily_limit,
        "unsubscribe_policy": company.unsubscribe_policy,
        "sending_preferences": company.sending_preferences,
        "role": user.role.value,
    }


@router.patch("/profile")
def update_profile(data: ProfileUpdate, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company = db.get(Company, user.company_id)
    if data.email and db.scalar(select(User).where(func.lower(User.email) == data.email.lower(), User.id != user.id)):
        raise HTTPException(409, "E-mail já utilizado.")
    if data.name: user.name = data.name
    if data.email: user.email = data.email.lower()
    if data.company: company.name = data.company
    if data.timezone: company.timezone = data.timezone
    if data.daily_limit: company.daily_limit = data.daily_limit
    if data.unsubscribe_policy is not None: company.unsubscribe_policy = data.unsubscribe_policy
    if data.sending_preferences is not None: company.sending_preferences = data.sending_preferences
    audit(
        db,
        "settings.profile_updated",
        user,
        "company",
        company.id,
        {"fields": sorted(data.model_fields_set)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"message": "Configurações atualizadas."}


@router.post("/password")
def update_password(
    data: PasswordUpdate,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Senha atual incorreta.")
    if not any(c.isalpha() for c in data.new_password) or not any(c.isdigit() for c in data.new_password):
        raise HTTPException(400, "A nova senha deve conter letras e números.")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    audit(
        db,
        "settings.password_updated",
        user,
        "user",
        user.id,
        ip=request.client.host if request.client else None,
    )
    db.commit()
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")
    return {"message": "Senha alterada. Entre novamente.", "reauthenticate": True}
