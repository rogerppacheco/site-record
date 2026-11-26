"""Inbox de atendimento WhatsApp no número do cliente (Cloud API).

Persiste entradas do webhook oficial e saídas do CRM (texto de sessão e modelos).
A resposta do operador só segue com a janela de 24 horas aberta.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any, Iterator, Optional

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

logger = logging.getLogger(__name__)

JANELA_ATENDIMENTO = timedelta(hours=24)

AVISO_JANELA_FECHADA = (
    "Janela de 24h fechada — texto/mídia bloqueados. Use a aba Template."
)

AVISO_SEM_MENSAGEM_CLIENTE = (
    "Sem resposta do cliente ainda — texto livre bloqueado. Use a aba Template."
)

# Catálogo fallback (quando o provedor não lista templates).
_TEMPLATES_INBOX_CURADOS = (
    {"name": "nio_boas_vindas_v1", "label": "Boas-vindas", "body_params": 2, "hint": "{{1}} saudação (Bom Dia) / {{2}} nome"},
    {"name": "nio_confirmacao_pedido_v1", "label": "Confirmação de pedido", "body_params": 3, "hint": "nome / endereço / data"},
    {"name": "nio_consulta_viabilidade_v1", "label": "Consulta viabilidade", "body_params": 3, "hint": "nome / endereço / pedido"},
    {"name": "nio_reativacao_contrato_v1", "label": "Reativação contrato", "body_params": 3, "hint": "nome / contrato / endereço"},
    {"name": "nio_selfie_pendente_v1", "label": "Selfie pendente", "body_params": 2, "hint": "nome / protocolo"},
    {"name": "nio_lembrete_instalacao_v1", "label": "Lembrete instalação", "body_params": 4, "hint": "saudação / nome / data / período"},
    {"name": "mailing_generico_v1", "label": "Mailing genérico", "body_params": 1, "hint": "{{1}} nome"},
)

AVISO_CANAL_INDISPONIVEL = (
    "O número oficial ainda não está liberado para envio a clientes. "
    "Quando a Meta aprovar o número e os envios a clientes forem ativados na aba WPP, "
    "esta tela passa a enviar normalmente."
)

_BACKENDS_OFICIAIS = frozenset({"meta", "whatsatende"})

_ctx_saida: ContextVar[Optional[dict]] = ContextVar("wa_atendimento_saida", default=None)


@contextmanager
def contexto_registro_saida(**kwargs: Any) -> Iterator[None]:
    """Marca a próxima saída do número do cliente (operador, pedido, origem)."""
    token = _ctx_saida.set(kwargs)
    try:
        yield
    finally:
        _ctx_saida.reset(token)


def _ctx() -> dict:
    return _ctx_saida.get() or {}


def canonicalizar_telefone(telefone: str) -> str:
    from crm_app.whatsapp_telefone_blocklist import normalizar_telefone_blocklist

    return normalizar_telefone_blocklist(telefone or "")


def telefones_equivalentes(telefone: str) -> list[str]:
    from crm_app.whatsapp_webhook_handler import _chaves_telefone_variantes

    canon = canonicalizar_telefone(telefone)
    chaves = list(_chaves_telefone_variantes(telefone) or [])
    if canon and canon not in chaves:
        chaves.append(canon)
    return [c for c in chaves if c]


def exibir_telefone(telefone: str) -> str:
    digitos = canonicalizar_telefone(telefone)
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return digitos or (telefone or "")


def _extrair_message_id(resposta: Any) -> str:
    if not isinstance(resposta, dict):
        return ""
    for chave in ("messageId", "message_id", "id", "wamid"):
        valor = resposta.get(chave)
        if valor:
            return str(valor)[:128]
    msgs = resposta.get("messages")
    if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
        mid = msgs[0].get("id")
        if mid:
            return str(mid)[:128]
    return ""


def _erro_resposta(resposta: Any, sucesso: bool) -> str:
    if sucesso or resposta is None:
        return ""
    if isinstance(resposta, str):
        return resposta[:500]
    if isinstance(resposta, dict):
        erro = resposta.get("error")
        if isinstance(erro, dict):
            return str(erro.get("message") or erro)[:500]
        if erro:
            return str(erro)[:500]
        return str(resposta)[:500]
    return str(resposta)[:500]


def resolver_venda(telefone: str):
    try:
        from crm_app.cliente_atendimento_ia_service import (
            buscar_venda_ativa_por_telefone_cliente,
        )

        return buscar_venda_ativa_por_telefone_cliente(telefone)
    except Exception:
        logger.debug("[Atendimento WA] Falha ao localizar pedido", exc_info=True)
        return None


def _venda_do_contexto_ou_telefone(telefone: str):
    ctx = _ctx()
    venda = ctx.get("venda")
    if venda is not None:
        return venda
    venda_id = ctx.get("venda_id")
    if venda_id:
        from crm_app.models import Venda

        return Venda.objects.filter(pk=venda_id).first()
    return resolver_venda(telefone)


def get_or_create_channel(role: str = "cliente"):
    """Garante canal WhatsAtende para o papel (interno|cliente|funil)."""
    from crm_app.models import WhatsAppChannel

    role_norm = (role or WhatsAppChannel.ROLE_CLIENTE).strip().lower()
    if role_norm in ("b", "oficial"):
        role_norm = WhatsAppChannel.ROLE_CLIENTE
    elif role_norm in ("a", "equipe", "bot"):
        role_norm = WhatsAppChannel.ROLE_INTERNO
    elif role_norm in ("f", "247"):
        role_norm = WhatsAppChannel.ROLE_FUNIL
    if role_norm not in {
        WhatsAppChannel.ROLE_INTERNO,
        WhatsAppChannel.ROLE_CLIENTE,
        WhatsAppChannel.ROLE_FUNIL,
    }:
        role_norm = WhatsAppChannel.ROLE_CLIENTE

    labels = {
        WhatsAppChannel.ROLE_INTERNO: "WhatsAtende A (equipe)",
        WhatsAppChannel.ROLE_CLIENTE: "WhatsAtende B (cliente)",
        WhatsAppChannel.ROLE_FUNIL: "WhatsAtende Funil",
    }
    channel, _ = WhatsAppChannel.objects.get_or_create(
        provider=WhatsAppChannel.PROVIDER_WHATSATENDE,
        role=role_norm,
        defaults={"label": labels.get(role_norm, role_norm), "ativo": True},
    )
    return channel


def get_or_create_conversation(
    telefone: str,
    *,
    role: str = "cliente",
    venda=None,
    contact_name: str = "",
):
    from crm_app.models import WhatsAppConversation

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 8:
        return None
    channel = get_or_create_channel(role)
    defaults = {
        "status": WhatsAppConversation.STATUS_ABERTA,
        "bot_pausado": bot_pausado(tel),
    }
    if venda is not None:
        defaults["venda"] = venda
    if contact_name:
        defaults["contact_name"] = (contact_name or "")[:255]
    conv, created = WhatsAppConversation.objects.get_or_create(
        channel=channel,
        telefone=tel,
        defaults=defaults,
    )
    dirty = []
    if venda is not None and conv.venda_id != getattr(venda, "pk", None):
        conv.venda = venda
        dirty.append("venda")
    if contact_name and not conv.contact_name:
        conv.contact_name = contact_name[:255]
        dirty.append("contact_name")
    if dirty:
        conv.save(update_fields=dirty + ["atualizado_em"])
    return conv


def _atualizar_conversa_apos_mensagem(msg, *, incrementar_unread: bool = False) -> None:
    from crm_app.models import MensagemWhatsAppAtendimento, WhatsAppConversation

    if msg is None:
        return
    conv = getattr(msg, "conversa", None)
    if conv is None and msg.conversa_id:
        conv = WhatsAppConversation.objects.filter(pk=msg.conversa_id).first()
    if conv is None:
        conv = get_or_create_conversation(msg.telefone, venda=msg.venda)
        if conv is None:
            return
        if msg.conversa_id != conv.id:
            MensagemWhatsAppAtendimento.objects.filter(pk=msg.pk).update(conversa_id=conv.id)
            msg.conversa_id = conv.id

    preview = (msg.texto or "").replace("\n", " ").strip()[:240]
    conv.last_message_at = msg.data_hora
    conv.last_message_preview = preview
    conv.last_direction = msg.direcao or ""
    if msg.venda_id and not conv.venda_id:
        conv.venda_id = msg.venda_id
    if msg.direcao == MensagemWhatsAppAtendimento.DIRECAO_ENTRADA and msg.data_hora:
        conv.janela_aberta_ate = msg.data_hora + JANELA_ATENDIMENTO
        if incrementar_unread:
            conv.unread_count = int(conv.unread_count or 0) + 1
    fields = [
        "last_message_at",
        "last_message_preview",
        "last_direction",
        "janela_aberta_ate",
        "unread_count",
        "venda",
        "atualizado_em",
    ]
    conv.save(update_fields=fields)

    try:
        from crm_app.services.whatsapp.inbox_events import publish_nova_mensagem

        publish_nova_mensagem(
            telefone=msg.telefone,
            direcao=msg.direcao,
            preview=preview,
            conversation_id=conv.id,
            message_id=msg.message_id or "",
        )
    except Exception:
        logger.debug("[Atendimento WA] publish inbox falhou", exc_info=True)


def gravar_mensagem(
    *,
    telefone: str,
    direcao: str,
    texto: str,
    tipo: str,
    origem: str,
    sucesso: bool = True,
    message_id: str = "",
    template_name: str = "",
    erro: str = "",
    venda=None,
    enviado_por=None,
    data_hora=None,
    media_url: str = "",
    media_tipo: str = "",
    role_canal: str = "cliente",
):
    """Cria o registro. Mensagens com o mesmo id e direção não duplicam."""
    from crm_app.models import MensagemWhatsAppAtendimento

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 8:
        return None
    texto_limpo = (texto or "")[:8000]
    mid = (message_id or "")[:128]
    if venda is None:
        venda = _venda_do_contexto_ou_telefone(tel)

    conversa = get_or_create_conversation(tel, role=role_canal, venda=venda)

    campos = dict(
        telefone=tel,
        conversa=conversa,
        venda=venda,
        direcao=direcao,
        tipo=tipo or MensagemWhatsAppAtendimento.TIPO_SESSAO,
        texto=texto_limpo,
        template_name=(template_name or "")[:120],
        message_id=mid,
        origem=(origem or "")[:20],
        sucesso=bool(sucesso),
        erro=(erro or "")[:2000],
        enviado_por=enviado_por,
        media_url=(media_url or "")[:500],
        media_tipo=(media_tipo or "")[:40],
    )
    if data_hora is not None:
        campos["data_hora"] = data_hora

    if mid:
        existente = MensagemWhatsAppAtendimento.objects.filter(
            message_id=mid,
            direcao=direcao,
        ).first()
        if existente:
            dirty_ex = []
            if conversa and not existente.conversa_id:
                existente.conversa = conversa
                dirty_ex.append("conversa")
            # Espelho histórico: corrige data se o caller passou o horário real do envio.
            if data_hora is not None and existente.data_hora != data_hora:
                existente.data_hora = data_hora
                dirty_ex.append("data_hora")
            if dirty_ex:
                existente.save(update_fields=dirty_ex)
                if "data_hora" in dirty_ex:
                    _atualizar_conversa_apos_mensagem(
                        existente,
                        incrementar_unread=False,
                    )
            return existente

    try:
        with transaction.atomic():
            msg = MensagemWhatsAppAtendimento.objects.create(**campos)
    except IntegrityError:
        if mid:
            return MensagemWhatsAppAtendimento.objects.filter(
                message_id=mid,
                direcao=direcao,
            ).first()
        raise

    from crm_app.models import MensagemWhatsAppAtendimento as M

    _atualizar_conversa_apos_mensagem(
        msg,
        incrementar_unread=(direcao == M.DIRECAO_ENTRADA),
    )
    if (
        direcao == M.DIRECAO_SAIDA
        and sucesso
        and enviado_por is not None
        and conversa is not None
    ):
        try:
            from crm_app.services.whatsapp.atendimento_metricas import (
                marcar_primeira_resposta_humana,
            )

            marcar_primeira_resposta_humana(
                conversa, quando=msg.data_hora, enviado_por=enviado_por
            )
        except Exception:
            logger.exception("[Atendimento WA] Falha ao marcar 1ª resposta humana")
    return msg


def _texto_entrada(data: dict) -> str:
    texto = ""
    bloco = data.get("text")
    if isinstance(bloco, dict):
        texto = bloco.get("message") or bloco.get("text") or bloco.get("body") or ""
    if not texto:
        msg = data.get("message")
        if isinstance(msg, dict):
            texto = msg.get("text") or msg.get("body") or msg.get("message") or ""
        elif isinstance(msg, str):
            texto = msg
    texto = str(texto or "").strip()

    # Clique em botão de template (Meta interactive / WhatsAtende).
    if not texto:
        btn = data.get("buttonsResponseMessage")
        if isinstance(btn, dict):
            texto = str(
                btn.get("message")
                or btn.get("selectedButtonText")
                or btn.get("selectedDisplayText")
                or btn.get("text")
                or ""
            ).strip()
    if not texto:
        inter = data.get("interactive") if isinstance(data.get("interactive"), dict) else {}
        for key in ("button_reply", "list_reply"):
            br = inter.get(key) if isinstance(inter.get(key), dict) else {}
            texto = str(br.get("title") or br.get("id") or "").strip()
            if texto:
                break
    if texto:
        return texto[:5000]

    tipo = str(data.get("whatsatendeMessageType") or data.get("type") or "").lower()
    if isinstance(data.get("image"), dict) or tipo in ("image", "img", "sticker"):
        return "[imagem]"
    if isinstance(data.get("audio"), dict) or tipo in ("audio", "ptt"):
        return "[áudio]"
    if isinstance(data.get("video"), dict) or tipo == "video":
        return "[vídeo]"
    if isinstance(data.get("document"), dict) or tipo in ("document", "pdf", "file"):
        return "[documento]"
    if tipo in ("button", "interactive", "button_reply", "buttons_response"):
        return "[botão]"
    return ""


def _canal_cliente(data: dict) -> bool:
    """Número oficial do cliente: Cloud API Meta ou WhatsAtende (Número B)."""
    return bool(data.get("_meta_raw") is not None or data.get("_whatsatende_raw") is not None)


def registrar_entrada_webhook(data: Any):
    """Grava mensagem do canal do cliente. Ignora o bot interno (Z-API/Evolution)."""
    if not isinstance(data, dict) or not data:
        return None
    payload = data
    if not _canal_cliente(payload):
        bruto = payload.get("object") == "whatsapp_business_account" or payload.get("senderNumber")
        if bruto:
            from crm_app.whatsapp_webhook_normalizer import normalizar_webhook

            payload = normalizar_webhook(payload)
        if not isinstance(payload, dict) or not _canal_cliente(payload):
            return None
    if payload.get("isGroup"):
        return None

    telefone = payload.get("phone") or payload.get("from") or ""
    texto = _texto_entrada(payload)
    if not texto:
        return None

    from crm_app.models import MensagemWhatsAppAtendimento

    from_me = bool(payload.get("fromMe") or payload.get("isFromMe") or payload.get("from_me"))
    direcao = (
        MensagemWhatsAppAtendimento.DIRECAO_SAIDA
        if from_me
        else MensagemWhatsAppAtendimento.DIRECAO_ENTRADA
    )
    origem = (
        MensagemWhatsAppAtendimento.ORIGEM_CANAL
        if from_me
        else MensagemWhatsAppAtendimento.ORIGEM_WEBHOOK
    )
    try:
        msg = gravar_mensagem(
            telefone=str(telefone),
            direcao=direcao,
            texto=texto,
            tipo=MensagemWhatsAppAtendimento.TIPO_SESSAO,
            origem=origem,
            sucesso=True,
            message_id=str(payload.get("messageId") or "")[:128],
        )
        if msg is not None:
            try:
                _marcar_reply_canal_por_webhook(msg.telefone, payload)
            except Exception:
                logger.debug(
                    "[Atendimento WA] reply_canal webhook falhou", exc_info=True
                )
        if (
            msg is not None
            and direcao == MensagemWhatsAppAtendimento.DIRECAO_ENTRADA
        ):
            try:
                from crm_app.services.whatsapp.atendimento_automacao import (
                    processar_entrada_para_automacao,
                )

                processar_entrada_para_automacao(msg)
            except Exception:
                logger.exception("[Atendimento WA] Automação pós-entrada falhou")
        return msg
    except Exception:
        logger.exception("[Atendimento WA] Falha ao gravar mensagem do webhook")
        return None


def registrar_saida_cliente(
    *,
    telefone: str,
    texto: str,
    tipo: str,
    sucesso: bool,
    resposta: Any = None,
    template_name: str = "",
) -> None:
    """Chamado pelo WhatsAppService no purpose cliente. Não propaga erro de gravação."""
    from crm_app.models import MensagemWhatsAppAtendimento

    ctx = _ctx()
    origem = ctx.get("origem") or MensagemWhatsAppAtendimento.ORIGEM_CRM
    enviado_por = ctx.get("enviado_por")
    try:
        gravar_mensagem(
            telefone=telefone,
            direcao=MensagemWhatsAppAtendimento.DIRECAO_SAIDA,
            texto=texto or (f"Modelo: {template_name}" if template_name else ""),
            tipo=tipo,
            origem=origem,
            sucesso=sucesso,
            message_id=_extrair_message_id(resposta),
            template_name=template_name,
            erro=_erro_resposta(resposta, sucesso),
            venda=ctx.get("venda"),
            enviado_por=enviado_por,
        )
    except Exception:
        logger.exception("[Atendimento WA] Falha ao gravar saída")


def texto_modelo(template_name: str, body_params: Any = None) -> str:
    """Texto do histórico: corpo legível do catálogo (ou fallback rotulado)."""
    from crm_app.services.whatsapp.nio_templates import render_template_preview

    params = body_params if isinstance(body_params, (list, tuple)) else None
    if params is None and isinstance(body_params, dict):
        corpo = body_params.get("body")
        if isinstance(corpo, list):
            params = corpo
    return render_template_preview(template_name or "", params or [])


def ultima_entrada(telefone: str):
    from crm_app.models import MensagemWhatsAppAtendimento

    chaves = telefones_equivalentes(telefone)
    if not chaves:
        return None
    return (
        MensagemWhatsAppAtendimento.objects.filter(
            telefone__in=chaves,
            direcao=MensagemWhatsAppAtendimento.DIRECAO_ENTRADA,
        )
        .order_by("-data_hora", "-id")
        .first()
    )


def estado_janela(telefone: str, agora=None) -> dict:
    agora = agora or timezone.now()
    ultima = ultima_entrada(telefone)
    if ultima is None:
        return {
            "aberta": False,
            "ate": None,
            "ultima_entrada_em": None,
            "aviso": AVISO_SEM_MENSAGEM_CLIENTE,
        }
    limite = ultima.data_hora + JANELA_ATENDIMENTO
    aberta = (agora - ultima.data_hora) < JANELA_ATENDIMENTO
    return {
        "aberta": aberta,
        "ate": limite if aberta else None,
        "ultima_entrada_em": ultima.data_hora,
        "aviso": "" if aberta else AVISO_JANELA_FECHADA,
    }


def _reply_canal_conversa(telefone: str) -> str:
    from crm_app.models import WhatsAppConversation

    tel = canonicalizar_telefone(telefone)
    conv = get_or_create_conversation(tel)
    if conv is None:
        return WhatsAppConversation.REPLY_CANAL_CLIENTE
    canal = (getattr(conv, "reply_canal", None) or "").strip().lower()
    if canal == WhatsAppConversation.REPLY_CANAL_FUNIL:
        return WhatsAppConversation.REPLY_CANAL_FUNIL
    return WhatsAppConversation.REPLY_CANAL_CLIENTE


def set_reply_canal(telefone: str, canal: str) -> None:
    from crm_app.models import WhatsAppConversation

    tel = canonicalizar_telefone(telefone)
    conv = get_or_create_conversation(tel)
    if conv is None:
        return
    canal_n = (canal or "").strip().lower()
    if canal_n not in (
        WhatsAppConversation.REPLY_CANAL_CLIENTE,
        WhatsAppConversation.REPLY_CANAL_FUNIL,
    ):
        canal_n = WhatsAppConversation.REPLY_CANAL_CLIENTE
    if getattr(conv, "reply_canal", "") != canal_n:
        WhatsAppConversation.objects.filter(pk=conv.pk).update(reply_canal=canal_n)


def _whatsapp_service_para_reply(telefone: str):
    """Escolhe para_funil (#247) ou para_cliente (#194) conforme reply_canal."""
    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp_config_service import canal_funil_pronto
    from crm_app.whatsapp_service import WhatsAppService

    if (
        _reply_canal_conversa(telefone) == WhatsAppConversation.REPLY_CANAL_FUNIL
        and canal_funil_pronto()
    ):
        return WhatsAppService.para_funil(), WhatsAppConversation.REPLY_CANAL_FUNIL
    return WhatsAppService.para_cliente(), WhatsAppConversation.REPLY_CANAL_CLIENTE


def _whatsapp_id_do_payload(payload: dict) -> str:
    raw = payload.get("_whatsatende_raw")
    sources = [payload]
    if isinstance(raw, dict):
        sources.append(raw)
    for src in sources:
        for key in ("whatsappId", "whatsapp_id", "wid", "connectionId", "whatsappID"):
            val = src.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return ""


def _marcar_reply_canal_por_webhook(telefone: str, payload: dict) -> None:
    """Se o inbound veio do ID Funil (#247), próximo reply humano sai pelo Funil."""
    from django.conf import settings

    from crm_app.models import WhatsAppConversation

    wid = _whatsapp_id_do_payload(payload if isinstance(payload, dict) else {})
    if not wid:
        return
    id_funil = str(getattr(settings, "WHATSATENDE_WHATSAPP_ID_FUNIL", "") or "").strip()
    if id_funil and wid == id_funil:
        set_reply_canal(telefone, WhatsAppConversation.REPLY_CANAL_FUNIL)


_CANAL_PRONTO_CACHE: tuple[float, bool] | None = None
_CANAL_PRONTO_TTL = 45.0


def canal_oficial_pronto() -> bool:
    """O inbox só envia pelo número oficial (Cloud API Meta ou WhatsAtende B)."""
    global _CANAL_PRONTO_CACHE
    import time

    agora = time.monotonic()
    if _CANAL_PRONTO_CACHE is not None and (agora - _CANAL_PRONTO_CACHE[0]) < _CANAL_PRONTO_TTL:
        return _CANAL_PRONTO_CACHE[1]
    ok = False
    try:
        from crm_app.services.whatsapp.factory import (
            PURPOSE_CLIENTE,
            resolve_backend_for_purpose,
        )
        from crm_app.services.whatsapp_config_service import (
            canal_cliente_pronto,
            get_active_whatsapp_provider_name,
        )

        if canal_cliente_pronto():
            backend, role = resolve_backend_for_purpose(
                get_active_whatsapp_provider_name(), PURPOSE_CLIENTE
            )
            ok = role == PURPOSE_CLIENTE and backend in _BACKENDS_OFICIAIS
    except Exception:
        logger.debug("[Atendimento WA] Falha ao checar canal oficial", exc_info=True)
        ok = False
    _CANAL_PRONTO_CACHE = (agora, ok)
    return ok


def bot_pausado(telefone: str) -> bool:
    from crm_app.whatsapp_telefone_blocklist import telefone_esta_bloqueado

    return telefone_esta_bloqueado(telefone)


def pausar_bot(telefone: str, usuario, descricao: str = "") -> None:
    from crm_app.models import WhatsAppTelefoneSemIa

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 10:
        return
    texto = (descricao or "Conversa assumida no atendimento WhatsApp")[:200]
    item = WhatsAppTelefoneSemIa.objects.filter(telefone=tel).first()
    if item:
        item.ativo = True
        item.motivo = WhatsAppTelefoneSemIa.MOTIVO_CONVERSA_MANUAL
        item.descricao = texto
        if usuario is not None and getattr(usuario, "pk", None) and not item.criado_por_id:
            item.criado_por = usuario
        item.save()
        return
    WhatsAppTelefoneSemIa.objects.create(
        telefone=tel,
        descricao=texto,
        motivo=WhatsAppTelefoneSemIa.MOTIVO_CONVERSA_MANUAL,
        ativo=True,
        criado_por=usuario if getattr(usuario, "pk", None) else None,
    )


def _qs_visivel(usuario) -> QuerySet:
    from crm_app.models import MensagemWhatsAppAtendimento
    from crm_app.services.escopo_operadora import (
        operadora_ids_permitidas,
        usuario_tem_bypass_operadora,
    )

    qs = MensagemWhatsAppAtendimento.objects.all()
    if usuario_tem_bypass_operadora(usuario):
        return qs
    permitidas = operadora_ids_permitidas(usuario)
    if permitidas is None:
        return qs
    return qs.filter(
        Q(venda__isnull=True) | Q(venda__plano__operadora_id__in=permitidas)
    )


def venda_visivel(usuario, venda) -> bool:
    if venda is None:
        return True
    from crm_app.services.escopo_operadora import (
        operadora_ids_permitidas,
        usuario_tem_bypass_operadora,
    )

    if usuario_tem_bypass_operadora(usuario):
        return True
    permitidas = operadora_ids_permitidas(usuario)
    plano = getattr(venda, "plano", None)
    operadora_id = getattr(plano, "operadora_id", None) if plano is not None else None
    if not operadora_id:
        return permitidas is None
    if permitidas is None:
        return True
    return int(operadora_id) in permitidas


def conversa_visivel(usuario, telefone: str) -> bool:
    if not _qs_visivel(usuario).filter(telefone__in=telefones_equivalentes(telefone)).exists():
        return False
    venda = _venda_cabecalho(telefone, usuario)
    return venda_visivel(usuario, venda)


def _venda_cabecalho(telefone: str, usuario=None):
    from crm_app.models import MensagemWhatsAppAtendimento

    chaves = telefones_equivalentes(telefone)
    if not chaves:
        return None
    qs = MensagemWhatsAppAtendimento.objects.filter(telefone__in=chaves, venda__isnull=False)
    if usuario is not None:
        qs = _qs_visivel(usuario).filter(telefone__in=chaves, venda__isnull=False)
    msg = (
        qs.select_related("venda__cliente", "venda__plano")
        .order_by("-data_hora", "-id")
        .first()
    )
    if msg and msg.venda_id:
        return msg.venda
    venda = resolver_venda(canonicalizar_telefone(telefone))
    if usuario is not None and not venda_visivel(usuario, venda):
        return None
    return venda


def _nome_cliente(venda) -> Optional[str]:
    cliente = getattr(venda, "cliente", None) if venda is not None else None
    if cliente is None:
        return None
    return cliente.nome_razao_social or None


def serializar_mensagem(msg, *, mailing_params_cache: Optional[dict] = None) -> dict:
    import re

    from crm_app.services.whatsapp.nio_templates import (
        botoes_template_catalogo,
        formatar_texto_template_exibicao,
        params_mailing_por_telefone,
    )

    texto_bruto = msg.texto or ""
    template_name = (msg.template_name or "").strip()
    if not template_name:
        m_mail = re.match(r"^\[Mailing\]\s*(\S+)\s*$", texto_bruto.strip(), re.I)
        if m_mail:
            template_name = m_mail.group(1)
    body_params = None
    tel_msg = getattr(msg, "telefone", "") or ""
    precisa_mail = bool(
        template_name.startswith("mailing_")
        or texto_bruto.startswith("[Mailing]")
        or (template_name and "—" in texto_bruto)
    )
    if precisa_mail and tel_msg and (
        texto_bruto.startswith("[Mailing]") or "—" in texto_bruto or "{{" in texto_bruto
    ):
        cache = mailing_params_cache if mailing_params_cache is not None else {}
        if tel_msg not in cache:
            cache[tel_msg] = params_mailing_por_telefone(tel_msg, template_name)
        body_params = cache.get(tel_msg)
    # Templates (tipo MODELO ou dump legado) → preview legível na UI.
    if (
        getattr(msg, "tipo", "") == "MODELO"
        or template_name
        or texto_bruto.startswith("Modelo:")
        or texto_bruto.startswith("[Mailing]")
        or "{{" in texto_bruto
        or (template_name.startswith("mailing_") and "—" in texto_bruto)
    ):
        texto_exibicao = formatar_texto_template_exibicao(
            texto_bruto,
            template_name,
            telefone=tel_msg,
            body_params=body_params,
        )
    else:
        texto_exibicao = texto_bruto
    return {
        "id": msg.id,
        "direcao": msg.direcao,
        "direcao_label": "Recebida" if msg.direcao == "ENTRADA" else "Enviada",
        "tipo": msg.tipo,
        "tipo_label": "Modelo" if msg.tipo == "MODELO" else "Sessão",
        "texto": texto_exibicao,
        "texto_bruto": texto_bruto,
        "template_name": template_name,
        "template_botoes": botoes_template_catalogo(template_name) if template_name else [],
        "data_hora": msg.data_hora.isoformat() if msg.data_hora else None,
        "sucesso": bool(msg.sucesso),
        "erro": msg.erro or "",
        "origem": msg.origem or "",
        "enviado_por": msg.enviado_por.username if getattr(msg, "enviado_por_id", None) else None,
        "venda_id": msg.venda_id,
        "status_entrega": getattr(msg, "status_entrega", "") or "",
        "media_url": getattr(msg, "media_url", "") or "",
        "media_tipo": getattr(msg, "media_tipo", "") or "",
        "conversation_id": getattr(msg, "conversa_id", None),
    }


def _painel_lead(venda) -> Optional[dict]:
    if venda is None:
        return None
    plano = getattr(venda, "plano", None)
    status_t = getattr(venda, "status_tratamento", None)
    status_e = getattr(venda, "status_esteira", None)
    endereco_bits = [
        getattr(venda, "logradouro", None) or "",
        getattr(venda, "numero_residencia", None) or "",
        getattr(venda, "bairro", None) or "",
        getattr(venda, "cidade", None) or "",
        getattr(venda, "estado", None) or "",
        getattr(venda, "cep", None) or "",
    ]
    endereco = ", ".join(p for p in endereco_bits if p and str(p).strip())
    elig = getattr(venda, "whatsapp_eligibility", None) or {}
    return {
        "venda_id": venda.id,
        "cliente": _nome_cliente(venda),
        "cpf_cnpj": getattr(getattr(venda, "cliente", None), "cpf_cnpj", None),
        "telefone1": venda.telefone1 or "",
        "telefone2": venda.telefone2 or "",
        "plano": getattr(plano, "nome", None) if plano else None,
        "status_tratamento": getattr(status_t, "nome", None) if status_t else None,
        "status_esteira": getattr(status_e, "nome", None) if status_e else None,
        "endereco": endereco,
        "ordem_servico": venda.ordem_servico or "",
        "pedido_pap": venda.pedido_pap or "",
        "nao_perturbe": bool(getattr(venda, "nao_perturbe", False)),
        "is_whatsapp_eligible": bool(getattr(venda, "is_whatsapp_eligible", False)),
        "whatsapp_eligibility": elig if isinstance(elig, dict) else {},
    }


def _serializar_conversa_base(
    telefone: str,
    ultima=None,
    usuario=None,
    *,
    ultima_entrada_msg=None,
    venda=None,
    bot_pausado_flag: Optional[bool] = None,
) -> dict:
    if venda is None:
        if ultima is not None and ultima.venda_id:
            venda = ultima.venda
        else:
            venda = _venda_cabecalho(telefone, usuario) if ultima is not None else None
    agora = timezone.now()
    if ultima_entrada_msg is None and telefone:
        # Fallback pontual (detalhe); listagem passa em lote.
        ultima_entrada_msg = ultima_entrada(telefone)
    if ultima_entrada_msg is None:
        janela = {
            "aberta": False,
            "ate": None,
            "ultima_entrada_em": None,
            "aviso": AVISO_SEM_MENSAGEM_CLIENTE,
        }
    else:
        limite = ultima_entrada_msg.data_hora + JANELA_ATENDIMENTO
        aberta = (agora - ultima_entrada_msg.data_hora) < JANELA_ATENDIMENTO
        janela = {
            "aberta": aberta,
            "ate": limite if aberta else None,
            "ultima_entrada_em": ultima_entrada_msg.data_hora,
            "aviso": "" if aberta else AVISO_JANELA_FECHADA,
        }
    preview = ""
    if ultima is not None:
        preview = (ultima.texto or "").replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:90] + "…"
    return {
        "telefone": canonicalizar_telefone(telefone),
        "telefone_exibicao": exibir_telefone(telefone),
        "cliente": _nome_cliente(venda),
        "venda_id": venda.id if venda is not None else None,
        "ultima_mensagem": preview,
        "ultima_direcao": ultima.direcao if ultima is not None else None,
        "ultima_tipo": ultima.tipo if ultima is not None else None,
        "ultima_em": ultima.data_hora.isoformat() if ultima is not None and ultima.data_hora else None,
        "janela_aberta": janela["aberta"],
        "janela_ate": janela["ate"].isoformat() if janela["ate"] else None,
        "aviso_janela": janela["aviso"],
        "bot_pausado": bot_pausado(telefone) if bot_pausado_flag is None else bool(bot_pausado_flag),
    }


_CHANNEL_CLIENTE_ID: int | None = None


def _channel_cliente_id() -> int:
    """Cache do FK do canal cliente — evita get_or_create a cada request."""
    global _CHANNEL_CLIENTE_ID
    if _CHANNEL_CLIENTE_ID:
        return _CHANNEL_CLIENTE_ID
    channel = get_or_create_channel("cliente")
    _CHANNEL_CLIENTE_ID = int(channel.pk)
    return _CHANNEL_CLIENTE_ID


def _qs_conversas_visiveis(usuario, *, for_list: bool = False):
    from crm_app.models import WhatsAppConversation
    from crm_app.services.escopo_operadora import (
        operadora_ids_permitidas,
        usuario_tem_bypass_operadora,
    )

    qs = WhatsAppConversation.objects.filter(channel_id=_channel_cliente_id())
    if for_list:
        # Listagem: JOINs mínimos (nome + assignee). Contagens usam select_related(None).
        qs = qs.select_related("venda__cliente", "assignee")
    else:
        qs = qs.select_related(
            "venda__cliente",
            "venda__plano",
            "venda__status_tratamento",
            "venda__status_esteira",
            "assignee",
            "channel",
            "funil_tratamento",
        )
    if usuario_tem_bypass_operadora(usuario):
        return qs
    permitidas = operadora_ids_permitidas(usuario)
    if permitidas is None:
        return qs
    return qs.filter(Q(venda__isnull=True) | Q(venda__plano__operadora_id__in=permitidas))


def _modo_conv(conv) -> str:
    try:
        from crm_app.services.whatsapp.atendimento_automacao import modo_atendimento

        return modo_atendimento(conv)
    except Exception:
        return "BOT"


def _preview_lista_legivel(preview: str) -> str:
    """Converte preview técnico [Template …] para texto do cliente na lista."""
    raw = (preview or "").strip()
    if not raw:
        return ""
    try:
        from crm_app.services.whatsapp.nio_templates import formatar_texto_template_exibicao

        raw = formatar_texto_template_exibicao(raw)
    except Exception:
        pass
    raw = raw.replace("\n", " ").strip()
    if len(raw) > 90:
        return raw[:90] + "…"
    return raw


def _serializar_conversation_row(conv, *, agora=None) -> dict:
    agora = agora or timezone.now()
    venda = conv.venda if conv.venda_id else None
    janela_ate = conv.janela_aberta_ate
    janela_aberta = bool(janela_ate and janela_ate > agora)
    preview = _preview_lista_legivel(conv.last_message_preview or "")
    nome = conv.contact_name or _nome_cliente(venda)
    tags = []
    try:
        tags = [
            {"id": t.id, "nome": t.nome, "cor": t.cor or "#6c757d"}
            for t in conv.tags.all()[:8]
        ]
    except Exception:
        tags = []
    return {
        "id": conv.id,
        "conversation_id": conv.id,
        "telefone": conv.telefone,
        "telefone_exibicao": exibir_telefone(conv.telefone),
        "cliente": nome,
        "venda_id": conv.venda_id,
        "ultima_mensagem": preview,
        "ultima_direcao": conv.last_direction or None,
        "ultima_tipo": None,
        "ultima_em": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "janela_aberta": janela_aberta,
        "janela_ate": janela_ate.isoformat() if janela_ate else None,
        "aviso_janela": "" if janela_aberta else AVISO_JANELA_FECHADA,
        # Lista usa flag denormalizada (sem hit extra na blocklist por linha).
        "bot_pausado": bool(conv.bot_pausado),
        "unread_count": int(conv.unread_count or 0),
        "status": conv.status,
        "assignee": conv.assignee.username if conv.assignee_id else None,
        "assignee_id": conv.assignee_id,
        "etapa_funil": getattr(conv, "etapa_funil", "") or "",
        "reply_canal": getattr(conv, "reply_canal", None) or "cliente",
        "reply_canal_label": (
            "Funil"
            if getattr(conv, "reply_canal", "") == "funil"
            else "Inbox"
        ),
        "tags": tags,
        "modo": _modo_conv(conv),
    }


def listar_conversas(
    usuario,
    busca: str = "",
    limite: int = 40,
    *,
    since: Optional[str] = None,
    fila: str = "todas",
    etapa: str = "",
    canal: str = "",
    janela: str = "",
    offset: int = 0,
) -> dict:
    """Lista conversas a partir de WhatsAppConversation (denormalizado).

    Retorna ``{items, has_more, limit, offset}``.
    """
    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp.atendimento_crm import aplicar_filtro_fila

    limite = max(1, min(int(limite or 40), 100))
    offset_n = max(0, int(offset or 0))
    qs = _qs_conversas_visiveis(usuario, for_list=True)
    qs = aplicar_filtro_fila(qs, usuario, fila)
    canal_n = (canal or "").strip().lower()
    if canal_n in ("cliente", "inbox"):
        qs = qs.filter(reply_canal=WhatsAppConversation.REPLY_CANAL_CLIENTE)
    elif canal_n == "funil":
        qs = qs.filter(reply_canal=WhatsAppConversation.REPLY_CANAL_FUNIL)
    janela_n = (janela or "").strip().lower()
    agora = timezone.now()
    if janela_n in ("aberta", "open", "24h"):
        qs = qs.filter(janela_aberta_ate__gt=agora)
    elif janela_n in ("fechada", "closed"):
        qs = qs.filter(Q(janela_aberta_ate__isnull=True) | Q(janela_aberta_ate__lte=agora))
    etapa_n = (etapa or "").strip().upper()
    if etapa_n:
        qs = qs.filter(etapa_funil=etapa_n)
    termo = (busca or "").strip()
    if termo:
        digitos = "".join(ch for ch in termo if ch.isdigit())
        filtro = (
            Q(contact_name__icontains=termo)
            | Q(venda__cliente__nome_razao_social__icontains=termo)
            | Q(tags__nome__icontains=termo)
        )
        if digitos:
            filtro |= Q(telefone__icontains=digitos)
        qs = qs.filter(filtro).distinct()

    if since:
        try:
            since_dt = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
            if timezone.is_naive(since_dt):
                since_dt = timezone.make_aware(since_dt)
            qs = qs.filter(last_message_at__gte=since_dt)
        except Exception:
            pass

    qs = (
        qs.only(
            "id",
            "telefone",
            "contact_name",
            "last_message_at",
            "last_message_preview",
            "last_direction",
            "janela_aberta_ate",
            "bot_pausado",
            "unread_count",
            "status",
            "assignee_id",
            "etapa_funil",
            "reply_canal",
            "venda_id",
            "assignee__username",
            "venda__cliente__nome_razao_social",
        )
        .prefetch_related("tags")
        .order_by("-last_message_at", "-id")
    )
    fatia = list(qs[offset_n : offset_n + limite + 1])
    has_more = len(fatia) > limite
    if has_more:
        fatia = fatia[:limite]
    items = [_serializar_conversation_row(c, agora=agora) for c in fatia]
    return {
        "items": items,
        "has_more": has_more,
        "limit": limite,
        "offset": offset_n,
        "loaded": offset_n + len(items),
    }


def detalhe_conversa(
    usuario,
    telefone: str,
    *,
    limit_msgs: int = 40,
    before_id: Optional[int] = None,
    incluir_crm: bool = True,
) -> Optional[dict]:
    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp_config_service import canal_funil_pronto as _funil_pronto

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 8:
        return None
    chaves = telefones_equivalentes(tel)
    limit_msgs = max(10, min(int(limit_msgs or 40), 80))

    # Uma query leve da conversa (sem JOINs de lead pesados).
    conv = (
        WhatsAppConversation.objects.filter(
            channel_id=_channel_cliente_id(),
            telefone__in=chaves,
        )
        .select_related("assignee", "venda__cliente")
        .order_by("-last_message_at", "-id")
        .first()
    )
    if conv is None and not conversa_visivel(usuario, tel):
        return None
    if conv is None:
        conv = get_or_create_conversation(tel, venda=_venda_cabecalho(tel, usuario))

    qs = (
        _qs_visivel(usuario)
        .filter(telefone__in=chaves)
        .select_related("enviado_por")
        .order_by("-data_hora", "-id")
    )
    if before_id:
        try:
            qs = qs.filter(id__lt=int(before_id))
        except (TypeError, ValueError):
            pass
    mensagens_desc = list(qs[:limit_msgs])
    if not mensagens_desc and not before_id and conv is None:
        return None
    mensagens = list(reversed(mensagens_desc))
    ultima = mensagens[-1] if mensagens else None
    mailing_cache: dict = {}
    if ultima is None:
        base = _serializar_conversation_row(conv) if conv else {
            "telefone": tel,
            "telefone_exibicao": exibir_telefone(tel),
        }
        base["mensagens"] = []
        base["has_more"] = False
    else:
        base = _serializar_conversa_base(
            tel, ultima, usuario, venda=conv.venda if conv else None
        )
        if conv:
            base["conversation_id"] = conv.id
            base["unread_count"] = int(conv.unread_count or 0)
            base["status"] = conv.status
            base["assignee"] = conv.assignee.username if conv.assignee_id else None
            base["assignee_id"] = conv.assignee_id
            base["etapa_funil"] = getattr(conv, "etapa_funil", "") or ""
            base["bot_pausado"] = bool(conv.bot_pausado)
            base["modo"] = _modo_conv(conv)
        base["mensagens"] = [
            serializar_mensagem(m, mailing_params_cache=mailing_cache) for m in mensagens
        ]
        base["has_more"] = len(mensagens_desc) >= limit_msgs
        base["oldest_id"] = mensagens[0].id if mensagens else None

    reply_canal = (
        getattr(conv, "reply_canal", None) or WhatsAppConversation.REPLY_CANAL_CLIENTE
        if conv is not None
        else WhatsAppConversation.REPLY_CANAL_CLIENTE
    )
    base["reply_canal"] = reply_canal
    base["reply_canal_label"] = (
        "Funil" if reply_canal == WhatsAppConversation.REPLY_CANAL_FUNIL else "Inbox"
    )
    canal_pronto = canal_oficial_pronto()
    envio_pronto = (
        _funil_pronto()
        if reply_canal == WhatsAppConversation.REPLY_CANAL_FUNIL
        else canal_pronto
    )
    if not envio_pronto:
        envio_pronto = canal_pronto or _funil_pronto()
    base["canal_oficial_pronto"] = bool(envio_pronto)
    base["aviso_canal"] = "" if envio_pronto else AVISO_CANAL_INDISPONIVEL
    base["pode_texto_livre"] = bool(base.get("janela_aberta")) and bool(envio_pronto)

    if conv and int(conv.unread_count or 0) > 0 and not before_id:
        WhatsAppConversation.objects.filter(pk=conv.pk).update(unread_count=0)
        base["unread_count"] = 0

    if not incluir_crm:
        base["lead"] = None
        base["tags"] = []
        base["notas"] = []
        base["tarefas"] = []
        base["eventos"] = []
        base["crm_parcial"] = True
        return base

    venda = conv.venda if conv and conv.venda_id else None
    if venda is None and incluir_crm:
        venda = _venda_cabecalho(tel, usuario)
    if venda is not None and not hasattr(venda, "cliente"):
        try:
            venda = type(venda).objects.select_related(
                "cliente", "plano", "status_tratamento", "status_esteira"
            ).filter(pk=venda.pk).first() or venda
        except Exception:
            pass
    base["lead"] = _painel_lead(venda)

    if conv is not None:
        from crm_app.services.whatsapp.atendimento_crm import enriquecer_detalhe_crm

        try:
            conv_crm = (
                WhatsAppConversation.objects.select_related(
                    "assignee", "funil_tratamento"
                )
                .prefetch_related("tags")
                .get(pk=conv.pk)
            )
        except WhatsAppConversation.DoesNotExist:
            pass
        else:
            base = enriquecer_detalhe_crm(base, conv_crm)
    return base


def assumir_conversa(usuario, telefone: str) -> Optional[dict]:
    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp.atendimento_crm import registrar_evento

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 10:
        return None
    if not conversa_visivel(usuario, tel):
        conv = get_or_create_conversation(tel)
        if conv is None:
            return None
    pausar_bot(tel, usuario, "Conversa assumida no atendimento WhatsApp")
    conv = get_or_create_conversation(tel)
    if conv is not None:
        conv.bot_pausado = True
        conv.assignee = usuario if getattr(usuario, "pk", None) else None
        conv.status = WhatsAppConversation.STATUS_EM_ATENDIMENTO
        if getattr(conv, "encerrada_em", None):
            conv.encerrada_em = None
            conv.save(
                update_fields=[
                    "bot_pausado",
                    "assignee",
                    "status",
                    "encerrada_em",
                    "atualizado_em",
                ]
            )
        else:
            conv.save(update_fields=["bot_pausado", "assignee", "status", "atualizado_em"])
        registrar_evento(
            conv,
            "ASSUMIU",
            autor=usuario,
            texto=f"Assumiu a conversa ({getattr(usuario, 'username', '')})",
        )
    return detalhe_conversa(usuario, tel)


def iniciar_conversa_por_telefone(
    usuario,
    telefone: str,
    *,
    venda=None,
    contact_name: str = "",
    aba: str = "",
    ref_id: str = "",
) -> Optional[dict]:
    """Cria/abre Conversation e retorna detalhe (uso Funil → Iniciar Conversa)."""
    from crm_app.services.whatsapp.atendimento_crm import vincular_funil_tratamento

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 10:
        return None
    if venda is None:
        venda = resolver_venda(tel)
    conv = get_or_create_conversation(
        tel, venda=venda, contact_name=contact_name or (_nome_cliente(venda) or "")
    )
    if conv is None:
        return None
    vincular_funil_tratamento(
        conv,
        aba=aba,
        ref_id=ref_id,
        usuario=usuario,
        telefone=tel,
        nome=contact_name or (_nome_cliente(venda) or ""),
    )
    return detalhe_conversa(usuario, tel)


def _preflight_envio(
    usuario,
    telefone: str,
    *,
    exigir_janela: bool = True,
) -> tuple[str, dict, str]:
    """Retorna (codigo, payload_erro, telefone_canonico). codigo 'ok' se liberado."""
    tel = canonicalizar_telefone(telefone)
    if len(tel) < 10:
        return "invalido", {"detail": "Telefone inválido."}, tel
    if not conversa_visivel(usuario, tel):
        return "nao_encontrado", {"detail": "Conversa não encontrada."}, tel
    if exigir_janela:
        janela = estado_janela(tel)
        if not janela["aberta"]:
            return (
                "janela_fechada",
                {
                    "detail": janela["aviso"],
                    "janela_aberta": False,
                    "codigo": "janela_fechada",
                },
                tel,
            )
    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp_config_service import canal_funil_pronto

    reply = _reply_canal_conversa(tel)
    envio_ok = (
        canal_funil_pronto()
        if reply == WhatsAppConversation.REPLY_CANAL_FUNIL
        else canal_oficial_pronto()
    )
    if not envio_ok and not canal_oficial_pronto() and not canal_funil_pronto():
        return (
            "canal_indisponivel",
            {
                "detail": "A resposta não foi enviada. " + AVISO_CANAL_INDISPONIVEL,
                "janela_aberta": True,
                "codigo": "canal_indisponivel",
            },
            tel,
        )
    return "ok", {}, tel


def _message_id_de_resp(resp) -> str:
    if not isinstance(resp, dict):
        return ""
    for key in ("messageId", "message_id", "id", "keyId"):
        val = resp.get(key)
        if val:
            return str(val)[:128]
    msgs = resp.get("messages")
    if isinstance(msgs, list) and msgs:
        mid = msgs[0].get("id") if isinstance(msgs[0], dict) else None
        if mid:
            return str(mid)[:128]
    data = resp.get("data")
    if isinstance(data, dict):
        return _message_id_de_resp(data)
    return ""


def responder_texto(usuario, telefone: str, texto: str) -> tuple[str, dict]:
    """
    Envia texto livre se a janela de 24h estiver aberta.
    Retorna (codigo, payload): ok | janela_fechada | canal_indisponivel | invalido |
    falha_envio | nao_encontrado.
    """
    from crm_app.models import MensagemWhatsAppAtendimento

    corpo = (texto or "").strip()
    if not corpo:
        return "invalido", {"detail": "Informe o telefone e o texto da resposta."}
    codigo, err, tel = _preflight_envio(usuario, telefone, exigir_janela=True)
    if codigo != "ok":
        return codigo, err

    pausar_bot(tel, usuario, "Resposta humana no atendimento WhatsApp")
    svc, purpose = _whatsapp_service_para_reply(tel)
    with contexto_registro_saida(
        origem=MensagemWhatsAppAtendimento.ORIGEM_OPERADOR,
        enviado_por=usuario,
    ):
        ok, resp = svc.enviar_mensagem_texto(tel, corpo, variar=False)
    if ok:
        set_reply_canal(tel, purpose)
        # Saídas via Funil não passam por _registrar_atendimento do purpose cliente.
        if purpose == "funil":
            try:
                gravar_mensagem(
                    telefone=tel,
                    direcao=MensagemWhatsAppAtendimento.DIRECAO_SAIDA,
                    texto=corpo[:4000],
                    tipo=MensagemWhatsAppAtendimento.TIPO_SESSAO,
                    origem=MensagemWhatsAppAtendimento.ORIGEM_OPERADOR,
                    sucesso=True,
                    message_id=_message_id_de_resp(resp) if isinstance(resp, dict) else "",
                    enviado_por=usuario,
                )
            except Exception:
                logger.exception("[atendimento] falha ao gravar reply Funil")
    if not ok:
        detalhe_api = ""
        if isinstance(resp, dict):
            detalhe_api = str(resp.get("message") or resp.get("error") or resp)[:240]
        else:
            detalhe_api = str(resp or "")[:240]
        # Meta/WhatsAtende diz janela fechada: alinha o CRM (evita badge 24h mentiroso).
        if "24-hour window is closed" in detalhe_api.lower() or "template is required" in detalhe_api.lower():
            try:
                from crm_app.models import WhatsAppConversation

                WhatsAppConversation.objects.filter(
                    telefone__in=telefones_equivalentes(tel)
                ).update(janela_aberta_ate=None)
            except Exception:
                logger.debug("[atendimento] falha ao alinhar janela fechada", exc_info=True)
        msg = "A Cloud API não confirmou o envio. A tentativa ficou registrada na conversa."
        if detalhe_api:
            msg = f"{msg} ({detalhe_api})"
        return "falha_envio", {
            "detail": msg,
            "janela_aberta": False if "24-hour window is closed" in detalhe_api.lower() else True,
            "codigo": "falha_envio",
            "conversa": detalhe_conversa(usuario, tel),
        }
    return "ok", {
        "ok": True,
        "janela_aberta": True,
        "bot_pausado": True,
        "reply_canal": purpose,
        "conversa": detalhe_conversa(usuario, tel),
    }



def _salvar_audio_local(b64: str, mime: str, filename: str) -> str:
    """Grava áudio em MEDIA_ROOT e devolve URL /media/... para o player do inbox."""
    import base64
    import uuid
    from pathlib import Path as _P

    from django.conf import settings

    raw = (b64 or "").strip()
    if "base64," in raw:
        raw = raw.split("base64,", 1)[1]
    raw = raw.replace(chr(13), "").replace(chr(10), "")
    blob = base64.b64decode(raw)
    if len(blob) > 15 * 1024 * 1024:
        raise ValueError("Áudio maior que 15 MB")
    ext = "ogg"
    mime_n = (mime or "").lower()
    if "webm" in mime_n:
        ext = "webm"
    elif "mpeg" in mime_n or "mp3" in mime_n:
        ext = "mp3"
    elif "mp4" in mime_n or "m4a" in mime_n:
        ext = "m4a"
    elif "wav" in mime_n:
        ext = "wav"
    elif "ogg" in mime_n or "opus" in mime_n:
        ext = "ogg"
    nome = (filename or ("audio." + ext)).replace("\\", "/").split("/")[-1]
    if "." not in nome:
        nome = nome + "." + ext
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in nome)[:80]
    rel_dir = _P("whatsapp_audio")
    dest_dir = _P(settings.MEDIA_ROOT) / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = uuid.uuid4().hex[:12] + "_" + safe
    (dest_dir / final).write_bytes(blob)
    base = (settings.MEDIA_URL or "/media/").rstrip("/")
    return base + "/" + rel_dir.as_posix() + "/" + final


def responder_midia(
    usuario,
    telefone: str,
    *,
    kind: str,
    base64_data: str,
    filename: str = "",
    caption: str = "",
    mime: str = "",
) -> tuple[str, dict]:
    """Envia imagem ou PDF (base64) na janela de 24h e grava no histórico."""
    from crm_app.models import MensagemWhatsAppAtendimento

    kind_n = (kind or "").strip().lower()
    if kind_n in ("image", "imagem", "img", "foto"):
        kind_n = "image"
    elif kind_n in ("document", "documento", "pdf", "doc"):
        kind_n = "document"
    elif kind_n in ("audio", "ptt", "voice", "voz", "ogg", "webm"):
        kind_n = "audio"
    else:
        return "invalido", {"detail": "Tipo de mídia inválido (use image, document ou audio)."}

    raw = (base64_data or "").strip()
    if not raw:
        return "invalido", {"detail": "Arquivo vazio."}

    codigo, err, tel = _preflight_envio(usuario, telefone, exigir_janela=True)
    if codigo != "ok":
        return codigo, err

    caption_n = (caption or "").strip()[:1000]
    if kind_n == "image":
        default_name, default_mime = "image.png", "image/png"
    elif kind_n == "audio":
        default_name, default_mime = "audio.ogg", "audio/ogg"
    else:
        default_name, default_mime = "documento.pdf", "application/pdf"
    fname = (filename or default_name)[:120]
    mime_n = (mime or "").strip()[:40]
    if not mime_n:
        mime_n = default_mime

    # Normaliza data-URL
    b64 = raw
    if "base64," in b64:
        header, b64 = b64.split("base64,", 1)
        if "image/" in header and kind_n == "image":
            mime_n = header.split("data:", 1)[-1].split(";", 1)[0] or mime_n
        elif "pdf" in header:
            mime_n = "application/pdf"

    pausar_bot(tel, usuario, "Envio de mídia no atendimento WhatsApp")
    svc, purpose = _whatsapp_service_para_reply(tel)
    ok = False
    resp: Any = None
    media_url_local = ""
    with contexto_registro_saida(
        origem=MensagemWhatsAppAtendimento.ORIGEM_OPERADOR,
        enviado_por=usuario,
    ):
        if kind_n == "image":
            data_url = raw if raw.startswith("data:") else f"data:{mime_n};base64,{b64}"
            resp = svc.enviar_imagem_b64(tel, data_url, caption=caption_n)
            ok = resp is not None
        elif kind_n == "audio":
            data_url = raw if raw.startswith("data:") else f"data:{mime_n};base64,{b64}"
            resp = svc.enviar_audio_b64(tel, data_url, mime=mime_n, filename=fname)
            ok = resp is not None
            if ok:
                try:
                    media_url_local = _salvar_audio_local(b64, mime_n, fname)
                except Exception:
                    logger.exception("[atendimento] falha ao salvar áudio local")
        else:
            ok = bool(
                svc.enviar_pdf_b64(
                    tel, b64, nome_arquivo=fname, caption=caption_n or fname
                )
            )
            resp = {"ok": ok}

    if kind_n == "image":
        preview = caption_n or f"[imagem] {fname}"
    elif kind_n == "audio":
        preview = caption_n or f"[áudio] {fname}"
    else:
        preview = caption_n or f"[documento] {fname}"
    try:
        gravar_mensagem(
            telefone=tel,
            direcao=MensagemWhatsAppAtendimento.DIRECAO_SAIDA,
            texto=preview[:4000],
            tipo=MensagemWhatsAppAtendimento.TIPO_SESSAO,
            origem=MensagemWhatsAppAtendimento.ORIGEM_OPERADOR,
            sucesso=bool(ok),
            message_id=_message_id_de_resp(resp) if isinstance(resp, dict) else "",
            erro="" if ok else str(resp)[:2000],
            enviado_por=usuario,
            media_tipo=mime_n,
            media_url=media_url_local if kind_n == "audio" else "",
        )
    except Exception:
        logger.exception("[atendimento] falha ao gravar mídia no histórico")

    if ok:
        set_reply_canal(tel, purpose)

    if not ok:
        return "falha_envio", {
            "detail": "O envio da mídia não foi confirmado pelo canal.",
            "codigo": "falha_envio",
            "conversa": detalhe_conversa(usuario, tel),
        }
    return "ok", {
        "ok": True,
        "janela_aberta": True,
        "bot_pausado": True,
        "reply_canal": purpose,
        "conversa": detalhe_conversa(usuario, tel),
    }


def _normalizar_status_template(valor: Any) -> str:
    s = str(valor or "").strip().upper()
    if s in ("APPROVED", "APROVADO", "ACTIVE", "ATIVO"):
        return "APPROVED"
    if s in ("PENDING", "PENDING_APPROVAL", "IN_REVIEW", "EM_ANALISE", "SUBMITTED"):
        return "PENDING"
    if s in ("REJECTED", "REJEITADO", "DISABLED", "PAUSED", "FAILED", "ERROR"):
        return "REJECTED"
    if not s:
        return "UNKNOWN"
    return s


def _extrair_lista_templates_api(raw: Any) -> list:
    if isinstance(raw, dict):
        raw = raw.get("templates") or raw.get("data") or raw.get("items") or raw.get("result") or []
    return raw if isinstance(raw, list) else []


def _parse_template_api_item(t: Any, *, source: str) -> Optional[dict]:
    import re

    if isinstance(t, str):
        name = t.strip()
        if not name:
            return None
        return {
            "name": name,
            "label": name,
            "body_params": 0,
            "hint": "",
            "status": "UNKNOWN",
            "status_label": "Desconhecido",
            "language": "",
            "category": "",
            "source": source,
            "aprovado": None,
        }
    if not isinstance(t, dict):
        return None
    name = (
        t.get("name")
        or t.get("template_name")
        or t.get("nome")
        or ""
    ).strip()
    if not name:
        return None
    status = _normalizar_status_template(
        t.get("status") or t.get("approval_status") or t.get("state") or ""
    )
    components = t.get("components") or []
    n_params = int(t.get("body_params") or t.get("params") or 0)
    if not n_params and isinstance(components, list):
        for c in components:
            if isinstance(c, dict) and str(c.get("type") or "").upper() == "BODY":
                texto = c.get("text") or ""
                n_params = max(n_params, len(re.findall(r"\{\{\d+\}\}", str(texto))))
    status_label = {
        "APPROVED": "Aprovado",
        "PENDING": "Em análise",
        "REJECTED": "Não aprovado",
        "UNKNOWN": "Desconhecido",
    }.get(status, status)
    return {
        "name": name,
        "label": (t.get("label") or t.get("displayName") or name).strip(),
        "body_params": n_params,
        "hint": "",
        "status": status,
        "status_label": status_label,
        "language": str(t.get("language") or t.get("language_code") or "")[:16],
        "category": str(t.get("category") or "")[:32],
        "source": source,
        "aprovado": True if status == "APPROVED" else (False if status == "REJECTED" else None),
    }


def listar_templates_inbox() -> list[dict]:
    """Catálogo para o composer: API cliente + Funil + fallback curado (com status)."""
    from crm_app.whatsapp_service import WhatsAppService

    items: list[dict] = []
    by_name: dict[str, dict] = {}

    def _merge(item: dict) -> None:
        name = item["name"]
        prev = by_name.get(name)
        if prev is None:
            by_name[name] = item
            return
        # Preferir status conhecido da API sobre curado/UNKNOWN
        if prev.get("status") in (None, "", "UNKNOWN") and item.get("status") not in (None, "", "UNKNOWN"):
            by_name[name] = {**prev, **item, "label": prev.get("label") or item.get("label")}
        elif item.get("source") == "provider_funil" and prev.get("source") == "curado":
            by_name[name] = {**item, "label": prev.get("label") or item.get("label")}

    for purpose, source in (("cliente", "provider"), ("funil", "provider_funil")):
        try:
            if purpose == "funil":
                raw = WhatsAppService.para_funil().listar_templates() or []
            else:
                raw = WhatsAppService.para_cliente().listar_templates() or []
        except Exception:
            logger.debug("[Atendimento WA] listar_templates %s falhou", purpose, exc_info=True)
            raw = []
        for t in _extrair_lista_templates_api(raw):
            parsed = _parse_template_api_item(t, source=source)
            if parsed:
                _merge(parsed)

    for t in _TEMPLATES_INBOX_CURADOS:
        _merge({
            **t,
            "status": "UNKNOWN",
            "status_label": "Desconhecido",
            "language": "pt_BR",
            "category": "",
            "source": "curado",
            "aprovado": None,
        })

    # Catálogo local completo (NIO + mailing) para listagem de status
    try:
        from crm_app.services.whatsapp.nio_templates import TEMPLATE_BOTOES, TEMPLATE_BODY_PREVIEW
        from crm_app.services.mailing_templates import TEMPLATE_SPECS

        locais = set(TEMPLATE_BODY_PREVIEW.keys()) | set(TEMPLATE_BOTOES.keys())
        for spec in TEMPLATE_SPECS:
            n = (spec.get("nome") or "").strip()
            if n:
                locais.add(n)
        for name in sorted(locais):
            if name in by_name:
                continue
            _merge({
                "name": name,
                "label": name,
                "body_params": 0,
                "hint": "Catálogo local (não retornado pela API)",
                "status": "UNKNOWN",
                "status_label": "Desconhecido",
                "language": "pt_BR",
                "category": "",
                "source": "catalogo_local",
                "aprovado": None,
            })
    except Exception:
        logger.debug("[Atendimento WA] merge catálogo local falhou", exc_info=True)

    items = list(by_name.values())
    ordem = {"APPROVED": 0, "PENDING": 1, "REJECTED": 2, "UNKNOWN": 3}
    items.sort(key=lambda x: (ordem.get(x.get("status") or "UNKNOWN", 9), (x.get("name") or "").lower()))
    return items


def resumo_status_templates() -> dict:
    """Agrega aprovados / pendentes / rejeitados / desconhecidos."""
    items = listar_templates_inbox()
    agg = {"APPROVED": 0, "PENDING": 0, "REJECTED": 0, "UNKNOWN": 0}
    for t in items:
        st = t.get("status") or "UNKNOWN"
        if st not in agg:
            st = "UNKNOWN"
        agg[st] += 1
    return {
        "total": len(items),
        "aprovados": agg["APPROVED"],
        "em_analise": agg["PENDING"],
        "nao_aprovados": agg["REJECTED"],
        "desconhecidos": agg["UNKNOWN"],
        "items": items,
    }


def responder_template(
    usuario,
    telefone: str,
    *,
    template_name: str,
    body_params: Optional[list] = None,
    language_code: str = "pt_BR",
) -> tuple[str, dict]:
    """Envia template Meta (reabre conversa fora da janela 24h)."""
    from crm_app.models import MensagemWhatsAppAtendimento

    nome = (template_name or "").strip()
    if not nome:
        return "invalido", {"detail": "Informe o nome do template."}
    codigo, err, tel = _preflight_envio(usuario, telefone, exigir_janela=False)
    if codigo != "ok":
        return codigo, err

    params = []
    for p in body_params or []:
        params.append("" if p is None else str(p))

    pausar_bot(tel, usuario, "Template enviado no atendimento WhatsApp")
    svc, purpose = _whatsapp_service_para_reply(tel)
    with contexto_registro_saida(
        origem=MensagemWhatsAppAtendimento.ORIGEM_OPERADOR,
        enviado_por=usuario,
    ):
        ok, resp = svc.enviar_template(
            tel,
            nome,
            language_code=language_code or "pt_BR",
            body_params=params,
        )
    if ok:
        set_reply_canal(tel, purpose)
        if purpose == "funil":
            try:
                gravar_mensagem(
                    telefone=tel,
                    direcao=MensagemWhatsAppAtendimento.DIRECAO_SAIDA,
                    texto=texto_modelo(nome, params)[:4000],
                    tipo=MensagemWhatsAppAtendimento.TIPO_MODELO,
                    template_name=nome[:120],
                    origem=MensagemWhatsAppAtendimento.ORIGEM_OPERADOR,
                    sucesso=True,
                    message_id=_message_id_de_resp(resp) if isinstance(resp, dict) else "",
                    enviado_por=usuario,
                )
            except Exception:
                logger.exception("[atendimento] falha ao gravar template Funil")
    if not ok:
        return "falha_envio", {
            "detail": "O template não foi aceito pelo canal. " + str(resp)[:300],
            "codigo": "falha_envio",
            "conversa": detalhe_conversa(usuario, tel),
        }
    return "ok", {
        "ok": True,
        "bot_pausado": True,
        "reply_canal": purpose,
        "conversa": detalhe_conversa(usuario, tel),
    }
