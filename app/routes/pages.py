from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Role, User
from app.security.auth import create_token, decode_token, set_session_cookies

router = APIRouter(tags=["Interface"])
templates = Jinja2Templates(directory="app/templates")


def render(request: Request, template: str, **context):
    return templates.TemplateResponse(request=request, name=template, context={"app_name": settings.app_name, "simulation_mode": settings.simulation_mode, **context})


def page_user(request: Request, db: Session) -> tuple[User | None, tuple[str, str] | None]:
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = decode_token(token)
            user = db.get(User, int(payload["sub"]))
            if user and user.is_active and payload.get("ver") == user.token_version:
                return user, None
        except (HTTPException, KeyError, TypeError, ValueError):
            pass

    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        return None, None
    try:
        payload = decode_token(refresh_token, "refresh")
        user = db.get(User, int(payload["sub"]))
    except (HTTPException, KeyError, TypeError, ValueError):
        return None, None
    if not user or not user.is_active or payload.get("ver") != user.token_version:
        return None, None
    user.token_version += 1
    db.commit()
    return user, (create_token(user), create_token(user, "refresh"))


def private_page(request: Request, db: Session, template: str, page: str, *, admin_only: bool = False):
    user, renewed_tokens = page_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if admin_only and user.role != Role.admin:
        return RedirectResponse("/dashboard", status_code=303)
    response = render(
        request,
        template,
        page=page,
        current_user=user,
        current_company=user.company,
        is_admin=user.role == Role.admin,
    )
    if renewed_tokens:
        set_session_cookies(response, request, *renewed_tokens)
    return response


@router.get("/", response_class=HTMLResponse)
def home(request: Request): return render(request, "landing.html")


@router.get("/login", response_class=HTMLResponse)
def login(request: Request): return render(request, "login.html")


@router.get("/cadastro", response_class=HTMLResponse)
def register(request: Request): return render(request, "register.html")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)): return private_page(request, db, "dashboard.html", "dashboard")


@router.get("/contatos", response_class=HTMLResponse)
def contacts(request: Request, db: Session = Depends(get_db)): return private_page(request, db, "contacts.html", "contacts")


@router.get("/campanhas", response_class=HTMLResponse)
def campaigns(request: Request, db: Session = Depends(get_db)): return private_page(request, db, "campaigns.html", "campaigns")


@router.get("/conteudo-ia", response_class=HTMLResponse)
def content(request: Request, db: Session = Depends(get_db)): return private_page(request, db, "content.html", "content")


@router.get("/integracoes", response_class=HTMLResponse)
def integrations(request: Request, db: Session = Depends(get_db)): return private_page(request, db, "integrations.html", "integrations")


@router.get("/historico", response_class=HTMLResponse)
def history(request: Request, db: Session = Depends(get_db)): return private_page(request, db, "history.html", "history")


@router.get("/configuracoes", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)): return private_page(request, db, "settings.html", "settings")


@router.get("/administracao", response_class=HTMLResponse)
def administration(request: Request, db: Session = Depends(get_db)): return private_page(request, db, "admin.html", "admin", admin_only=True)


@router.get("/privacidade", response_class=HTMLResponse)
def privacy(request: Request): return render(request, "privacy.html")


@router.get("/termos", response_class=HTMLResponse)
def terms(request: Request): return render(request, "terms.html")
