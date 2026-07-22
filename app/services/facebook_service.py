import httpx

from app.config import settings
from app.services.exceptions import IntegrationError
from app.services.whatsapp_service import SendResult


class FacebookService:
    @property
    def configured(self) -> bool:
        return self.is_configured(settings.facebook_page_id, settings.facebook_page_access_token)

    @staticmethod
    def is_configured(page_id: str | None, access_token: str | None) -> bool:
        return bool(
            settings.external_services_enabled
            and settings.environment != "test"
            and page_id
            and access_token
        )

    async def publish(
        self,
        message: str,
        link: str | None = None,
        image_url: str | None = None,
        video_url: str | None = None,
        *,
        page_id: str | None = None,
        access_token: str | None = None,
    ) -> SendResult:
        page_id = settings.facebook_page_id if page_id is None else page_id
        access_token = settings.facebook_page_access_token if access_token is None else access_token
        if not self.is_configured(page_id, access_token):
            if settings.simulation_mode:
                return SendResult(False, error="SIMULAÇÃO: publicação não realizada; Página do Facebook não configurada.", simulated=True)
            raise IntegrationError("Facebook não configurado para esta empresa.")
        message_with_link = f"{message}\n\n{link}" if link else message
        payload = {"message": message}
        headers = {"Authorization": f"Bearer {access_token}"}
        endpoint = "feed"
        if video_url:
            endpoint, payload["file_url"], payload["description"] = "videos", video_url, message_with_link
            payload.pop("message")
        elif image_url:
            endpoint, payload["url"], payload["caption"] = "photos", image_url, message_with_link
            payload.pop("message")
        elif link:
            payload["link"] = link
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"https://graph.facebook.com/{settings.meta_graph_version}/{page_id}/{endpoint}",
                    data=payload,
                    headers=headers,
                )
                response.raise_for_status()
            external_id = response.json().get("id")
            if not external_id:
                raise IntegrationError("A Meta não confirmou o identificador da publicação no Facebook.")
            return SendResult(True, external_id=external_id)
        except IntegrationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise IntegrationError("A Meta recusou a publicação no Facebook.") from exc


facebook_service = FacebookService()
