"""
Worker dedicado para automações Playwright/PAP (fila PostgreSQL).

Uso: python manage.py run_pap_worker
Railway: serviço site-record-pap com PAP_WORKER_MODE=true
"""
from __future__ import annotations

import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from crm_app.pap_job_fila import PapJobFila, reivindicar_proximo_job
from crm_app.services.pap_job_processor import processar_job


class Command(BaseCommand):
    help = "Processa fila de jobs PAP (Playwright) em processo dedicado."

    def handle(self, *args, **options):
        intervalo = float(getattr(settings, "PAP_WORKER_POLL_SECONDS", 2.0))
        self._running = True

        def _shutdown(signum=None, frame=None):
            self.stdout.write(self.style.WARNING(f"[PAP_WORKER] Sinal {signum} — encerrando..."))
            self._running = False

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        self.stdout.write(self.style.SUCCESS(
            f"[PAP_WORKER] Iniciado (poll={intervalo}s). PAP_WORKER_MODE={getattr(settings, 'PAP_WORKER_MODE', False)}"
        ))

        while self._running:
            job = reivindicar_proximo_job()
            if job:
                processar_job(job)
                continue
            time.sleep(intervalo)

        self.stdout.write(self.style.SUCCESS("[PAP_WORKER] Encerrado."))
