import httpx

from app.config import settings
from app.schemas import GenerateContentRequest
from app.services.exceptions import IntegrationError


class AIService:
    async def generate(self, data: GenerateContentRequest, api_key: str | None = None) -> tuple[str, str]:
        if not settings.external_services_enabled or settings.environment == "test":
            content = (
                f"[SIMULAÇÃO — revise antes de usar]\n\n"
                f"Título: {data.product} para {data.audience}\n\n"
                f"Texto principal: Uma solução pensada para {data.audience}. "
                f"Nosso objetivo é {data.objective}, com uma comunicação {data.tone}. "
                f"{data.required_information}\n\n"
                "CTA: Saiba mais e fale com nossa equipe.\n\n"
                "Hashtags: #Novidade #MarketingResponsável\n\n"
                f"Variação alternativa: Conheça {data.product} e descubra uma forma responsável de {data.objective}."
            )
            return content, "simulation"
        effective_api_key = settings.ai_api_key if api_key is None else api_key
        if not effective_api_key:
            raise IntegrationError("O provedor de IA ainda não está configurado.")
        prompt = (
            "Crie texto publicitário em português do Brasil. Não invente fatos. "
            f"Canal: {data.channel.value}. Produto: {data.product}. Público: {data.audience}. "
            f"Objetivo: {data.objective}. Tom: {data.tone}. Informações obrigatórias: {data.required_information}. "
            "Inclua título, texto, CTA, hashtags e duas variações claramente identificadas. "
            "O conteúdo será revisado por uma pessoa."
        )
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    settings.ai_api_url,
                    headers={"Authorization": f"Bearer {effective_api_key}"},
                    json={"model": settings.ai_model, "input": prompt, "max_output_tokens": settings.ai_max_output_tokens},
                )
                response.raise_for_status()
            payload = response.json()
            text = payload.get("output_text")
            if not text:
                text = payload["output"][0]["content"][0]["text"]
            if not isinstance(text, str) or not text.strip():
                raise IntegrationError("O provedor de IA retornou uma resposta vazia.")
            return text.strip(), "official_api"
        except IntegrationError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            raise IntegrationError("Não foi possível gerar o conteúdo agora. Tente novamente.") from None


ai_service = AIService()

