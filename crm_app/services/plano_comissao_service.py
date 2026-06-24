"""
Propagação de valores de comissão ao cadastrar/atualizar planos.
Vincula o plano às regras por faixa e às configs de vendedor.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction

from crm_app.comissao_folha_service import _plano_nome_to_banda
from crm_app.models import (
    ComissaoOperadora,
    ConfigComissaoVendedor,
    Plano,
    PlanoValoresComissao,
    PlanoValoresComissaoVendedor,
    RegraComissaoFaixa,
)


def _decimal_or_none(val: Any) -> Decimal | None:
    if val is None or val == '':
        return None
    return Decimal(str(val))


def inferir_banda_comissao(plano: Plano) -> str:
    """Infere banda (500MB/700MB/1GB) pelo nome do plano; senão PERSONALIZADO."""
    banda = _plano_nome_to_banda(plano.nome)
    return banda or 'PERSONALIZADO'


def get_valor_comissao_plano(plano: Plano | None, tipo_cliente: str) -> float | None:
    """Valor de comissão cadastrado no plano para CPF (PAP) ou CNPJ."""
    if not plano:
        return None
    try:
        vc = plano.valores_comissao
    except PlanoValoresComissao.DoesNotExist:
        vc = None
    if vc:
        if tipo_cliente == 'CPF' and vc.valor_pap is not None:
            return float(vc.valor_pap)
        if tipo_cliente == 'CNPJ' and vc.valor_cnpj is not None:
            return float(vc.valor_cnpj)
    if tipo_cliente == 'CPF' and plano.comissao_base is not None:
        return float(plano.comissao_base)
    return None


def get_valor_manual_plano(config, plano: Plano | None, chave: str) -> float | None:
    """Valor manual por plano na config do vendedor (prioridade sobre colunas de banda)."""
    if not config or not plano or not chave:
        return None
    try:
        row = PlanoValoresComissaoVendedor.objects.get(config=config, plano=plano)
    except PlanoValoresComissaoVendedor.DoesNotExist:
        return None
    if chave.endswith('_PAP') and row.valor_pap is not None:
        return float(row.valor_pap)
    if chave.endswith('_CNPJ') and row.valor_cnpj is not None:
        return float(row.valor_cnpj)
    return None


def _updates_faixa_por_banda(
    banda: str,
    valor_pap: Decimal | None,
    valor_cnpj: Decimal | None,
) -> dict[str, Decimal]:
    updates: dict[str, Decimal] = {}
    if banda == '500MB':
        if valor_pap is not None:
            updates['valor_500mb_pap'] = valor_pap
        if valor_cnpj is not None:
            updates['valor_500mb_cnpj'] = valor_cnpj
    elif banda == '700MB':
        if valor_pap is not None:
            updates['valor_700mb_pap'] = valor_pap
        if valor_cnpj is not None:
            updates['valor_700mb_cnpj'] = valor_cnpj
    elif banda == '1GB':
        if valor_pap is not None:
            updates['valor_1gb_pap'] = valor_pap
        if valor_cnpj is not None:
            updates['valor_1gb_cnpj'] = valor_cnpj
    return updates


def propagar_valores_para_faixas(
    banda: str,
    valor_pap: Decimal | None,
    valor_cnpj: Decimal | None,
) -> int:
    """Atualiza colunas da banda em todas as regras COMISSÃO (Regras por Faixa)."""
    if banda == 'PERSONALIZADO':
        return 0
    updates = _updates_faixa_por_banda(banda, valor_pap, valor_cnpj)
    if not updates:
        return 0
    return RegraComissaoFaixa.objects.filter(finalidade='COMISSAO').update(**updates)


def propagar_valores_para_configs_vendedor(
    plano: Plano,
    valor_pap: Decimal | None,
    valor_cnpj: Decimal | None,
) -> int:
    """Cria vínculo plano × config em cada template de vendedor (ano/mês nulos)."""
    if valor_pap is None and valor_cnpj is None:
        return 0
    configs = ConfigComissaoVendedor.objects.filter(ano__isnull=True, mes__isnull=True)
    count = 0
    for config in configs:
        PlanoValoresComissaoVendedor.objects.update_or_create(
            config=config,
            plano=plano,
            defaults={'valor_pap': valor_pap, 'valor_cnpj': valor_cnpj},
        )
        count += 1
    return count


def _garantir_comissao_operadora(plano: Plano, valor_base: Any) -> ComissaoOperadora:
    base = _decimal_or_none(valor_base)
    if base is None:
        base = Decimal('0')
    co, _ = ComissaoOperadora.objects.update_or_create(
        plano=plano,
        defaults={'valor_base': base},
    )
    return co


@transaction.atomic
def configurar_comissao_plano(
    plano: Plano,
    valores_data: dict[str, Any] | None = None,
    *,
    recebimento_operadora_base: Any = None,
    sincronizar_operadora: bool = True,
) -> PlanoValoresComissao:
    """
    Persiste valores do plano e propaga para Regras por Faixa e configs de vendedor.
    Chamado no create/update do Plano via API de governança.
    """
    valores_data = valores_data or {}
    banda = valores_data.get('banda_comissao') or inferir_banda_comissao(plano)
    valor_pap = valores_data.get('valor_pap')
    if valor_pap is None and plano.comissao_base is not None:
        valor_pap = plano.comissao_base
    valor_cnpj = valores_data.get('valor_cnpj')
    propagar_faixas = valores_data.get('propagar_faixas', True)
    propagar_vendedores = valores_data.get('propagar_vendedores', True)

    vc, _ = PlanoValoresComissao.objects.update_or_create(
        plano=plano,
        defaults={
            'banda_comissao': banda,
            'valor_pap': _decimal_or_none(valor_pap),
            'valor_cnpj': _decimal_or_none(valor_cnpj),
            'propagar_faixas': bool(propagar_faixas),
            'propagar_vendedores': bool(propagar_vendedores),
        },
    )

    if sincronizar_operadora:
        if recebimento_operadora_base is not None:
            _garantir_comissao_operadora(plano, recebimento_operadora_base)
        elif not ComissaoOperadora.objects.filter(plano=plano).exists():
            _garantir_comissao_operadora(plano, Decimal('0'))

    if propagar_faixas:
        propagar_valores_para_faixas(banda, vc.valor_pap, vc.valor_cnpj)

    if propagar_vendedores:
        propagar_valores_para_configs_vendedor(plano, vc.valor_pap, vc.valor_cnpj)

    return vc
