from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Role, User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def create_token(user: User, token_type: str = "access") -> str:
    expires = datetime.now(timezone.utc) + (
        timedelta(minutes=settings.access_token_minutes)
        if token_type == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    payload = {"sub": str(user.id), "company_id": user.company_id, "role": user.role.value, "type": token_type, "exp": expires}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessão inválida ou expirada.") from exc
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="Tipo de token inválido.")
    return payload


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    payload = decode_token(token)
    user = db.scalar(select(User).where(User.id == int(payload["sub"]), User.is_active.is_(True)))
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado ou inativo.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return user

