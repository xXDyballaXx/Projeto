import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import Base, engine
from app.routes import admin, auth, campaigns, contacts, content, dashboard, integrations, pages, settings as settings_routes, tracking, webhooks
from app.services.exceptions import IntegrationError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("divulgai")
login_attempts: dict[str, deque] = defaultdict(deque)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.environment in {"development", "test"}:
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins_list, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"])
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin not in settings.allowed_origins_list:
            return JSONResponse({"detail": "Origem da requisição não autorizada."}, status_code=403)
    if request.url.path == "/api/auth/login" and request.method == "POST":
        key = request.client.host if request.client else "unknown"
        now = datetime.now(timezone.utc)
        bucket = login_attempts[key]
        while bucket and bucket[0] < now - timedelta(minutes=15):
            bucket.popleft()
        if len(bucket) >= 20:
            response = JSONResponse({"detail": "Muitas tentativas deste endereço. Aguarde 15 minutos."}, status_code=429)
            response.headers["Retry-After"] = "900"
            return response
    response = await call_next(request)
    if request.url.path == "/api/auth/login" and request.method == "POST" and response.status_code in {401, 422, 429}:
        key = request.client.host if request.client else "unknown"
        login_attempts[key].append(datetime.now(timezone.utc))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; script-src 'self' https://cdn.jsdelivr.net https://cdn.jsdelivr.net/npm/chart.js; img-src 'self' data: https:; font-src 'self' https://cdn.jsdelivr.net; connect-src 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers.append("Vary", "Cookie")
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(IntegrationError)
async def integration_error(request: Request, exc: IntegrationError):
    logger.warning("Falha de integração em %s: %s", request.url.path, exc)
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    logger.exception("Erro interno em %s", request.url.path)
    return JSONResponse({"detail": "Não foi possível concluir a operação."}, status_code=500)


for route in [auth.router, contacts.router, campaigns.router, content.router, integrations.router, dashboard.router, settings_routes.router, admin.router, webhooks.router, tracking.router, pages.router]:
    app.include_router(route)


@app.get("/health", tags=["Sistema"])
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Falha no health check do banco de dados")
        return JSONResponse(
            {
                "status": "unavailable",
                "database": "error",
                "environment": settings.environment,
                "simulation_mode": settings.simulation_mode,
            },
            status_code=503,
        )
    return {
        "status": "ok",
        "database": "ok",
        "environment": settings.environment,
        "simulation_mode": settings.simulation_mode,
        "external_services_enabled": settings.external_services_enabled,
    }
