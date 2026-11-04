"""Testes do import e classificação de mailings OPTIC / ATV ALG."""
from django.test import SimpleTestCase

from crm_app.models import MailingContato, MailingLote
from crm_app.services import mailing_import_service as svc
from crm_app.services.mailing_templates import body_params_contato, template_para_situacao


class DetectarLayoutTests(SimpleTestCase):
    def test_optic(self):
        self.assertEqual(
            svc.detectar_layout(['NOME', 'CPF', 'TELEFONE_COMPLETO', 'Macro Atividade', 'UF']),
            MailingLote.LAYOUT_OPTIC,
        )

    def test_atv(self):
        self.assertEqual(
            svc.detectar_layout(['Cliente', 'Documento', 'Telefone', 'Status', 'Cidade']),
            MailingLote.LAYOUT_ATV_ALG,
        )

    def test_desconhecido(self):
        self.assertIsNone(svc.detectar_layout(['A', 'B']))

    def test_mercado_algar_e_tim(self):
        self.assertEqual(
            svc.detectar_layout(
                ['Nome', 'CPF/CNPJ', 'Telefone', 'Plano', 'Status', 'Cidade']
            ),
            MailingLote.LAYOUT_ATV_ALG,
        )
        self.assertEqual(
            svc.detectar_layout(['Nome', 'CPF/CNPJ', 'Telefone', 'Cidade', 'CEP']),
            MailingLote.LAYOUT_ATV_ALG,
        )
        self.assertEqual(
            svc.detectar_layout(['NOME', 'DOCUMENTO', 'TELEFONE', 'CONTRATO_STATUS']),
            MailingLote.LAYOUT_ATV_ALG,
        )
        self.assertEqual(
            svc.detectar_layout(['Nome', 'Telefone1', 'Telefne2', 'Cidade']),
            MailingLote.LAYOUT_ATV_ALG,
        )


class ClassificarTests(SimpleTestCase):
    def test_optic_macros(self):
        self.assertEqual(svc.classificar_optic('REP-FTTH'), MailingContato.SIT_REPARO)
        self.assertEqual(svc.classificar_optic('INST-FTTH'), MailingContato.SIT_INSTALACAO)
        self.assertEqual(svc.classificar_optic('MUD-FTTH'), MailingContato.SIT_MUDANCA)
        self.assertEqual(svc.classificar_optic('SRV-FTTH'), MailingContato.SIT_SERVICO)

    def test_atv_status(self):
        self.assertEqual(svc.classificar_atv('CANCELAMENTO'), MailingContato.SIT_CANCELAMENTO)
        self.assertEqual(svc.classificar_atv('FECHADO'), MailingContato.SIT_FECHADO)
        self.assertEqual(svc.classificar_atv('ABERTO'), MailingContato.SIT_ABERTO)
        self.assertEqual(svc.classificar_atv('TECNICO'), MailingContato.SIT_ABERTO)
        self.assertEqual(svc.classificar_atv('Suspensão'), MailingContato.SIT_GENERICO)
        self.assertEqual(svc.classificar_atv('EM APROVISIONAMENTO'), MailingContato.SIT_ABERTO)
        self.assertEqual(svc.classificar_atv('CONCLUÍDO'), MailingContato.SIT_INSTALACAO)
        self.assertEqual(svc.classificar_atv('DESISTÊNCIA CONCLUÍDA'), MailingContato.SIT_CANCELAMENTO)
        self.assertEqual(
            svc.situacao_pelo_arquivo('SUSPENSÃO VERO 03 NOV 2026.xlsx'),
            MailingContato.SIT_GENERICO,
        )


class TelefoneTests(SimpleTestCase):
    def test_celular(self):
        e164, ok = svc.normalizar_telefone_e164('(61) 98551-7198')
        self.assertTrue(ok)
        self.assertEqual(e164, '5561985517198')

    def test_vazio(self):
        e164, ok = svc.normalizar_telefone_e164('')
        self.assertFalse(ok)


class ParseOpticTests(SimpleTestCase):
    def test_dedup_e_situacao(self):
        headers = ['NOME', 'CPF', 'TELEFONE_COMPLETO', 'Macro Atividade', 'Bairro', 'UF']
        rows = [
            ('MARIA SILVA', '12345678901', '(61) 985517198', 'REP-FTTH', 'Centro', 'DF'),
            ('MARIA DUP', '999', '(61) 985517198', 'INST-FTTH', 'Centro', 'DF'),
            ('JOAO', '111', '(62) 999755053', 'INST-FTTH', 'X', 'GO'),
        ]
        parsed = svc.parse_linhas(headers, rows, MailingLote.LAYOUT_OPTIC)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['situacao'], MailingContato.SIT_REPARO)
        self.assertEqual(parsed[1]['situacao'], MailingContato.SIT_INSTALACAO)
        self.assertTrue(parsed[0]['telefone_valido'])


class ParseMercadoTests(SimpleTestCase):
    def test_algar_status_e_cpf_null(self):
        headers = ['Nome', 'CPF/CNPJ', 'Telefone', 'Status', 'Cidade']
        rows = [
            ('ELAINE CRISTINA', 'Null', '16996239823', 'Cancelamento', 'FRANCA'),
            ('HOMERO', 'Null', '34997655234', 'Técnico', 'UBERLANDIA'),
        ]
        parsed = svc.parse_linhas(headers, rows, MailingLote.LAYOUT_ATV_ALG)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]['situacao'], MailingContato.SIT_CANCELAMENTO)
        self.assertEqual(parsed[0]['cpf'], '')
        self.assertEqual(parsed[1]['situacao'], MailingContato.SIT_ABERTO)
        self.assertTrue(parsed[0]['telefone_valido'])

    def test_vero_sem_status_usa_arquivo(self):
        headers = ['Nome', 'CPF/CNPJ', 'Telefone1', 'Cidade']
        rows = [('ANTONIO CARLOS', '32938411804', '19982800085', 'PIRASSUNUNGA')]
        parsed = svc.parse_linhas(
            headers,
            rows,
            MailingLote.LAYOUT_ATV_ALG,
            arquivo_nome='SUSPENSÃO VERO 03 NOV 2026.xlsx',
        )
        self.assertEqual(parsed[0]['situacao'], MailingContato.SIT_GENERICO)
        self.assertEqual(parsed[0]['telefone_e164'], '5519982800085')


class TemplateMapTests(SimpleTestCase):
    def test_templates(self):
        self.assertEqual(template_para_situacao(MailingContato.SIT_REPARO), 'mailing_reparo_v1')
        self.assertEqual(template_para_situacao(MailingContato.SIT_CANCELAMENTO), 'mailing_cancelamento_v1')

    def test_params_duas_vars(self):
        c = MailingContato(
            nome='LUCIA SOUZA',
            situacao=MailingContato.SIT_CANCELAMENTO,
            cidade='Uberlândia',
        )
        self.assertEqual(body_params_contato(c), ['Lucia', 'Uberlândia'])
