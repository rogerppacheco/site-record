"""Testes da API Churn / Cancelamentos na Esteira."""

from datetime import date, datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from crm_app.churn_os_utils import os_variantes
from crm_app.models import Cliente, ImportacaoChurn, StatusCRM, Venda
from usuarios.models import Perfil, Usuario


class EsteiraChurnTratamentoTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil_gestao = Perfil.objects.create(cod_perfil='DIR2', nome='Diretoria')
        cls.perfil_vend = Perfil.objects.create(cod_perfil='VND2', nome='Vendedor')
        cls.gestor = Usuario.objects.create_user(
            username='gestor_churn_trat',
            password='SenhaSegura123',
            perfil=cls.perfil_gestao,
        )
        cls.vendedor = Usuario.objects.create_user(
            username='vend_churn_trat',
            password='SenhaSegura123',
            perfil=cls.perfil_vend,
        )
        cls.cliente = Cliente.objects.create(
            cpf_cnpj='98765432100',
            nome_razao_social='CLIENTE CHURN TESTE',
        )
        cls.st_cad = StatusCRM.objects.create(nome='CADASTRADA', tipo='Tratamento')
        cls.st_inst = StatusCRM.objects.create(nome='INSTALADA', tipo='Esteira', estado='FECHADO')

    def setUp(self):
        hoje = timezone.localdate()
        self.venda = Venda.objects.create(
            vendedor=self.vendedor,
            cliente=self.cliente,
            status_tratamento=self.st_cad,
            status_esteira=self.st_inst,
            ordem_servico='09761234',
            data_instalacao=hoje,
            data_abertura=timezone.make_aware(datetime.combine(hoje.replace(day=1), datetime.min.time())),
            ativo=True,
        )
        ImportacaoChurn.objects.create(
            numero_pedido='09761234',
            nr_ordem='09761234',
            tipo_retirada='CANCELAMENTO',
            motivo_retirada='INADIMPLENCIA',
            cd_tr_vdd_original='TT999',
            anomes_gross='202506',
            anomes_retirada='202506',
            dt_retirada=hoje,
        )

    def test_os_variantes_zeros(self):
        v = os_variantes('09761234')
        self.assertIn('09761234', v)
        self.assertIn('9761234', v)

    def test_negado_para_vendedor(self):
        self.client.force_authenticate(user=self.vendedor)
        r = self.client.get('/api/crm/esteira/churn-tratamento/?mes_referencia=2025-06')
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_recebe_lista_e_ranking(self):
        self.client.force_authenticate(user=self.gestor)
        r = self.client.get('/api/crm/esteira/churn-tratamento/?mes_referencia=2025-06')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.json()
        self.assertIn('lista', data)
        self.assertIn('ranking', data)
        self.assertGreaterEqual(data['totais']['linhas_lista'], 1)
        row = next((x for x in data['lista'] if x.get('venda_id') == self.venda.id), None)
        self.assertIsNotNone(row)
        self.assertEqual(row['TP_RETIRADA'], 'CANCELAMENTO')
        self.assertEqual(row['cd_tr_vdd_original'], 'TT999')
        self.assertEqual(row['nome_cliente'], 'CLIENTE CHURN TESTE')
        self.assertEqual(row['cpf_cliente'], '98765432100')

    def test_situacao_nio_na_lista_e_filtro(self):
        from crm_app.models import ChurnConsultaDebitoNio

        ChurnConsultaDebitoNio.objects.create(
            cpf='98765432100', situacao='INADIMPLENTE', qtd_vencidas=1,
            valor_vencido='90.00', consultado_em=timezone.now(),
        )
        self.client.force_authenticate(user=self.gestor)
        base = '/api/crm/esteira/churn-tratamento/?mes_referencia=2025-06'
        data = self.client.get(base).json()
        row = next(x for x in data['lista'] if x.get('venda_id') == self.venda.id)
        self.assertEqual(row['situacao_nio'], 'INADIMPLENTE')
        self.assertEqual(row['debito_nio']['valor_vencido'], 90.0)
        self.assertEqual(data['contagens_nio']['INADIMPLENTE'], 1)

        so_adimplentes = self.client.get(base + '&situacao_nio=ADIMPLENTE').json()
        self.assertEqual(so_adimplentes['paginacao']['total'], 0)
        self.assertEqual(so_adimplentes['contagens_nio']['INADIMPLENTE'], 1)

    def test_todos_os_meses_inclui_outra_safra(self):
        outro = Cliente.objects.create(cpf_cnpj='11122233344', nome_razao_social='OUTRO CLIENTE')
        Venda.objects.create(
            vendedor=self.vendedor,
            cliente=outro,
            status_tratamento=self.st_cad,
            status_esteira=self.st_inst,
            ordem_servico='11112222',
            data_instalacao=date(2020, 1, 10),
            ativo=True,
        )
        ImportacaoChurn.objects.create(
            numero_pedido='11112222',
            nr_ordem='11112222',
            tipo_retirada='CANCELAMENTO',
            motivo_retirada='MUDANCA',
            anomes_retirada='202001',
            dt_retirada=date(2020, 1, 15),
        )
        self.client.force_authenticate(user=self.gestor)
        so_junho = self.client.get('/api/crm/esteira/churn-tratamento/?mes_referencia=2025-06')
        ids_junho = {x.get('cpf_cliente') for x in so_junho.json()['lista']}
        self.assertIn('98765432100', ids_junho)
        self.assertNotIn('11122233344', ids_junho)

        todos = self.client.get('/api/crm/esteira/churn-tratamento/?mes_referencia=todos')
        ids_todos = {x.get('cpf_cliente') for x in todos.json()['lista']}
        self.assertIn('98765432100', ids_todos)
        self.assertIn('11122233344', ids_todos)
        self.assertTrue(any(m.get('mes') == '2020-01' for m in todos.json().get('meses') or []))
