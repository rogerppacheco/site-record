import io
import logging
import re
from datetime import timedelta
from typing import Any, Dict, Optional

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import AuditoriaLigacao, Venda
from crm_app.onedrive_service import OneDriveUploader
from crm_app.zenvia_voice_service import ZenviaVoiceService

logger = logging.getLogger(__name__)


def _is_member(user, groups) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return user.is_superuser or user.groups.filter(name__in=groups).exists()


def _normalize_phone(raw: Optional[str]) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) in (10, 11):
        return f"55{digits}"
    return digits


def _extract_first(data: Dict[str, Any], keys, default=None):
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


class AuditoriaLigacaoStartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: HttpRequest, venda_id: int):
        grupos = ["Diretoria", "Admin", "BackOffice", "Supervisor", "Auditoria", "Qualidade"]
        if not _is_member(request.user, grupos):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        venda = Venda.objects.filter(id=venda_id, ativo=True).first()
        if not venda:
            return Response({"detail": "Venda não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        destination = request.data.get("destination_number") or venda.telefone1 or venda.telefone2
        source = request.data.get("source_number") or getattr(settings, "ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER", "")
        if not source:
            return Response(
                {"detail": "Defina ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER ou envie source_number no payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not destination:
            return Response(
                {"detail": "Venda sem telefone de destino e destination_number não informado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        source = _normalize_phone(source)
        destination = _normalize_phone(destination)
        tags = f"auditoria_venda_{venda.id}"

        service = ZenviaVoiceService()
        try:
            provider_resp = service.create_call(
                source_number=source,
                destination_number=destination,
                record_audio=True,
                tags=tags,
                bina=request.data.get("bina"),
            )
        except Exception as exc:
            logger.exception("Erro ao iniciar ligação na Zenvia: %s", exc)
            return Response(
                {"detail": f"Falha ao iniciar ligação: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        dados = provider_resp.get("dados") if isinstance(provider_resp, dict) else {}
        call_id = _extract_first(
            dados if isinstance(dados, dict) else {},
            ["id", "chamada_id", "call_id"],
            default=_extract_first(provider_resp, ["id", "chamada_id", "call_id"]),
        )
        if call_id is None:
            call_id = f"sem_id_{timezone.now().timestamp()}"

        ligacao = AuditoriaLigacao.objects.create(
            venda=venda,
            auditor=request.user,
            provedor="ZENVIA",
            provider_call_id=str(call_id),
            numero_origem=source,
            numero_destino=destination,
            status="INICIADA",
            consentimento_declarado=bool(request.data.get("consentimento_declarado", True)),
            consentimento_observacao=request.data.get(
                "consentimento_observacao",
                "Auditor informou em voz que a chamada estava sendo gravada.",
            ),
            payload_inicio=provider_resp if isinstance(provider_resp, dict) else {"raw": str(provider_resp)},
        )

        return Response(
            {
                "detail": "Ligação iniciada com sucesso.",
                "ligacao_id": ligacao.id,
                "provider_call_id": ligacao.provider_call_id,
                "provider_response": provider_resp,
            },
            status=status.HTTP_201_CREATED,
        )


class AuditoriaLigacaoListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: HttpRequest, venda_id: int):
        grupos = ["Diretoria", "Admin", "BackOffice", "Supervisor", "Auditoria", "Qualidade"]
        if not _is_member(request.user, grupos):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        limite = int(request.GET.get("limite", 30))
        rows = AuditoriaLigacao.objects.filter(venda_id=venda_id).select_related("auditor").order_by("-criado_em")[:limite]
        data = [
            {
                "id": r.id,
                "status": r.status,
                "provedor": r.provedor,
                "provider_call_id": r.provider_call_id,
                "provider_recording_id": r.provider_recording_id,
                "numero_origem": r.numero_origem,
                "numero_destino": r.numero_destino,
                "duracao_segundos": r.duracao_segundos,
                "link_gravacao_provedor": r.link_gravacao_provedor,
                "link_gravacao_onedrive": r.link_gravacao_onedrive,
                "auditor": r.auditor.username if r.auditor else None,
                "criado_em": r.criado_em,
            }
            for r in rows
        ]
        return Response({"results": data})


class AuditoriaLigacaoWebhookView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request: HttpRequest):
        expected_secret = getattr(settings, "ZENVIA_VOICE_WEBHOOK_SECRET", "")
        if expected_secret:
            received_secret = request.headers.get("X-Webhook-Secret") or request.query_params.get("secret")
            if received_secret != expected_secret:
                return Response({"detail": "Webhook não autorizado."}, status=status.HTTP_401_UNAUTHORIZED)

        payload = request.data if isinstance(request.data, dict) else {}
        call_id = _extract_first(payload, ["id", "chamada_id", "call_id"])
        if not call_id:
            return Response({"detail": "call_id não encontrado no webhook."}, status=status.HTTP_400_BAD_REQUEST)

        ligacao = AuditoriaLigacao.objects.filter(provider_call_id=str(call_id)).order_by("-id").first()
        if not ligacao:
            return Response({"detail": "Ligação não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        status_provedor = str(_extract_first(payload, ["status", "status_chamada"], default="")).upper()
        status_interno = "FINALIZADA" if status_provedor in {"ATENDIDA", "FINALIZADA", "ENCERRADA"} else "PROCESSANDO"
        duracao = _extract_first(payload, ["duracao_segundos", "duracao_falada_segundos", "duration"], default=0)
        recording_url = _extract_first(
            payload,
            ["url_gravacao", "recording_url", "link_gravacao"],
            default=None,
        )

        with transaction.atomic():
            ligacao.payload_webhook = payload
            ligacao.status = status_interno
            ligacao.finalizado_em = timezone.now()
            try:
                ligacao.duracao_segundos = int(duracao or 0)
            except Exception:
                ligacao.duracao_segundos = 0
            if recording_url:
                ligacao.link_gravacao_provedor = recording_url
            ligacao.save(update_fields=[
                "payload_webhook",
                "status",
                "finalizado_em",
                "duracao_segundos",
                "link_gravacao_provedor",
                "atualizado_em",
            ])

        if ligacao.link_gravacao_provedor:
            try:
                _sync_recording_to_onedrive(ligacao)
            except Exception as exc:
                logger.exception("Falha ao sincronizar gravação no OneDrive: %s", exc)

        return Response({"detail": "Webhook processado."}, status=status.HTTP_200_OK)


def _sync_recording_to_onedrive(ligacao: AuditoriaLigacao) -> None:
    url = ligacao.link_gravacao_provedor
    if not url:
        return

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    extension = ".mp3"
    if "wav" in content_type:
        extension = ".wav"
    elif "ogg" in content_type:
        extension = ".ogg"

    filename = f"venda_{ligacao.venda_id}_ligacao_{ligacao.id}{extension}"
    folder_name = f"{getattr(settings, 'AUDITORIA_ONEDRIVE_FOLDER', 'Auditoria_Ligacoes')}/{timezone.localdate().isoformat()}"
    file_obj = io.BytesIO(response.content)
    file_obj.seek(0)

    uploader = OneDriveUploader()
    web_url = uploader.upload_file(file_obj=file_obj, folder_name=folder_name, filename=filename)

    ligacao.link_gravacao_onedrive = web_url
    ligacao.status = "ARQUIVADA"
    if not ligacao.finalizado_em:
        ligacao.finalizado_em = timezone.now()
    if not ligacao.expira_em:
        ligacao.expira_em = timezone.now() + timedelta(days=180)
    ligacao.save(update_fields=["link_gravacao_onedrive", "status", "finalizado_em", "expira_em", "atualizado_em"])

