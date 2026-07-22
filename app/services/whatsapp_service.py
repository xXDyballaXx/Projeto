import hashlib
import hmac
from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.exceptions import IntegrationError


@dataclass
class SendResult:
    success: bool
    external_id: str | None = None
    error: str | None = None
    simulated: bool = False


class WhatsAppService:
    @property
    def configured(self) -> bool:
        return bool(settings.whatsapp_phone_number_id and settings.whatsapp_access_token)

    async def send_template(self, phone: str, template_name: str, language: str = "pt_BR") -> SendResult:
        if not self.configured:
            if settings.simulation_mode:
                return SendResult(False, error="SIMULAÇÃO: mensagem não enviada; credenciais oficiais ausentes.", simulated=True)
            raise IntegrationError("WhatsApp não configurado.")
        url = f"https://graph.facebook.com/{settings.meta_graph_version}/{settings.whatsapp_phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": phone.lstrip("+"),
            "type": "template",
            "template": {"name": template_name, "language": {"code": language}},
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(url, json=payload, headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"})
                response.raise_for_status()
            data = response.json()
            return SendResult(True, external_id=data["messages"][0]["id"])
        except (httpx.HTTPError, KeyError) as exc:
            raise IntegrationError("A Meta recusou a mensagem do WhatsApp. Verifique template, token e número.") from exc

    @staticmethod
    def validate_signature(raw_body: bytes, signature_header: str | None) -> bool:
        if not settings.meta_app_secret:
            return settings.simulation_mode
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        digest = hmac.new(settings.meta_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={digest}", signature_header)


whatsapp_service = WhatsAppService()
