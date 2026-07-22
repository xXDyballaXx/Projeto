from itsdangerous import BadSignature, URLSafeSerializer

from app.config import settings


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key, salt="campaign-click")


def make_tracking_url(campaign_id: int) -> str:
    token = _serializer().dumps({"campaign_id": campaign_id})
    return f"{settings.base_url.rstrip('/')}/track/{token}"


def read_tracking_token(token: str) -> int | None:
    try:
        return int(_serializer().loads(token)["campaign_id"])
    except (BadSignature, KeyError, TypeError, ValueError):
        return None

