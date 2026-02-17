# crm_app/comissao_folha_service.py
"""
Serviço de cálculo da folha de comissão no formato Excel (REGRAS_FAIXAS + REGRAS_VENDEDORES).
Mapeamento: plano.nome + tipo_cliente -> chave (500MB_PAP, 700MB_CNPJ, etc.)
"""
from decimal import Decimal
from collections import defaultdict
from datetime import datetime

CHAVES_PLANO = [
    '500MB_PAP', '700MB_PAP', '1GB_PAP',
    '500MB_CNPJ', '700MB_CNPJ', '1GB_CNPJ',
]

# Nomes de plano (normalizado) -> banda para chave
def _plano_nome_to_banda(nome):
    if not nome:
        return None
    n = (nome or '').upper().replace(' ', '')
    if '500' in n:
        return '500MB'
    if '700' in n:
        return '700MB'
    if '1GB' in n or '1G' in n:
        return '1GB'
    return None


def plano_tipo_to_chave(plano_nome, tipo_cliente):
    """
    Retorna a chave do Excel (ex: 500MB_PAP, 1GB_CNPJ) a partir do nome do plano e CPF/CNPJ.
    tipo_cliente: 'CPF' ou 'CNPJ'. PAP = CPF no Excel.
    """
    banda = _plano_nome_to_banda(plano_nome)
    if not banda:
        return None
    sufixo = 'PAP' if tipo_cliente == 'CPF' else 'CNPJ'
    chave = f"{banda}_{sufixo}"
    return chave if chave in CHAVES_PLANO else None


def get_valor_from_faixa(regra_faixa, chave):
    """Retorna o valor decimal da regra de faixa para a chave (500MB_PAP, etc.)."""
    if not regra_faixa or not chave:
        return None
    m = {
        '500MB_PAP': regra_faixa.valor_500mb_pap,
        '700MB_PAP': regra_faixa.valor_700mb_pap,
        '1GB_PAP': regra_faixa.valor_1gb_pap,
        '500MB_CNPJ': regra_faixa.valor_500mb_cnpj,
        '700MB_CNPJ': regra_faixa.valor_700mb_cnpj,
        '1GB_CNPJ': regra_faixa.valor_1gb_cnpj,
    }
    v = m.get(chave)
    return float(v) if v is not None else None


def get_valor_manual(config, chave):
    """Retorna o valor manual da config do vendedor para a chave."""
    if not config or not chave:
        return None
    m = {
        '500MB_PAP': config.valor_500mb_pap_manual,
        '700MB_PAP': config.valor_700mb_pap_manual,
        '1GB_PAP': config.valor_1gb_pap_manual,
        '500MB_CNPJ': config.valor_500mb_cnpj_manual,
        '700MB_CNPJ': config.valor_700mb_cnpj_manual,
        '1GB_CNPJ': config.valor_1gb_cnpj_manual,
    }
    v = m.get(chave)
    return float(v) if v is not None else None


def calcular_folha_mes(ano, mes, vendedor_id=None):
    """
    Calcula a folha de comissão do mês no formato Excel.
    Retorna: {
      "periodo": "01/2026",
      "ano_mes": 202601,
      "vendedores": [
        {
          "vendedor_id", "vendedor_nome",
          "resumo": { "total_qtd_instalada_a_pagar", "por_plano": [...], "comissao_total_geral", "ajustes": {...}, "liquido" },
          "extrato": [ { "venda_id", "nome", "dacc", "cnpj", "plano", "dt_pedido", "dt_inst", "os", "situacao", "vendedor", "churn" }, ... ]
        }
      ]
    }
    """
    from django.contrib.auth import get_user_model
    from .models import (
        Venda, RegraComissaoFaixa, ConfigComissaoVendedor,
        LancamentoFinanceiro,
    )

    User = get_user_model()
    data_inicio = datetime(ano, mes, 1)
    if mes == 12:
        data_fim = datetime(ano + 1, 1, 1)
    else:
        data_fim = datetime(ano, mes + 1, 1)

    consultores = User.objects.filter(is_active=True).order_by('username')
    if vendedor_id:
        consultores = consultores.filter(id=vendedor_id)
        if not consultores.exists():
            return {"periodo": f"{mes:02d}/{ano}", "ano_mes": ano * 100 + mes, "vendedores": []}

    # Regras por faixa: por perfil e por vendedor individual
    regras_faixa_perfil = list(
        RegraComissaoFaixa.objects.filter(vendedor__isnull=True).order_by('perfil', 'min_vendas')
    )
    regras_faixa_vendedor = defaultdict(list)
    for r in RegraComissaoFaixa.objects.filter(vendedor__isnull=False).select_related('vendedor'):
        regras_faixa_vendedor[r.vendedor_id].append(r)

    # Config do mês (ano, mes) com fallback para modelo padrão (ano/mes nulos)
    configs = {}
    for c in ConfigComissaoVendedor.objects.filter(ano=ano, mes=mes).select_related('usuario'):
        configs[c.usuario_id] = c
    for c in ConfigComissaoVendedor.objects.filter(ano__isnull=True, mes__isnull=True).select_related('usuario'):
        if c.usuario_id not in configs:
            configs[c.usuario_id] = c

    def encontrar_faixa(consultor, qtd_vendas):
        # 1) Regra individual do vendedor
        listas = regras_faixa_vendedor.get(consultor.id, [])
        for r in sorted(listas, key=lambda x: x.min_vendas, reverse=True):
            if r.min_vendas <= qtd_vendas <= r.max_vendas:
                return r
        # 2) Regra por perfil
        config = configs.get(consultor.id)
        perfil = (config.perfil_comissao if config else 'Vendedor') or 'Vendedor'
        for r in regras_faixa_perfil:
            if r.perfil != perfil:
                continue
            if r.min_vendas <= qtd_vendas <= r.max_vendas:
                return r
        return None

    resultado = []
    for consultor in consultores:
        vendas = Venda.objects.filter(
            vendedor=consultor,
            ativo=True,
            status_esteira__nome__iexact='INSTALADA',
            data_instalacao__gte=data_inicio,
            data_instalacao__lt=data_fim,
        ).select_related('plano', 'cliente', 'forma_pagamento')

        config = configs.get(consultor.id)
        qtd_instalada_a_pagar = vendas.count()
        faixa_regra = encontrar_faixa(consultor, qtd_instalada_a_pagar)
        usar_manual = config and config.usar_valor_manual

        # Por plano (chave): qtd, valor unit, total
        por_plano = defaultdict(lambda: {'qtd': 0, 'valor_unit': None, 'total': 0.0})
        comissao_total_geral = Decimal('0')

        for v in vendas:
            doc = (v.cliente.cpf_cnpj or '') if v.cliente else ''
            doc_limpo = ''.join(filter(str.isdigit, doc))
            tipo_cliente = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
            plano_nome = v.plano.nome if v.plano else ''
            chave = plano_tipo_to_chave(plano_nome, tipo_cliente)
            if not chave:
                continue

            if usar_manual:
                valor_unit = get_valor_manual(config, chave)
            else:
                valor_unit = get_valor_from_faixa(faixa_regra, chave) if faixa_regra else None

            valor_unit = valor_unit if valor_unit is not None else 0
            por_plano[chave]['qtd'] += 1
            por_plano[chave]['valor_unit'] = valor_unit
            por_plano[chave]['total'] += valor_unit
            comissao_total_geral += Decimal(str(valor_unit))

        # Montar lista por_plano no formato do Excel (500MB PAP, 700MB PAP, ...)
        labels = {
            '500MB_PAP': '500MB PAP', '700MB_PAP': '700MB PAP', '1GB_PAP': '1GB PAP',
            '500MB_CNPJ': '500MB CNPJ', '700MB_CNPJ': '700MB CNPJ', '1GB_CNPJ': '1GB CNPJ',
        }
        por_plano_lista = []
        for chave in CHAVES_PLANO:
            d = por_plano.get(chave, {'qtd': 0, 'valor_unit': None, 'total': 0})
            por_plano_lista.append({
                'plano': labels.get(chave, chave),
                'qtd_instalada_a_pagar': d['qtd'],
                'qtd_ja_pago': 0,
                'qtd_churn_30': 0,
                'valor_unitario_instalados': d['valor_unit'],
                'valor_unitario_churn': None,
                'valor_total_instalados': round(d['total'], 2),
                'valor_total_churn': 0,
                'comissao_total': round(d['total'], 2),
            })

        # Ajustes: descontos e bônus (lançamentos do mês + config)
        lancamentos = LancamentoFinanceiro.objects.filter(
            usuario=consultor,
            data__gte=data_inicio.date(),
            data__lt=data_fim.date(),
        )
        total_descontos = Decimal('0')
        if config:
            for v in vendas:
                if v.forma_pagamento and 'BOLETO' in (v.forma_pagamento.nome or '').upper():
                    total_descontos += (config.desconto_boleto or 0)
                if getattr(v, 'inclusao', False):
                    total_descontos += (config.desconto_inclusao or 0)
                if getattr(v, 'antecipou_instalacao', False):
                    total_descontos += (config.desconto_instalacao or 0)
                doc = (v.cliente.cpf_cnpj or '') if v.cliente else ''
                if len(''.join(filter(str.isdigit, doc))) > 11:
                    total_descontos += (config.adiantar_cnpj or 0)
            total_descontos += (config.inss_valor or 0) + (config.adiantamento or 0)
            total_descontos += (config.cartao_trafego or 0) + (config.gestor_trafego or 0)
        for l in lancamentos:
            total_descontos += l.valor  # lançamentos são descontos (valor positivo = desconto)

        total_bonus = Decimal('0')
        if config:
            total_bonus += (getattr(config, 'premiação', None) or 0) + (config.bonus_cartao_credito or 0)

        liquido = comissao_total_geral + total_bonus - total_descontos
        faixa_aplicada = (faixa_regra.faixa_nome if faixa_regra else None) or ('MANUAL' if usar_manual else '')

        ajustes = {
            'premiacao': float(getattr(config, 'premiação', None) or 0) if config else 0,
            'instalacao': 0,
            'adiantar_cnpj': 0,
            'desconto_boleto': 0,
            'gestor_trafego': float(config.gestor_trafego) if config and config.gestor_trafego else 0,
            'cartao_trafego': float(config.cartao_trafego) if config and config.cartao_trafego else 0,
            'adiantar_mes': 0,
            'churn_ate_30_dias': 0,
            'churn_acima_30_dias': 0,
        }
        if config:
            ajustes['desconto_boleto'] = float(config.desconto_boleto or 0)
            ajustes['adiantar_cnpj'] = float(config.adiantar_cnpj or 0)
            ajustes['instalacao'] = float(config.desconto_instalacao or 0)

        extrato = []
        for v in vendas:
            doc = (v.cliente.cpf_cnpj or '') if v.cliente else ''
            doc_limpo = ''.join(filter(str.isdigit, doc))
            eh_cnpj = len(doc_limpo) > 11
            plano_nome = v.plano.nome if v.plano else ''
            chave = plano_tipo_to_chave(plano_nome, 'CNPJ' if eh_cnpj else 'CPF')
            plano_label = labels.get(chave, plano_nome or '-')
            dacc = 'SIM' if (v.forma_pagamento and 'DÉBITO' in (v.forma_pagamento.nome or '').upper()) else 'NÃO'
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': 'SIM' if eh_cnpj else 'NÃO',
                'plano': plano_label,
                'dt_pedido': v.data_criacao.strftime('%Y-%m-%d') if v.data_criacao else '',
                'dt_inst': v.data_instalacao.strftime('%Y-%m-%d') if v.data_instalacao else '',
                'os': v.ordem_servico or '',
                'situacao': v.status_esteira.nome if v.status_esteira else 'INSTALADA',
                'vendedor': consultor.username,
                'churn': 'ATIVO',
            })

        resultado.append({
            'vendedor_id': consultor.id,
            'vendedor_nome': consultor.username,
            'resumo': {
                'total_qtd_instalada_a_pagar': qtd_instalada_a_pagar,
                'total_qtd_ja_pago': 0,
                'total_qtd_churn_30': 0,
                'faixa_aplicada': faixa_aplicada,
                'por_plano': por_plano_lista,
                'comissao_total_geral': float(comissao_total_geral),
                'ajustes': ajustes,
                'total_descontos': float(total_descontos),
                'total_bonus': float(total_bonus),
                'liquido': float(liquido),
            },
            'extrato': extrato,
        })

    return {
        'periodo': f"{mes:02d}/{ano}",
        'ano_mes': ano * 100 + mes,
        'vendedores': resultado,
    }
