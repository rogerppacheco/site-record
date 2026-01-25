"""
Consulta quantas vendas INSTALADA aparecem no CRM para cada mês que existe no sistema.

Regra CRM: status INSTALADA e (data_criacao no mês OU data_instalacao no mês).
Também exibe instaladas só por data_instalacao no mês (estilo M-10) para comparação.

Uso (produção):
  python manage.py contar_instaladas_por_mes
  python manage.py contar_instaladas_por_mes --json
  python manage.py contar_instaladas_por_mes --inicio 2025-01 --fim 2026-12
"""
from __future__ import print_function

import json
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q, Count
from django.db.models.functions import TruncMonth
from dateutil.relativedelta import relativedelta

from crm_app.models import Venda, StatusCRM


def parse_month(s):
    """YYYY-MM -> (date inicio, date fim)"""
    y, m = int(s[:4]), int(s[5:7])
    d0 = date(y, m, 1)
    d1 = d0 + relativedelta(months=1)
    return d0, d1


class Command(BaseCommand):
    help = 'Conta vendas INSTALADA por mês (como no CRM) para cada mês existente no sistema'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Saída JSON')
        parser.add_argument('--inicio', default=None, help='Mês inicial YYYY-MM (opcional)')
        parser.add_argument('--fim', default=None, help='Mês final YYYY-MM (opcional)')

    def handle(self, *args, **options):
        status_instalada = StatusCRM.objects.filter(tipo='Esteira', nome__iexact='INSTALADA').first()
        if not status_instalada:
            self.stdout.write(self.style.ERROR('Status INSTALADA não encontrado.'))
            return

        base = Venda.objects.filter(ativo=True, status_esteira=status_instalada)

        def _month_date(m):
            if hasattr(m, 'date') and callable(getattr(m, 'date')):
                m = m.date()
            return date(m.year, m.month, 1)

        # Meses que existem: union de (data_criacao) e (data_instalacao)
        meses_data_criacao = set(
            base.exclude(data_criacao__isnull=True)
            .annotate(mes=TruncMonth('data_criacao'))
            .values_list('mes', flat=True)
            .distinct()
        )
        meses_data_inst = set(
            base.exclude(data_instalacao__isnull=True)
            .annotate(mes=TruncMonth('data_instalacao'))
            .values_list('mes', flat=True)
            .distinct()
        )
        todos_meses = sorted(set(_month_date(m) for m in (meses_data_criacao | meses_data_inst)))

        if not todos_meses:
            self.stdout.write('Nenhum mês encontrado com vendas INSTALADA.')
            return

        # Filtrar por --inicio / --fim se informados
        if options.get('inicio'):
            try:
                d_ini, _ = parse_month(options['inicio'])
                todos_meses = [m for m in todos_meses if m >= d_ini]
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR('--inicio inválido. Use YYYY-MM.'))
                return
        if options.get('fim'):
            try:
                _, d_fim = parse_month(options['fim'])
                todos_meses = [m for m in todos_meses if m < d_fim]
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR('--fim inválido. Use YYYY-MM.'))
                return

        if not todos_meses:
            self.stdout.write('Nenhum mês no intervalo informado.')
            return

        rows = []
        for mes_ref in todos_meses:
            inicio = mes_ref
            fim = inicio + relativedelta(months=1)

            # CRM: INSTALADA com (data_criacao no mês OU data_instalacao no mês)
            q_crm = (
                (Q(data_criacao__date__gte=inicio) & Q(data_criacao__date__lt=fim))
                | (Q(data_instalacao__gte=inicio) & Q(data_instalacao__lt=fim))
            )
            n_crm = base.filter(q_crm).count()

            # Só data_instalacao no mês (estilo M-10)
            n_inst = base.filter(
                data_instalacao__gte=inicio,
                data_instalacao__lt=fim,
            ).count()

            rows.append({
                'mes': inicio.strftime('%Y-%m'),
                'mes_label': inicio.strftime('%m/%Y'),
                'instaladas_crm': n_crm,
                'instaladas_data_instalacao': n_inst,
            })

        out = {
            'meses': rows,
            'total_meses': len(rows),
        }

        if options.get('json'):
            self.stdout.write(json.dumps(out, indent=2, ensure_ascii=False))
            return

        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write(self.style.SUCCESS('VENDAS INSTALADA POR MES (como no CRM)'))
        self.stdout.write('Regra CRM: status INSTALADA e (data_criacao OU data_instalacao) no mes.')
        self.stdout.write('')
        self.stdout.write('{:<10} {:>18} {:>22}'.format(
            'Mes', 'Instaladas (CRM)', 'Instaladas (dt_inst)'
        ))
        self.stdout.write('-' * 52)
        for r in rows:
            self.stdout.write('{:<10} {:>18} {:>22}'.format(
                r['mes_label'],
                r['instaladas_crm'],
                r['instaladas_data_instalacao'],
            ))
        self.stdout.write('-' * 52)
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('')
