# -*- coding: utf-8 -*-
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from crm_app.models import Cliente, Venda
from crm_app.services.cnpj_mei_service import (
    CLASSIFICACAO_MEI,
    CLASSIFICACAO_NMEI,
    CLASSIFICACAO_MEI,
    classificar_cnpj_mei,
    queryset_clientes_cnpj,
    _interpretar_resposta_brasilapi,
)


class InterpretarBrasilApiTest(SimpleTestCase):
    def test_mei_pela_opcao(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'natureza_juridica': 'Empresário (Individual)',
                'opcao_pelo_mei': 'Sim',
                'data_exclusao_do_mei': None,
            },
            '12345678000199',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_MEI)

    def test_mei_2135_opcao_false_sem_exclusao(self):
        """BrasilAPI: opcao_pelo_mei=False comum em MEI; não deve virar NMEI."""
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'natureza_juridica': 'Empresário (Individual)',
                'opcao_pelo_mei': False,
                'data_opcao_pelo_mei': None,
                'data_exclusao_do_mei': None,
            },
            '13015154000107',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_MEI)

    def test_nmei_2135_com_exclusao_mei(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'opcao_pelo_mei': False,
                'data_exclusao_do_mei': '2025-12-31',
            },
            '43655857000152',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_NMEI)

    def test_mei_opcao_boolean_true(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'opcao_pelo_mei': True,
                'data_exclusao_do_mei': None,
            },
            '66088769000111',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_MEI)

    def test_nmei_pela_natureza(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 3999,
                'natureza_juridica': 'Associação Privada',
                'opcao_pelo_mei': None,
            },
            '19131243000197',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_NMEI)

    def test_nmei_apos_exclusao_mei(self):
        r = _interpretar_resposta_brasilapi(
            {
                'codigo_natureza_juridica': 2135,
                'opcao_pelo_mei': 'Sim',
                'data_exclusao_do_mei': '2020-01-01',
            },
            '12345678000199',
        )
        self.assertEqual(r.classificacao, CLASSIFICACAO_NMEI)


class ClassificarCnpjMeiTest(SimpleTestCase):
    @patch('crm_app.services.cnpj_mei_service._consultar_brasilapi')
    def test_nmei_quando_api_falha(self, mock_api):
        mock_api.return_value = None
        r = classificar_cnpj_mei('12345678000199', usar_cache=False)
        self.assertEqual(r.classificacao, CLASSIFICACAO_NMEI)

    def test_cpf_sem_classificacao(self):
        r = classificar_cnpj_mei('12345678901', usar_cache=False)
        self.assertIsNone(r.classificacao)
        self.assertEqual(r.descricao, '-')


class QuerysetClientesCnpjTest(TestCase):
    def test_filtra_cnpj_e_ignora_cpf(self):
        c_cnpj = Cliente.objects.create(
            cpf_cnpj='12345678000199',
            nome_razao_social='EMPRESA TESTE',
        )
        Cliente.objects.create(
            cpf_cnpj='12345678901',
            nome_razao_social='PESSOA CPF',
        )
        ids = list(queryset_clientes_cnpj(apenas_sem_classificacao=True).values_list('id', flat=True))
        self.assertEqual(ids, [c_cnpj.id])

    @patch('crm_app.services.cnpj_mei_service.persistir_classificacao_mei_cliente_e_vendas')
    def test_backfill_atualiza_vendas(self, mock_persistir):
        from crm_app.services.cnpj_mei_service import (
            ResultadoClassificacaoMei,
            backfill_classificacao_mei_lote,
        )

        cliente = Cliente.objects.create(
            cpf_cnpj='19131243000197',
            nome_razao_social='CLIENTE CNPJ',
        )
        venda = Venda.objects.create(cliente=cliente, telefone1='31999999999', telefone2='31988888888')
        mock_persistir.return_value = ResultadoClassificacaoMei(
            classificacao=CLASSIFICACAO_MEI,
            descricao='MEI',
            cache_hit=True,
        )

        r = backfill_classificacao_mei_lote(limite=10)
        self.assertEqual(r['processados_lote'], 1)
        self.assertEqual(r['mei'], 1)
        self.assertEqual(r['vendas_atualizadas'], 1)
        self.assertEqual(r['restantes'], 0)
        self.assertTrue(r['concluido'])
        mock_persistir.assert_called_once()
        self.assertEqual(mock_persistir.call_args[0][0].id, cliente.id)
