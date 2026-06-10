# -*- coding: utf-8 -*-
from decimal import Decimal

from django.test import SimpleTestCase

from crm_app.services.adiantamento_sabado_service import (
    calcular_complemento_adiantamento_sabado_folha,
    valor_alvo_adiantamento_sabado_folha,
    valor_pago_adiantamento_sabado_venda,
)


class _PlanoStub:
    def __init__(self, nome: str) -> None:
        self.nome = nome


class _ClienteStub:
    def __init__(self, cpf_cnpj: str = '12345678901') -> None:
        self.cpf_cnpj = cpf_cnpj


class _FaixaStub:
    def __init__(
        self,
        faixa_nome: str = 'Faixa 2',
        valor_500mb_pap: float = 150.0,
        valor_500mb_cnpj: float | None = None,
    ) -> None:
        self.faixa_nome = faixa_nome
        self.valor_500mb_pap = Decimal(str(valor_500mb_pap))
        self.valor_700mb_pap = None
        self.valor_1gb_pap = None
        self.valor_500mb_cnpj = Decimal(str(valor_500mb_cnpj)) if valor_500mb_cnpj is not None else None
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


class ValorPagoAdiantamentoSabadoTests(SimpleTestCase):
    def test_prioriza_campo_valor_pago(self) -> None:
        venda = _VendaStub(
            pk=1,
            adiantamento_sabado_valor_pago=Decimal('130.00'),
            adiantamento_sabado_valor=Decimal('180.00'),
        )
        self.assertEqual(130.0, valor_pago_adiantamento_sabado_venda(venda))

    def test_usa_lancamento_quando_campo_vazio(self) -> None:
        venda = _VendaStub(pk=2, adiantamento_sabado_valor=Decimal('180.00'))
        self.assertEqual(
            130.0,
            valor_pago_adiantamento_sabado_venda(venda, {2: 130.0}),
        )


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


class CalcularComplementoAdiantamentoSabadoFolhaTests(SimpleTestCase):
    def test_complemento_positivo_para_instalada(self) -> None:
        venda = _VendaStub(
            pk=10,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('130.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(20.0, res['total_complemento'])
        self.assertEqual(130.0, res['total_pago'])
        self.assertEqual(150.0, res['total_alvo'])
        self.assertEqual(20.0, res['por_venda'][10]['complemento'])

    def test_complemento_negativo_na_rebaixa(self) -> None:
        venda = _VendaStub(
            pk=11,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('160.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=130.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(-30.0, res['total_complemento'])

    def test_nao_calcula_sem_marcacao(self) -> None:
        venda = _VendaStub(
            pk=12,
            adiantamento_sabado_marcado=False,
            adiantamento_sabado_valor_pago=Decimal('130.00'),
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(0.0, res['total_complemento'])

    def test_complemento_manual_usa_config(self) -> None:
        venda = _VendaStub(
            pk=14,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('100.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(),
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=150.0),
            config=_ConfigStub(valor_500mb_pap_manual=145.0),
            usar_manual=True,
        )
        self.assertEqual(45.0, res['total_complemento'])


class ComplementoMeiVsCnpjTests(SimpleTestCase):
    def test_mei_usa_tabela_pap_no_complemento(self) -> None:
        venda = _VendaStub(
            pk=20,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('150.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(cpf_cnpj='12345678000199'),
            classificacao_mei='MEI',
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_pap=180.0, faixa_nome='Faixa 2'),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(30.0, res['total_complemento'])
        self.assertEqual('500MB_PAP', res['por_venda'][20]['chave'])
        self.assertEqual('MEI', res['detalhes'][0]['classificacao_mei'])
        self.assertEqual('CPF', res['detalhes'][0]['tipo_cliente'])

    def test_nmei_usa_tabela_cnpj_no_complemento(self) -> None:
        venda = _VendaStub(
            pk=21,
            adiantamento_sabado_marcado=True,
            adiantamento_sabado_valor_pago=Decimal('220.00'),
            flag_desc_adiantamento_sabado=False,
            plano=_PlanoStub('500 MB'),
            cliente=_ClienteStub(cpf_cnpj='12345678000199'),
            classificacao_mei='NMEI',
        )
        res = calcular_complemento_adiantamento_sabado_folha(
            [venda],
            faixa_regra_total=_FaixaStub(valor_500mb_cnpj=250.0, valor_500mb_pap=180.0),
            config=None,
            usar_manual=False,
        )
        self.assertEqual(30.0, res['total_complemento'])
        self.assertEqual('500MB_CNPJ', res['por_venda'][21]['chave'])
