"""Importa planilhas de mailing de um diretório.

Uso:
  python manage.py importar_mailings docs/mailings
  python manage.py importar_mailings C:\\caminho\\xls --dry-run
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from crm_app.models import MailingLote
from crm_app.services import mailing_import_service as import_svc

EXTENSOES = {'.xlsx', '.xls'}


class Command(BaseCommand):
    help = 'Importa XLS/XLSX de mailing a partir de uma pasta.'

    def add_arguments(self, parser):
        parser.add_argument('pasta', type=str, help='Diretório com as planilhas')
        parser.add_argument('--dry-run', action='store_true', help='Só lista os arquivos, sem gravar')

    def handle(self, *args, **options):
        pasta = Path(options['pasta']).expanduser()
        if not pasta.exists() or not pasta.is_dir():
            raise CommandError(f'Pasta não encontrada: {pasta}')

        arquivos = sorted(
            p for p in pasta.iterdir()
            if p.is_file() and p.suffix.lower() in EXTENSOES and not p.name.startswith('~$')
        )
        if not arquivos:
            raise CommandError(f'Nenhum XLS/XLSX em {pasta}')

        for path in arquivos:
            ja = MailingLote.objects.filter(arquivo_nome=path.name).first()
            if ja:
                self.stdout.write(f'Pula {path.name}: já importado como lote #{ja.pk}.')
                continue
            if options['dry_run']:
                self.stdout.write(f'Dry-run: {path.name}')
                continue
            with path.open('rb') as fh:
                lote = import_svc.importar_arquivo(
                    fh.read(),
                    nome_lote=path.stem,
                    arquivo_nome=path.name,
                )
            self.stdout.write(self.style.SUCCESS(
                f'Lote #{lote.pk} {lote.nome}: {lote.total_validos} válidos / {lote.total_contatos} contatos'
            ))
