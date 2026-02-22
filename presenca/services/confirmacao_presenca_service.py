"""
Serviço de confirmação de presença do dia (selfie): upload OneDrive, registro
no banco e envio da imagem por WhatsApp para a Diretoria.

Centraliza a regra de negócio: um supervisor/diretoria confirma o dia com uma
foto; a foto é armazenada no OneDrive por pasta (Presenca_Selfies/YYYY-MM-DD)
e opcionalmente enviada em silêncio para os diretores com WhatsApp cadastrado.
"""
from __future__ import annotations

import base64
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from django.conf import settings as django_settings

from presenca.models import ConfirmacaoPresencaDia
from usuarios.models import Usuario

logger = logging.getLogger(__name__)


class ConfirmacaoPresencaServiceError(Exception):
    """Erro no serviço de confirmação (ex.: falha no upload OneDrive)."""

    pass


def usuario_pode_confirmar_presenca(user: Any) -> bool:
    """
    Retorna True se o usuário pode registrar confirmação de presença (selfie):
    superuser, grupos Diretoria/Admin/BackOffice ou supervisor (tem liderados).
    """
    if getattr(user, "is_superuser", False):
        return True
    if user.groups.filter(name__in=["Diretoria", "Admin", "BackOffice"]).exists():
        return True
    if hasattr(user, "liderados") and user.liderados.exists():
        return True
    return False


def obter_confirmacao_dia(
    data_dia: date, user: Any
) -> dict[str, Any]:
    """
    Retorna o payload para o GET: se o usuário é Diretoria/Admin/BackOffice
    vê todas as confirmações do dia; caso contrário apenas as do próprio supervisor.
    """
    from presenca.models import ConfirmacaoPresencaDia
    from presenca.serializers import ConfirmacaoPresencaDiaSerializer

    qs = ConfirmacaoPresencaDia.objects.filter(data=data_dia)
    if not (
        user.is_superuser
        or user.groups.filter(name__in=["Diretoria", "Admin", "BackOffice"]).exists()
    ):
        qs = qs.filter(supervisor=user)
    conf = qs.first()
    if not conf:
        return {"confirmado": False, "detalhe": None}
    return {
        "confirmado": True,
        "detalhe": ConfirmacaoPresencaDiaSerializer(conf).data,
    }


def _normalizar_coordenada(
    valor: Any,
) -> Optional[Decimal]:
    """Converte valor de latitude/longitude para Decimal ou None."""
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor).strip())
    except (TypeError, ValueError):
        return None


def registrar_selfie(
    usuario: Any,
    data_dia: date,
    foto_bytes: bytes,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> tuple[ConfirmacaoPresencaDia, bool]:
    """
    Faz upload da foto para o OneDrive, persiste o registro de confirmação e
    envia a imagem por WhatsApp para os usuários do grupo Diretoria (opcional).

    Returns:
        Tupla (instância ConfirmacaoPresencaDia, created: bool).
    """
    from presenca.models import ConfirmacaoPresencaDia

    now_dt = datetime.now()
    nome_arquivo = f"equipe_{getattr(usuario, 'username', 'user')}_{data_dia}_{now_dt.strftime('%H-%M')}.jpg"
    pasta_base = getattr(
        django_settings, "PRESENCA_ONEDRIVE_FOLDER", "Presenca_Selfies"
    )
    folder_name = f"{pasta_base}/{data_dia}"

    foto_io = io.BytesIO(foto_bytes)
    try:
        from crm_app.onedrive_service import OneDriveUploader

        uploader = OneDriveUploader()
        foto_url = uploader.upload_file(foto_io, folder_name, nome_arquivo)
    except Exception as e:
        logger.exception("Upload OneDrive selfie: %s", e)
        raise ConfirmacaoPresencaServiceError(f"Erro ao enviar foto para o OneDrive: {e}") from e

    lat_dec = _normalizar_coordenada(latitude) if latitude is not None else None
    lng_dec = _normalizar_coordenada(longitude) if longitude is not None else None

    conf, created = ConfirmacaoPresencaDia.objects.update_or_create(
        data=data_dia,
        supervisor=usuario,
        defaults={
            "foto_url": foto_url,
            "latitude": lat_dec,
            "longitude": lng_dec,
        },
    )

    diretores = Usuario.objects.filter(
        groups__name="Diretoria",
        is_active=True,
    ).exclude(tel_whatsapp__isnull=True).exclude(tel_whatsapp="").distinct()

    if diretores.exists():
        try:
            from crm_app.whatsapp_service import WhatsAppService

            svc = WhatsAppService()
            data_fmt = data_dia.strftime("%d/%m/%Y")
            caption = f"Presença do dia {data_fmt} - supervisor: {getattr(usuario, 'username', '')}"
            img_b64 = base64.b64encode(foto_bytes).decode("utf-8")
            for d in diretores:
                try:
                    tel = (d.tel_whatsapp or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                    if tel:
                        svc.enviar_imagem_b64(tel, img_b64, caption=caption)
                except Exception as e:
                    logger.debug("WhatsApp diretor %s: %s", d.username, e)
        except Exception as e:
            logger.warning("Envio WhatsApp Diretoria: %s", e)

    return conf, created


def excluir_confirmacao_dia(data_dia: date) -> int:
    """
    Remove todas as confirmações (selfies) do dia. Usado pelo DELETE da API.
    Retorna o número de registros excluídos.
    """
    from presenca.models import ConfirmacaoPresencaDia

    deleted, _ = ConfirmacaoPresencaDia.objects.filter(data=data_dia).delete()
    return deleted
