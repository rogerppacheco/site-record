from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from crm_app.models import Cliente, StatusCRM, Venda
from usuarios.models import Perfil, Usuario


class GestaoAproveitamentoEsteiraTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil_gestao = Perfil.objects.create(cod_perfil="DIR", nome="Diretoria")
        cls.perfil_vend = Perfil.objects.create(cod_perfil="VEND", nome="Vendedor")
        cls.gestor = Usuario.objects.create_user(
            username="gestor_aprov",
            password="SenhaSegura123",
            perfil=cls.perfil_gestao,
        )
        cls.vendedor = Usuario.objects.create_user(
            username="vend_aprov",
            password="SenhaSegura123",
            perfil=cls.perfil_vend,
        )
        cls.cliente = Cliente.objects.create(
            cpf_cnpj="11122233344",
            nome_razao_social="CLIENTE APROV",
        )
        cls.st_cad = StatusCRM.objects.create(nome="CADASTRADA", tipo="Tratamento")
        cls.st_agend = StatusCRM.objects.create(nome="AGENDADO", tipo="Esteira", estado="ABERTO")
        cls.st_inst = StatusCRM.objects.create(nome="INSTALADA", tipo="Esteira", estado="FECHADO")

    def test_negado_para_vendedor(self):
        self.client.force_authenticate(user=self.vendedor)
        r = self.client.get("/api/crm/esteira/gestao-aproveitamento/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_recebe_payload(self):
        hoje = timezone.localdate()
        Venda.objects.create(
            vendedor=self.vendedor,
            cliente=self.cliente,
            status_tratamento=self.st_cad,
            status_esteira=self.st_inst,
            ordem_servico="12345678",
            data_abertura=timezone.make_aware(
                datetime.combine(hoje.replace(day=1), datetime.min.time())
            ),
            data_instalacao=hoje,
            ativo=True,
        )
        self.client.force_authenticate(user=self.gestor)
        mes = hoje.strftime("%Y-%m")
        r = self.client.get(f"/api/crm/esteira/gestao-aproveitamento/?mes_referencia={mes}")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("resumo", r.data)
        self.assertIn("por_vendedor", r.data)
        self.assertIn("aproveitamento", r.data["resumo"])

    def test_instaladas_conta_data_efetiva_mes_independente_abertura(self):
        hoje = timezone.localdate()
        inicio_mes = hoje.replace(day=1)
        mes_anterior = (inicio_mes - timedelta(days=1)).replace(day=15)

        Venda.objects.create(
            vendedor=self.vendedor,
            cliente=self.cliente,
            status_tratamento=self.st_cad,
            status_esteira=self.st_inst,
            ordem_servico="87654321",
            data_abertura=timezone.make_aware(
                datetime.combine(mes_anterior, datetime.min.time())
            ),
            data_instalacao=hoje,
            ativo=True,
        )
        self.client.force_authenticate(user=self.gestor)
        mes = hoje.strftime("%Y-%m")
        r = self.client.get(f"/api/crm/esteira/gestao-aproveitamento/?mes_referencia={mes}")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(r.data["resumo"]["instaladas"], 1)
        self.assertEqual(r.data["resumo"]["total_abertas"], 0)
