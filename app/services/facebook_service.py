import httpx

from app.config import settings
from app.services.exceptions import IntegrationError
from app.services.whatsapp_service import SendResult


class FacebookService:
    @property
    def configured(self) -> bool:
        return bool(settings.facebook_page_id and settings.facebook_page_access_token)

    async def publish(self, message: str, link: str | None = None, image_url: str | None = None, video_url: str | None = None) -> SendResult:
        if not self.configured:
            return SendResult(False, error="SIMULAÇÃO: publicação não realizada; Página do Facebook não configurada.", simulated=True)
        payload = {"message": message, "access_token": settings.facebook_page_access_token}
        endpoint = "feed"
        if video_url:
            endpoint, payload["file_url"], payload["description"] = "videos", video_url, message
            payload.pop("message")
        elif image_url:
            endpoint, payload["url"], payload["caption"] = "photos", image_url, message
            payload.pop("message")
        elif link:
            payload["link"] = link
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"https://graph.facebook.com/{settings.meta_graph_version}/{settings.facebook_page_id}/{endpoint}", data=payload
                )
                response.raise_for_status()
            return SendResult(True, external_id=response.json().get("id"))
        except httpx.HTTPError as exc:
            raise IntegrationError("A Meta recusou a publicação no Facebook.") from exc


facebook_service = FacebookService()
