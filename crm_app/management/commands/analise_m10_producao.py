"""
Análise M-10 para produção: diagnostica por que uma safra tem menos registros que o esperado.

Uso (rodar no ambiente de produção, ex. Railway):
  python manage.py analise_m10_producao 2025-07
  python manage.py analise_m10_producao 2025-07 --json
  python manage.py analise_m10_producao 2025-07 --amostra 50

Ex.: Julho/2025 deveria ter 895 e mostra 14. O comando lista:
- Total vendas com data_instalacao no mês (qualquer status)
- Por status (INSTALADA vs outros)
- INSTALADA + data_instalacao: com/sem O.S.
- ContratoM10 no mês (por data_instalacao, igual ao dashboard)
- Faltando no M-10 e amostra (ids, OS, status).
"""
from __future__ import print_function

import json
from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q, Count
from dateutil.relativedelta import relativedelta

from crm_app.models import Venda, ContratoM10, SafraM10, StatusCRM


def parse_month(s):
    year, month = int(s[:4]), int(s[5:7])
    d0 = date(year, month, 1)
    d1 = d0 + relativedelta(months=1)
    return d0, d1


class Command(BaseCommand):
    help = 'Analisa vendas vs M-10 por safra (para produção)'

    def add_arguments(self, parser):
        parser.add_argument('mes', help='Mês YYYY-MM (ex: 2025-07)')
        parser.add_argument('--json', action='store_true', help='Saída JSON')
        parser.add_argument('--amostra', type=int, default=30, help='Quantos "faltando" listar (default 30)')

    def handle(self, *args, **options):
        mes = options.get('mes')
        if not mes or len(mes) != 7 or mes[4] != '-':
            self.stdout.write(self.style.ERROR('Use: python manage.py analise_m10_producao YYYY-MM'))
            return

        inicio, fim = parse_month(mes)
        base = Venda.objects.filter(ativo=True)
        status_instalada = StatusCRM.objects.filter(tipo='Esteira', nome__iexact='INSTALADA').first()
        if not status_instalada:
            self.stdout.write(self.style.ERROR('Status INSTALADA não encontrado.'))
            return

        q_mes = Q(data_instalacao__gte=inicio, data_instalacao__lt=fim)

        # 1) Vendas com data_instalacao no mês (qualquer status)
        vendas_mes = base.filter(data_instalacao__gte=inicio, data_instalacao__lt=fim)
        total_mes = vendas_mes.count()

        # 1b) Vendas com data_criacao no mês (qualquer status) - para comparar "895 vendas de julho"
        vendas_criacao_mes = base.filter(
            data_criacao__date__gte=inicio,
            data_criacao__date__lt=fim,
        )
        total_criacao_mes = vendas_criacao_mes.count()

        # 2) Por status
        por_status = list(
            vendas_mes.values('status_esteira__nome')
            .annotate(n=Count('id'))
            .order_by('-n')
        )
        status_map = {r['status_esteira__nome'] or '(sem status)': r['n'] for r in por_status}

        # 3) INSTALADA + data_instalacao no mês
        instaladas = base.filter(status_esteira=status_instalada).filter(q_mes)
        n_instaladas = instaladas.count()
        com_os = instaladas.exclude(ordem_servico__isnull=True).exclude(ordem_servico='').count()
        sem_os = n_instaladas - com_os

        # 4) ContratoM10 com data_instalacao no mês (igual dashboard)
        contratos = ContratoM10.objects.filter(
            data_instalacao__gte=inicio,
            data_instalacao__lt=fim,
        )
        n_contratos = contratos.count()
        os_com_contrato = set(contratos.exclude(ordem_servico__isnull=True).exclude(ordem_servico='').values_list('ordem_servico', flat=True))
        venda_ids_com_contrato = set(contratos.exclude(venda_id__isnull=True).values_list('venda_id', flat=True))

        # 5) Faltando: INSTALADA + data_instalacao no mês, sem ContratoM10
        faltando = []
        for v in instaladas.only('id', 'ordem_servico', 'data_criacao', 'data_instalacao', 'status_esteira'):
            if v.id in venda_ids_com_contrato:
                continue
            if not v.ordem_servico or not str(v.ordem_servico).strip():
                faltando.append({'id': v.id, 'os': None, 'motivo': 'sem O.S.'})
            elif v.ordem_servico not in os_com_contrato:
                faltando.append({'id': v.id, 'os': v.ordem_servico, 'motivo': 'sem contrato'})

        amostra_n = min(options.get('amostra', 30), len(faltando))
        amostra = faltando[:amostra_n]

        out = {
            'mes': mes,
            'data_inicio': str(inicio),
            'data_fim': str(fim),
            'vendas_data_instalacao_no_mes': total_mes,
            'vendas_data_criacao_no_mes': total_criacao_mes,
            'por_status': status_map,
            'instalada_data_instalacao_no_mes': n_instaladas,
            'instaladas_com_os': com_os,
            'instaladas_sem_os': sem_os,
            'contratos_m10_no_mes': n_contratos,
            'faltando_no_m10': len(faltando),
            'amostra_faltando': amostra,
        }

        if options.get('json'):
            self.stdout.write(json.dumps(out, indent=2, ensure_ascii=False))
            return

        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write(self.style.SUCCESS('ANALISE M-10 PRODUCAO - {}'.format(mes)))
        self.stdout.write('=' * 70)
        self.stdout.write('Vendas com data_instalacao no mes (qualquer status): {}'.format(total_mes))
        self.stdout.write('Vendas com data_criacao no mes (qualquer status): {}'.format(total_criacao_mes))
        self.stdout.write('Por status (data_instalacao no mes): {}'.format(status_map))
        self.stdout.write('')
        self.stdout.write('INSTALADA + data_instalacao no mes: {}'.format(n_instaladas))
        self.stdout.write('  Com O.S.: {} | Sem O.S.: {}'.format(com_os, sem_os))
        self.stdout.write('')
        self.stdout.write('ContratoM10 no mes (data_instalacao): {}'.format(n_contratos))
        self.stdout.write('')
        self.stdout.write('Faltando no M-10 (instaladas sem contrato): {}'.format(len(faltando)))
        for i, f in enumerate(amostra, 1):
            self.stdout.write('  {}  id={} os={} -> {}'.format(i, f['id'], f['os'] or '-', f['motivo']))
        if len(faltando) > amostra_n:
            self.stdout.write('  ... e mais {}'.format(len(faltando) - amostra_n))
        self.stdout.write('')
        self.stdout.write('=' * 70)
        self.stdout.write('')
        if total_mes > 0 and n_instaladas < total_mes:
            self.stdout.write(self.style.WARNING(
                'Muitas vendas no mes tem status diferente de INSTALADA. '
                'M-10 so considera INSTALADA.'
            ))
        if total_criacao_mes > 0 and total_mes < total_criacao_mes:
            self.stdout.write(self.style.WARNING(
                'Ha mais vendas por data_criacao que por data_instalacao. '
                'M-10 usa data_instalacao. Corrija com corrigir_data_venda_legado --atualizar-instalacao se for o caso.'
            ))
        if len(faltando) > 0:
            self.stdout.write(self.style.WARNING(
                'Rode "Popular safra" no Bonus M-10 ou: python manage.py reprocessar_vendas_m10.'
            ))
