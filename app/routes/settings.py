from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Company, User
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


class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


@router.patch("/profile")
def update_profile(data: ProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    db.commit()
    return {"message": "Configurações atualizadas."}


@router.post("/password")
def update_password(data: PasswordUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Senha atual incorreta.")
    if not any(c.isalpha() for c in data.new_password) or not any(c.isdigit() for c in data.new_password):
        raise HTTPException(400, "A nova senha deve conter letras e números.")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"message": "Senha alterada."}
