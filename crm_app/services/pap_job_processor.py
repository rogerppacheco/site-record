"""
Processamento de jobs da fila PAP (serviço dedicado).
"""
from __future__ import annotations

import logging
import traceback

from django.utils import timezone

from crm_app.pap_job_fila import PapJobFila

logger = logging.getLogger(__name__)


def _executar_handler(job: PapJobFila) -> None:
    from crm_app.whatsapp_webhook_handler import (
        _executar_analise_credito_background,
        _executar_consulta_pedido_background,
        _executar_consulta_status_online_background,
    )

    handlers = {
        "status_online": lambda p: _executar_consulta_status_online_background(
            p["telefone"],
            p["cpf"],
            p.get("os_filtro"),
            p.get("run_id"),
        ),
        "analise_credito": lambda p: _executar_analise_credito_background(
            p["telefone"],
            p["usuario_id"],
            p["documento"],
            p.get("cpf_representante"),
        ),
        "consulta_pedido": lambda p: _executar_consulta_pedido_background(
            p["telefone"],
            p["usuario_id"],
            p["cpf"],
        ),
    }
    handler = handlers.get(job.tipo)
    if not handler:
        raise ValueError(f"Tipo de job PAP desconhecido: {job.tipo}")
    handler(job.payload or {})


def processar_job(job: PapJobFila) -> bool:
    """Executa um job e atualiza status. Retorna True se concluído."""
    import django.db

    django.db.close_old_connections()
    try:
        logger.info("[PAP_WORKER] Processando job %s tipo=%s", job.id, job.tipo)
        _executar_handler(job)
        job.status = PapJobFila.STATUS_CONCLUIDO
        job.concluido_em = timezone.now()
        job.erro = ""
        job.save(update_fields=["status", "concluido_em", "erro"])
        return True
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("[PAP_WORKER] Erro job %s: %s", job.id, exc)
        if job.tentativas < job.max_tentativas:
            job.status = PapJobFila.STATUS_PENDENTE
            job.erro = f"{exc}\n{tb}"[:4000]
            job.save(update_fields=["status", "erro"])
            return False
        job.status = PapJobFila.STATUS_ERRO
        job.concluido_em = timezone.now()
        job.erro = f"{exc}\n{tb}"[:4000]
        job.save(update_fields=["status", "concluido_em", "erro"])
        return False
    finally:
        django.db.close_old_connections()
