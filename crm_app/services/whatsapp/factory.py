"""Factory do provider WhatsApp (zapi | evolution híbrido n8n)."""
from __future__ import annotations

from functools import lru_cache

from crm_app.services.whatsapp.base import WhatsAppProvider
from crm_app.services.whatsapp.n8n_outbound_provider import N8nOutboundProvider
from crm_app.services.whatsapp.zapi_provider import ZapiProvider


@lru_cache(maxsize=1)
def get_whatsapp_provider() -> WhatsAppProvider:
    from crm_app.services.whatsapp_config_service import get_active_whatsapp_provider_name

    provider = get_active_whatsapp_provider_name()
    if provider == "evolution":
        return N8nOutboundProvider()
    return ZapiProvider()
