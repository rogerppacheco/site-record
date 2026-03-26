import io
import logging
import re
from typing import Any, Dict, List, Optional

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
from crm_app.sonax_voice_service import SonaxVoiceService, unpack_recording_zip
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


def _auditoria_grupos():
    return ["Diretoria", "Admin", "BackOffice", "Supervisor", "Auditoria", "Qualidade"]


def _resolved_voice_provider() -> str:
    p = getattr(settings, "AUDITORIA_VOICE_PROVIDER", "auto").strip().lower()
    if p == "sonax":
        return "sonax"
    if p == "zenvia":
        return "zenvia"
    if getattr(settings, "SONAX_CLICK2CALL_TOKEN", ""):
        return "sonax"
    return "zenvia"


def _sonax_ramais_permitidos() -> List[str]:
    raw = getattr(settings, "SONAX_RAMAIS", "101,102,103")
    return [x.strip() for x in str(raw).split(",") if x.strip()]


def _merge_webhook_payload(request: HttpRequest) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    try:
        for key in request.query_params:
            merged[str(key)] = request.query_params.get(key)
    except Exception:
        pass
    try:
        body = getattr(request, "data", None)
    except Exception:
        body = None
    if isinstance(body, dict):
        for k, v in body.items():
            merged[str(k)] = v
    return merged


def _webhook_call_id(payload: Dict[str, Any]) -> Optional[str]:
    for key in (
        "id_chamada",
        "ID_CHAMADA",
        "id",
        "chamada_id",
        "call_id",
        "protocolo",
    ):
        val = payload.get(key)
        if val not in (None, ""):
            return str(val).strip()
    return None


def _webhook_recording_url(payload: Dict[str, Any]) -> Optional[str]:
    for key in (
        "link_gravacao",
        "url_gravacao",
        "gravacao_url",
        "link_gravação",
        "recording_url",
        "LINK_GRAVACAO",
        "gravacao",
    ):
        val = payload.get(key)
        if val and isinstance(val, str) and val.strip().lower().startswith(("http://", "https://")):
            return val.strip()
    return None


def _webhook_duracao(payload: Dict[str, Any]) -> int:
    raw = _extract_first(
        payload,
        ["duracao_segundos", "duracao", "DURACAO_CHAMADA", "duration", "Duracao"],
        default=0,
    )
    try:
        return int(float(raw or 0))
    except (TypeError, ValueError):
        return 0


def _webhook_status_raw(payload: Dict[str, Any]) -> str:
    return str(
        _extract_first(
            payload,
            ["status_chamada", "STATUS_CHAMADA", "status", "Status"],
            default="",
        )
        or ""
    ).strip()


def _finalizada_por_status(provedor: str, status_provedor: str) -> bool:
    sp = status_provedor.upper()
    if provedor == "SONAX":
        sl = status_provedor.lower()
        if sl in ("desligada", "encerrada", "finalizada", "atendida"):
            return True
        if "deslig" in sl:
            return True
        return False
    return sp in {"ATENDIDA", "FINALIZADA", "ENCERRADA"}


class AuditoriaLigacaoOpcoesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: HttpRequest):
        if not _is_member(request.user, _auditoria_grupos()):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)
        provider = _resolved_voice_provider()
        return Response(
            {
                "voice_provider": provider,
                "sonax_ramais": _sonax_ramais_permitidos() if provider == "sonax" else [],
            }
        )


class AuditoriaLigacaoStartView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: HttpRequest, venda_id: int):
        if not _is_member(request.user, _auditoria_grupos()):
            return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        venda = Venda.objects.filter(id=venda_id, ativo=True).first()
        if not venda:
            return Response({"detail": "Venda não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        destination = request.data.get("destination_number") or venda.telefone1 or venda.telefone2
        if not destination:
            return Response(
                {"detail": "Venda sem telefone de destino e destination_number não informado."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        destination = _normalize_phone(destination)

        provider = _resolved_voice_provider()
        try:
            if provider == "sonax":
                ligacao, provider_resp = self._iniciar_sonax(request, venda, destination)
            else:
                ligacao, provider_resp = self._iniciar_zenvia(request, venda, destination)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("Erro ao iniciar ligação (%s): %s", provider, exc)
            return Response(
                {"detail": f"Falha ao iniciar ligação: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "detail": "Ligação iniciada com sucesso.",
                "ligacao_id": ligacao.id,
                "provider_call_id": ligacao.provider_call_id,
                "provedor": ligacao.provedor,
                "warning": (
                    "Provedor não retornou ID da chamada (sem_id). "
                    "Verifique token/IP liberado/ramal e logs do backend."
                    if str(ligacao.provider_call_id).startswith("sem_id_")
                    else None
                ),
                "provider_response": provider_resp,
            },
            status=status.HTTP_201_CREATED,
        )

    def _iniciar_sonax(self, request, venda: Venda, destination: str):
        ramal = request.data.get("sip_extension") or request.data.get("ramal")
        if not ramal:
            raise ValueError("Informe o ramal SIP (campo sip_extension ou ramal).")
        ramal = str(ramal).strip()
        permitidos = _sonax_ramais_permitidos()
        if permitidos and ramal not in permitidos:
            raise ValueError(f"Ramal não permitido. Use um de: {', '.join(permitidos)}")

        sonax = SonaxVoiceService()
        var_tags = {
            "auditoria_venda": str(venda.id),
        }
        provider_resp = sonax.click_to_call(
            destination_digits=destination,
            ramal=ramal,
            var_tags=var_tags,
        )
        call_id = provider_resp.get("id_chamada")
        if not call_id:
            call_id = f"sem_id_{timezone.now().timestamp()}"
            logger.warning(
                "Auditoria Sonax sem id_chamada. venda_id=%s usuario=%s ramal=%s destino=%s debug=%s parsed=%s raw=%s",
                venda.id,
                getattr(request.user, "username", None),
                ramal,
                destination,
                provider_resp.get("debug"),
                provider_resp.get("parsed"),
                (provider_resp.get("raw_text") or "")[:500],
            )

        ligacao = AuditoriaLigacao.objects.create(
            venda=venda,
            auditor=request.user,
            provedor="SONAX",
            provider_call_id=str(call_id),
            numero_origem=ramal,
            numero_destino=destination,
            status="INICIADA",
            consentimento_declarado=bool(request.data.get("consentimento_declarado", True)),
            consentimento_observacao=request.data.get(
                "consentimento_observacao",
                "Cliente informado pelo auditor no início da chamada.",
            ),
            payload_inicio=dict(provider_resp) if isinstance(provider_resp, dict) else {"raw": str(provider_resp)},
        )
        return ligacao, provider_resp

    def _iniciar_zenvia(self, request, venda: Venda, destination: str):
        source = request.data.get("source_number") or getattr(settings, "ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER", "")
        if not source:
            raise ValueError(
                "Defina ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER ou envie source_number no payload."
            )
        source = _normalize_phone(source)
        tags = f"auditoria_venda_{venda.id}"

        service = ZenviaVoiceService()
        provider_resp = service.create_call(
            source_number=source,
            destination_number=destination,
            record_audio=True,
            tags=tags,
            bina=request.data.get("bina"),
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
        return ligacao, provider_resp


class AuditoriaLigacaoListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: HttpRequest, venda_id: int):
        if not _is_member(request.user, _auditoria_grupos()):
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

    def get(self, request: HttpRequest):
        return self._process(request)

    def post(self, request: HttpRequest):
        return self._process(request)

    def _process(self, request: HttpRequest):
        z_secret = (getattr(settings, "ZENVIA_VOICE_WEBHOOK_SECRET", "") or "").strip()
        s_secret = (getattr(settings, "SONAX_WEBHOOK_SECRET", "") or "").strip()
        configured = [s for s in (z_secret, s_secret) if s]
        received = (request.headers.get("X-Webhook-Secret") or request.query_params.get("secret") or "").strip()
        if configured:
            if received not in configured:
                return Response({"detail": "Webhook não autorizado."}, status=status.HTTP_401_UNAUTHORIZED)

        payload = _merge_webhook_payload(request)
        call_id = _webhook_call_id(payload)
        if not call_id:
            return Response({"detail": "call_id / id_chamada não encontrado no webhook."}, status=status.HTTP_400_BAD_REQUEST)

        ligacao = AuditoriaLigacao.objects.filter(provider_call_id=str(call_id)).order_by("-id").first()
        if not ligacao:
            return Response({"detail": "Ligação não encontrada."}, status=status.HTTP_404_NOT_FOUND)

        status_provedor = _webhook_status_raw(payload)
        finalizada = _finalizada_por_status(ligacao.provedor, status_provedor)
        if not status_provedor and _webhook_recording_url(payload):
            finalizada = True
        duracao = _webhook_duracao(payload)
        recording_url = _webhook_recording_url(payload)

        status_interno = "FINALIZADA" if finalizada else "PROCESSANDO"

        with transaction.atomic():
            ligacao.payload_webhook = payload
            ligacao.status = status_interno
            ligacao.finalizado_em = timezone.now()
            ligacao.duracao_segundos = duracao
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
        elif ligacao.provedor == "SONAX" and finalizada:
            try:
                _try_sonax_download_and_archive(ligacao)
            except Exception as exc:
                logger.exception("Falha ao baixar gravação Sonax (pega_gravacao): %s", exc)

        return Response({"detail": "Webhook processado."}, status=status.HTTP_200_OK)


def _upload_bytes_to_onedrive(ligacao: AuditoriaLigacao, data: bytes, extension: str) -> None:
    filename = f"venda_{ligacao.venda_id}_ligacao_{ligacao.id}{extension}"
    folder_name = f"{getattr(settings, 'AUDITORIA_ONEDRIVE_FOLDER', 'Auditoria_Ligacoes')}/{timezone.localdate().isoformat()}"
    file_obj = io.BytesIO(data)
    file_obj.seek(0)
    uploader = OneDriveUploader()
    web_url = uploader.upload_file(file_obj=file_obj, folder_name=folder_name, filename=filename)

    ligacao.link_gravacao_onedrive = web_url
    ligacao.status = "ARQUIVADA"
    if not ligacao.finalizado_em:
        ligacao.finalizado_em = timezone.now()
    ligacao.save(update_fields=["link_gravacao_onedrive", "status", "finalizado_em", "atualizado_em"])


def _sync_recording_to_onedrive(ligacao: AuditoriaLigacao) -> None:
    url = ligacao.link_gravacao_provedor
    if not url or ligacao.link_gravacao_onedrive:
        return

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    extension = ".mp3"
    if "wav" in content_type:
        extension = ".wav"
    elif "ogg" in content_type:
        extension = ".ogg"

    if response.content[:2] == b"PK":
        content, extension = unpack_recording_zip(response.content)
        _upload_bytes_to_onedrive(ligacao, content, extension)
        return

    _upload_bytes_to_onedrive(ligacao, response.content, extension)


def _try_sonax_download_and_archive(ligacao: AuditoriaLigacao) -> None:
    if ligacao.link_gravacao_onedrive or ligacao.provedor != "SONAX":
        return
    cid = str(ligacao.provider_call_id or "")
    if not cid or cid.startswith("sem_id_"):
        return
    svc = SonaxVoiceService()
    if not svc.is_recording_download_configured:
        logger.warning("Sonax pega_gravacao: credenciais id_cliente/token não configuradas.")
        return
    content, ext = svc.download_recording(cid)
    _upload_bytes_to_onedrive(ligacao, content, ext)
