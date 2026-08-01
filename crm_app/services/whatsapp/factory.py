"""Factory do provider WhatsApp (zapi | evolution híbrido n8n | whatsatende)."""
from __future__ import annotations

from typing import Dict, Tuple

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.n8n_outbound_provider import N8nOutboundProvider
from crm_app.services.whatsapp.whatsatende_provider import WhatsAtendeProvider
from crm_app.services.whatsapp.zapi_provider import ZapiProvider

PURPOSE_INTERNO = "interno"
PURPOSE_CLIENTE = "cliente"

_cached_providers: Dict[Tuple[str, str], WhatsAppProvider] = {}


def clear_whatsapp_provider_cache() -> None:
    """Invalida cache in-process (ex.: após salvar provedor na mesma réplica)."""
    _cached_providers.clear()


def get_whatsapp_provider(purpose: str = PURPOSE_INTERNO) -> WhatsAppProvider:
    """
    Resolve o provider ativo consultando o banco a cada chamada.

    purpose=interno → bot/equipe (Número A na WhatsAtende).
    purpose=cliente → cliente final (Número B / oficial na WhatsAtende).
    Z-API e Evolution ignoram purpose (uma conexão só).
    """
    from crm_app.services.whatsapp_config_service import get_active_whatsapp_provider_name

    provider_name = get_active_whatsapp_provider_name()
    role = (
        PURPOSE_CLIENTE
        if (purpose or "").strip().lower() == PURPOSE_CLIENTE
        else PURPOSE_INTERNO
    )
    # Só WhatsAtende tem dual A/B; demais provedores compartilham a mesma instância.
    cache_role = role if provider_name == "whatsatende" else PURPOSE_INTERNO
    key = (provider_name, cache_role)
    cached = _cached_providers.get(key)
    if cached is not None:
        return cached

    if provider_name == "evolution":
        inst: WhatsAppProvider = N8nOutboundProvider()
    elif provider_name == "whatsatende":
        inst = WhatsAtendeProvider(role=cache_role)
    else:
        inst = ZapiProvider()
    _cached_providers[key] = inst
    return inst
