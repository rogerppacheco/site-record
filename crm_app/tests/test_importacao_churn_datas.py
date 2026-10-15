"""Conversão de datas e colunas da planilha CHURN (.xlsb entrega datas como serial do Excel)."""

from datetime import date

from django.test import SimpleTestCase

from crm_app.views import _CHURN_ALIASES, _data_planilha_churn


class DataPlanilhaChurnTests(SimpleTestCase):
    def test_serial_excel_vira_data(self):
        self.assertEqual(_data_planilha_churn(46261), date(2026, 8, 27))
        self.assertEqual(_data_planilha_churn(46011.0), date(2025, 12, 20))

    def test_texto_dia_mes_ano(self):
        self.assertEqual(_data_planilha_churn('26/08/2026'), date(2026, 8, 26))

    def test_vazio(self):
        self.assertIsNone(_data_planilha_churn(None))
        self.assertIsNone(_data_planilha_churn(float('nan')))

    def test_alias_colunas_cmges(self):
        self.assertEqual(_CHURN_ALIASES['ANOMES_RET'], 'ANOMES_RETIRADA')
        self.assertEqual(_CHURN_ALIASES['NM_MUNICIPIO'], 'MUNICIPIO')
        self.assertEqual(_CHURN_ALIASES['SG_UF'], 'UF')
