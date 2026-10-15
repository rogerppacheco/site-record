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
