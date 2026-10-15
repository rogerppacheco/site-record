"""Rotina: busca no GED360 (Br Pronto) o relatório de biometrias dos últimos N meses.

Uso:
  python manage.py buscar_repescagem_bio_ged
  python manage.py buscar_repescagem_bio_ged --dias 183
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from crm_app.services import repescagem_bio_service as svc


class Command(BaseCommand):
    help = 'Busca no GED360 o relatório detalhado de digitalizações (Repescagem Bio).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias',
            type=int,
            default=svc.DIAS_ROTINA_BIO,
            help=f'Quantidade de dias para trás (padrão {svc.DIAS_ROTINA_BIO} ≈ 6 meses).',
        )
        parser.add_argument(
            '--aguardar',
            action='store_true',
            help='Espera a importação terminar (útil em testes; o scheduler não usa).',
        )

    def handle(self, *args, **options):
        dias = max(1, min(int(options['dias'] or svc.DIAS_ROTINA_BIO), svc.MAX_DIAS_PERIODO))
        fim = timezone.localdate()
        inicio = fim - timedelta(days=dias - 1)
        self.stdout.write(f'[RepescagemBio] Buscando GED de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} ({dias} dias)…')
        importacao, criada = svc.iniciar_importacao(None, inicio, fim)
        if not criada:
            self.stdout.write(self.style.WARNING(
                f'Já havia importação #{importacao.pk} em andamento ({importacao.etapa or importacao.status}).'
            ))
            return
        self.stdout.write(self.style.SUCCESS(f'Importação #{importacao.pk} iniciada.'))
        if not options['aguardar']:
            return
        import time
        from crm_app.models import RepescagemBioImportacao as I
        while True:
            time.sleep(5)
            importacao.refresh_from_db()
            if importacao.status != I.STATUS_EM_ANDAMENTO:
                break
            self.stdout.write(f'  … {importacao.etapa or "processando"}')
        if importacao.status == I.STATUS_CONCLUIDO:
            self.stdout.write(self.style.SUCCESS(importacao.mensagem or 'Concluída.'))
        else:
            self.stdout.write(self.style.ERROR(importacao.mensagem or importacao.status))
