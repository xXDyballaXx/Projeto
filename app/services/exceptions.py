class IntegrationError(Exception):
    """Erro seguro e apresentável de integração externa."""


class ConsentRequiredError(Exception):
    """Contato não possui consentimento válido."""

