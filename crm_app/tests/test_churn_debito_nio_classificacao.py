"""Classificação adimplente / inadimplente / a vencer a partir das faturas da API Nio."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from crm_app.services.churn_debito_nio_service import classificar_faturas, normalizar_documento

HOJE = date(2026, 10, 15)


class ClassificarFaturasTests(SimpleTestCase):
    def test_sem_faturas_e_adimplente(self):
        r = classificar_faturas([], hoje=HOJE)
        self.assertEqual(r['situacao'], 'ADIMPLENTE')

    def test_fatura_vencida_e_inadimplente(self):
        r = classificar_faturas(
            [{'amount': 90.0, 'due_date_raw': '2026-06-16', 'status': 'em aberto'}], hoje=HOJE,
        )
        self.assertEqual(r['situacao'], 'INADIMPLENTE')
        self.assertEqual(r['qtd_vencidas'], 1)
        self.assertEqual(r['valor_vencido'], Decimal('90.0'))
        self.assertEqual(r['vencimento_mais_antigo'], date(2026, 6, 16))

    def test_fatura_no_prazo_e_a_vencer(self):
        r = classificar_faturas(
            [{'amount': '99,90', 'due_date_raw': '2026-10-20T00:00:00', 'status': 'OPEN'}], hoje=HOJE,
        )
        self.assertEqual(r['situacao'], 'A_VENCER')
        self.assertEqual(r['valor_a_vencer'], Decimal('99.90'))

    def test_vencida_prevalece_sobre_a_vencer(self):
        r = classificar_faturas([
            {'amount': 50, 'due_date_raw': '2026-11-10', 'status': 'OPEN'},
            {'amount': 70, 'due_date_raw': '20260910', 'status': 'OPEN'},
        ], hoje=HOJE)
        self.assertEqual(r['situacao'], 'INADIMPLENTE')
        self.assertEqual(r['qtd_a_vencer'], 1)

    def test_fatura_paga_e_ignorada(self):
        r = classificar_faturas(
            [{'amount': 90, 'due_date_raw': '2026-06-16', 'status': 'PAID'}], hoje=HOJE,
        )
        self.assertEqual(r['situacao'], 'ADIMPLENTE')

    def test_sem_data_mas_status_atrasado(self):
        r = classificar_faturas([{'amount': 10, 'status': 'overdue'}], hoje=HOJE)
        self.assertEqual(r['situacao'], 'INADIMPLENTE')

    def test_normalizar_documento(self):
        self.assertEqual(normalizar_documento('703.123.456-11'), '70312345611')


class ConsultarDocumentoTests(SimpleTestCase):
    def _consultar(self, resposta):
        import threading
        from unittest import mock

        from crm_app.services import churn_debito_nio_service as svc

        with mock.patch('crm_app.nio_api.consultar_dividas_nio', return_value=resposta):
            return svc.consultar_documento('70312345611', svc._Pausa(), threading.Event())

    def test_debts_not_found_e_adimplente(self):
        r = self._consultar({'debts': [], 'erro_400': True, 'detail': 'debts not found'})
        self.assertEqual(r['situacao'], 'ADIMPLENTE')

    def test_outro_400_e_erro(self):
        r = self._consultar({'erro_400': True, 'detail': 'invalid document'})
        self.assertEqual(r['situacao'], 'ERRO')
