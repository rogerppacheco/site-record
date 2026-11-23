"""Kanban, SLA/métricas e CSAT do inbox WhatsApp (Fase 5)."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

SLA_ALVO_MINUTOS = 15

PERIODOS = {
    "hoje": 1,
    "7d": 7,
    "30d": 30,
}


def _inicio_periodo(periodo: str):
    dias = PERIODOS.get((periodo or "7d").strip().lower(), 7)
    agora = timezone.now()
    if dias == 1:
        return agora.replace(hour=0, minute=0, second=0, microsecond=0)
    return agora - timedelta(days=dias)


def marcar_primeira_resposta_humana(conversa, *, quando=None, enviado_por=None) -> bool:
    """Preenche primeira_resposta_humana_em se ainda vazio. Retorna True se gravou."""
    if conversa is None or getattr(conversa, "primeira_resposta_humana_em", None):
        return False
    if not getattr(enviado_por, "pk", None):
        return False
    agora = quando or timezone.now()
    type(conversa).objects.filter(
        pk=conversa.pk, primeira_resposta_humana_em__isnull=True
    ).update(primeira_resposta_humana_em=agora, atualizado_em=agora)
    conversa.primeira_resposta_humana_em = agora
    return True


def _card_kanban(conv) -> dict:
    """Serialização leve para o board (sem tags/M2M)."""
    from crm_app.services.whatsapp.atendimento_service import exibir_telefone

    venda = conv.venda if conv.venda_id else None
    nome = conv.contact_name or ""
    if not nome and venda is not None and getattr(venda, "cliente", None):
        nome = getattr(venda.cliente, "nome_razao_social", "") or ""
    preview = (conv.last_message_preview or "").strip()
    if len(preview) > 90:
        preview = preview[:90] + "…"
    if conv.status == type(conv).STATUS_ENCERRADA:
        modo = "ENCERRADA"
    elif conv.bot_pausado:
        modo = "HUMANO"
    else:
        modo = "BOT"
    return {
        "id": conv.id,
        "conversation_id": conv.id,
        "telefone": conv.telefone,
        "telefone_exibicao": exibir_telefone(conv.telefone),
        "cliente": nome or exibir_telefone(conv.telefone),
        "venda_id": conv.venda_id,
        "ultima_mensagem": preview,
        "ultima_em": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "unread_count": int(conv.unread_count or 0),
        "status": conv.status,
        "assignee": conv.assignee.username if conv.assignee_id else None,
        "assignee_id": conv.assignee_id,
        "etapa_funil": conv.etapa_funil or "",
        "modo": modo,
    }


def listar_kanban(usuario) -> dict:
    """Cards abertos agrupados por etapa_funil."""
    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp.atendimento_service import _qs_conversas_visiveis

    qs = list(
        _qs_conversas_visiveis(usuario)
        .exclude(status=WhatsAppConversation.STATUS_ENCERRADA)
        .select_related("assignee", "venda__cliente", "channel")
        .order_by("-last_message_at", "-id")[:150]
    )
    colunas = []
    buckets: dict[str, list] = {v: [] for v, _ in WhatsAppConversation.ETAPA_CHOICES}
    for conv in qs:
        chave = conv.etapa_funil or ""
        if chave not in buckets:
            buckets[chave] = []
        buckets[chave].append(_card_kanban(conv))

    for value, label in WhatsAppConversation.ETAPA_CHOICES:
        items = buckets.get(value) or []
        colunas.append(
            {
                "etapa": value,
                "label": label or "Sem etapa",
                "count": len(items),
                "items": items,
            }
        )
    return {"colunas": colunas, "total": sum(c["count"] for c in colunas)}


def metricas_inbox(usuario, *, periodo: str = "7d") -> dict:
    """Agregados de volume, TMR, SLA e CSAT no período."""
    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp.atendimento_service import _qs_conversas_visiveis

    inicio = _inicio_periodo(periodo)
    agora = timezone.now()
    base = _qs_conversas_visiveis(usuario)

    # Atividade no período: criadas, atualizadas ou encerradas
    qs_periodo = base.filter(
        Q(criado_em__gte=inicio)
        | Q(atualizado_em__gte=inicio)
        | Q(encerrada_em__gte=inicio)
        | Q(primeira_resposta_humana_em__gte=inicio)
    )

    abertas = base.exclude(status=WhatsAppConversation.STATUS_ENCERRADA).count()
    encerradas = base.filter(
        status=WhatsAppConversation.STATUS_ENCERRADA, encerrada_em__gte=inicio
    ).count()
    bot = base.filter(
        bot_pausado=False,
    ).exclude(status=WhatsAppConversation.STATUS_ENCERRADA).count()
    humanas = base.filter(
        bot_pausado=True,
    ).exclude(status=WhatsAppConversation.STATUS_ENCERRADA).count()

    com_resposta = list(
        qs_periodo.filter(primeira_resposta_humana_em__isnull=False).values_list(
            "criado_em", "primeira_resposta_humana_em"
        )
    )
    deltas = []
    dentro_sla = 0
    for criado, resp in com_resposta:
        if not criado or not resp:
            continue
        seg = (resp - criado).total_seconds()
        if seg < 0:
            continue
        deltas.append(seg)
        if seg <= SLA_ALVO_MINUTOS * 60:
            dentro_sla += 1

    tmr_seg = (sum(deltas) / len(deltas)) if deltas else None
    sla_pct = round(100.0 * dentro_sla / len(deltas), 1) if deltas else None

    csat_qs = base.filter(csat_em__gte=inicio, csat_nota__isnull=False)
    csat_agg = csat_qs.aggregate(media=Avg("csat_nota"), n=Count("id"))
    encerradas_periodo = max(encerradas, 1)
    csat_taxa = round(100.0 * (csat_agg["n"] or 0) / encerradas_periodo, 1) if encerradas else (
        round(100.0 * (csat_agg["n"] or 0) / max(csat_agg["n"] or 1, 1), 1) if csat_agg["n"] else 0.0
    )

    por_agente = []
    agentes = (
        base.filter(assignee__isnull=False)
        .exclude(status=WhatsAppConversation.STATUS_ENCERRADA)
        .values("assignee_id", "assignee__username")
        .annotate(abertas=Count("id"))
        .order_by("-abertas")[:15]
    )
    for row in agentes:
        uid = row["assignee_id"]
        enc = base.filter(
            assignee_id=uid,
            status=WhatsAppConversation.STATUS_ENCERRADA,
            encerrada_em__gte=inicio,
        ).count()
        csat_a = base.filter(
            assignee_id=uid, csat_em__gte=inicio, csat_nota__isnull=False
        ).aggregate(media=Avg("csat_nota"), n=Count("id"))
        resp_a = list(
            base.filter(
                assignee_id=uid, primeira_resposta_humana_em__gte=inicio
            ).values_list("criado_em", "primeira_resposta_humana_em")
        )
        segs = []
        for c, r in resp_a:
            if c and r and r >= c:
                segs.append((r - c).total_seconds())
        por_agente.append(
            {
                "assignee_id": uid,
                "username": row["assignee__username"],
                "abertas": row["abertas"],
                "encerradas_periodo": enc,
                "tmr_segundos": round(sum(segs) / len(segs), 1) if segs else None,
                "csat_medio": round(csat_a["media"], 2) if csat_a["media"] is not None else None,
                "csat_n": csat_a["n"] or 0,
            }
        )

    return {
        "periodo": periodo if periodo in PERIODOS else "7d",
        "desde": inicio.isoformat(),
        "ate": agora.isoformat(),
        "sla_alvo_minutos": SLA_ALVO_MINUTOS,
        "volume": {
            "abertas": abertas,
            "encerradas_periodo": encerradas,
            "bot": bot,
            "humanas": humanas,
            "com_1a_resposta_periodo": len(deltas),
        },
        "tmr_segundos": round(tmr_seg, 1) if tmr_seg is not None else None,
        "tmr_minutos": round(tmr_seg / 60.0, 1) if tmr_seg is not None else None,
        "sla_pct": sla_pct,
        "csat_medio": round(csat_agg["media"], 2) if csat_agg["media"] is not None else None,
        "csat_n": csat_agg["n"] or 0,
        "csat_taxa_pct": csat_taxa if (csat_agg["n"] or encerradas) else None,
        "por_agente": por_agente,
    }


def registrar_csat(usuario, telefone: str, nota) -> tuple[str, dict]:
    """Grava CSAT 1–5 e evento na timeline."""
    from crm_app.services.whatsapp.atendimento_crm import (
        _conv_por_telefone,
        registrar_evento,
    )
    from crm_app.services.whatsapp.atendimento_service import detalhe_conversa

    try:
        n = int(nota)
    except (TypeError, ValueError):
        return "invalido", {"detail": "Informe uma nota CSAT de 1 a 5."}
    if n < 1 or n > 5:
        return "invalido", {"detail": "Informe uma nota CSAT de 1 a 5."}

    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}

    agora = timezone.now()
    conv.csat_nota = n
    conv.csat_em = agora
    conv.save(update_fields=["csat_nota", "csat_em", "atualizado_em"])
    registrar_evento(
        conv,
        "CSAT",
        autor=usuario,
        texto=f"CSAT registrado: {n}/5",
        payload={"nota": n},
    )
    return "ok", {
        "ok": True,
        "csat_nota": n,
        "csat_em": agora.isoformat(),
        "conversa": detalhe_conversa(usuario, conv.telefone),
    }
