"""Página e API do inbox de atendimento WhatsApp (número do cliente)."""
from __future__ import annotations

from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.services.whatsapp.atendimento_service import (
    assumir_conversa,
    detalhe_conversa,
    listar_conversas,
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


class AtendimentoWhatsAppConversasView(_AtendimentoAutenticado):
    """GET: lista de conversas do número oficial."""

    def get(self, request):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        busca = request.query_params.get("q") or ""
        try:
            limite = int(request.query_params.get("limit") or 40)
        except (TypeError, ValueError):
            limite = 40
        since = request.query_params.get("since") or ""
        return Response({
            "items": listar_conversas(request.user, busca, limite=limite, since=since or None),
        })


class AtendimentoWhatsAppDetalheView(_AtendimentoAutenticado):
    """GET: histórico paginado de um telefone (últimas N; before_id para carregar mais)."""

    def get(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        try:
            limit_msgs = int(request.query_params.get("limit") or 80)
        except (TypeError, ValueError):
            limit_msgs = 80
        before_id = request.query_params.get("before_id") or request.query_params.get("before")
        detalhe = detalhe_conversa(
            request.user,
            telefone,
            limit_msgs=limit_msgs,
            before_id=int(before_id) if before_id and str(before_id).isdigit() else None,
        )
        if detalhe is None:
            return Response({"detail": "Conversa não encontrada."}, status=status.HTTP_404_NOT_FOUND)
        return Response(detalhe)


class AtendimentoWhatsAppResponderView(_AtendimentoAutenticado):
    """POST: texto livre, somente com a janela de 24 horas aberta."""

    def post(self, request, telefone):
        negado = self._negar_se_sem_perfil(request)
        if negado:
            return negado
        texto = request.data.get("texto") if isinstance(request.data, dict) else ""
        codigo, payload = responder_texto(request.user, telefone, texto or "")
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
