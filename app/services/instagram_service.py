import asyncio

import httpx

from app.config import settings
from app.services.exceptions import IntegrationError
from app.services.whatsapp_service import SendResult


class InstagramService:
    @property
    def configured(self) -> bool:
        return self.is_configured(settings.instagram_account_id, settings.facebook_page_access_token)

    @staticmethod
    def is_configured(account_id: str | None, access_token: str | None) -> bool:
        return bool(
            settings.external_services_enabled
            and settings.environment != "test"
            and account_id
            and access_token
        )

    async def publish_media(
        self,
        media_url: str,
        caption: str,
        is_video: bool = False,
        *,
        account_id: str | None = None,
        access_token: str | None = None,
    ) -> SendResult:
        account_id = settings.instagram_account_id if account_id is None else account_id
        access_token = settings.facebook_page_access_token if access_token is None else access_token
        if not self.is_configured(account_id, access_token):
            if settings.simulation_mode:
                return SendResult(False, error="SIMULAÇÃO: publicação não realizada; Instagram profissional não configurado.", simulated=True)
            raise IntegrationError("Instagram não configurado para esta empresa.")
        base = f"https://graph.facebook.com/{settings.meta_graph_version}/{account_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                media_payload = {"caption": caption}
                if is_video:
                    media_payload.update({"video_url": media_url, "media_type": "REELS"})
                else:
                    media_payload["image_url"] = media_url
                create = await client.post(f"{base}/media", data=media_payload, headers=headers)
                create.raise_for_status()
                creation_id = create.json()["id"]
                if is_video:
                    for _ in range(10):
                        status = await client.get(
                            f"https://graph.facebook.com/{settings.meta_graph_version}/{creation_id}",
                            params={"fields": "status_code"},
                            headers=headers,
                        )
                        status.raise_for_status()
                        state = status.json().get("status_code")
                        if state == "FINISHED":
                            break
                        if state in {"ERROR", "EXPIRED"}:
                            raise IntegrationError("O Instagram não conseguiu processar o vídeo.")
                        await asyncio.sleep(3)
                    else:
                        raise IntegrationError("O vídeo ainda está sendo processado; tente publicar novamente em alguns instantes.")
                publish = await client.post(
                    f"{base}/media_publish",
                    data={"creation_id": creation_id},
                    headers=headers,
                )
                publish.raise_for_status()
            external_id = publish.json().get("id")
            if not external_id:
                raise IntegrationError("A Meta não confirmou o identificador da publicação no Instagram.")
            return SendResult(True, external_id=external_id)
        except IntegrationError:
            raise
        except (httpx.HTTPError, KeyError, ValueError):
            raise IntegrationError(
                "O Instagram recusou a publicação. Confirme a conta profissional, mídia e permissões."
            ) from None


instagram_service = InstagramService()
