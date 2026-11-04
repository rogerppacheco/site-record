"""Tratamento unificado do Funil (todas as abas) e disparo de mailing."""
from unittest.mock import patch

from django.contrib.auth.models import Group
from rest_framework.test import APIClient
from django.test import TestCase

from crm_app.models import (
    FunilTratamento,
    HistoricoPapPedido,
    MailingContato,
    MailingEnvio,
    MailingLote,
)
from usuarios.models import Usuario


class FunilTratarApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = Usuario.objects.create_user(username='bo', password='x', email='bo@x.com')
        Group.objects.get_or_create(name='BackOffice')[0].user_set.add(self.user)
        self.client.force_authenticate(self.user)
        self.pedido = HistoricoPapPedido.objects.create(
            numero_pedido='2026110001',
            tipo_venda='VENDA',
            payload={
                'cliente': 'MARIA SILVA',
                'cpf': '12345678901',
                'dadosCliente': {'nome': 'MARIA SILVA', 'contatos': [{'telefone': '61985517198'}]},
            },
        )

    def test_tratar_venda_cria_marca(self) -> None:
        previa = self.client.get('/api/crm/funil-tratar/', {'aba': 'VENDA', 'id': self.pedido.pk})
        self.assertEqual(previa.status_code, 200, previa.content)
        self.assertFalse(previa.json()['tratado'])

        resp = self.client.post('/api/crm/funil-tratar/', {'aba': 'VENDA', 'id': self.pedido.pk, 'observacao': 'Ligou'})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['tratado'])
        self.assertEqual(data['aba'], 'VENDA')
        self.assertTrue(FunilTratamento.objects.filter(aba='VENDA', ref_id=str(self.pedido.pk)).exists())

    def test_tratar_mailing(self) -> None:
        lote = MailingLote.objects.create(nome='Lote T', tipo_layout=MailingLote.LAYOUT_OPTIC, status=MailingLote.STATUS_PRONTO)
        c = MailingContato.objects.create(
            lote=lote, nome='JOAO', telefone_e164='5561985517198', telefone_valido=True,
            situacao=MailingContato.SIT_REPARO, status=MailingContato.STATUS_RESPONDEU,
        )
        resp = self.client.post('/api/crm/funil-tratar/', {'aba': 'MAILING', 'id': c.pk})
        self.assertEqual(resp.status_code, 200, resp.content)
        c.refresh_from_db()
        self.assertEqual(c.status, MailingContato.STATUS_TRATADO)


class MailingDisparoElegiveisTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = Usuario.objects.create_superuser(username='dir', password='x', email='d@x.com')
        self.client.force_authenticate(self.user)
        self.lote = MailingLote.objects.create(
            nome='Lote D', tipo_layout=MailingLote.LAYOUT_OPTIC, status=MailingLote.STATUS_PRONTO,
            total_validos=2,
        )
        self.c1 = MailingContato.objects.create(
            lote=self.lote, nome='ANA', telefone_e164='5561999990001', telefone_valido=True,
            situacao=MailingContato.SIT_REPARO, status=MailingContato.STATUS_NOVO,
        )
        self.c2 = MailingContato.objects.create(
            lote=self.lote, nome='BIA', telefone_e164='5561999990002', telefone_valido=True,
            situacao=MailingContato.SIT_INSTALACAO, status=MailingContato.STATUS_NOVO,
        )

    @patch('crm_app.services.mailing_dispatch_service.enviar_mailing_contato')
    def test_envia_so_situacao_e_marca_enviado(self, mock_env) -> None:
        mock_env.return_value = (True, {'messages': [{'id': 'wamid.abc'}]}, 'template', 'mailing_reparo_v1')
        resp = self.client.post(
            '/api/crm/mailings/disparo-elegiveis/',
            {'situacao': 'REPARO', 'lote_id': self.lote.pk},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual(self.c1.status, MailingContato.STATUS_ENVIADO)
        self.assertEqual(self.c2.status, MailingContato.STATUS_NOVO)
        self.assertTrue(MailingEnvio.objects.filter(contato=self.c1, sucesso=True).exists())

    def test_funil_lista_traz_contagens_por_situacao(self) -> None:
        resp = self.client.get('/api/crm/mailings/funil/', {'status': 'TODOS'})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertIn('elegiveis_situacao', data)
        self.assertEqual(data['elegiveis_situacao'].get('REPARO'), 1)
        self.assertEqual(data['contagens']['NOVO'], 2)
