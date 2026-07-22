import asyncio

import httpx

from app.config import settings
from app.services.exceptions import IntegrationError
from app.services.whatsapp_service import SendResult


class InstagramService:
    @property
    def configured(self) -> bool:
        return bool(settings.instagram_account_id and settings.facebook_page_access_token)

    async def publish_media(self, media_url: str, caption: str, is_video: bool = False) -> SendResult:
        if not self.configured:
            return SendResult(False, error="SIMULAÇÃO: publicação não realizada; Instagram profissional não configurado.", simulated=True)
        base = f"https://graph.facebook.com/{settings.meta_graph_version}/{settings.instagram_account_id}"
        token = settings.facebook_page_access_token
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                media_payload = {"caption": caption, "access_token": token}
                if is_video:
                    media_payload.update({"video_url": media_url, "media_type": "REELS"})
                else:
                    media_payload["image_url"] = media_url
                create = await client.post(f"{base}/media", data=media_payload)
                create.raise_for_status()
                creation_id = create.json()["id"]
                if is_video:
                    for _ in range(10):
                        status = await client.get(f"https://graph.facebook.com/{settings.meta_graph_version}/{creation_id}", params={"fields": "status_code", "access_token": token})
                        status.raise_for_status()
                        state = status.json().get("status_code")
                        if state == "FINISHED":
                            break
                        if state in {"ERROR", "EXPIRED"}:
                            raise IntegrationError("O Instagram não conseguiu processar o vídeo.")
                        await asyncio.sleep(3)
                    else:
                        raise IntegrationError("O vídeo ainda está sendo processado; tente publicar novamente em alguns instantes.")
                publish = await client.post(f"{base}/media_publish", data={"creation_id": creation_id, "access_token": token})
                publish.raise_for_status()
            return SendResult(True, external_id=publish.json().get("id"))
        except IntegrationError:
            raise
        except (httpx.HTTPError, KeyError) as exc:
            raise IntegrationError("O Instagram recusou a publicação. Confirme a conta profissional, mídia e permissões.") from exc


instagram_service = InstagramService()
