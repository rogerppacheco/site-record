"""Importação de cancelamentos pela tela /importar-churn/."""
import io
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from rest_framework import status
from rest_framework.test import APITestCase

from crm_app.models import ImportacaoChurn
from usuarios.models import Perfil, Usuario


class ImportacaoChurnViewTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil_dir = Perfil.objects.create(cod_perfil='DIRCHURN', nome='Diretoria')
        cls.perfil_vend = Perfil.objects.create(cod_perfil='VNDCHURN', nome='Vendedor')
        cls.diretoria = Usuario.objects.create_user(
            username='dir_import_churn',
            password='SenhaSegura123',
            perfil=cls.perfil_dir,
        )
        cls.vendedor = Usuario.objects.create_user(
            username='vend_import_churn',
            password='SenhaSegura123',
            perfil=cls.perfil_vend,
        )

    def _csv(self, texto, nome='1068561.csv'):
        return SimpleUploadedFile(nome, texto.encode('utf-8'), content_type='text/csv')

    def test_vendedor_recebe_erro_explicito(self):
        self.client.force_authenticate(user=self.vendedor)
        resposta = self.client.post(
            '/api/crm/import/churn/',
            {'file': self._csv('PEDIDO,DT_RETIRADA\n1,2026-09-01\n')},
            format='multipart',
        )
        self.assertEqual(resposta.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('error', resposta.json())

    def test_planilha_com_coluna_pedido_e_anomes_com_hifen(self):
        self.client.force_authenticate(user=self.diretoria)
        motivo = 'M' * 400
        csv = (
            'PEDIDO,NR_ORDEM,DT_RETIRADA,ANOMES_RETIRADA,ANOMES_GROSS,MOTIVO_RETIRADA\n'
            '123456,99887766,2026-09-15,2026-09,2026-08,PRIMEIRA\n'
            f'123456,99887766,2026-09-16,202609,202608,{motivo}\n'
        )
        resposta = self.client.post(
            '/api/crm/import/churn/',
            {'file': self._csv(csv)},
            format='multipart',
        )
        self.assertEqual(resposta.status_code, status.HTTP_200_OK, resposta.content)
        corpo = resposta.json()
        self.assertEqual(corpo['criados'], 1)
        self.assertEqual(corpo['atualizados'], 0)
        registro = ImportacaoChurn.objects.get(numero_pedido='123456')
        self.assertEqual(registro.dt_retirada, date(2026, 9, 16))
        self.assertEqual(registro.anomes_retirada, '202609')
        self.assertEqual(registro.anomes_gross, '202608')
        self.assertEqual(registro.motivo_retirada, motivo[:255])

    def test_atualiza_pedido_existente(self):
        ImportacaoChurn.objects.create(numero_pedido='777', nr_ordem='1', anomes_retirada='202601')
        self.client.force_authenticate(user=self.diretoria)
        csv = 'PEDIDO,NR_ORDEM,DT_RETIRADA,ANOMES_RETIRADA\n777,222,2026-09-02,2026-09\n'
        resposta = self.client.post(
            '/api/crm/import/churn/',
            {'file': self._csv(csv)},
            format='multipart',
        )
        self.assertEqual(resposta.status_code, status.HTTP_200_OK, resposta.content)
        self.assertEqual(resposta.json()['atualizados'], 1)
        registro = ImportacaoChurn.objects.get(numero_pedido='777')
        self.assertEqual(registro.nr_ordem, '222')
        self.assertEqual(registro.anomes_retirada, '202609')

    def test_escolhe_aba_com_pedido_e_ignora_base_click(self):
        planilha = Workbook()
        base = planilha.active
        base.title = 'BASE_CLICK'
        base.append(['SEGMENTO', 'QTD'])
        base.append(['VAREJO', 10])
        churn = planilha.create_sheet('CHURN X GROSS')
        churn.append(['PEDIDO', 'DT_RETIRADA', 'NR_ORDEM'])
        churn.append([555001, date(2026, 9, 1), '111222'])
        buffer = io.BytesIO()
        planilha.save(buffer)
        arquivo = SimpleUploadedFile(
            '1068561.xlsx',
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.client.force_authenticate(user=self.diretoria)
        resposta = self.client.post('/api/crm/import/churn/', {'file': arquivo}, format='multipart')
        self.assertEqual(resposta.status_code, status.HTTP_200_OK, resposta.content)
        registro = ImportacaoChurn.objects.get(numero_pedido='555001')
        self.assertEqual(registro.nr_ordem, '111222')
        self.assertEqual(registro.dt_retirada, date(2026, 9, 1))

    def test_sem_colunas_de_chave_devolve_erro(self):
        self.client.force_authenticate(user=self.diretoria)
        resposta = self.client.post(
            '/api/crm/import/churn/',
            {'file': self._csv('FOO,BAR\n1,2\n')},
            format='multipart',
        )
        self.assertEqual(resposta.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('PEDIDO', resposta.json()['error'])
