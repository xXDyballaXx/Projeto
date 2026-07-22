from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models import Company, Role, User
from app.repositories.audit import audit
from app.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse
from app.security.auth import create_token, decode_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(data: RegisterRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "E-mail já cadastrado.")
    company = Company(name=data.company_name)
    db.add(company)
    db.flush()
    role = Role.admin if settings.admin_email and email == settings.admin_email.lower() else Role.user
    user = User(company_id=company.id, name=data.name, email=email, password_hash=hash_password(data.password), role=role)
    db.add(user)
    db.flush()
    audit(db, "user.registered", user, "user", user.id, ip=request.client.host if request.client else None)
    db.commit()
    access, refresh = create_token(user), create_token(user, "refresh")
    response.set_cookie("access_token", access, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=1800)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    now = datetime.now(timezone.utc)
    if user and user.locked_until:
        locked_until = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            raise HTTPException(429, "Muitas tentativas. Tente novamente mais tarde.")
    if not user or not verify_password(data.password, user.password_hash):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_login_attempts = 0
            db.commit()
        raise HTTPException(401, "E-mail ou senha inválidos.")
    if not user.is_active:
        raise HTTPException(403, "Conta inativa.")
    user.failed_login_attempts, user.locked_until = 0, None
    audit(db, "user.login", user, "user", user.id, ip=request.client.host if request.client else None)
    db.commit()
    access, refresh = create_token(user), create_token(user, "refresh")
    response.set_cookie("access_token", access, httponly=True, secure=request.url.scheme == "https", samesite="strict", max_age=1800)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(data.refresh_token, "refresh")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(401, "Conta indisponível.")
    return TokenResponse(access_token=create_token(user), refresh_token=create_token(user, "refresh"))


@router.post("/forgot-password")
def forgot_password():
    return {"message": "Se o e-mail existir, enviaremos instruções. Configure um provedor de e-mail para entrega real."}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Sessão encerrada."}
