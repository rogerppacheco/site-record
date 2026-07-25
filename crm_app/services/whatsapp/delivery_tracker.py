"""
Correlação de DeliveryCallback (Z-API) com envios aguardando confirmação.

messageId da API send ≠ entrega real. O webhook DeliveryCallback confirma
aceitação/rejeição pelo WhatsApp (campo `error` só em falha).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, Optional, Tuple

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "wa_delivery:"
_DEFAULT_TTL = 180
_DEFAULT_WAIT = 25.0
_POLL_INTERVAL = 0.25


def _ttl() -> int:
    return int(getattr(settings, "WHATSAPP_DELIVERY_CACHE_TTL", _DEFAULT_TTL))


def _wait_seconds() -> float:
    return float(getattr(settings, "WHATSAPP_DELIVERY_WAIT_SECONDS", _DEFAULT_WAIT))


def _ids_from_payload(data: Dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("messageId", "zaapId", "id"):
        val = data.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s and s not in ids:
            ids.append(s)
    return ids


def _cache_key(message_id: str) -> str:
    return f"{_CACHE_PREFIX}{message_id}"


def registrar_resultado_entrega(
    message_ids: Iterable[str],
    *,
    ok: bool,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    phone: Optional[str] = None,
) -> None:
    """Grava resultado para todos os IDs (messageId e zaapId podem diferir)."""
    payload = {
        "ok": bool(ok),
        "error": (error or "").strip() or None,
        "error_code": (error_code or "").strip() or None,
        "phone": (phone or "").strip() or None,
    }
    ttl = _ttl()
    for mid in message_ids:
        if not mid:
            continue
        cache.set(_cache_key(str(mid)), payload, timeout=ttl)
    logger.info(
        "[DeliveryTracker] resultado ok=%s ids=%s error=%s code=%s phone=%s",
        payload["ok"],
        list(message_ids),
        payload["error"],
        payload["error_code"],
        payload["phone"],
    )


def processar_delivery_callback(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processa payload type=DeliveryCallback.
    Sucesso = ausência de `error`; falha = `error` presente.
    """
    ids = _ids_from_payload(data)
    error = data.get("error")
    error_code = data.get("errorCode") or data.get("error_code")
    phone = str(data.get("phone") or "")
    ok = not bool(error)
    if not ids:
        logger.warning(
            "[DeliveryTracker] DeliveryCallback sem messageId/zaapId phone=%s",
            phone,
        )
        return {"status": "ok", "mensagem": "DeliveryCallback sem id"}

    registrar_resultado_entrega(
        ids,
        ok=ok,
        error=str(error) if error else None,
        error_code=str(error_code) if error_code else None,
        phone=phone or None,
    )
    return {
        "status": "ok",
        "mensagem": "DeliveryCallback processado",
        "ok": ok,
        "ids": ids,
    }


def obter_resultado(message_id: str) -> Optional[Dict[str, Any]]:
    if not message_id:
        return None
    val = cache.get(_cache_key(str(message_id)))
    return val if isinstance(val, dict) else None


def aguardar_entrega(
    *message_ids: str,
    timeout: Optional[float] = None,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Espera DeliveryCallback correlacionado a qualquer um dos IDs.

    Returns:
        (True, result) se entregue sem error;
        (False, result) se callback com error;
        (False, None) se timeout sem callback.
    """
    ids = [str(i).strip() for i in message_ids if i and str(i).strip()]
    if not ids:
        return False, None

    deadline = time.monotonic() + (timeout if timeout is not None else _wait_seconds())
    while True:
        for mid in ids:
            result = obter_resultado(mid)
            if result is not None:
                return bool(result.get("ok")), result
        if time.monotonic() >= deadline:
            logger.warning(
                "[DeliveryTracker] timeout aguardando entrega ids=%s",
                ids,
            )
            return False, None
        time.sleep(_POLL_INTERVAL)
