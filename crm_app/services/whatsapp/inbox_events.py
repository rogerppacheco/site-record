"""Pub/sub Redis para alertas em tempo real do inbox WhatsApp (SSE)."""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

CHANNEL_NAME = "wa:inbox"
REDIS_TIMEOUT = 1.0


def _redis_client():
    try:
        from django.conf import settings
        import redis

        url = getattr(settings, "CELERY_BROKER_URL", None) or getattr(
            settings, "REDIS_URL", "redis://localhost:6379/0"
        )
        client = redis.from_url(
            url,
            socket_connect_timeout=REDIS_TIMEOUT,
            socket_timeout=REDIS_TIMEOUT,
            socket_keepalive=True,
        )
        # Falha rápido se o broker estiver inacessível (não trava o SSE).
        client.ping()
        return client
    except Exception:
        logger.debug("[WA inbox] Redis indisponível", exc_info=True)
        return None


def publish_inbox_event(event: dict) -> bool:
    """Publica evento JSON no canal wa:inbox. Nunca propaga erro."""
    try:
        client = _redis_client()
        if client is None:
            return False
        payload = json.dumps(event, default=str, ensure_ascii=False)
        client.publish(CHANNEL_NAME, payload)
        return True
    except Exception:
        logger.debug("[WA inbox] Falha ao publicar evento", exc_info=True)
        return False


def publish_nova_mensagem(
    *,
    telefone: str,
    direcao: str,
    preview: str,
    conversation_id: Optional[int] = None,
    message_id: str = "",
) -> None:
    publish_inbox_event(
        {
            "type": "message.new",
            "telefone": telefone,
            "direcao": direcao,
            "preview": (preview or "")[:200],
            "conversation_id": conversation_id,
            "message_id": message_id or "",
        }
    )


def iter_inbox_events(stop_check=None, timeout: float = 15.0) -> Iterator[dict]:
    """Gera eventos do pub/sub. Yields dicts; None indica heartbeat.

    stop_check: callable opcional que retorna True para encerrar.
    """
    client = _redis_client()
    if client is None:
        while True:
            if stop_check and stop_check():
                return
            yield None  # heartbeat sem Redis
            import time

            time.sleep(timeout)
            continue

    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        pubsub.subscribe(CHANNEL_NAME)
        while True:
            if stop_check and stop_check():
                return
            msg = pubsub.get_message(timeout=timeout)
            if msg is None:
                yield None
                continue
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            try:
                yield json.loads(data)
            except Exception:
                continue
    finally:
        try:
            pubsub.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass
