"""Factory do provider WhatsApp (zapi | evolution híbrido n8n)."""
from __future__ import annotations

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.n8n_outbound_provider import N8nOutboundProvider
from crm_app.services.whatsapp.zapi_provider import ZapiProvider

_cached_provider_name: str | None = None
_cached_provider: WhatsAppProvider | None = None


def clear_whatsapp_provider_cache() -> None:
    """Invalida cache in-process (ex.: após salvar provedor na mesma réplica)."""
    global _cached_provider_name, _cached_provider
    _cached_provider_name = None
    _cached_provider = None


def get_whatsapp_provider() -> WhatsAppProvider:
    """
    Resolve o provider ativo consultando o banco a cada chamada.
    Recria a instância apenas quando o nome do provedor muda.
    """
    global _cached_provider_name, _cached_provider

    from crm_app.services.whatsapp_config_service import get_active_whatsapp_provider_name

    provider = get_active_whatsapp_provider_name()
    if _cached_provider is not None and _cached_provider_name == provider:
        return _cached_provider

    if provider == "evolution":
        _cached_provider = N8nOutboundProvider()
    else:
        _cached_provider = ZapiProvider()
    _cached_provider_name = provider
    return _cached_provider
