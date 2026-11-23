"""CRM conversacional no inbox WhatsApp (estilo Kommo) — Fase 0+1.

Filas, transferência, etapa funil, tags, notas, tarefas e timeline.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from crm_app.services.whatsapp.atendimento_service import (
    bot_pausado,
    canonicalizar_telefone,
    detalhe_conversa,
    get_or_create_conversation,
    pausar_bot,
    telefones_equivalentes,
)

FILAS = ("todas", "minhas", "nao_atribuidas", "bot", "encerradas")
ETAPAS_VALIDAS = {
    "",
    "INTERESSE",
    "PRE_VENDA",
    "VENDA",
    "CHURN",
    "BIO",
    "MAILING",
    "SUPORTE",
}
GRUPOS_ATENDIMENTO = ("Diretoria", "Admin", "BackOffice", "Auditoria", "Qualidade")


def registrar_evento(
    conversa,
    tipo: str,
    *,
    autor=None,
    texto: str = "",
    payload: Optional[dict] = None,
) -> None:
    from crm_app.models import ConversacaoEvento

    if conversa is None:
        return
    ConversacaoEvento.objects.create(
        conversa=conversa,
        tipo=tipo,
        autor=autor if getattr(autor, "pk", None) else None,
        texto=(texto or "")[:500],
        payload=payload or {},
    )


def _conv_por_telefone(telefone: str, *, role: str = "cliente"):
    from crm_app.models import WhatsAppConversation

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 8:
        return None
    conv = (
        WhatsAppConversation.objects.filter(
            telefone__in=telefones_equivalentes(tel),
            channel__role=role,
        )
        .select_related("assignee", "venda", "funil_tratamento", "channel")
        .order_by("-last_message_at", "-id")
        .first()
    )
    if conv is None:
        conv = get_or_create_conversation(tel)
    return conv


def _user_by_id(user_id) -> Any:
    User = get_user_model()
    try:
        return User.objects.filter(pk=int(user_id), is_active=True).first()
    except (TypeError, ValueError):
        return None


def listar_agentes_atendimento() -> list[dict]:
    User = get_user_model()
    qs = (
        User.objects.filter(is_active=True, groups__name__in=GRUPOS_ATENDIMENTO)
        .distinct()
        .order_by("username")
    )
    return [
        {
            "id": u.id,
            "username": u.username,
            "nome": (getattr(u, "get_full_name", lambda: "")() or u.username),
        }
        for u in qs[:200]
    ]


def aplicar_filtro_fila(qs, usuario, fila: str):
    """Aplica filtro de fila ao queryset de WhatsAppConversation."""
    from crm_app.models import WhatsAppConversation

    f = (fila or "todas").strip().lower()
    if f not in FILAS:
        f = "todas"
    if f == "minhas" and getattr(usuario, "pk", None):
        return qs.filter(assignee_id=usuario.pk).exclude(
            status=WhatsAppConversation.STATUS_ENCERRADA
        )
    if f == "nao_atribuidas":
        # Sem responsável e já tocadas por humano / abertas (não só bot).
        return qs.filter(assignee__isnull=True, bot_pausado=True).exclude(
            status=WhatsAppConversation.STATUS_ENCERRADA
        )
    if f == "bot":
        # Ainda com o bot (não pausado) ou marcado explicitamente como BOT.
        return qs.filter(
            Q(status=WhatsAppConversation.STATUS_BOT)
            | Q(bot_pausado=False, assignee__isnull=True)
        ).exclude(status=WhatsAppConversation.STATUS_ENCERRADA)
    if f == "encerradas":
        return qs.filter(status=WhatsAppConversation.STATUS_ENCERRADA)
    # todas: exclui encerradas por padrão
    return qs.exclude(status=WhatsAppConversation.STATUS_ENCERRADA)


def contagem_filas(usuario) -> dict:
    """Uma agregação em vez de 7 COUNTs (cada um com RTT no DB remoto)."""
    from django.db.models import Count, Q

    from crm_app.models import WhatsAppConversation
    from crm_app.services.whatsapp.atendimento_service import _qs_conversas_visiveis

    # select_related só atrasa COUNT — remove JOINs.
    base = _qs_conversas_visiveis(usuario).select_related(None)
    uid = getattr(usuario, "pk", None)
    enc = WhatsAppConversation.STATUS_ENCERRADA
    bot_st = WhatsAppConversation.STATUS_BOT
    filtro_minhas = (
        Q(assignee_id=uid) & ~Q(status=enc) if uid else Q(pk__in=[])
    )
    agora = timezone.now()
    agg = base.aggregate(
        todas=Count("id", filter=~Q(status=enc)),
        minhas=Count("id", filter=filtro_minhas),
        nao_atribuidas=Count(
            "id",
            filter=Q(assignee__isnull=True, bot_pausado=True) & ~Q(status=enc),
        ),
        bot=Count(
            "id",
            filter=(
                Q(status=bot_st) | Q(bot_pausado=False, assignee__isnull=True)
            )
            & ~Q(status=enc),
        ),
        encerradas=Count("id", filter=Q(status=enc)),
        canal_cliente=Count(
            "id",
            filter=Q(reply_canal=WhatsAppConversation.REPLY_CANAL_CLIENTE)
            & ~Q(status=enc),
        ),
        canal_funil=Count(
            "id",
            filter=Q(reply_canal=WhatsAppConversation.REPLY_CANAL_FUNIL)
            & ~Q(status=enc),
        ),
        janela_aberta=Count(
            "id",
            filter=Q(janela_aberta_ate__gt=agora) & ~Q(status=enc),
        ),
    )
    return {
        "todas": int(agg.get("todas") or 0),
        "minhas": int(agg.get("minhas") or 0),
        "nao_atribuidas": int(agg.get("nao_atribuidas") or 0),
        "bot": int(agg.get("bot") or 0),
        "encerradas": int(agg.get("encerradas") or 0),
        "canal_cliente": int(agg.get("canal_cliente") or 0),
        "canal_funil": int(agg.get("canal_funil") or 0),
        "janela_aberta": int(agg.get("janela_aberta") or 0),
    }


def serializar_tag(tag) -> dict:
    return {
        "id": tag.id,
        "nome": tag.nome,
        "cor": tag.cor or "#6c757d",
    }


def serializar_nota(nota) -> dict:
    return {
        "id": nota.id,
        "texto": nota.texto or "",
        "autor": nota.autor.username if nota.autor_id else None,
        "criado_em": nota.criado_em.isoformat() if nota.criado_em else None,
    }


def serializar_tarefa(tarefa) -> dict:
    return {
        "id": tarefa.id,
        "titulo": tarefa.titulo,
        "status": tarefa.status,
        "dono": tarefa.dono.username if tarefa.dono_id else None,
        "dono_id": tarefa.dono_id,
        "prazo": tarefa.prazo.isoformat() if tarefa.prazo else None,
        "criado_em": tarefa.criado_em.isoformat() if tarefa.criado_em else None,
        "concluida_em": tarefa.concluida_em.isoformat() if tarefa.concluida_em else None,
    }


def serializar_evento(ev) -> dict:
    return {
        "id": ev.id,
        "tipo": ev.tipo,
        "texto": ev.texto or "",
        "autor": ev.autor.username if ev.autor_id else None,
        "payload": ev.payload or {},
        "criado_em": ev.criado_em.isoformat() if ev.criado_em else None,
    }


def enriquecer_detalhe_crm(base: dict, conversa) -> dict:
    """Anexa bloco CRM (etapa, tags, notas, tarefas, eventos) ao detalhe."""
    if base is None or conversa is None:
        return base
    from crm_app.models import WhatsAppConversation

    tags = list(conversa.tags.filter(ativo=True).order_by("nome")[:12])
    notas = list(conversa.notas.select_related("autor").order_by("-criado_em")[:6])
    tarefas = list(
        conversa.tarefas.select_related("dono", "criado_por").order_by("status", "prazo")[:10]
    )
    eventos = list(
        conversa.eventos.select_related("autor").order_by("-criado_em")[:8]
    )
    ft = conversa.funil_tratamento
    base["conversation_id"] = conversa.id
    base["status"] = conversa.status
    base["assignee"] = conversa.assignee.username if conversa.assignee_id else None
    base["assignee_id"] = conversa.assignee_id
    base["etapa_funil"] = conversa.etapa_funil or ""
    base["etapa_funil_label"] = (
        dict(WhatsAppConversation.ETAPA_CHOICES).get(conversa.etapa_funil or "", "")
        or "—"
    )
    base["reply_canal"] = (
        getattr(conversa, "reply_canal", None)
        or WhatsAppConversation.REPLY_CANAL_CLIENTE
    )
    base["reply_canal_label"] = (
        "Funil"
        if base["reply_canal"] == WhatsAppConversation.REPLY_CANAL_FUNIL
        else "Inbox"
    )
    try:
        from crm_app.services.whatsapp.atendimento_automacao import modo_atendimento

        base["modo"] = modo_atendimento(conversa)
    except Exception:
        base["modo"] = "BOT"
    base["etapas_opcoes"] = [
        {"value": v, "label": lbl} for v, lbl in WhatsAppConversation.ETAPA_CHOICES
    ]
    base["tags"] = [serializar_tag(t) for t in tags]
    base["notas"] = [serializar_nota(n) for n in notas]
    base["tarefas"] = [serializar_tarefa(t) for t in tarefas]
    base["eventos"] = [serializar_evento(e) for e in eventos]
    base["funil"] = None
    if ft is not None:
        base["funil"] = {
            "id": ft.id,
            "aba": ft.aba,
            "ref_id": ft.ref_id,
            "status": ft.status,
            "observacao": ft.observacao or "",
            "telefone": ft.telefone or "",
        }
    base["encerrada_em"] = (
        conversa.encerrada_em.isoformat() if conversa.encerrada_em else None
    )
    base["primeira_resposta_humana_em"] = (
        conversa.primeira_resposta_humana_em.isoformat()
        if getattr(conversa, "primeira_resposta_humana_em", None)
        else None
    )
    base["csat_nota"] = getattr(conversa, "csat_nota", None)
    base["csat_em"] = (
        conversa.csat_em.isoformat() if getattr(conversa, "csat_em", None) else None
    )
    return base


def _disparar_triggers_etapa(conversa, etapa: str, etapa_anterior: str = "", usuario=None) -> None:
    """Executa Salesbot/triggers após mudança de etapa (CRM ou vínculo Funil)."""
    if conversa is None:
        return
    try:
        from crm_app.services.whatsapp.atendimento_automacao import (
            executar_triggers_etapa,
        )

        executar_triggers_etapa(
            conversa,
            etapa,
            usuario=usuario,
            etapa_anterior=etapa_anterior or "",
        )
        conversa.refresh_from_db()
    except Exception:
        pass


def vincular_funil_tratamento(
    conversa,
    *,
    aba: str = "",
    ref_id: str = "",
    usuario=None,
    telefone: str = "",
    nome: str = "",
) -> None:
    """Cria/atualiza FunilTratamento e liga na Conversation + etapa."""
    from crm_app.models import FunilTratamento, WhatsAppConversation

    if conversa is None:
        return
    aba_n = (aba or "").strip().upper()
    ref = str(ref_id or "").strip()
    if not aba_n or not ref:
        if aba_n and aba_n in ETAPAS_VALIDAS:
            if conversa.etapa_funil != aba_n:
                antiga = conversa.etapa_funil
                conversa.etapa_funil = aba_n
                conversa.save(update_fields=["etapa_funil", "atualizado_em"])
                _disparar_triggers_etapa(
                    conversa, aba_n, etapa_anterior=antiga or "", usuario=usuario
                )
        return

    abas_ok = {c[0] for c in FunilTratamento.ABA_CHOICES}
    if aba_n not in abas_ok:
        if aba_n in ETAPAS_VALIDAS:
            if conversa.etapa_funil != aba_n:
                antiga = conversa.etapa_funil
                conversa.etapa_funil = aba_n
                conversa.save(update_fields=["etapa_funil", "atualizado_em"])
                _disparar_triggers_etapa(
                    conversa, aba_n, etapa_anterior=antiga or "", usuario=usuario
                )
        return

    tel = canonicalizar_telefone(telefone or conversa.telefone)
    obj = FunilTratamento.objects.filter(aba=aba_n, ref_id=ref[:64]).first()
    if obj is None:
        obj = FunilTratamento.objects.create(
            aba=aba_n,
            ref_id=ref[:64],
            telefone=tel[:20],
            nome=(nome or conversa.contact_name or "")[:200],
            status=FunilTratamento.STATUS_ABERTO,
        )
    else:
        dirty_ft = []
        if tel and obj.telefone != tel[:20]:
            obj.telefone = tel[:20]
            dirty_ft.append("telefone")
        if nome and not obj.nome:
            obj.nome = (nome or "")[:200]
            dirty_ft.append("nome")
        if dirty_ft:
            obj.save(update_fields=dirty_ft + ["atualizado_em"])
    dirty = []
    etapa_mudou = False
    etapa_anterior = conversa.etapa_funil or ""
    if conversa.funil_tratamento_id != obj.id:
        conversa.funil_tratamento = obj
        dirty.append("funil_tratamento")
    if conversa.etapa_funil != aba_n:
        conversa.etapa_funil = aba_n
        dirty.append("etapa_funil")
        etapa_mudou = True
    if dirty:
        conversa.save(update_fields=dirty + ["atualizado_em"])
        registrar_evento(
            conversa,
            "FUNIL",
            autor=usuario,
            texto=f"Vinculado ao Funil {aba_n} #{ref}",
            payload={"aba": aba_n, "ref_id": ref, "tratamento_id": obj.id},
        )
        if etapa_mudou:
            _disparar_triggers_etapa(
                conversa, aba_n, etapa_anterior=etapa_anterior, usuario=usuario
            )


def transferir_conversa(usuario, telefone: str, assignee_id) -> tuple[str, dict]:
    from crm_app.models import WhatsAppConversation

    dest = _user_by_id(assignee_id)
    if dest is None:
        return "invalido", {"detail": "Informe um atendente válido."}
    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    anterior = conv.assignee.username if conv.assignee_id else None
    pausar_bot(conv.telefone, usuario, "Transferência de conversa")
    conv.assignee = dest
    conv.bot_pausado = True
    if conv.status == WhatsAppConversation.STATUS_ENCERRADA:
        conv.status = WhatsAppConversation.STATUS_EM_ATENDIMENTO
        conv.encerrada_em = None
    else:
        conv.status = WhatsAppConversation.STATUS_EM_ATENDIMENTO
    conv.save(
        update_fields=["assignee", "bot_pausado", "status", "encerrada_em", "atualizado_em"]
    )
    registrar_evento(
        conv,
        "TRANSFERIU",
        autor=usuario,
        texto=f"Transferiu para {dest.username}"
        + (f" (antes: {anterior})" if anterior else ""),
        payload={"de": anterior, "para": dest.username, "para_id": dest.id},
    )
    return "ok", {"ok": True, "conversa": detalhe_conversa(usuario, conv.telefone)}


def liberar_conversa(usuario, telefone: str, *, devolver_bot: bool = True) -> tuple[str, dict]:
    from crm_app.models import WhatsAppConversation, WhatsAppTelefoneSemIa

    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    anterior = conv.assignee.username if conv.assignee_id else None
    conv.assignee = None
    if devolver_bot:
        conv.bot_pausado = False
        conv.status = WhatsAppConversation.STATUS_BOT
        # Remove pausa persistente do bot se existir
        WhatsAppTelefoneSemIa.objects.filter(
            telefone__in=telefones_equivalentes(conv.telefone)
        ).delete()
    else:
        conv.status = WhatsAppConversation.STATUS_ABERTA
    conv.save(update_fields=["assignee", "bot_pausado", "status", "atualizado_em"])
    registrar_evento(
        conv,
        "LIBEROU",
        autor=usuario,
        texto="Liberou conversa"
        + (" e devolveu ao bot" if devolver_bot else "")
        + (f" (antes: {anterior})" if anterior else ""),
        payload={"devolver_bot": devolver_bot, "de": anterior},
    )
    return "ok", {"ok": True, "conversa": detalhe_conversa(usuario, conv.telefone)}


def encerrar_conversa(usuario, telefone: str, *, csat_nota=None) -> tuple[str, dict]:
    from crm_app.models import WhatsAppConversation

    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    agora = timezone.now()
    conv.status = WhatsAppConversation.STATUS_ENCERRADA
    conv.encerrada_em = agora
    conv.unread_count = 0
    dirty = ["status", "encerrada_em", "unread_count", "atualizado_em"]
    nota_ok = None
    if csat_nota is not None and str(csat_nota).strip() != "":
        try:
            n = int(csat_nota)
        except (TypeError, ValueError):
            return "invalido", {"detail": "Informe uma nota CSAT de 1 a 5."}
        if n < 1 or n > 5:
            return "invalido", {"detail": "Informe uma nota CSAT de 1 a 5."}
        conv.csat_nota = n
        conv.csat_em = agora
        dirty.extend(["csat_nota", "csat_em"])
        nota_ok = n
    conv.save(update_fields=dirty)
    registrar_evento(conv, "ENCERROU", autor=usuario, texto="Encerrou a conversa")
    if nota_ok is not None:
        registrar_evento(
            conv,
            "CSAT",
            autor=usuario,
            texto=f"CSAT registrado: {nota_ok}/5",
            payload={"nota": nota_ok},
        )
    return "ok", {"ok": True, "conversa": detalhe_conversa(usuario, conv.telefone)}

def reabrir_conversa(usuario, telefone: str) -> tuple[str, dict]:
    from crm_app.models import WhatsAppConversation

    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    conv.status = WhatsAppConversation.STATUS_EM_ATENDIMENTO
    conv.encerrada_em = None
    conv.assignee = usuario if getattr(usuario, "pk", None) else conv.assignee
    conv.bot_pausado = True
    conv.save(
        update_fields=["status", "encerrada_em", "assignee", "bot_pausado", "atualizado_em"]
    )
    pausar_bot(conv.telefone, usuario, "Conversa reaberta")
    registrar_evento(conv, "REABRIU", autor=usuario, texto="Reabriu a conversa")
    return "ok", {"ok": True, "conversa": detalhe_conversa(usuario, conv.telefone)}


def atualizar_crm(usuario, telefone: str, data: dict) -> tuple[str, dict]:
    """PATCH CRM: etapa, assignee, tags, nao_perturbe, contact_name."""
    from crm_app.models import Venda, WhatsAppConversation, WhatsAppTag

    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    data = data if isinstance(data, dict) else {}
    dirty = []

    if "contact_name" in data and data.get("contact_name") is not None:
        nome = str(data.get("contact_name") or "")[:255]
        if conv.contact_name != nome:
            conv.contact_name = nome
            dirty.append("contact_name")

    if "etapa_funil" in data:
        etapa = str(data.get("etapa_funil") or "").strip().upper()
        if etapa not in ETAPAS_VALIDAS:
            return "invalido", {"detail": f"Etapa inválida: {etapa}"}
        if conv.etapa_funil != etapa:
            antiga = conv.etapa_funil
            conv.etapa_funil = etapa
            dirty.append("etapa_funil")
            registrar_evento(
                conv,
                "ETAPA",
                autor=usuario,
                texto=f"Etapa: {antiga or '—'} → {etapa or '—'}",
                payload={"de": antiga, "para": etapa},
            )
            # Persiste etapa antes dos triggers (precisam do valor novo).
            conv.save(update_fields=["etapa_funil", "atualizado_em"])
            if "etapa_funil" in dirty:
                dirty.remove("etapa_funil")
            _disparar_triggers_etapa(
                conv, etapa, etapa_anterior=antiga or "", usuario=usuario
            )

    if "assignee_id" in data:
        raw = data.get("assignee_id")
        if raw in (None, "", 0, "0"):
            if conv.assignee_id:
                ant = conv.assignee.username if conv.assignee_id else None
                conv.assignee = None
                dirty.append("assignee")
                registrar_evento(
                    conv,
                    "TRANSFERIU",
                    autor=usuario,
                    texto="Removeu responsável",
                    payload={"de": ant, "para": None},
                )
        else:
            dest = _user_by_id(raw)
            if dest is None:
                return "invalido", {"detail": "Atendente inválido."}
            if conv.assignee_id != dest.id:
                ant = conv.assignee.username if conv.assignee_id else None
                conv.assignee = dest
                dirty.append("assignee")
                conv.bot_pausado = True
                dirty.append("bot_pausado")
                if conv.status != WhatsAppConversation.STATUS_ENCERRADA:
                    conv.status = WhatsAppConversation.STATUS_EM_ATENDIMENTO
                    dirty.append("status")
                pausar_bot(conv.telefone, usuario, "Responsável alterado no CRM")
                registrar_evento(
                    conv,
                    "TRANSFERIU",
                    autor=usuario,
                    texto=f"Responsável → {dest.username}",
                    payload={"de": ant, "para": dest.username},
                )

    if "tag_ids" in data and isinstance(data.get("tag_ids"), (list, tuple)):
        ids = []
        for x in data["tag_ids"]:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
        tags = list(WhatsAppTag.objects.filter(id__in=ids, ativo=True))
        conv.tags.set(tags)
        registrar_evento(
            conv,
            "TAG",
            autor=usuario,
            texto="Tags atualizadas: " + (", ".join(t.nome for t in tags) or "—"),
            payload={"tag_ids": [t.id for t in tags]},
        )

    if "add_tag" in data and data.get("add_tag"):
        nome = str(data.get("add_tag") or "").strip()[:40]
        if nome:
            tag, _ = WhatsAppTag.objects.get_or_create(
                nome=nome, defaults={"cor": data.get("tag_cor") or "#6c757d"}
            )
            conv.tags.add(tag)
            registrar_evento(
                conv, "TAG", autor=usuario, texto=f"Tag adicionada: {tag.nome}"
            )

    if "remove_tag_id" in data and data.get("remove_tag_id"):
        try:
            tid = int(data["remove_tag_id"])
            tag = WhatsAppTag.objects.filter(pk=tid).first()
            if tag:
                conv.tags.remove(tag)
                registrar_evento(
                    conv, "TAG", autor=usuario, texto=f"Tag removida: {tag.nome}"
                )
        except (TypeError, ValueError):
            pass

    if "nao_perturbe" in data and conv.venda_id:
        flag = bool(data.get("nao_perturbe"))
        Venda.objects.filter(pk=conv.venda_id).update(nao_perturbe=flag)
        registrar_evento(
            conv,
            "NAO_PERTURBE",
            autor=usuario,
            texto="Não perturbe: " + ("sim" if flag else "não"),
            payload={"nao_perturbe": flag},
        )

    if dirty:
        # unique dirty fields
        fields = list(dict.fromkeys(dirty + ["atualizado_em"]))
        conv.save(update_fields=fields)

    return "ok", {"ok": True, "conversa": detalhe_conversa(usuario, conv.telefone)}


def adicionar_nota(usuario, telefone: str, texto: str) -> tuple[str, dict]:
    from crm_app.models import ConversacaoNota

    corpo = (texto or "").strip()
    if not corpo:
        return "invalido", {"detail": "Informe o texto da nota."}
    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    nota = ConversacaoNota.objects.create(
        conversa=conv,
        autor=usuario if getattr(usuario, "pk", None) else None,
        texto=corpo[:5000],
    )
    registrar_evento(
        conv,
        "NOTA",
        autor=usuario,
        texto=corpo[:200],
        payload={"nota_id": nota.id},
    )
    return "ok", {"ok": True, "nota": serializar_nota(nota), "conversa": detalhe_conversa(usuario, conv.telefone)}


def criar_tarefa(
    usuario,
    telefone: str,
    *,
    titulo: str,
    prazo: str = "",
    dono_id=None,
) -> tuple[str, dict]:
    from crm_app.models import ConversacaoTarefa

    tit = (titulo or "").strip()
    if not tit:
        return "invalido", {"detail": "Informe o título da tarefa."}
    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    prazo_dt = None
    if prazo:
        prazo_dt = parse_datetime(str(prazo).replace("Z", "+00:00"))
        if prazo_dt and timezone.is_naive(prazo_dt):
            prazo_dt = timezone.make_aware(prazo_dt)
    dono = _user_by_id(dono_id) if dono_id else (usuario if getattr(usuario, "pk", None) else None)
    tarefa = ConversacaoTarefa.objects.create(
        conversa=conv,
        titulo=tit[:200],
        prazo=prazo_dt,
        dono=dono,
        criado_por=usuario if getattr(usuario, "pk", None) else None,
    )
    registrar_evento(
        conv,
        "TAREFA",
        autor=usuario,
        texto=f"Tarefa: {tarefa.titulo}",
        payload={"tarefa_id": tarefa.id},
    )
    return "ok", {
        "ok": True,
        "tarefa": serializar_tarefa(tarefa),
        "conversa": detalhe_conversa(usuario, conv.telefone),
    }


def atualizar_tarefa(usuario, telefone: str, tarefa_id, data: dict) -> tuple[str, dict]:
    from crm_app.models import ConversacaoTarefa

    conv = _conv_por_telefone(telefone)
    if conv is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    try:
        tarefa = ConversacaoTarefa.objects.get(pk=int(tarefa_id), conversa=conv)
    except (ConversacaoTarefa.DoesNotExist, TypeError, ValueError):
        return "nao_encontrado", {"detail": "Tarefa não encontrada."}
    data = data if isinstance(data, dict) else {}
    dirty = []
    if "titulo" in data and data.get("titulo"):
        tarefa.titulo = str(data["titulo"])[:200]
        dirty.append("titulo")
    if "status" in data:
        st = str(data.get("status") or "").upper()
        if st in {
            ConversacaoTarefa.STATUS_PENDENTE,
            ConversacaoTarefa.STATUS_CONCLUIDA,
            ConversacaoTarefa.STATUS_CANCELADA,
        }:
            tarefa.status = st
            dirty.append("status")
            if st == ConversacaoTarefa.STATUS_CONCLUIDA:
                tarefa.concluida_em = timezone.now()
                dirty.append("concluida_em")
    if "dono_id" in data:
        tarefa.dono = _user_by_id(data.get("dono_id"))
        dirty.append("dono")
    if "prazo" in data:
        raw = data.get("prazo")
        if not raw:
            tarefa.prazo = None
        else:
            dt = parse_datetime(str(raw).replace("Z", "+00:00"))
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            tarefa.prazo = dt
        dirty.append("prazo")
    if dirty:
        tarefa.save(update_fields=list(dict.fromkeys(dirty + ["atualizado_em"])))
        registrar_evento(
            conv,
            "TAREFA",
            autor=usuario,
            texto=f"Tarefa atualizada: {tarefa.titulo} ({tarefa.status})",
            payload={"tarefa_id": tarefa.id, "status": tarefa.status},
        )
    return "ok", {
        "ok": True,
        "tarefa": serializar_tarefa(tarefa),
        "conversa": detalhe_conversa(usuario, conv.telefone),
    }


def listar_tags(*, q: str = "") -> list[dict]:
    from crm_app.models import WhatsAppTag

    qs = WhatsAppTag.objects.filter(ativo=True).order_by("nome")
    if q:
        qs = qs.filter(nome__icontains=q.strip())
    return [serializar_tag(t) for t in qs[:100]]


def criar_tag(nome: str, cor: str = "#6c757d") -> dict:
    from crm_app.models import WhatsAppTag

    n = (nome or "").strip()[:40]
    if not n:
        raise ValueError("Informe o nome da tag.")
    tag, _ = WhatsAppTag.objects.get_or_create(
        nome=n, defaults={"cor": (cor or "#6c757d")[:16]}
    )
    return serializar_tag(tag)


def listar_respostas_rapidas() -> list[dict]:
    from crm_app.models import RespostaRapida

    return [
        {
            "id": r.id,
            "atalho": r.atalho,
            "texto": r.texto,
            "grupo": r.grupo or "",
        }
        for r in RespostaRapida.objects.filter(ativo=True).order_by("atalho")[:100]
    ]


def espelhar_envio_funil_no_inbox(
    *,
    telefone: str,
    template_nome: str,
    texto: str = "",
    message_id: str = "",
    sucesso: bool = True,
    erro: str = "",
    usuario=None,
    venda=None,
    aba: str = "",
    ref_id: str = "",
    data_hora=None,
) -> None:
    """Grava template do Funil (#247) no histórico do inbox (canal cliente).

    Unifica a timeline: o humano vê o disparo mesmo tendo saído pelo canal Funil.
    Marca reply_canal=funil para o próximo reply humano sair pelo #247.
    ``data_hora``: use o horário real do envio (ex.: MailingEnvio.enviado_em).
    """
    from crm_app.models import MensagemWhatsAppAtendimento, WhatsAppConversation
    from crm_app.services.whatsapp.atendimento_service import gravar_mensagem

    tel = canonicalizar_telefone(telefone)
    if len(tel) < 8:
        return
    conv = get_or_create_conversation(tel, venda=venda)
    if conv is None:
        return
    if aba or ref_id:
        vincular_funil_tratamento(
            conv, aba=aba, ref_id=ref_id, usuario=usuario, telefone=tel
        )
    preview = texto or f"[Template] {template_nome}"
    tipo = (
        MensagemWhatsAppAtendimento.TIPO_MODELO
        if (template_nome or "").strip()
        else MensagemWhatsAppAtendimento.TIPO_SESSAO
    )
    try:
        gravar_mensagem(
            telefone=tel,
            direcao=MensagemWhatsAppAtendimento.DIRECAO_SAIDA,
            texto=preview[:4000],
            tipo=tipo,
            template_name=(template_nome or "")[:120],
            message_id=(message_id or "")[:128],
            origem=MensagemWhatsAppAtendimento.ORIGEM_FUNIL,
            sucesso=bool(sucesso),
            erro=(erro or "")[:2000],
            enviado_por=usuario if getattr(usuario, "pk", None) else None,
            venda=venda,
            role_canal="cliente",
            data_hora=data_hora,
        )
    except Exception:
        # Dedup message_id ou falha de gravação não deve quebrar o disparo Funil.
        pass
    dirty_conv = []
    if sucesso and getattr(conv, "reply_canal", "") != WhatsAppConversation.REPLY_CANAL_FUNIL:
        conv.reply_canal = WhatsAppConversation.REPLY_CANAL_FUNIL
        dirty_conv.append("reply_canal")
    # Mailings e disparos Funil: marca etapa para filtrar no inbox/kanban.
    tpl = (template_nome or "").strip().lower()
    aba_u = (aba or "").strip().upper()
    if (
        tpl.startswith("mailing_") or aba_u == "MAILING"
    ) and getattr(conv, "etapa_funil", "") != WhatsAppConversation.ETAPA_MAILING:
        conv.etapa_funil = WhatsAppConversation.ETAPA_MAILING
        dirty_conv.append("etapa_funil")
    if dirty_conv:
        WhatsAppConversation.objects.filter(pk=conv.pk).update(
            **{f: getattr(conv, f) for f in dirty_conv}
        )