"""
Fila de jobs PAP em PostgreSQL — isola Playwright do serviço web sem Redis.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class PapJobFila(models.Model):
    STATUS_PENDENTE = "pendente"
    STATUS_PROCESSANDO = "processando"
    STATUS_CONCLUIDO = "concluido"
    STATUS_ERRO = "erro"

    STATUS_CHOICES = [
        (STATUS_PENDENTE, "Pendente"),
        (STATUS_PROCESSANDO, "Processando"),
        (STATUS_CONCLUIDO, "Concluído"),
        (STATUS_ERRO, "Erro"),
    ]

    tipo = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDENTE,
        db_index=True,
    )
    prioridade = models.SmallIntegerField(default=5, db_index=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    max_tentativas = models.PositiveSmallIntegerField(default=2)
    erro = models.TextField(blank=True, default="")
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    concluido_em = models.DateTimeField(null=True, blank=True)
    telefone = models.CharField(max_length=32, blank=True, default="", db_index=True)

    class Meta:
        db_table = "crm_pap_job_fila"
        ordering = ["prioridade", "criado_em"]
        indexes = [
            models.Index(fields=["status", "prioridade", "criado_em"]),
        ]

    def __str__(self) -> str:
        return f"PapJobFila({self.id}, {self.tipo}, {self.status})"


def enfileirar_job_pap(
    tipo: str,
    payload: dict[str, Any],
    *,
    telefone: str = "",
    prioridade: int = 5,
) -> PapJobFila:
    job = PapJobFila.objects.create(
        tipo=tipo,
        payload=payload,
        telefone=telefone or "",
        prioridade=prioridade,
    )
    logger.info("[PAP_FILA] Job %s enfileirado tipo=%s telefone=%s", job.id, tipo, telefone)
    return job


def reivindicar_proximo_job() -> PapJobFila | None:
    """Claim atômico do próximo job pendente (SELECT FOR UPDATE SKIP LOCKED)."""
    with transaction.atomic():
        job = (
            PapJobFila.objects.select_for_update(skip_locked=True)
            .filter(status=PapJobFila.STATUS_PENDENTE)
            .order_by("prioridade", "criado_em")
            .first()
        )
        if not job:
            return None
        job.status = PapJobFila.STATUS_PROCESSANDO
        job.iniciado_em = timezone.now()
        job.tentativas = (job.tentativas or 0) + 1
        job.save(update_fields=["status", "iniciado_em", "tentativas"])
        return job
