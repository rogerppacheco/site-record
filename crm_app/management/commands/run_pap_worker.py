"""
Worker dedicado para automações Playwright/PAP (fila PostgreSQL).

Uso: python manage.py run_pap_worker
Railway: serviço site-record-pap com PAP_WORKER_MODE=true
"""
from __future__ import annotations

import logging
import signal
import threading
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from crm_app.pap_job_fila import PapJobFila, recuperar_jobs_pap_travados, reivindicar_proximo_job
from crm_app.services.pap_job_processor import processar_job

logger = logging.getLogger(__name__)


def _timeout_job_segundos(tipo: str) -> int:
    defaults = {
        "status_online": 240,
        "consulta_pedido": 240,
        "analise_credito": 360,
    }
    base = int(getattr(settings, "PAP_JOB_TIMEOUT_SECONDS", 0) or 0)
    if base > 0:
        return base
    return defaults.get(tipo, 300)


class Command(BaseCommand):
    help = "Processa fila de jobs PAP (Playwright) em processo dedicado."

    def handle(self, *args, **options):
        intervalo = float(getattr(settings, "PAP_WORKER_POLL_SECONDS", 2.0))
        self._running = True
        ciclos_sem_job = 0

        def _shutdown(signum=None, frame=None):
            self.stdout.write(self.style.WARNING(f"[PAP_WORKER] Sinal {signum} — encerrando..."))
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        stats = recuperar_jobs_pap_travados()
        self.stdout.write(self.style.SUCCESS(
            f"[PAP_WORKER] Iniciado (poll={intervalo}s). "
            f"PAP_WORKER_MODE={getattr(settings, 'PAP_WORKER_MODE', False)} "
            f"recuperacao={stats}"
        ))

        while self._running:
            # A cada ~30s sem job (ou sempre antes de reivindicar periodicamente)
            if ciclos_sem_job == 0 or ciclos_sem_job % 15 == 0:
                recuperar_jobs_pap_travados()

            job = reivindicar_proximo_job()
            if not job:
                ciclos_sem_job += 1
                time.sleep(intervalo)
                continue

            ciclos_sem_job = 0
            timeout_seg = _timeout_job_segundos(job.tipo)
            self.stdout.write(
                f"[PAP_WORKER] Job {job.id} tipo={job.tipo} timeout={timeout_seg}s"
            )
            travou = self._processar_com_timeout(job, timeout_seg)
            if travou:
                # Playwright pode ter deixado o processo inconsistente — Railway reinicia.
                self.stdout.write(self.style.ERROR(
                    f"[PAP_WORKER] Job {job.id} excedeu {timeout_seg}s — encerrando worker para limpar Playwright."
                ))
                raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("[PAP_WORKER] Encerrado."))

    def _processar_com_timeout(self, job: PapJobFila, timeout_seg: int) -> bool:
        """
        Executa o job em thread. Se estourar o timeout, marca erro e retorna True (travou).
        """
        resultado: dict = {"done": False, "exc": None}

        def _runner() -> None:
            try:
                processar_job(job)
            except Exception as exc:
                resultado["exc"] = exc
                logger.exception("[PAP_WORKER] Exceção no job %s: %s", job.id, exc)
            finally:
                resultado["done"] = True

        t = threading.Thread(target=_runner, name=f"pap-job-{job.id}", daemon=True)
        t.start()
        t.join(timeout=max(30, timeout_seg))

        if resultado["done"]:
            return False

        # Timeout: marca job como erro (não reprocessa — provavelmente Playwright zumbi).
        try:
            PapJobFila.objects.filter(pk=job.id, status=PapJobFila.STATUS_PROCESSANDO).update(
                status=PapJobFila.STATUS_ERRO,
                concluido_em=timezone.now(),
                erro=(
                    f"Job abandonado: timeout de {timeout_seg}s no worker PAP "
                    f"(tipo={job.tipo})."
                )[:4000],
            )
        except Exception:
            logger.exception("[PAP_WORKER] Falha ao marcar timeout do job %s", job.id)

        # Libera BO se o job travou com lock (timeout do pool = 30 min; aqui antecipamos).
        try:
            from crm_app.pool_bo_pap import limpar_sessoes_expiradas
            limpar_sessoes_expiradas()
        except Exception:
            pass

        return True
