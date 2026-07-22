import httpx

from app.config import settings
from app.schemas import GenerateContentRequest
from app.services.exceptions import IntegrationError


class AIService:
    async def generate(self, data: GenerateContentRequest) -> tuple[str, str]:
        if not settings.ai_api_key:
            content = (
                f"[SIMULAÇÃO — revise antes de usar]\n\n"
                f"{data.product}: uma solução pensada para {data.audience}. "
                f"Nosso objetivo é {data.objective}, com uma comunicação {data.tone}.\n\n"
                f"{data.required_information}\n\nSaiba mais e fale com nossa equipe. #Novidade #MarketingResponsável"
            )
            return content, "simulation"
        prompt = (
            "Crie texto publicitário em português do Brasil. Não invente fatos. "
            f"Canal: {data.channel.value}. Produto: {data.product}. Público: {data.audience}. "
            f"Objetivo: {data.objective}. Tom: {data.tone}. Informações obrigatórias: {data.required_information}. "
            "Inclua título, texto, CTA e hashtags. O conteúdo será revisado por uma pessoa."
        )
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    settings.ai_api_url,
                    headers={"Authorization": f"Bearer {settings.ai_api_key}"},
                    json={"model": settings.ai_model, "input": prompt},
                )
                response.raise_for_status()
            payload = response.json()
            text = payload.get("output_text")
            if not text:
                text = payload["output"][0]["content"][0]["text"]
            return text, "official_api"
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise IntegrationError("Não foi possível gerar o conteúdo agora. Tente novamente.") from exc


ai_service = AIService()

