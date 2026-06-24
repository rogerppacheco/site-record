"""
Normaliza webhooks Z-API e Evolution para formato canonico consumido pelo handler.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_PROVEDOR_ZAPI = "zapi"
_PROVEDOR_EVOLUTION = "evolution"


def detectar_provedor(payload: Any) -> str:
    if not isinstance(payload, dict):
        return _PROVEDOR_ZAPI
    evento = str(payload.get("event") or "").lower()
    if evento in ("messages.upsert", "messages.update", "send.message"):
        return _PROVEDOR_EVOLUTION
    if payload.get("data") and isinstance(payload.get("data"), dict):
        data = payload["data"]
        if isinstance(data.get("key"), dict) and "remoteJid" in data["key"]:
            return _PROVEDOR_EVOLUTION
    if payload.get("phone") or payload.get("type") == "ReceivedCallback":
        return _PROVEDOR_ZAPI
    return _PROVEDOR_ZAPI


def normalizar_webhook(payload: Any) -> Dict[str, Any]:
    """Retorna payload canonico (compativel com handler Z-API existente)."""
    if not isinstance(payload, dict):
        return {}
    if detectar_provedor(payload) == _PROVEDOR_EVOLUTION:
        return _normalizar_evolution(payload)
    return payload


def _extrair_texto_evolution(msg: Dict[str, Any]) -> str:
    if not msg:
        return ""
    if msg.get("conversation"):
        return str(msg["conversation"]).strip()
    ext = msg.get("extendedTextMessage") or {}
    if isinstance(ext, dict) and ext.get("text"):
        return str(ext["text"]).strip()
    for key in ("imageMessage", "videoMessage", "documentMessage"):
        part = msg.get(key)
        if isinstance(part, dict) and part.get("caption"):
            return str(part["caption"]).strip()
    return ""


def _extrair_botao_evolution(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(msg, dict):
        return None
    for key in (
        "buttonsResponseMessage",
        "templateButtonReplyMessage",
        "interactiveResponseMessage",
    ):
        br = msg.get(key)
        if not isinstance(br, dict):
            continue
        bid = (
            br.get("selectedButtonId")
            or br.get("selectedId")
            or br.get("buttonId")
            or br.get("id")
            or ""
        )
        texto = (
            br.get("selectedDisplayText")
            or br.get("selectedButtonText")
            or br.get("displayText")
            or br.get("text")
            or ""
        )
        if bid or texto:
            return {
                "buttonId": str(bid),
                "selectedButtonId": str(bid),
                "message": str(texto),
                "selectedButtonText": str(texto),
            }
    return None


def _jid_para_phone(remote_jid: str, participant: str = "") -> Tuple[str, bool, str]:
    jid = str(remote_jid or "")
    part = str(participant or "")
    is_group = "@g.us" in jid or "-group" in jid
    phone = jid.split("@")[0] if "@" in jid else jid
    if is_group and "@g.us" in jid:
        phone = phone + "-group"
    participant_phone = part.split("@")[0] if part else ""
    return phone, is_group, participant_phone


def _resolver_midia_evolution(
    msg: Dict[str, Any], evolution_data: Dict[str, Any], payload: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Retorna (image_url_or_data_uri, document_url_or_data_uri, mime).
    Usa URL direta se presente; senao baixa base64 via Evolution API.
    """
    image_url = None
    document_url = None
    mime = None

    img = msg.get("imageMessage")
    if isinstance(img, dict):
        mime = img.get("mimetype") or "image/jpeg"
        if img.get("url"):
            image_url = img["url"]
        elif img.get("directPath"):
            image_url = None

    doc = msg.get("documentMessage")
    if isinstance(doc, dict):
        mime = doc.get("mimetype") or "application/pdf"
        if doc.get("url"):
            document_url = doc["url"]

    if image_url or document_url:
        return image_url, document_url, mime

    tem_midia = any(
        isinstance(msg.get(k), dict)
        for k in ("imageMessage", "documentMessage", "videoMessage", "audioMessage")
    )
    if not tem_midia:
        return None, None, None

    try:
        from crm_app.services.whatsapp.evolution_provider import EvolutionProvider

        provider = EvolutionProvider()
        envelope = {
            "key": evolution_data.get("key") or {},
            "message": msg,
            "messageTimestamp": evolution_data.get("messageTimestamp"),
        }
        b64 = provider.baixar_midia_base64(envelope)
        if not b64:
            return None, None, mime
        if isinstance(msg.get("imageMessage"), dict):
            mt = mime or "image/jpeg"
            return f"data:{mt};base64,{b64}", None, mt
        if isinstance(msg.get("documentMessage"), dict):
            mt = mime or "application/pdf"
            return None, f"data:{mt};base64,{b64}", mt
    except Exception as exc:
        logger.warning("[WebhookNormalizer] Falha ao baixar midia Evolution: %s", exc)

    return None, None, mime


def _normalizar_evolution(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload

    key = data.get("key") or {}
    msg = data.get("message") or {}
    if not isinstance(msg, dict):
        msg = {}

    remote_jid = key.get("remoteJid") or ""
    participant = key.get("participant") or data.get("participant") or ""
    phone, is_group, participant_phone = _jid_para_phone(remote_jid, participant)

    texto = _extrair_texto_evolution(msg)
    botao = _extrair_botao_evolution(msg)
    image_url, document_url, _mime = _resolver_midia_evolution(msg, data, payload)

    canonico: Dict[str, Any] = {
        "phone": phone,
        "from": phone,
        "fromMe": bool(key.get("fromMe")),
        "isFromMe": bool(key.get("fromMe")),
        "isGroup": is_group,
        "messageId": key.get("id"),
        "type": "message",
        "message": {"text": texto, "body": texto},
        "text": {"message": texto, "text": texto},
    }

    if participant_phone:
        canonico["participantPhone"] = participant_phone
        if isinstance(canonico.get("text"), dict):
            canonico["text"]["participant"] = participant_phone

    if botao:
        canonico["buttonsResponseMessage"] = botao

    ref = None
    ext_ctx = (msg.get("extendedTextMessage") or {}).get("contextInfo")
    if isinstance(ext_ctx, dict):
        ref = ext_ctx
    if not ref:
        for val in msg.values():
            if isinstance(val, dict) and isinstance(val.get("contextInfo"), dict):
                ref = val["contextInfo"]
                break
    if isinstance(ref, dict):
        ref_id = ref.get("stanzaId") or ref.get("quotedMessageId")
        if ref_id:
            canonico["referenceMessageId"] = ref_id

    if image_url:
        if image_url.startswith("data:"):
            canonico["image"] = {"image": image_url}
        else:
            canonico["image"] = {"imageUrl": image_url}

    if document_url:
        if document_url.startswith("data:"):
            canonico["document"] = {"document": document_url}
        else:
            canonico["document"] = {"documentUrl": document_url}

    canonico["_evolution_raw"] = payload
    return canonico
