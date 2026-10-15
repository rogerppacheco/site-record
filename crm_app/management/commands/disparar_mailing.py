"""Dispara (ou continua) o envio de templates de um lote de mailing.

Uso:
  python manage.py disparar_mailing --lote 1
  python manage.py disparar_mailing --lote 1 --tudo
  python manage.py disparar_mailing --ciclos  # processa todos os lotes DISPARANDO
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from crm_app.models import MailingLote
from crm_app.services import mailing_dispatch_service as dispatch


class Command(BaseCommand):
    help = 'Dispara templates Meta de um lote de mailing.'

    def add_arguments(self, parser):
        parser.add_argument('--lote', type=int, help='ID do MailingLote')
        parser.add_argument('--tudo', action='store_true', help='Processa até esvaziar a fila do lote')
        parser.add_argument('--ciclos', action='store_true', help='Um ciclo em cada lote DISPARANDO')
        parser.add_argument('--limite', type=int, default=40, help='Contatos por ciclo')

    def handle(self, *args, **options):
        if options['ciclos']:
            n = dispatch.processar_lotes_em_disparo()
            self.stdout.write(self.style.SUCCESS(f'{n} lote(s) processado(s).'))
            return

        lote_id = options.get('lote')
        if not lote_id:
            raise CommandError('Informe --lote ID ou --ciclos.')

        try:
            lote = dispatch.iniciar_disparo(lote_id)
        except MailingLote.DoesNotExist as exc:
            raise CommandError(str(exc)) from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f'Lote #{lote.pk} status={lote.status}')
        while True:
            stats = dispatch.processar_ciclo(lote_id, limite=options['limite'], sleep=True)
            self.stdout.write(f"  ciclo: +{stats['enviados']} ok, +{stats['falhas']} falha, restam {stats['restantes']}")
            if not options['tudo'] or stats['restantes'] == 0 or stats['status'] != MailingLote.STATUS_DISPARANDO:
                break
        lote.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f'Final: status={lote.status} enviados={lote.total_enviados} falhas={lote.total_falhas}'
        ))
