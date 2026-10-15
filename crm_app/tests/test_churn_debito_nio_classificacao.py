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


NEGOCIA_SEM_DIVIDA = {'debts': [], 'erro_400': True, 'detail': 'debts not found'}
CONTA_2VIA_VENCIDA = {
    'amount': '160,00', 'due_date_raw': '31/05/2026', 'status': 'OVERDUE', 'origem': '2via',
}


class ConsultarDocumentoTests(SimpleTestCase):
    def _consultar(self, negocia, via2):
        import threading
        from unittest import mock

        from crm_app.services import churn_debito_nio_service as svc

        via2_mock = {'side_effect': via2} if isinstance(via2, Exception) else {'return_value': via2}
        with mock.patch('crm_app.nio_api.consultar_dividas_nio', return_value=negocia), \
                mock.patch.object(svc, 'faturas_segunda_via', **via2_mock), \
                mock.patch.object(svc.time, 'sleep'):
            return svc.consultar_documento('70312345611', svc._Pausa(), threading.Event())

    def test_sem_conta_nas_duas_fontes_e_adimplente(self):
        r = self._consultar(NEGOCIA_SEM_DIVIDA, [])
        self.assertEqual(r['situacao'], 'ADIMPLENTE')

    def test_conta_so_na_segunda_via_e_inadimplente(self):
        r = self._consultar(NEGOCIA_SEM_DIVIDA, [CONTA_2VIA_VENCIDA])
        self.assertEqual(r['situacao'], 'INADIMPLENTE')
        self.assertEqual(r['valor_vencido'], Decimal('160.00'))

    def test_mesma_conta_nas_duas_fontes_conta_uma_vez(self):
        negocia = {'invoices': [{'amount': 160, 'due_date_raw': '20260531', 'status': 'overdue'}]}
        r = self._consultar(negocia, [CONTA_2VIA_VENCIDA])
        self.assertEqual(r['qtd_vencidas'], 1)

    def test_falha_na_segunda_via_e_erro_e_nao_adimplente(self):
        r = self._consultar(NEGOCIA_SEM_DIVIDA, ConnectionError('timeout'))
        self.assertEqual(r['situacao'], 'ERRO')

    def test_outro_400_e_erro(self):
        r = self._consultar({'erro_400': True, 'detail': 'invalid document'}, [])
        self.assertEqual(r['situacao'], 'ERRO')
