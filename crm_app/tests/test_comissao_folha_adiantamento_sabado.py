# -*- coding: utf-8 -*-
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from crm_app.services.adiantamento_sabado_service import (
    aplicar_complemento_adiantamento_sabado_folha,
    valor_alvo_adiantamento_sabado_folha,
)


class _PlanoStub:
    def __init__(self, nome: str) -> None:
        self.nome = nome


class _ClienteStub:
    def __init__(self, cpf_cnpj: str = '12345678901') -> None:
        self.cpf_cnpj = cpf_cnpj


class _FaixaStub:
    def __init__(self, faixa_nome: str = 'Faixa 2', valor_500mb_pap: float = 150.0) -> None:
        self.faixa_nome = faixa_nome
        self.valor_500mb_pap = Decimal(str(valor_500mb_pap))
        self.valor_700mb_pap = None
        self.valor_1gb_pap = None
        self.valor_500mb_cnpj = None
        self.valor_700mb_cnpj = None
        self.valor_1gb_cnpj = None


class _ConfigStub:
    def __init__(self, valor_500mb_pap_manual: float = 145.0) -> None:
        self.valor_500mb_pap_manual = Decimal(str(valor_500mb_pap_manual))
        self.valor_700mb_pap_manual = None
        self.valor_1gb_pap_manual = None
        self.valor_500mb_cnpj_manual = None
        self.valor_700mb_cnpj_manual = None
        self.valor_1gb_cnpj_manual = None


class _VendaStub:
    def __init__(self, **kwargs) -> None:
        self.pk = kwargs.pop('pk', 1)
        for chave, valor in kwargs.items():
            setattr(self, chave, valor)


class ValorAlvoAdiantamentoSabadoFolhaTests(SimpleTestCase):
    def test_usa_faixa_comissao_quando_nao_manual(self) -> None:
        venda = _VendaStub(plano=_PlanoStub('500 MB'), cliente=_ClienteStub())
        alvo = valor_alvo_adiantamento_sabado_folha(
            venda,
            faixa_regra=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(150.0, alvo)

    def test_usa_valor_manual_da_config(self) -> None:
        venda = _VendaStub(plano=_PlanoStub('500 MB'), cliente=_ClienteStub())
        alvo = valor_alvo_adiantamento_sabado_folha(
            venda,
            faixa_regra=_FaixaStub(valor_500mb_pap=150.0),
            config=_ConfigStub(valor_500mb_pap_manual=145.0),
            usar_manual=True,
        )
        self.assertEqual(145.0, alvo)


class AplicarComplementoAdiantamentoSabadoFolhaTests(SimpleTestCase):
    @patch('crm_app.models.Venda.objects.bulk_update')
    def test_complementa_instalada_ate_faixa_alcancada(self, mock_bulk) -> None:
        venda = _VendaStub(
            pk=10,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor=Decimal('130.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        qtd = aplicar_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(1, qtd)
        self.assertEqual(Decimal('150.00'), venda.adiantamento_sabado_valor)
        mock_bulk.assert_called_once()

    @patch('crm_app.models.Venda.objects.bulk_update')
    def test_rebaixa_quando_pago_maior_que_faixa(self, mock_bulk) -> None:
        venda = _VendaStub(
            pk=11,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor=Decimal('160.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        qtd = aplicar_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=130.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(1, qtd)
        self.assertEqual(Decimal('130.00'), venda.adiantamento_sabado_valor)
        mock_bulk.assert_called_once()

    @patch('crm_app.models.Venda.objects.bulk_update')
    def test_nao_altera_sem_marcacao_sabado(self, mock_bulk) -> None:
        venda = _VendaStub(
            pk=12,
            adiantamento_sabado_marcado=False,
            adiantamento_sabado_valor=Decimal('130.00'),
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        qtd = aplicar_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(0, qtd)
        self.assertEqual(Decimal('130.00'), venda.adiantamento_sabado_valor)
        mock_bulk.assert_not_called()

    @patch('crm_app.models.Venda.objects.bulk_update')
    def test_nao_altera_com_estorno_ja_aplicado(self, mock_bulk) -> None:
        venda = _VendaStub(
            pk=13,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor=Decimal('130.00'),
            flag_desc_adiantamento_sabado=True,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        qtd = aplicar_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(0, qtd)
        mock_bulk.assert_not_called()

    @patch('crm_app.models.Venda.objects.bulk_update')
    def test_complementa_valor_manual_ate_config(self, mock_bulk) -> None:
        venda = _VendaStub(
            pk=14,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor=Decimal('100.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        qtd = aplicar_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=_ConfigStub(valor_500mb_pap_manual=145.0),
            usar_manual=True,
        )
        self.assertEqual(1, qtd)
        self.assertEqual(Decimal('145.00'), venda.adiantamento_sabado_valor)
        mock_bulk.assert_called_once()
