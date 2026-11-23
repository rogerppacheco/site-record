"""Página e API do inbox de atendimento WhatsApp (número do cliente) — estilo Kommo."""
from __future__ import annotations

import json
import time

from django.http import StreamingHttpResponse
from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.services.whatsapp import atendimento_copilot as copilot
from crm_app.services.whatsapp import atendimento_crm as crm
from crm_app.services.whatsapp import atendimento_automacao as automacao
from crm_app.services.whatsapp import atendimento_metricas as metricas
from crm_app.services.whatsapp.atendimento_service import (
    assumir_conversa,
    detalhe_conversa,
    iniciar_conversa_por_telefone,
    listar_conversas,
    listar_templates_inbox,
    responder_midia,
    responder_template,
    responder_texto,
)
from crm_app.utils import is_member

GRUPOS_ATENDIMENTO = ("Diretoria", "Admin", "BackOffice", "Auditoria", "Qualidade")


def page_atendimento_whatsapp(request):
    """Tela de conversas do WhatsApp oficial."""
    return render(request, "atendimento-whatsapp.html")


class _AtendimentoAutenticado(APIView):
    permission_classes = [IsAuthenticated]

    def _negar_se_sem_perfil(self, request):
        if is_member(request.user, list(GRUPOS_ATENDIMENTO)):
            return None
        return Response({"detail": "Sem permissão."}, status=status.HTTP_403_FORBIDDEN)


def _map_codigo(codigo: str, payload: dict):
    if codigo == "ok":
        return Response(payload)
    if codigo == "nao_encontrado":
        return Response(payload, status=status.HTTP_404_NOT_FOUND)
    if codigo == "invalido":
        return Response(payload, status=status.HTTP_400_BAD_REQUEST)
    return Response(payload, status=status.HTTP_400_BAD_REQUEST)


class AtendimentoWhatsAppConversasView(_AtendimentoAutenticado):
    """GET: lista de conversas do número oficial (+ filas)."""

    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        busca = request.query_params.get("q") or ""
        fila = request.query_params.get("fila") or "todas"
        etapa = request.query_params.get("etapa") or ""
        canal = request.query_params.get("canal") or ""
        janela = request.query_params.get("janela") or ""
        # Troca rápida de canal/fila: pula contagens (skip_counts=1).
        skip_counts = str(request.query_params.get("skip_counts") or "").lower() in (
            "1",
            "true",
            "yes",
        )
        try:
            limite = int(request.query_params.get("limit") or 60)
        except (TypeError, ValueError):
            limite = 60
        try:
            offset = int(request.query_params.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        since = request.query_params.get("since") or ""
        listagem = listar_conversas(
            request.user,
            busca,
            limite=limite,
            since=since or None,
            fila=fila,
            etapa=etapa,
            canal=canal,
            janela=janela,
            offset=offset,
        )
        payload = {
            **listagem,
            "fila": fila,
            "canal": canal,
            "janela": janela,
        }
        if not skip_counts:
            payload["filas"] = crm.contagem_filas(request.user)
        return Response(payload)


class AtendimentoWhatsAppDetalheView(_AtendimentoAutenticado):
    """GET: histórico paginado de um telefone (últimas N; before_id para carregar mais)."""

    def get(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        try:
            limit_msgs = int(request.query_params.get("limit") or 30)
        except (TypeError, ValueError):
            limit_msgs = 30
        before_id = request.query_params.get("before_id") or request.query_params.get("before")
        crm_flag = str(request.query_params.get("crm") or "1").lower()
        incluir_crm = crm_flag not in ("0", "false", "no")
        detalhe = detalhe_conversa(
            request.user,
            telefone,
            limit_msgs=limit_msgs,
            before_id=int(before_id) if before_id and str(before_id).isdigit() else None,
            incluir_crm=incluir_crm,
        )
        if detalhe is None:
            return Response({"detail": "Conversa não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        return Response(detalhe)


def _map_envio(codigo: str, payload: dict):
    if codigo == "ok":
        return Response(payload)
    if codigo == "janela_fechada":
        return Response(payload, status=status.HTTP_409_CONFLICT)
    if codigo == "canal_indisponivel":
        return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if codigo == "falha_envio":
        return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
    if codigo == "nao_encontrado":
        return Response(payload, status=status.HTTP_404_NOT_FOUND)
    return Response(payload, status=status.HTTP_400_BAD_REQUEST)


class AtendimentoWhatsAppResponderView(_AtendimentoAutenticado):
    """POST: texto livre, somente com a janela de 24 horas aberta."""

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        texto = request.data.get("texto") if isinstance(request.data, dict) else ""
        return _map_envio(*responder_texto(request.user, telefone, texto or ""))


class AtendimentoWhatsAppMidiaView(_AtendimentoAutenticado):
    """POST: imagem/PDF em base64 (JSON) ou multipart file."""

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        import base64

        data = request.data if hasattr(request, "data") else {}
        kind = (data.get("kind") or data.get("tipo") or "").strip()
        caption = data.get("caption") or data.get("legenda") or ""
        filename = data.get("filename") or data.get("nome") or ""
        mime = data.get("mime") or data.get("content_type") or ""
        b64 = data.get("base64") or data.get("base64_data") or data.get("file_b64") or ""

        upload = request.FILES.get("file") or request.FILES.get("arquivo")
        if upload is not None:
            blob = upload.read()
            if len(blob) > 15 * 1024 * 1024:
                return Response(
                    {"detail": "Arquivo maior que 15 MB."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            b64 = base64.b64encode(blob).decode("ascii")
            filename = filename or getattr(upload, "name", "") or "arquivo"
            mime = mime or getattr(upload, "content_type", "") or ""
            if not kind:
                ct = (mime or "").lower()
                name = (filename or "").lower()
                if ct.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    kind = "image"
                else:
                    kind = "document"

        return _map_envio(
            *responder_midia(
                request.user,
                telefone,
                kind=kind,
                base64_data=b64,
                filename=filename,
                caption=caption,
                mime=mime,
            )
        )


class AtendimentoWhatsAppTemplateView(_AtendimentoAutenticado):
    """GET: catálogo | POST: envia template Meta (sem exigir janela 24h)."""

    def get(self, request, telefone=None):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        return Response({"items": listar_templates_inbox()})

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        params = data.get("body_params") or data.get("params") or []
        if isinstance(params, str):
            params = [p.strip() for p in params.split("|")]
        return _map_envio(
            *responder_template(
                request.user,
                telefone,
                template_name=data.get("template_name") or data.get("template") or "",
                body_params=list(params) if isinstance(params, (list, tuple)) else [],
                language_code=data.get("language_code") or "pt_BR",
            )
        )


class AtendimentoWhatsAppAssumirView(_AtendimentoAutenticado):
    """POST: pausa o bot neste telefone sem enviar mensagem."""

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        detalhe = assumir_conversa(request.user, telefone)
        if detalhe is None:
            return Response({"detail": "Conversa não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"ok": True, "bot_pausado": True, "conversa": detalhe})


class AtendimentoWhatsAppIniciarView(_AtendimentoAutenticado):
    """POST: cria/abre Conversation a partir do Funil (Iniciar Conversa)."""

    def post(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        telefone = data.get("telefone") or ""
        contact_name = (data.get("contact_name") or data.get("nome") or "")[:255]
        venda_id = data.get("venda_id")
        aba = data.get("aba") or data.get("etapa_funil") or ""
        ref_id = data.get("ref_id") or data.get("id") or ""
        venda = None
        if venda_id:
            from crm_app.models import Venda

            venda = Venda.objects.filter(pk=venda_id).first()
        detalhe = iniciar_conversa_por_telefone(
            request.user,
            telefone,
            venda=venda,
            contact_name=contact_name,
            aba=str(aba or ""),
            ref_id=str(ref_id or ""),
        )
        if detalhe is None:
            return Response(
                {"detail": "Telefone inválido para iniciar conversa."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"ok": True, "conversa": detalhe})


class AtendimentoWhatsAppPatchView(_AtendimentoAutenticado):
    """PATCH: etapa, responsável, tags, não-perturbe."""

    def patch(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(*crm.atualizar_crm(request.user, telefone, data))

    def post(self, request, telefone):
        # Alias para clientes que não enviam PATCH
        return self.patch(request, telefone)


class AtendimentoWhatsAppTransferirView(_AtendimentoAutenticado):
    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(
            *crm.transferir_conversa(request.user, telefone, data.get("assignee_id"))
        )


class AtendimentoWhatsAppLiberarView(_AtendimentoAutenticado):
    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        devolver = data.get("devolver_bot", True)
        return _map_codigo(
            *crm.liberar_conversa(request.user, telefone, devolver_bot=bool(devolver))
        )


class AtendimentoWhatsAppEncerrarView(_AtendimentoAutenticado):
    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(
            *crm.encerrar_conversa(
                request.user, telefone, csat_nota=data.get("csat_nota")
            )
        )


class AtendimentoWhatsAppReabrirView(_AtendimentoAutenticado):
    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        return _map_codigo(*crm.reabrir_conversa(request.user, telefone))


class AtendimentoWhatsAppNotaView(_AtendimentoAutenticado):
    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(
            *crm.adicionar_nota(request.user, telefone, data.get("texto") or "")
        )


class AtendimentoWhatsAppTarefaView(_AtendimentoAutenticado):
    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(
            *crm.criar_tarefa(
                request.user,
                telefone,
                titulo=data.get("titulo") or "",
                prazo=data.get("prazo") or "",
                dono_id=data.get("dono_id"),
            )
        )


class AtendimentoWhatsAppTarefaDetailView(_AtendimentoAutenticado):
    def patch(self, request, telefone, tarefa_id):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(
            *crm.atualizar_tarefa(request.user, telefone, tarefa_id, data)
        )

    def post(self, request, telefone, tarefa_id):
        return self.patch(request, telefone, tarefa_id)


class AtendimentoWhatsAppMetaView(_AtendimentoAutenticado):
    """GET: agentes, tags, respostas rápidas, contagem de filas."""

    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        return Response({
            "agentes": crm.listar_agentes_atendimento(),
            "tags": crm.listar_tags(q=request.query_params.get("q") or ""),
            "respostas_rapidas": crm.listar_respostas_rapidas(),
            "templates": listar_templates_inbox(),
            "filas": crm.contagem_filas(request.user),
            "triggers": __import__(
                "crm_app.services.whatsapp.atendimento_automacao",
                fromlist=["listar_triggers"],
            ).listar_triggers(),
            "etapas": [
                {"value": v, "label": lbl}
                for v, lbl in __import__(
                    "crm_app.models", fromlist=["WhatsAppConversation"]
                ).WhatsAppConversation.ETAPA_CHOICES
            ],
        })


class AtendimentoWhatsAppTagsView(_AtendimentoAutenticado):
    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        return Response({"items": crm.listar_tags(q=request.query_params.get("q") or "")})

    def post(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        try:
            tag = crm.criar_tag(data.get("nome") or "", data.get("cor") or "#6c757d")
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"ok": True, "tag": tag})


class AtendimentoWhatsAppCopilotView(_AtendimentoAutenticado):
    """POST: ações do copilot (resumo | sugestao | reescrever | resumo_lead)."""

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        acao = (data.get("acao") or data.get("action") or "").strip().lower()
        if acao in ("resumo", "summarize", "summary"):
            codigo, payload = copilot.resumir_conversa(request.user, telefone)
        elif acao in ("sugestao", "sugerir", "suggest"):
            codigo, payload = copilot.sugerir_resposta(
                request.user, telefone, instrucao=data.get("instrucao") or ""
            )
        elif acao in ("reescrever", "rewrite"):
            codigo, payload = copilot.reescrever_texto(
                request.user,
                telefone,
                texto=data.get("texto") or "",
                tom=data.get("tom") or "profissional",
            )
        elif acao in ("resumo_lead", "lead"):
            codigo, payload = copilot.resumir_lead(request.user, telefone)
        else:
            return Response(
                {"detail": "Ação inválida. Use resumo, sugestao, reescrever ou resumo_lead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if codigo == "ok":
            return Response(payload)
        if codigo == "nao_encontrado":
            return Response(payload, status=status.HTTP_404_NOT_FOUND)
        if codigo == "falha_ia":
            return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(payload, status=status.HTTP_400_BAD_REQUEST)



class AtendimentoWhatsAppKanbanView(_AtendimentoAutenticado):
    """GET: colunas do kanban por etapa_funil."""

    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        return Response(metricas.listar_kanban(request.user))


class AtendimentoWhatsAppMetricasView(_AtendimentoAutenticado):
    """GET: SLA / volume / CSAT (?periodo=hoje|7d|30d)."""

    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        periodo = request.query_params.get("periodo") or "7d"
        return Response(metricas.metricas_inbox(request.user, periodo=periodo))


class AtendimentoWhatsAppCsatView(_AtendimentoAutenticado):
    """POST: registra CSAT 1–5 na conversa."""

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(
            *metricas.registrar_csat(
                request.user, telefone, data.get("nota") or data.get("csat_nota")
            )
        )


class AtendimentoWhatsAppTriggersView(_AtendimentoAutenticado):
    """GET lista / POST cria triggers de etapa."""

    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        return Response({"items": automacao.listar_triggers()})

    def post(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(*automacao.criar_trigger(data))


class AtendimentoWhatsAppTriggersSeedView(_AtendimentoAutenticado):
    """POST: cria triggers padrão se a tabela estiver vazia."""

    def post(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        return _map_codigo(*automacao.seed_triggers_api())


class AtendimentoWhatsAppMailingBackfillView(_AtendimentoAutenticado):
    """POST: espelha envios de mailing históricos no inbox."""

    def post(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        from crm_app.services.mailing_templates import backfill_mailing_no_inbox

        data = request.data if isinstance(request.data, dict) else {}
        try:
            limite = int(data.get("limite") or request.query_params.get("limite") or 800)
        except (TypeError, ValueError):
            limite = 800
        return Response(backfill_mailing_no_inbox(limite=limite))


class AtendimentoWhatsAppTriggerDetailView(_AtendimentoAutenticado):
    """PATCH atualiza / DELETE remove trigger."""

    def patch(self, request, trigger_id):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        data = request.data if isinstance(request.data, dict) else {}
        return _map_codigo(*automacao.atualizar_trigger(trigger_id, data))

    def post(self, request, trigger_id):
        return self.patch(request, trigger_id)

    def delete(self, request, trigger_id):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        return _map_codigo(*automacao.excluir_trigger(trigger_id))

class EventStreamRenderer(BaseRenderer):
    """Permite Accept: text/event-stream no DRF (evita HTTP 406 no SSE)."""

    media_type = "text/event-stream"
    format = "event-stream"
    charset = None
    render_style = "binary"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if data is None:
            return b""
        if isinstance(data, (bytes, bytearray)):
            return data
        return str(data).encode("utf-8")


class AtendimentoWhatsAppEventsView(_AtendimentoAutenticado):
    """GET: Server-Sent Events (Redis pub/sub) para alertas em tempo real."""

    # Sem isso o DRF rejeita Accept: text/event-stream com 406 Not Acceptable.
    renderer_classes = [EventStreamRenderer]

    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado

        def event_stream():
            from crm_app.services.whatsapp.inbox_events import iter_inbox_events

            # Padding inicial: evita buffer do WSGI/proxy engolir o 1º frame SSE.
            yield ": " + (" " * 2048) + "\n\n"
            yield ": connected\n\n"
            yield "event: ready\ndata: {\"ok\":true}\n\n"
            started = time.time()
            max_seconds = 25 * 60
            for event in iter_inbox_events(timeout=15.0):
                if time.time() - started > max_seconds:
                    yield "event: reconnect\ndata: {}\n\n"
                    break
                if event is None:
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False, default=str)
                yield f"event: message\ndata: {payload}\n\n"

        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache, no-transform"
        response["X-Accel-Buffering"] = "no"
        return response
