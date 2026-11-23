"""Automação do inbox (Fase 3): handoff bot→humano e triggers por etapa."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Frases que pedem atendimento humano (botões Meta + linguagem natural).
_HANDOFF_EXATOS = frozenset({
    "FALAR COM ATENDENTE",
    "FALAR COM UM ATENDENTE",
    "ATENDENTE",
    "FALAR COM SUPORTE",
    "QUERO FALAR COM ATENDENTE",
    "QUERO ATENDENTE",
    "HUMANO",
    "PESSOA",
    "OPERADOR",
})

_HANDOFF_REGEX = re.compile(
    r"\b(falar\s+com\s+(um\s+)?(atendente|humano|suporte|pessoa)|"
    r"atendente\s+humano|quero\s+atendente|preciso\s+de\s+ajuda\s+humana|"
    r"sair\s+do\s+bot|parar\s+bot)\b",
    re.IGNORECASE,
)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"\s+", " ", t).strip().upper()
    return t


def detectar_pedido_humano(texto: str) -> bool:
    n = _norm(texto)
    if not n:
        return False
    if n in _HANDOFF_EXATOS:
        return True
    # botões curtos
    if n.replace(" ", "") in {x.replace(" ", "") for x in _HANDOFF_EXATOS}:
        return True
    return bool(_HANDOFF_REGEX.search(texto or ""))


_IA_MODO_CACHE: tuple[float, bool] | None = None
_IA_MODO_TTL_SEC = 60.0


def _ia_atendimento_ligada() -> bool:
    """Cache curto — evita 1 SELECT por conversa na listagem."""
    global _IA_MODO_CACHE
    import time

    agora = time.monotonic()
    if _IA_MODO_CACHE is not None and (agora - _IA_MODO_CACHE[0]) < _IA_MODO_TTL_SEC:
        return _IA_MODO_CACHE[1]
    ligada = False
    try:
        from crm_app.models import WhatsAppIaConfig

        cfg = WhatsAppIaConfig.objects.order_by("id").only(
            "ia_contatos_externos_ativa", "ia_clientes_venda_ativa"
        ).first()
        ligada = bool(
            cfg is not None
            and (
                getattr(cfg, "ia_contatos_externos_ativa", False)
                or getattr(cfg, "ia_clientes_venda_ativa", False)
            )
        )
    except Exception:
        ligada = False
    _IA_MODO_CACHE = (agora, ligada)
    return ligada


def modo_atendimento(conv) -> str:
    """BOT | IA | HUMANO | ENCERRADA — badge estilo Kommo."""
    from crm_app.models import WhatsAppConversation

    if conv is None:
        return "BOT"
    if getattr(conv, "status", None) == WhatsAppConversation.STATUS_ENCERRADA:
        return "ENCERRADA"
    if (
        getattr(conv, "assignee_id", None)
        or getattr(conv, "bot_pausado", False)
        or getattr(conv, "status", None) == WhatsAppConversation.STATUS_EM_ATENDIMENTO
    ):
        return "HUMANO"
    if _ia_atendimento_ligada():
        return "IA"
    return "BOT"


def handoff_para_humano(
    conversa,
    *,
    motivo: str = "",
    texto_cliente: str = "",
    usuario=None,
) -> bool:
    """Pausa bot, coloca na fila humana e registra evento + SSE."""
    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp.atendimento_crm import registrar_evento
    from crm_app.services.whatsapp.atendimento_service import pausar_bot
    from crm_app.services.whatsapp.inbox_events import publish_inbox_event

    if conversa is None:
        return False
    # Já com humano e pausado: só reforça unread/evento leve
    ja_humano = bool(conversa.bot_pausado) and (
        conversa.status == WhatsAppConversation.STATUS_EM_ATENDIMENTO
        or conversa.assignee_id
    )

    pausar_bot(
        conversa.telefone,
        usuario,
        motivo or "Handoff automático: cliente pediu atendente",
    )
    conversa.bot_pausado = True
    if conversa.status != WhatsAppConversation.STATUS_ENCERRADA:
        # Sem assignee = fila "Não atribuídas"
        conversa.status = WhatsAppConversation.STATUS_ABERTA
    conversa.unread_count = int(conversa.unread_count or 0) + (0 if ja_humano else 1)
    conversa.save(
        update_fields=["bot_pausado", "status", "unread_count", "atualizado_em"]
    )

    resumo = motivo or "Cliente pediu atendimento humano"
    if texto_cliente:
        resumo = f"{resumo}: “{(texto_cliente or '')[:120]}”"
    registrar_evento(
        conversa,
        "HANDOFF",
        autor=usuario,
        texto=resumo[:500],
        payload={"texto_cliente": (texto_cliente or "")[:300], "motivo": motivo},
    )
    try:
        publish_inbox_event(
            {
                "type": "handoff",
                "telefone": conversa.telefone,
                "conversation_id": conversa.id,
                "preview": resumo[:200],
                "motivo": motivo or "pedido_humano",
            }
        )
    except Exception:
        pass
    return True


def processar_entrada_para_automacao(msg) -> None:
    """Chamado após gravar mensagem de entrada no inbox."""
    from crm_app.models import MensagemWhatsAppAtendimento, WhatsAppConversation

    if msg is None:
        return
    if getattr(msg, "direcao", None) != MensagemWhatsAppAtendimento.DIRECAO_ENTRADA:
        return
    texto = (msg.texto or "").strip()
    conv = getattr(msg, "conversa", None)
    if conv is None and getattr(msg, "conversa_id", None):
        conv = WhatsAppConversation.objects.filter(pk=msg.conversa_id).first()
    if conv is None:
        from crm_app.services.whatsapp.atendimento_service import get_or_create_conversation

        conv = get_or_create_conversation(msg.telefone, venda=msg.venda)
    if conv is None:
        return

    # Mantém status BOT enquanto bot ativo e sem handoff
    if (
        not conv.bot_pausado
        and not conv.assignee_id
        and conv.status
        not in (
            WhatsAppConversation.STATUS_ENCERRADA,
            WhatsAppConversation.STATUS_EM_ATENDIMENTO,
        )
    ):
        if conv.status != WhatsAppConversation.STATUS_BOT:
            conv.status = WhatsAppConversation.STATUS_BOT
            conv.save(update_fields=["status", "atualizado_em"])

    if detectar_pedido_humano(texto):
        try:
            handoff_para_humano(
                conv,
                motivo="Pedido explícito de atendente",
                texto_cliente=texto,
            )
        except Exception:
            logger.exception("[WA automacao] handoff falhou tel=%s", msg.telefone)


def executar_triggers_etapa(
    conversa,
    etapa: str,
    *,
    usuario=None,
    etapa_anterior: str = "",
) -> list[dict]:
    """Executa triggers ativos da etapa (após mudança no CRM)."""
    from crm_app.models import (
        ConversacaoTarefa,
        WhatsAppEtapaTrigger,
        WhatsAppTag,
        WhatsAppTelefoneSemIa,
    )
    from crm_app.services.whatsapp.atendimento_crm import registrar_evento
    from crm_app.services.whatsapp.atendimento_service import (
        pausar_bot,
        telefones_equivalentes,
    )

    etapa_n = (etapa or "").strip().upper()
    if not conversa or not etapa_n:
        return []
    resultados = []
    qs = WhatsAppEtapaTrigger.objects.filter(etapa=etapa_n, ativo=True).order_by(
        "prioridade", "id"
    )
    for trig in qs:
        try:
            if trig.acao == WhatsAppEtapaTrigger.ACAO_PAUSAR_BOT:
                pausar_bot(conversa.telefone, usuario, f"Trigger etapa {etapa_n}")
                conversa.bot_pausado = True
                conversa.save(update_fields=["bot_pausado", "atualizado_em"])
                resultados.append({"acao": trig.acao, "ok": True})
            elif trig.acao == WhatsAppEtapaTrigger.ACAO_DEVOLVER_BOT:
                conversa.bot_pausado = False
                conversa.assignee = None
                from crm_app.models import WhatsAppConversation

                conversa.status = WhatsAppConversation.STATUS_BOT
                conversa.save(
                    update_fields=["bot_pausado", "assignee", "status", "atualizado_em"]
                )
                WhatsAppTelefoneSemIa.objects.filter(
                    telefone__in=telefones_equivalentes(conversa.telefone)
                ).delete()
                resultados.append({"acao": trig.acao, "ok": True})
            elif trig.acao == WhatsAppEtapaTrigger.ACAO_TAG:
                nome = (trig.tag_nome or "").strip()[:40]
                if nome:
                    tag, _ = WhatsAppTag.objects.get_or_create(
                        nome=nome, defaults={"cor": trig.tag_cor or "#6c757d"}
                    )
                    conversa.tags.add(tag)
                    resultados.append({"acao": trig.acao, "ok": True, "tag": nome})
            elif trig.acao == WhatsAppEtapaTrigger.ACAO_TAREFA:
                titulo = (trig.tarefa_titulo or f"Follow-up etapa {etapa_n}")[:200]
                ConversacaoTarefa.objects.create(
                    conversa=conversa,
                    titulo=titulo,
                    dono=usuario if getattr(usuario, "pk", None) else None,
                    criado_por=usuario if getattr(usuario, "pk", None) else None,
                )
                resultados.append({"acao": trig.acao, "ok": True, "titulo": titulo})
            elif trig.acao == WhatsAppEtapaTrigger.ACAO_TEMPLATE:
                nome_tmpl = (trig.template_name or "").strip()
                if nome_tmpl:
                    from crm_app.whatsapp_service import WhatsAppService

                    params = trig.template_params if isinstance(trig.template_params, list) else []
                    ok, resp = WhatsAppService.para_cliente().enviar_template(
                        conversa.telefone,
                        nome_tmpl,
                        body_params=params,
                    )
                    resultados.append(
                        {"acao": trig.acao, "ok": bool(ok), "template": nome_tmpl}
                    )
            registrar_evento(
                conversa,
                "TRIGGER",
                autor=usuario,
                texto=f"Trigger {trig.acao} na etapa {etapa_n}",
                payload={
                    "trigger_id": trig.id,
                    "acao": trig.acao,
                    "de": etapa_anterior,
                    "para": etapa_n,
                },
            )
        except Exception as exc:
            logger.exception("[WA automacao] trigger %s falhou", trig.id)
            resultados.append({"acao": trig.acao, "ok": False, "erro": str(exc)[:200]})
    return resultados


def seed_triggers_padrao() -> int:
    """Cria triggers iniciais se a tabela estiver vazia."""
    from crm_app.models import WhatsAppEtapaTrigger

    if WhatsAppEtapaTrigger.objects.exists():
        return 0
    defaults = [
        ("CHURN", WhatsAppEtapaTrigger.ACAO_TAG, {"tag_nome": "Follow-up", "tag_cor": "#0d6efd", "prioridade": 10}),
        ("CHURN", WhatsAppEtapaTrigger.ACAO_TAREFA, {"tarefa_titulo": "Follow-up churn WhatsApp", "prioridade": 20}),
        ("CHURN", WhatsAppEtapaTrigger.ACAO_PAUSAR_BOT, {"prioridade": 30}),
        ("BIO", WhatsAppEtapaTrigger.ACAO_TAG, {"tag_nome": "Aguardando docs", "tag_cor": "#fd7e14", "prioridade": 10}),
        ("BIO", WhatsAppEtapaTrigger.ACAO_TAREFA, {"tarefa_titulo": "Cobrar selfie/docs bio", "prioridade": 20}),
        ("INTERESSE", WhatsAppEtapaTrigger.ACAO_TAG, {"tag_nome": "Quente", "tag_cor": "#dc3545", "prioridade": 10}),
        ("SUPORTE", WhatsAppEtapaTrigger.ACAO_PAUSAR_BOT, {"prioridade": 10}),
        ("SUPORTE", WhatsAppEtapaTrigger.ACAO_TAREFA, {"tarefa_titulo": "Atender suporte WhatsApp", "prioridade": 20}),
        ("VENDA", WhatsAppEtapaTrigger.ACAO_TAG, {"tag_nome": "Fechado", "tag_cor": "#198754", "prioridade": 10}),
    ]
    criados = 0
    for etapa, acao, extra in defaults:
        WhatsAppEtapaTrigger.objects.create(etapa=etapa, acao=acao, **extra)
        criados += 1
    return criados


def seed_triggers_api() -> tuple[str, dict]:
    """Endpoint: cria defaults só se a tabela estiver vazia."""
    criados = seed_triggers_padrao()
    return "ok", {
        "ok": True,
        "criados": criados,
        "items": listar_triggers(),
        "detail": (
            f"{criados} triggers padrão criados."
            if criados
            else "Já existem triggers; seed não alterou nada."
        ),
    }




def _serializar_trigger(t) -> dict:
    return {
        "id": t.id,
        "etapa": t.etapa,
        "acao": t.acao,
        "ativo": t.ativo,
        "prioridade": t.prioridade,
        "tag_nome": t.tag_nome,
        "tag_cor": t.tag_cor,
        "tarefa_titulo": t.tarefa_titulo,
        "template_name": t.template_name,
        "template_params": t.template_params or [],
    }


def criar_trigger(data: dict) -> tuple[str, dict]:
    from crm_app.models import WhatsAppEtapaTrigger
    from crm_app.services.whatsapp.atendimento_crm import ETAPAS_VALIDAS

    data = data if isinstance(data, dict) else {}
    etapa = (data.get("etapa") or "").strip().upper()
    acao = (data.get("acao") or "").strip().upper()
    if not etapa or etapa not in ETAPAS_VALIDAS:
        return "invalido", {"detail": "Etapa inválida."}
    acoes = {c[0] for c in WhatsAppEtapaTrigger.ACAO_CHOICES}
    if acao not in acoes:
        return "invalido", {"detail": "Ação inválida."}
    try:
        prioridade = int(data.get("prioridade") or 100)
    except (TypeError, ValueError):
        prioridade = 100
    obj = WhatsAppEtapaTrigger.objects.create(
        etapa=etapa,
        acao=acao,
        ativo=bool(data.get("ativo", True)),
        prioridade=max(0, min(prioridade, 9999)),
        tag_nome=(data.get("tag_nome") or "")[:40],
        tag_cor=(data.get("tag_cor") or "#6c757d")[:16],
        tarefa_titulo=(data.get("tarefa_titulo") or "")[:200],
        template_name=(data.get("template_name") or "")[:120],
        template_params=data.get("template_params")
        if isinstance(data.get("template_params"), list)
        else [],
    )
    return "ok", {"ok": True, "trigger": _serializar_trigger(obj)}


def atualizar_trigger(trigger_id, data: dict) -> tuple[str, dict]:
    from crm_app.models import WhatsAppEtapaTrigger
    from crm_app.services.whatsapp.atendimento_crm import ETAPAS_VALIDAS

    obj = WhatsAppEtapaTrigger.objects.filter(pk=trigger_id).first()
    if obj is None:
        return "nao_encontrado", {"detail": "Trigger não encontrado."}
    data = data if isinstance(data, dict) else {}
    dirty = []
    if "etapa" in data:
        etapa = (data.get("etapa") or "").strip().upper()
        if not etapa or etapa not in ETAPAS_VALIDAS:
            return "invalido", {"detail": "Etapa inválida."}
        obj.etapa = etapa
        dirty.append("etapa")
    if "acao" in data:
        acao = (data.get("acao") or "").strip().upper()
        acoes = {c[0] for c in WhatsAppEtapaTrigger.ACAO_CHOICES}
        if acao not in acoes:
            return "invalido", {"detail": "Ação inválida."}
        obj.acao = acao
        dirty.append("acao")
    if "ativo" in data:
        obj.ativo = bool(data.get("ativo"))
        dirty.append("ativo")
    if "prioridade" in data:
        try:
            obj.prioridade = max(0, min(int(data.get("prioridade")), 9999))
            dirty.append("prioridade")
        except (TypeError, ValueError):
            return "invalido", {"detail": "Prioridade inválida."}
    for campo, lim in (
        ("tag_nome", 40),
        ("tag_cor", 16),
        ("tarefa_titulo", 200),
        ("template_name", 120),
    ):
        if campo in data:
            setattr(obj, campo, (data.get(campo) or "")[:lim])
            dirty.append(campo)
    if "template_params" in data and isinstance(data.get("template_params"), list):
        obj.template_params = data.get("template_params")
        dirty.append("template_params")
    if dirty:
        dirty.append("atualizado_em")
        obj.save(update_fields=dirty)
    return "ok", {"ok": True, "trigger": _serializar_trigger(obj)}


def excluir_trigger(trigger_id) -> tuple[str, dict]:
    from crm_app.models import WhatsAppEtapaTrigger

    obj = WhatsAppEtapaTrigger.objects.filter(pk=trigger_id).first()
    if obj is None:
        return "nao_encontrado", {"detail": "Trigger não encontrado."}
    obj.delete()
    return "ok", {"ok": True}

def listar_triggers() -> list[dict]:
    from crm_app.models import WhatsAppEtapaTrigger

    return [
        _serializar_trigger(t)
        for t in WhatsAppEtapaTrigger.objects.order_by("etapa", "prioridade")[:200]
    ]
