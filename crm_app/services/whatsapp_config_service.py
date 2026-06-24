"""Resolução do provedor WhatsApp ativo (banco + variáveis de ambiente)."""
from __future__ import annotations

import os
from typing import Any, Dict

from django.conf import settings

from crm_app.models import WhatsAppIntegracaoConfig


def get_active_whatsapp_provider_name() -> str:
    """Provedor efetivo: registro único no banco; fallback para env/settings."""
    try:
        cfg = WhatsAppIntegracaoConfig.load()
        provider = (cfg.provider or "").strip().lower()
        if provider in (
            WhatsAppIntegracaoConfig.PROVIDER_ZAPI,
            WhatsAppIntegracaoConfig.PROVIDER_EVOLUTION,
        ):
            return provider
    except Exception:
        pass
    fallback = (
        getattr(settings, "WHATSAPP_PROVIDER", None)
        or os.environ.get("WHATSAPP_PROVIDER", "zapi")
        or "zapi"
    )
    return str(fallback).strip().lower()


def clear_whatsapp_provider_cache() -> None:
    from crm_app.services.whatsapp.factory import get_whatsapp_provider

    get_whatsapp_provider.cache_clear()


def _credenciais_zapi_ok() -> bool:
    return bool(
        getattr(settings, "ZAPI_INSTANCE_ID", "")
        and getattr(settings, "ZAPI_TOKEN", "")
    )


def _credenciais_evolution_ok() -> bool:
    return bool(
        getattr(settings, "EVOLUTION_API_URL", "")
        and getattr(settings, "EVOLUTION_API_KEY", "")
    )


def _credenciais_n8n_ok() -> bool:
    for key in ("N8N_OUTBOUND_WEBHOOK_URL", "N8N_WEBHOOK_URL", "OUTBOUND_WEBHOOK_URL"):
        val = getattr(settings, key, None) or os.environ.get(key, "")
        if val and str(val).strip():
            return True
    return False


def build_whatsapp_config_payload() -> Dict[str, Any]:
    cfg = WhatsAppIntegracaoConfig.load()
    provider = get_active_whatsapp_provider_name()
    env_default = (
        getattr(settings, "WHATSAPP_PROVIDER", None)
        or os.environ.get("WHATSAPP_PROVIDER", "zapi")
        or "zapi"
    ).strip().lower()
    return {
        "provider": provider,
        "providerLabel": dict(WhatsAppIntegracaoConfig.PROVIDER_CHOICES).get(
            provider, provider
        ),
        "instanceName": getattr(settings, "EVOLUTION_INSTANCE_NAME", "site_record_zap"),
        "zapiConfigured": _credenciais_zapi_ok(),
        "evolutionConfigured": _credenciais_evolution_ok(),
        "n8nConfigured": _credenciais_n8n_ok(),
        "envDefaultProvider": env_default,
        "atualizadoEm": cfg.atualizado_em.isoformat() if cfg.atualizado_em else None,
        "atualizadoPor": (
            cfg.atualizado_por.get_full_name() or cfg.atualizado_por.username
            if cfg.atualizado_por_id
            else None
        ),
    }


def set_whatsapp_provider(provider: str, user) -> WhatsAppIntegracaoConfig:
    normalized = (provider or "").strip().lower()
    valid = {
        WhatsAppIntegracaoConfig.PROVIDER_ZAPI,
        WhatsAppIntegracaoConfig.PROVIDER_EVOLUTION,
    }
    if normalized not in valid:
        raise ValueError(f"Provedor inválido: {provider}")
    cfg = WhatsAppIntegracaoConfig.load()
    cfg.provider = normalized
    cfg.atualizado_por = user
    cfg.save(update_fields=["provider", "atualizado_por", "atualizado_em"])
    clear_whatsapp_provider_cache()
    return cfg
