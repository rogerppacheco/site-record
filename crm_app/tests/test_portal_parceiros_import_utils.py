"""Testes de normalização Portal Parceiros (FPD/OSAB)."""

import io
from pathlib import Path

import pandas as pd
from django.test import SimpleTestCase

from crm_app.fpd_status_mapping import normalizar_status_fpd
from crm_app.portal_parceiros_import_utils import (
    coluna_nr_ordem_fpd_presente,
    coluna_tem_valores,
    extrair_indicador_fpd,
    extrair_vl_fatura_fpd,
    ler_excel_fpd,
    normalizar_colunas_fpd,
    normalizar_colunas_osab,
    resolver_coluna_pedido_osab,
)


FPD_FIXTURE = Path(r'c:\Users\rogge\Downloads\FPD_PORTAL PARCEIROS.xlsx')
OSAB_FIXTURE = Path(r'c:\Users\rogge\Downloads\OSAB_PORTAL PARCEIROS.xlsx')


class PortalParceirosImportUtilsTest(SimpleTestCase):
    def test_fpd_aliases_from_fixture(self):
        if not FPD_FIXTURE.is_file():
            self.skipTest('Planilha FPD de exemplo não disponível')

        df = pd.read_excel(FPD_FIXTURE, sheet_name='Export', nrows=50)
        out = normalizar_colunas_fpd(df)

        self.assertIn('nr_ordem', out.columns)
        self.assertIn('ds_status_fatura', out.columns)
        self.assertTrue(coluna_nr_ordem_fpd_presente(out))
        self.assertNotIn('nr_ordem_venda', out.columns)
        self.assertNotIn('status_pag', out.columns)
        self.assertIn('indicador', out.columns)

    def test_fpd_indicador_e_vl_fatura(self):
        if not FPD_FIXTURE.is_file():
            self.skipTest('Planilha FPD de exemplo não disponível')

        df = pd.read_excel(FPD_FIXTURE, sheet_name='Export', nrows=10)
        out = normalizar_colunas_fpd(df)
        row = out.iloc[0]
        self.assertEqual(extrair_vl_fatura_fpd(row), 0.0)
        self.assertIn(extrair_indicador_fpd(row), {'FPD', 'SPD', 'TPD'})

    def test_osab_aliases_from_fixture(self):
        if not OSAB_FIXTURE.is_file():
            self.skipTest('Planilha OSAB de exemplo não disponível')

        df = pd.read_excel(OSAB_FIXTURE, sheet_name='Export', nrows=50)
        out = normalizar_colunas_osab(df)

        self.assertIn('PEDIDO', out.columns)
        self.assertIn('DT_REF', out.columns)
        self.assertIn('SITUACAO', out.columns)
        self.assertIn('LOCALIDADE', out.columns)
        self.assertIn('MEIO_PAGAMENTO', out.columns)
        self.assertIn('DATA_ABERTURA', out.columns)
        self.assertIn('COD_PENDENCIA', out.columns)
        self.assertTrue(coluna_tem_valores(out, 'PEDIDO'))

    def test_osab_pedido_fallback_nr_ordem(self):
        df = pd.DataFrame({'NR_ORDEM': ['11045939', '10849125']})
        out = resolver_coluna_pedido_osab(normalizar_colunas_osab(df))
        self.assertEqual(out['PEDIDO'].tolist(), ['11045939', '10849125'])

    def test_osab_data_agendamento_nao_e_sobrescrita_pelo_inicio_real(self):
        """Layout Nio: Data Agendamento e Inicio execucao real coexistem."""
        df = pd.DataFrame({
            'nr_ordem': ['11162752', '11109675'],
            'Status': ['Em Aprovisionamento', 'Em Aprovisionamento'],
            'Data Agendamento': ['2026-09-14 13:00:00', None],
            'Inicio execucao real': [None, '2026-09-13 16:25:45'],
        })
        out = normalizar_colunas_osab(df)

        self.assertEqual(list(out.columns).count('DATA_AGENDAMENTO'), 1)
        self.assertIn('INICIO_EXECUCAO_REAL', out.columns)
        registros = out.to_dict('records')
        self.assertIn('2026-09-14', str(registros[0]['DATA_AGENDAMENTO']))
        self.assertIn('2026-09-13', str(registros[1]['DATA_AGENDAMENTO']))

    def test_nr_ordem_ignora_maiusculas(self):
        for coluna in ('nr_ordem', 'NR_ORDEM', 'Nr_Ordem'):
            out = normalizar_colunas_fpd(pd.DataFrame({coluna: ['9569823']}))
            self.assertTrue(coluna_nr_ordem_fpd_presente(out), coluna)

    def test_fpd_escolhe_aba_com_nr_ordem_e_nao_o_resumo(self):
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            pd.DataFrame({
                'MÊS FATURA': ['FATURA PAGA'],
                '202608': [613],
                '202609': [657],
            }).to_excel(writer, sheet_name='Planilha1', index=False)
            pd.DataFrame({
                'id_contrato': ['2666130'],
                'nr_ordem': ['09569823'],
                'nr_fatura': ['11248607438'],
            }).to_excel(writer, sheet_name='BASE_PRE_FPD_ABERTO', index=False)
        buf.seek(0)

        df = ler_excel_fpd(buf)
        out = normalizar_colunas_fpd(df)

        self.assertEqual(df.attrs['aba_fpd'], 'BASE_PRE_FPD_ABERTO')
        self.assertTrue(coluna_nr_ordem_fpd_presente(out))
        self.assertEqual(out.iloc[0]['nr_ordem'], '09569823')
        self.assertEqual(extrair_indicador_fpd(out.iloc[0]), 'FPD')

    def test_fpd_status_nao_paga(self):
        self.assertEqual(normalizar_status_fpd('NAO PAGA'), 'NAO_PAGO')
        self.assertEqual(normalizar_status_fpd('PAGA'), 'PAGO')
