"""API Repescagem Bio — filtro ?rep= / ?repescavel= antes da paginação."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from crm_app.repescagem_bio_api import (
    RepescagemBioListaView,
    filtrar_base_repescavel,
    normalizar_filtro_repescavel,
)


def _linha(cpf, nome, repescavel, situacao='APTO'):
    return {
        'cpf': cpf,
        'situacao': situacao,
        'repescavel': repescavel,
        'motivo_repescagem': 'ok' if repescavel else 'Venda com O.S. 1',
        'status_tratamento': '',
        'vinculo': '',
        'nome_cliente': nome,
        'venda_id': None if repescavel else 1,
        'data_venda': None,
        'ordem_servico': '' if repescavel else '1',
        'status_esteira': '',
        'vendedor': '',
        'telefone': '',
        'ultimo_resultado': '',
        'ultimo_envio': None,
        'ultima_origem': '',
        'protocolo': '',
        'login_ged': '',
        'qtd_envios': 1,
    }


BASE = [
    _linha('1', 'SIM_A', True),
    _linha('2', 'NAO_A', False),
    _linha('3', 'SIM_B', True),
    _linha('4', 'NAO_B', False),
    _linha('5', 'NAO_C', False),
]


class NormalizarFiltroRepescavelTests(SimpleTestCase):
    def test_rep_e_repescavel(self):
        self.assertEqual(normalizar_filtro_repescavel({'rep': 'SIM'}), 'SIM')
        self.assertEqual(normalizar_filtro_repescavel({'repescavel': 'NAO'}), 'NAO')
        self.assertEqual(normalizar_filtro_repescavel({'repescavel': 'sim'}), 'SIM')
        self.assertEqual(normalizar_filtro_repescavel({'rep': 'true'}), 'SIM')
        self.assertEqual(normalizar_filtro_repescavel({'rep': '0'}), 'NAO')
        self.assertEqual(normalizar_filtro_repescavel({}), '')

    def test_repescavel_tem_prioridade_sobre_rep(self):
        self.assertEqual(normalizar_filtro_repescavel({'rep': 'NAO', 'repescavel': 'SIM'}), 'SIM')


class FiltrarBaseRepescavelTests(SimpleTestCase):
    def test_sim_e_nao(self):
        self.assertEqual(
            [b['nome_cliente'] for b in filtrar_base_repescavel(BASE, 'SIM')],
            ['SIM_A', 'SIM_B'],
        )
        self.assertEqual(
            [b['nome_cliente'] for b in filtrar_base_repescavel(BASE, 'NAO')],
            ['NAO_A', 'NAO_B', 'NAO_C'],
        )
        self.assertEqual(len(filtrar_base_repescavel(BASE, '')), 5)

    def test_boolean_em_string_nao_conta_como_sim(self):
        # Garante comparação por bool(), não por truthiness de string "NAO".
        mista = [{**BASE[0], 'repescavel': True}, {**BASE[1], 'repescavel': False}]
        self.assertEqual(len(filtrar_base_repescavel(mista, 'SIM')), 1)


class RepescagemBioListaFiltroTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = RepescagemBioListaView.as_view()
        self.user = get_user_model()(username='bio-teste', is_superuser=True)

    def _get(self, **params):
        with patch('crm_app.repescagem_bio_api.svc.montar_base', return_value=[dict(b) for b in BASE]), \
             patch('crm_app.repescagem_bio_api.svc.cobertura_ged', return_value=[]), \
             patch('crm_app.repescagem_bio_api.RepescagemBioImportacao.objects') as objs, \
             patch('crm_app.repescagem_bio_api.is_member', return_value=True):
            objs.filter.return_value.first.return_value = None
            req = self.factory.get('/api/crm/repescagem-bio/', {
                'de': '2026-10-01', 'ate': '2026-10-15', **params,
            })
            force_authenticate(req, user=self.user)
            return self.view(req)

    def test_rep_sim_nao_mostra_nao_repescaveis(self):
        resp = self._get(rep='SIM')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['filtro_repescavel'], 'SIM')
        self.assertEqual(resp.data['contagens_repescavel'], {'SIM': 2, 'NAO': 3})
        self.assertEqual(resp.data['paginacao']['total'], 2)
        nomes = [x['nome_cliente'] for x in resp.data['lista']]
        self.assertEqual(nomes, ['SIM_A', 'SIM_B'])
        self.assertTrue(all(x['repescavel'] for x in resp.data['lista']))

    def test_repescavel_nao(self):
        resp = self._get(repescavel='NAO')
        self.assertEqual(resp.data['filtro_repescavel'], 'NAO')
        self.assertEqual(resp.data['paginacao']['total'], 3)
        self.assertTrue(all(not x['repescavel'] for x in resp.data['lista']))

    def test_sem_filtro_mantem_todos_e_contagens(self):
        resp = self._get()
        self.assertEqual(resp.data['filtro_repescavel'], '')
        self.assertEqual(resp.data['paginacao']['total'], 5)
        self.assertEqual(resp.data['contagens_repescavel']['SIM'], 2)

    def test_filtro_antes_da_paginacao(self):
        resp = self._get(rep='SIM', page_size='1', page='1')
        self.assertEqual(resp.data['paginacao']['total'], 2)
        self.assertEqual(resp.data['paginacao']['total_pages'], 2)
        self.assertEqual(len(resp.data['lista']), 1)
        self.assertTrue(resp.data['lista'][0]['repescavel'])

    def test_cache_control_no_store(self):
        resp = self._get(rep='SIM')
        self.assertIn('no-store', resp.get('Cache-Control', ''))
