"""Endpoints admin para conexão e configuração WhatsApp."""
from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from crm_app.models import WhatsAppIntegracaoConfig
from crm_app.services.evolution_connection_service import (
    EvolutionConnectionError,
    EvolutionConnectionService,
)
from crm_app.services.whatsapp_config_service import (
    build_whatsapp_config_payload,
    set_whatsapp_provider,
)
from crm_app.utils import is_member

_GESTAO_WHATSAPP = ("Diretoria", "Admin", "BackOffice")


def _usuario_pode_gerenciar_whatsapp(user) -> bool:
    return bool(user and user.is_authenticated) and (
        user.is_superuser or is_member(user, list(_GESTAO_WHATSAPP))
    )


def _evolution_disponivel() -> bool:
    from crm_app.services.whatsapp_config_service import _credenciais_evolution_ok

    return _credenciais_evolution_ok()


@api_view(["GET", "PATCH"])
@permission_classes([permissions.IsAuthenticated])
def whatsapp_config_api(request):
    if not _usuario_pode_gerenciar_whatsapp(request.user):
        return Response({"detail": "Sem permissão."}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "GET":
        return Response(build_whatsapp_config_payload())

    provider = (request.data.get("provider") or "").strip().lower()
    try:
        set_whatsapp_provider(provider, request.user)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    payload = build_whatsapp_config_payload()
    payload["message"] = (
        "Provedor alterado. Confirme que o webhook inbound aponta para "
        "/api/crm/webhook-whatsapp/ no provedor escolhido."
    )
    return Response(payload)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def whatsapp_status_api(request):
    if not _usuario_pode_gerenciar_whatsapp(request.user):
        return Response({"detail": "Sem permissão."}, status=status.HTTP_403_FORBIDDEN)

    config = build_whatsapp_config_payload()
    if not _evolution_disponivel():
        return Response(
            {
                "provider": config["provider"],
                "connected": False,
                "state": "unconfigured",
                "instanceName": config.get("instanceName"),
                "message": (
                    "Credenciais Evolution ausentes no servidor "
                    "(EVOLUTION_API_URL / EVOLUTION_API_KEY)."
                ),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        data = EvolutionConnectionService().get_status()
        data["provider"] = config["provider"]
        data["activeProvider"] = config["provider"]
        data["setupMode"] = config["provider"] != WhatsAppIntegracaoConfig.PROVIDER_EVOLUTION
        if data.get("setupMode"):
            data["message"] = (
                "Aparelho Evolution (setup). Provedor ativo ainda é Z-API — "
                "escaneie o QR e só então salve Evolution como provedor."
            )
        return Response(data)
    except EvolutionConnectionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def whatsapp_qrcode_api(request):
    if not _usuario_pode_gerenciar_whatsapp(request.user):
        return Response({"detail": "Sem permissão."}, status=status.HTTP_403_FORBIDDEN)
    if not _evolution_disponivel():
        return Response(
            {
                "detail": (
                    "Credenciais Evolution não configuradas no servidor "
                    "(EVOLUTION_API_URL / EVOLUTION_API_KEY)."
                )
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
        data = EvolutionConnectionService().get_qrcode()
        return Response(data)
    except EvolutionConnectionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated])
def whatsapp_disconnect_api(request):
    if not _usuario_pode_gerenciar_whatsapp(request.user):
        return Response({"detail": "Sem permissão."}, status=status.HTTP_403_FORBIDDEN)
    if not _evolution_disponivel():
        return Response(
            {"detail": "Credenciais Evolution não configuradas no servidor."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
        data = EvolutionConnectionService().disconnect()
        return Response(data)
    except EvolutionConnectionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
