from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

router = APIRouter(tags=["Interface"])
templates = Jinja2Templates(directory="app/templates")


def render(request: Request, template: str, **context):
    return templates.TemplateResponse(request=request, name=template, context={"app_name": settings.app_name, "simulation_mode": settings.simulation_mode, **context})


@router.get("/", response_class=HTMLResponse)
def home(request: Request): return render(request, "landing.html")


@router.get("/login", response_class=HTMLResponse)
def login(request: Request): return render(request, "login.html")


@router.get("/cadastro", response_class=HTMLResponse)
def register(request: Request): return render(request, "register.html")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request): return render(request, "dashboard.html", page="dashboard")


@router.get("/contatos", response_class=HTMLResponse)
def contacts(request: Request): return render(request, "contacts.html", page="contacts")


@router.get("/campanhas", response_class=HTMLResponse)
def campaigns(request: Request): return render(request, "campaigns.html", page="campaigns")


@router.get("/conteudo-ia", response_class=HTMLResponse)
def content(request: Request): return render(request, "content.html", page="content")


@router.get("/integracoes", response_class=HTMLResponse)
def integrations(request: Request): return render(request, "integrations.html", page="integrations")


@router.get("/historico", response_class=HTMLResponse)
def history(request: Request): return render(request, "history.html", page="history")


@router.get("/configuracoes", response_class=HTMLResponse)
def settings_page(request: Request): return render(request, "settings.html", page="settings")


@router.get("/administracao", response_class=HTMLResponse)
def administration(request: Request): return render(request, "admin.html", page="admin")


@router.get("/privacidade", response_class=HTMLResponse)
def privacy(request: Request): return render(request, "privacy.html")


@router.get("/termos", response_class=HTMLResponse)
def terms(request: Request): return render(request, "terms.html")
