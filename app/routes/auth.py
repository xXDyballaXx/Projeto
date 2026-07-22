from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings
from app.models import Company, Role, User
from app.repositories.audit import audit
from app.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse
from app.security.auth import create_token, decode_token, get_current_user, hash_password, set_session_cookies, verify_password

router = APIRouter(prefix="/api/auth", tags=["Autenticação"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(data: RegisterRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    email = data.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "E-mail já cadastrado.")
    company = Company(name=data.company_name)
    db.add(company)
    try:
        db.flush()
        user = User(
            company_id=company.id,
            name=data.name,
            email=email,
            password_hash=hash_password(data.password),
            role=Role.user,
        )
        db.add(user)
        db.flush()
        audit(db, "user.registered", user, "user", user.id, ip=request.client.host if request.client else None)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "E-mail já cadastrado.") from exc
    access, refresh = create_token(user), create_token(user, "refresh")
    set_session_cookies(response, request, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    now = datetime.now(timezone.utc)
    if user and user.locked_until:
        locked_until = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            audit(db, "user.login_blocked", user, "user", user.id, ip=request.client.host if request.client else None)
            db.commit()
            raise HTTPException(429, "Muitas tentativas. Tente novamente mais tarde.")
    if not user or not verify_password(data.password, user.password_hash):
        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
                user.failed_login_attempts = 0
        audit(
            db,
            "user.login_failed",
            user,
            "user" if user else None,
            user.id if user else None,
            {"reason": "invalid_credentials"},
            ip=request.client.host if request.client else None,
        )
        db.commit()
        raise HTTPException(401, "E-mail ou senha inválidos.")
    if not user.is_active:
        audit(db, "user.login_blocked", user, "user", user.id, {"reason": "inactive"}, ip=request.client.host if request.client else None)
        db.commit()
        raise HTTPException(403, "Conta inativa.")
    user.failed_login_attempts, user.locked_until = 0, None
    audit(db, "user.login", user, "user", user.id, ip=request.client.host if request.client else None)
    db.commit()
    access, refresh = create_token(user), create_token(user, "refresh")
    set_session_cookies(response, request, access, refresh)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response,
    request: Request,
    data: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    refresh_token = data.refresh_token if data and data.refresh_token else request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(401, "Sessão de atualização ausente.")
    payload = decode_token(refresh_token, "refresh")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(401, "Sessão de atualização inválida.") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Conta indisponível.")
    if payload.get("ver") != user.token_version:
        raise HTTPException(401, "Sessão de atualização revogada.")
    user.token_version += 1
    audit(db, "user.session_refreshed", user, "user", user.id, ip=request.client.host if request.client else None)
    db.commit()
    access, rotated_refresh = create_token(user), create_token(user, "refresh")
    set_session_cookies(response, request, access, rotated_refresh)
    return TokenResponse(access_token=access, refresh_token=rotated_refresh)


@router.post("/forgot-password")
def forgot_password():
    return {
        "configured": False,
        "message": "A recuperação por e-mail ainda não está configurada. Solicite a redefinição ao administrador da sua empresa.",
    }


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.token_version += 1
    audit(db, "user.logout", user, "user", user.id, ip=request.client.host if request.client else None)
    db.commit()
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("refresh_token", path="/api/auth")
    return {"message": "Sessão encerrada."}
