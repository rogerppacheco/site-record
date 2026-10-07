"""Recompra na folha: só venda em aberto perde a comissão e leva multa."""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from crm_app.comissao_folha_service import MULTA_RECOMPRA, _variantes_os, venda_recompra_desconta


class RecompraFolhaTest(SimpleTestCase):
    def setUp(self):
        self.os_base = set()
        self.os_base.update(_variantes_os('9761234'))

    def _venda(self, **extra):
        dados = dict(
            ordem_servico='09761234',
            desconto_recompra_aplicado_em=None,
            status_comissionamento=None,
            reemissao=False,
            adiantamento_sabado_marcado=False,
            antecipacao_comissao=False,
            flag_desc_adiantamento_sabado=False,
            adiantamento_sabado_quitado_em=None,
            status_esteira=None,
        )
        dados.update(extra)
        return SimpleNamespace(**dados)

    def test_venda_em_aberto_desconta(self):
        self.assertTrue(venda_recompra_desconta(self._venda(), 202609, self.os_base))

    def test_venda_paga_nao_desconta(self):
        venda = self._venda(status_comissionamento=SimpleNamespace(nome='PAGO'))
        self.assertFalse(venda_recompra_desconta(venda, 202609, self.os_base))

    def test_venda_adiantada_nao_desconta(self):
        venda = self._venda(antecipacao_comissao=True)
        self.assertFalse(venda_recompra_desconta(venda, 202609, self.os_base))

    def test_mes_fechado_com_desconto_continua_na_folha_daquele_mes(self):
        venda = self._venda(
            desconto_recompra_aplicado_em=202609,
            status_comissionamento=SimpleNamespace(nome='PAGO'),
        )
        self.assertTrue(venda_recompra_desconta(venda, 202609, self.os_base))
        self.assertFalse(venda_recompra_desconta(venda, 202610, self.os_base))

    def test_multa_e_quinhentos(self):
        self.assertEqual(MULTA_RECOMPRA, Decimal('500'))
