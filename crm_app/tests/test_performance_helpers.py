from django.test import SimpleTestCase

from crm_app.performance_helpers import (
    cores_linha_performance,
    ordenar_lista_performance,
    ordem_cluster_performance,
)


class PerformanceHelpersTests(SimpleTestCase):
    def test_ordem_cluster(self):
        self.assertEqual(ordem_cluster_performance('CLUSTER_1'), 1)
        self.assertEqual(ordem_cluster_performance('CLUSTER_2'), 2)
        self.assertEqual(ordem_cluster_performance('CLUSTER_3'), 3)
        self.assertEqual(ordem_cluster_performance(''), 99)

    def test_cores_faixas(self):
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
