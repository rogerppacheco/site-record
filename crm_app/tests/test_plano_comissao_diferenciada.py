from decimal import Decimal
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from crm_app.comissao_folha_service import resolver_valor_comissao_venda
from crm_app.services.plano_comissao_service import (
    plano_comissao_diferenciada,
    resolver_banda_comissao_cadastro,
)


class PlanoComissaoDiferenciadaTest(SimpleTestCase):
    def test_plano_personalizado_usa_valor_do_plano(self) -> None:
        plano = MagicMock()
        vc = MagicMock()
        vc.banda_comissao = 'PERSONALIZADO'
        vc.valor_pap = Decimal('150.00')
        vc.valor_cnpj = Decimal('250.00')
        plano.valores_comissao = vc

        self.assertTrue(plano_comissao_diferenciada(plano))
        valor = resolver_valor_comissao_venda(
            plano,
            'CPF',
            faixa_regra=MagicMock(valor_1gb_pap=Decimal('220.00')),
            config=None,
            usar_manual=False,
            chave='1GB_PAP',
        )
        self.assertEqual(valor, 150.0)

    def test_plano_1gb_padrao_usa_faixa(self) -> None:
        plano = MagicMock()
        vc = MagicMock()
        vc.banda_comissao = '1GB'
        plano.valores_comissao = vc
        faixa = MagicMock(valor_1gb_pap=Decimal('220.00'))

        self.assertFalse(plano_comissao_diferenciada(plano))
        valor = resolver_valor_comissao_venda(
            plano,
            'CPF',
            faixa_regra=faixa,
            config=None,
            usar_manual=False,
            chave='1GB_PAP',
        )
        self.assertEqual(valor, 220.0)

    def test_resolver_banda_forca_personalizado_quando_duplicada(self) -> None:
        plano = MagicMock()
        plano.pk = 10
        plano.operadora_id = 1
        plano.nome = 'NIO FIBRA ULTRA 1GB (SEM MESH)'

        from crm_app.models import Plano as PlanoModel

        with self.settings():
            # Simula outro plano 1GB já cadastrado na mesma operadora
            original = PlanoModel.objects.filter
            PlanoModel.objects.filter = MagicMock(
                return_value=MagicMock(
                    exclude=MagicMock(return_value=MagicMock(exists=MagicMock(return_value=True))),
                ),
            )
            try:
                banda = resolver_banda_comissao_cadastro(plano, '1GB')
            finally:
                PlanoModel.objects.filter = original
        self.assertEqual(banda, 'PERSONALIZADO')
