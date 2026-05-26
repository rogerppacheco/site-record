from datetime import date, timedelta

from django.test import SimpleTestCase

from crm_app.performance_helpers import (
    cores_linha_performance,
    cores_linha_semanal,
    dias_decorridos_semana,
    indice_faixa_comissao,
    media_diaria_semana_referencia,
    ordenar_lista_performance,
    ordem_cluster_performance,
)


class _RegraStub:
    def __init__(self, pk, perfil=None, vendedor_id=None, min_v=0, max_v=99999):
        self.pk = pk
        self.id = pk
        self.perfil = perfil
        self.vendedor_id = vendedor_id
        self.min_vendas = min_v
        self.max_vendas = max_v


class PerformanceHelpersTests(SimpleTestCase):
    def test_ordem_cluster(self):
        self.assertEqual(ordem_cluster_performance('CLUSTER_1'), 1)
        self.assertEqual(ordem_cluster_performance('CLUSTER_2'), 2)
        self.assertEqual(ordem_cluster_performance('CLUSTER_3'), 3)
        self.assertEqual(ordem_cluster_performance(''), 99)

    def test_cores_faixas_hoje(self):
        self.assertEqual(cores_linha_performance(0)[0], (248, 215, 218))
        self.assertEqual(cores_linha_performance(2)[0], (255, 243, 205))
        self.assertEqual(cores_linha_performance(5)[0], (207, 226, 255))
        self.assertEqual(cores_linha_performance(6)[0], (20, 108, 67))

    def test_ordenacao_cluster_nome(self):
        lista = [
            {'nome': 'ZARA', 'cluster': 'CLUSTER_3'},
            {'nome': 'ANA', 'cluster': 'CLUSTER_1'},
            {'nome': 'BOB', 'cluster': 'CLUSTER_2'},
        ]
        ordenada = ordenar_lista_performance(lista)
        self.assertEqual([x['nome'] for x in ordenada], ['ANA', 'BOB', 'ZARA'])

    def test_dias_decorridos_semana(self):
        seg = date(2026, 5, 25)
        sab = seg + timedelta(days=5)
        self.assertEqual(dias_decorridos_semana(seg, sab, seg), 1)
        self.assertEqual(dias_decorridos_semana(seg, sab, seg + timedelta(days=2)), 3)
        self.assertEqual(dias_decorridos_semana(seg, sab, sab + timedelta(days=1)), 6)

    def test_media_semanal_cores(self):
        self.assertEqual(media_diaria_semana_referencia(14, 3), 5)
        self.assertEqual(cores_linha_semanal(14, 3)[0], cores_linha_performance(5)[0])

    def test_indice_faixa_vendedor(self):
        ctx = {
            'regras_perfil': [
                _RegraStub(1, perfil='Vendedor', min_v=1, max_v=20),
                _RegraStub(2, perfil='Vendedor', min_v=21, max_v=39),
                _RegraStub(3, perfil='Vendedor', min_v=51, max_v=99999),
            ],
            'regras_vendedor': {},
        }
        self.assertEqual(indice_faixa_comissao(ctx, 99, 'Vendedor', 0), -1)
        self.assertEqual(indice_faixa_comissao(ctx, 99, 'Vendedor', 10), 0)
        self.assertEqual(indice_faixa_comissao(ctx, 99, 'Vendedor', 25), 1)
        self.assertEqual(indice_faixa_comissao(ctx, 99, 'Vendedor', 60), 2)
