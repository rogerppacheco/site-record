from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from crm_app.comissao_folha_service import resolver_valor_comissao_venda


class ComissaoMatrizPlanoTest(SimpleTestCase):
    def test_resolver_usa_matriz_faixa_plano(self) -> None:
        plano = MagicMock()
        plano.id = 99
        faixa = MagicMock()

        with patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=150.0):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='1GB_PAP',
            )
        self.assertEqual(valor, 150.0)

    def test_resolver_fallback_faixa_legada(self) -> None:
        plano = MagicMock()
        faixa = MagicMock(valor_1gb_pap=Decimal('220.00'))

        with patch('crm_app.services.comissao_matriz_service.get_valor_faixa_plano', return_value=None):
            valor = resolver_valor_comissao_venda(
                plano,
                'CPF',
                faixa_regra=faixa,
                config=None,
                usar_manual=False,
                chave='1GB_PAP',
            )
        self.assertEqual(valor, 220.0)
