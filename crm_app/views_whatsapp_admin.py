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
    update_whatsapp_config,
)
from crm_app.services.whatsatende_connection_service import (
    WhatsAtendeConnectionError,
    WhatsAtendeConnectionService,
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


def _whatsatende_conexao_disponivel(role: str = "a") -> bool:
    from crm_app.services.whatsapp_config_service import (
        _credenciais_whatsatende_cliente_ok,
        _credenciais_whatsatende_conexao_ok,
        _credenciais_whatsatende_funil_ok,
    )

    r = (role or "a").strip().lower()
    if r in ("b", "cliente", "qualidade"):
        return _credenciais_whatsatende_cliente_ok()
    if r in ("funil", "f", "247"):
        return _credenciais_whatsatende_funil_ok()
    return _credenciais_whatsatende_conexao_ok()


def _whatsatende_role(request) -> str:
    return (request.query_params.get("role") or request.query_params.get("conexao") or "a").strip().lower()


def _backend_conexao(request) -> str:
    """
    Qual backend usar para status/QR/disconnect.
    Query ?backend=evolution|whatsatende ou provedor ativo.
    Em hybrid o QR do Número A fica na Z-API (painel externo).
    """
    q = (request.query_params.get("backend") or "").strip().lower()
    if q in ("evolution", "whatsatende"):
        return q
    provider = build_whatsapp_config_payload().get("provider") or "zapi"
    if provider == WhatsAppIntegracaoConfig.PROVIDER_WHATSATENDE:
        return "whatsatende"
    if provider == WhatsAppIntegracaoConfig.PROVIDER_EVOLUTION:
        return "evolution"
    if provider == WhatsAppIntegracaoConfig.PROVIDER_HYBRID:
        # Número A = Z-API (sem QR aqui); QR WhatsAtende A não é necessário.
        return "evolution"
    if provider == WhatsAppIntegracaoConfig.PROVIDER_META:
        return "evolution"
    # Z-API ativo: preferir WhatsAtende se já tiver ID+token (setup paralelo)
    if _whatsatende_conexao_disponivel():
        return "whatsatende"
    return "evolution"


@api_view(["GET", "PATCH"])
@permission_classes([permissions.IsAuthenticated])
def whatsapp_config_api(request):
    if not _usuario_pode_gerenciar_whatsapp(request.user):
        return Response({"detail": "Sem permissão."}, status=status.HTTP_403_FORBIDDEN)

    if request.method == "GET":
        return Response(build_whatsapp_config_payload())

    raw_provider = request.data.get("provider")
    provider = (
        str(raw_provider).strip().lower()
        if raw_provider is not None and str(raw_provider).strip()
        else None
    )
    envios = request.data.get("enviosClienteAtivos")
    if envios is None:
        envios = request.data.get("envios_cliente_ativos")
    numero_equipe = request.data.get("numeroEquipeLabel")
    if numero_equipe is None:
        numero_equipe = request.data.get("numero_equipe_label")
    numero_cliente = request.data.get("numeroClienteLabel")
    if numero_cliente is None:
        numero_cliente = request.data.get("numero_cliente_label")

    if (
        provider is None
        and envios is None
        and numero_equipe is None
        and numero_cliente is None
    ):
        return Response(
            {"detail": "Informe o provedor ou a configuração dos canais (equipe/cliente)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        update_whatsapp_config(
            user=request.user,
            provider=provider,
            envios_cliente_ativos=envios,
            numero_equipe_label=numero_equipe,
            numero_cliente_label=numero_cliente,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    payload = build_whatsapp_config_payload()
    if payload.get("canalClientePronto"):
        payload["message"] = (
            "Canal de clientes ativo no número Meta (WhatsAtende B). "
            "O número do time comercial continua só para equipe/grupos."
        )
    elif payload.get("provider") == WhatsAppIntegracaoConfig.PROVIDER_HYBRID:
        payload["message"] = (
            "Modo híbrido: equipe na Z-API. Envios a clientes continuam bloqueados "
            "até o número Meta estar configurado e liberado nesta tela."
        )
    else:
        payload["message"] = (
            "Configuração salva. Envios a clientes só saem pelo número oficial Meta, "
            "quando ele estiver configurado e ativado nesta aba."
        )
    return Response(payload)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def whatsapp_status_api(request):
    if not _usuario_pode_gerenciar_whatsapp(request.user):
        return Response({"detail": "Sem permissão."}, status=status.HTTP_403_FORBIDDEN)

    config = build_whatsapp_config_payload()
    backend = _backend_conexao(request)

    if backend == "zapi":
        from crm_app.services.whatsapp.zapi_provider import ZapiProvider

        if not config.get("zapiConfigured"):
            return Response(
                {
                    "provider": config["provider"],
                    "backend": "zapi",
                    "connected": False,
                    "state": "unconfigured",
                    "phone": config.get("numeroEquipeLabel") or "",
                    "message": "Credenciais Z-API ausentes (ZAPI_INSTANCE_ID / ZAPI_TOKEN).",
                }
            )
        me = ZapiProvider().obter_dados_instancia() or {}
        phone = (
            str(me.get("phone") or me.get("wid") or me.get("id") or "").strip()
            if isinstance(me, dict)
            else ""
        )
        connected = bool(isinstance(me, dict) and me and not me.get("error"))
        return Response(
            {
                "provider": config["provider"],
                "backend": "zapi",
                "connected": connected,
                "state": "open" if connected else "close",
                "phone": phone or (config.get("numeroEquipeLabel") or ""),
                "instanceName": config.get("zapiConfigured") and "z-api" or "",
            }
        )

    if backend == "whatsatende":
        role = _whatsatende_role(request)
        if not _whatsatende_conexao_disponivel(role):
            return Response(
                {
                    "provider": config["provider"],
                    "connected": False,
                    "state": "unconfigured",
                    "role": role,
                    "instanceName": (
                        config.get("whatsatendeWhatsappIdFunil") if role in ("funil", "f", "247")
                        else config.get("whatsatendeWhatsappIdB") if role in ("b", "cliente")
                        else config.get("whatsatendeWhatsappId")
                    ) or "",
                    "message": (
                        f"Credenciais WhatsAtende ({role}) incompletas. "
                        "Confira TOKEN e WHATSAPP_ID da conexão no servidor."
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            data = WhatsAtendeConnectionService(role=role).get_status()
            data["provider"] = config["provider"]
            data["activeProvider"] = config["provider"]
            data["role"] = role
            data["setupMode"] = (
                config["provider"] != WhatsAppIntegracaoConfig.PROVIDER_WHATSATENDE
            )
            if data.get("setupMode") and role in ("a", "interno", ""):
                data["message"] = (
                    "Aparelho WhatsAtende (setup). Provedor ativo ainda não é "
                    "WhatsAtende — escaneie o QR e só então salve WhatsAtende."
                )
            return Response(data)
        except WhatsAtendeConnectionError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

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

    backend = _backend_conexao(request)
    if backend == "whatsatende":
        role = _whatsatende_role(request)
        if not _whatsatende_conexao_disponivel(role):
            return Response(
                {
                    "detail": (
                        f"Credenciais WhatsAtende ({role}) incompletas "
                        "(TOKEN / WHATSAPP_ID da conexão)."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            return Response(WhatsAtendeConnectionService(role=role).get_qrcode())
        except WhatsAtendeConnectionError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

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

    backend = _backend_conexao(request)
    if backend == "whatsatende":
        role = _whatsatende_role(request)
        if not _whatsatende_conexao_disponivel(role):
            return Response(
                {"detail": f"Credenciais WhatsAtende ({role}) não configuradas no servidor."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            return Response(WhatsAtendeConnectionService(role=role).disconnect())
        except WhatsAtendeConnectionError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

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
