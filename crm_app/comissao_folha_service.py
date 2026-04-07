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


def calcular_folha_mes(ano, mes, vendedor_id=None, use_effective_date_for_display=False):
    """
    Calcula a folha de comissão do mês no formato Excel.
    use_effective_date_for_display: se True, no extrato dt_inst usa data_instalacao_fisica (quando preenchida) para consultores.
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
        LancamentoFinanceiro, ImportacaoChurn,
    )

    User = get_user_model()

    def _norm_os(val):
        if val is None or (isinstance(val, str) and not val.strip()):
            return None
        s = str(val).strip()
        # Remover prefixos comuns (OS-, OS, etc.) para cruzar com base churn
        for prefix in ('OS-', 'OS', 'os-', 'os'):
            if s.upper().startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix):].strip()
                break
        if not s:
            return None
        return s.zfill(8) if len(s) <= 8 else s

    def _norm_os_variantes(val):
        """Retorna variantes da O.S. para match (com zeros, sem zeros)."""
        n = _norm_os(val)
        if not n:
            return set()
        return {n, n.lstrip('0') or '0'}

    ano_mes = ano * 100 + mes
    mes_ant = (ano * 100 + mes - 1) if mes > 1 else ((ano - 1) * 100 + 12)
    # Aceitar anomes_gross em vários formatos (202512, 2025-12, 2025/12) para não falhar com imports antigos
    def _anomes_variantes(am):
        return [str(am), f"{am // 100}-{am % 100:02d}", f"{am // 100}/{am % 100:02d}"]
    variantes_m0 = _anomes_variantes(ano_mes)
    variantes_m1 = _anomes_variantes(mes_ant)
    churns_m0 = list(ImportacaoChurn.objects.filter(anomes_gross__in=variantes_m0).exclude(nr_ordem__isnull=True).exclude(nr_ordem='').values_list('nr_ordem', flat=True))
    churns_m1 = list(ImportacaoChurn.objects.filter(anomes_gross__in=variantes_m1).exclude(nr_ordem__isnull=True).exclude(nr_ordem='').values_list('nr_ordem', flat=True))
    set_os_churn_m0 = set()
    for os_val in churns_m0:
        if os_val is not None:
            set_os_churn_m0.update(_norm_os_variantes(str(os_val).strip()))
    set_os_churn_m1 = set()
    for os_val in churns_m1:
        if os_val is not None:
            set_os_churn_m1.update(_norm_os_variantes(str(os_val).strip()))
    set_os_churn_mes_extrato = set_os_churn_m0
    data_inicio = datetime(ano, mes, 1)
    if mes == 12:
        data_fim = datetime(ano + 1, 1, 1)
    else:
        data_fim = datetime(ano, mes + 1, 1)
    # Mês anterior (para M-1: churns instalados no mês anterior descontados na comissão deste mês)
    if mes == 1:
        data_inicio_ant = datetime(ano - 1, 12, 1)
        data_fim_ant = datetime(ano, 1, 1)
    else:
        data_inicio_ant = datetime(ano, mes - 1, 1)
        data_fim_ant = datetime(ano, mes, 1)

    consultores = User.objects.filter(is_active=True).order_by('username')
    if vendedor_id:
        consultores = consultores.filter(id=vendedor_id)
        if not consultores.exists():
            return {"periodo": f"{mes:02d}/{ano}", "ano_mes": ano * 100 + mes, "vendedores": []}

    # Regras por faixa: apenas finalidade COMISSAO (folha de pagamento). ADIANTAMENTO não entra aqui.
    from django.db.models import Q
    q_comissao = Q(finalidade='COMISSAO') | Q(finalidade__isnull=True)
    regras_faixa_perfil = list(
        RegraComissaoFaixa.objects.filter(q_comissao, vendedor__isnull=True).order_by('perfil', 'min_vendas')
    )
    regras_faixa_vendedor = defaultdict(list)
    for r in RegraComissaoFaixa.objects.filter(q_comissao, vendedor__isnull=False).select_related('vendedor'):
        regras_faixa_vendedor[r.vendedor_id].append(r)

    # Config do mês (ano, mes) com fallback para modelo padrão (ano/mes nulos)
    configs = {}
    for c in ConfigComissaoVendedor.objects.filter(ano=ano, mes=mes).select_related('usuario'):
        configs[c.usuario_id] = c
    for c in ConfigComissaoVendedor.objects.filter(ano__isnull=True, mes__isnull=True).select_related('usuario'):
        if c.usuario_id not in configs:
            configs[c.usuario_id] = c

    def _safe_min_max(r):
        """Evita comparação None > None no sorted e no intervalo."""
        min_v = r.min_vendas if r.min_vendas is not None else 0
        max_v = r.max_vendas if r.max_vendas is not None else (10 ** 9)
        return min_v, max_v

    def encontrar_faixa(consultor, qtd_vendas):
        # 1) Regra individual do vendedor
        listas = regras_faixa_vendedor.get(consultor.id, [])
        for r in sorted(listas, key=lambda x: _safe_min_max(x)[0], reverse=True):
            min_v, max_v = _safe_min_max(r)
            if min_v <= qtd_vendas <= max_v:
                return r
        # 2) Regra por perfil
        config = configs.get(consultor.id)
        perfil = (config.perfil_comissao if config else 'Vendedor') or 'Vendedor'
        for r in regras_faixa_perfil:
            if r.perfil != perfil:
                continue
            min_v, max_v = _safe_min_max(r)
            if min_v <= qtd_vendas <= max_v:
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
        # Vendas instaladas no mês anterior (para desconto M-1: churn dez descontado na comissão jan)
        vendas_m1 = Venda.objects.filter(
            vendedor=consultor,
            ativo=True,
            status_esteira__nome__iexact='INSTALADA',
            data_instalacao__gte=data_inicio_ant,
            data_instalacao__lt=data_fim_ant,
        ).select_related('plano', 'cliente', 'forma_pagamento')

        config = configs.get(consultor.id)
        # Vendas adiantadas (comissão antecipada): não entram no volume a pagar
        lancamentos_adiant = LancamentoFinanceiro.objects.filter(
            usuario=consultor,
            tipo='ADIANTAMENTO_COMISSAO',
            data__gte=data_inicio.date(),
            data__lt=data_fim.date(),
        )
        set_adiantadas = set()
        for la in lancamentos_adiant:
            ids = (la.metadados or {}).get('venda_ids') or []
            set_adiantadas.update(int(x) for x in ids if x is not None)
        vendas_para_pagar = [v for v in vendas if v.id not in set_adiantadas]
        qtd_instalada_a_pagar = len(vendas_para_pagar)
        faixa_regra = encontrar_faixa(consultor, qtd_instalada_a_pagar)
        usar_manual = config and config.usar_valor_manual

        # Por plano (chave): qtd a pagar, qtd antecipada, valor unit, total
        por_plano = defaultdict(lambda: {'qtd': 0, 'qtd_antecipada': 0, 'valor_unit': None, 'total': 0.0})
        comissao_total_geral = Decimal('0')
        for v in vendas:
            doc = (v.cliente.cpf_cnpj or '') if v.cliente else ''
            doc_limpo = ''.join(filter(str.isdigit, doc))
            tipo_cliente = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
            plano_nome = v.plano.nome if v.plano else ''
            chave = plano_tipo_to_chave(plano_nome, tipo_cliente)
            if not chave:
                continue
            if v.id in set_adiantadas:
                por_plano[chave]['qtd_antecipada'] += 1
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

        # Montar lista por_plano no formato do Excel (500MB PAP, 700MB PAP, ...) + qtd_antecipada
        labels = {
            '500MB_PAP': '500MB PAP', '700MB_PAP': '700MB PAP', '1GB_PAP': '1GB PAP',
            '500MB_CNPJ': '500MB CNPJ', '700MB_CNPJ': '700MB CNPJ', '1GB_CNPJ': '1GB CNPJ',
        }
        por_plano_lista = []
        for chave in CHAVES_PLANO:
            d = por_plano.get(chave, {'qtd': 0, 'qtd_antecipada': 0, 'valor_unit': None, 'total': 0})
            por_plano_lista.append({
                'plano': labels.get(chave, chave),
                'qtd_instalada_a_pagar': d['qtd'],
                'qtd_antecipada': d.get('qtd_antecipada', 0),
                'qtd_ja_pago': 0,
                'qtd_churn_30': 0,
                'valor_unitario_instalados': d['valor_unit'],
                'valor_unitario_churn': None,
                'valor_total_instalados': round(d['total'], 2),
                'valor_total_churn': 0,
                'comissao_total': round(d['total'], 2),
            })

        # Ajustes: descontos vêm dos lançamentos confirmados (Adiantamentos e Descontos / Confirmar Descontos) + config (INSS, etc.)
        # Não somar por venda da config: boleto/inclusão/instalação/adiant.CNPJ só entram após confirmação (LancamentoFinanceiro).
        lancamentos = LancamentoFinanceiro.objects.filter(
            usuario=consultor,
            data__gte=data_inicio.date(),
            data__lt=data_fim.date(),
        ).order_by('data', 'id')
        total_descontos = Decimal('0')
        detalhes_descontos = []
        for l in lancamentos:
            qtd = getattr(l, 'quantidade_vendas', None) or 1
            if getattr(l, 'tipo', None) == 'ADIANTAMENTO_COMISSAO':
                venda_ids = (l.metadados or {}).get('venda_ids') or []
                if venda_ids:
                    qtd = len(venda_ids)
            elif getattr(l, 'tipo', None) == 'ADIANTAMENTO_CNPJ':
                venda_ids_cnpj = (l.metadados or {}).get('venda_ids') or []
                if venda_ids_cnpj:
                    qtd = len(venda_ids_cnpj)
            desc = (l.descricao or l.get_tipo_display() or 'Desconto')
            # Exibir desconto direto (sem "Processamento Auto:") e classificar para separar boleto / adiant. CNPJ / adiant. comissão
            if getattr(l, 'tipo', None) == 'ADIANTAMENTO_COMISSAO':
                motivo_limpo = 'Adiant. Comissão'
            elif getattr(l, 'tipo', None) == 'ADIANTAMENTO_CNPJ':
                motivo_limpo = 'Adiant. CNPJ'
            elif desc.startswith('Processamento Auto:'):
                resto = desc.replace('Processamento Auto:', '').strip()
                mapa = {'BOLETO': 'Desconto Boleto', 'CNPJ': 'Adiant. CNPJ', 'VIABILIDADE': 'Desconto Inclusão', 'ANTECIPACAO': 'Desconto Antecipação'}
                partes = [mapa.get(p.strip(), p.strip()) for p in resto.split(',') if p.strip()]
                motivo_limpo = ', '.join(partes) if partes else resto
            else:
                motivo_limpo = desc
            # tipo_exibicao: boleto | adiant_cnpj | adiant_comissao | outros (para agrupar na UI)
            lt = getattr(l, 'tipo', None)
            if lt == 'ADIANTAMENTO_COMISSAO':
                tipo_exibicao = 'adiant_comissao'
            elif lt == 'ADIANTAMENTO_CNPJ':
                tipo_exibicao = 'adiant_cnpj'
            else:
                tipo_exibicao = 'outros'
            if tipo_exibicao == 'outros' and desc.startswith('Processamento Auto:'):
                resto_upper = desc.upper()
                if 'BOLETO' in resto_upper and 'CNPJ' not in resto_upper:
                    tipo_exibicao = 'boleto'
                elif 'CNPJ' in resto_upper:
                    tipo_exibicao = 'adiant_cnpj'
                elif 'BOLETO' in resto_upper:
                    tipo_exibicao = 'boleto'
            valor_item = float(l.valor)
            # Se config diz "não descontar boleto PAP", valor exibido/efetivo é 0 (quantidade continua para informação)
            if tipo_exibicao == 'boleto' and config and not getattr(config, 'desconta_boleto_pap', True):
                total_descontos += 0  # não soma no total
                valor_item = 0
            else:
                total_descontos += l.valor
            detalhes_descontos.append({'motivo': motivo_limpo, 'valor': valor_item, 'tipo_exibicao': tipo_exibicao, 'quantidade': qtd})
        if config:
            if config.inss_valor and float(config.inss_valor) > 0:
                total_descontos += config.inss_valor
                detalhes_descontos.append({'motivo': 'INSS / Encargos', 'valor': float(config.inss_valor), 'tipo_exibicao': 'outros', 'quantidade': 1})
            if config.adiantamento and float(config.adiantamento) > 0:
                total_descontos += config.adiantamento
                detalhes_descontos.append({'motivo': 'Adiantamento', 'valor': float(config.adiantamento), 'tipo_exibicao': 'outros', 'quantidade': 1})
            if config.cartao_trafego and float(config.cartao_trafego) > 0:
                total_descontos += config.cartao_trafego
                detalhes_descontos.append({'motivo': 'Cartão Tráfego', 'valor': float(config.cartao_trafego), 'tipo_exibicao': 'outros', 'quantidade': 1})
            if config.gestor_trafego and float(config.gestor_trafego) > 0:
                total_descontos += config.gestor_trafego
                detalhes_descontos.append({'motivo': 'Gestor Tráfego', 'valor': float(config.gestor_trafego), 'tipo_exibicao': 'outros', 'quantidade': 1})

        # Desconto Churn M0 e M-1: cruza base churn (ANOMES_GROSS) com Venda por O.S.; só Vendas ainda não marcadas com desconto_churn_aplicado_em
        # M0 = churns do mês da comissão (ex.: jan/26) -> vendas instaladas no mês da comissão
        # M-1 = churns do mês anterior (ex.: dez/25) -> descontado na comissão do mês atual (jan/26); vendas instaladas no mês anterior
        valor_churn_m0 = Decimal('0')
        valor_churn_m1 = Decimal('0')
        qtd_churn_m0 = 0
        qtd_churn_m1 = 0
        for v in vendas:
            if not v.ordem_servico or getattr(v, 'desconto_churn_aplicado_em', None) is not None:
                continue
            variantes = _norm_os_variantes(v.ordem_servico)
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
            valor_unit = Decimal(str(valor_unit)) if valor_unit is not None else Decimal('0')
            if variantes & set_os_churn_m0:
                valor_churn_m0 += valor_unit
                qtd_churn_m0 += 1
        for v in vendas_m1:
            if not v.ordem_servico or getattr(v, 'desconto_churn_aplicado_em', None) is not None:
                continue
            variantes = _norm_os_variantes(v.ordem_servico)
            if not (variantes & set_os_churn_m1):
                continue
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
            valor_unit = Decimal(str(valor_unit)) if valor_unit is not None else Decimal('0')
            valor_churn_m1 += valor_unit
            qtd_churn_m1 += 1
        if qtd_churn_m0 > 0 or valor_churn_m0 > 0:
            total_descontos += valor_churn_m0
            detalhes_descontos.append({'motivo': 'Desconto Churn M0', 'valor': float(valor_churn_m0), 'tipo_exibicao': 'churn_m0', 'quantidade': qtd_churn_m0})
        if qtd_churn_m1 > 0 or valor_churn_m1 > 0:
            total_descontos += valor_churn_m1
            detalhes_descontos.append({'motivo': 'Desconto Churn M-1', 'valor': float(valor_churn_m1), 'tipo_exibicao': 'churn_m1', 'quantidade': qtd_churn_m1})

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
            churn_status = 'SIM' if _norm_os_variantes(v.ordem_servico) & set_os_churn_mes_extrato else 'NÃO'
            dt_inst = (v.data_instalacao_fisica or v.data_instalacao) if use_effective_date_for_display else v.data_instalacao
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': 'SIM' if eh_cnpj else 'NÃO',
                'plano': plano_label,
                'dt_pedido': v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '',
                'dt_inst': dt_inst.strftime('%d/%m/%Y') if dt_inst else '',
                'os': v.ordem_servico or '',
                'situacao': v.status_esteira.nome if v.status_esteira else 'INSTALADA',
                'vendedor': consultor.username,
                'churn': churn_status,
                'adiantada': 'SIM' if v.id in set_adiantadas else 'NÃO',
            })
        # Incluir no extrato as vendas churn M-1 (mês anterior), para aparecerem na lista com CHURN=SIM
        for v in vendas_m1:
            if not v.ordem_servico or getattr(v, 'desconto_churn_aplicado_em', None) is not None:
                continue
            variantes = _norm_os_variantes(v.ordem_servico)
            if not (variantes & set_os_churn_m1):
                continue
            doc = (v.cliente.cpf_cnpj or '') if v.cliente else ''
            doc_limpo = ''.join(filter(str.isdigit, doc))
            eh_cnpj = len(doc_limpo) > 11
            plano_nome = v.plano.nome if v.plano else ''
            chave = plano_tipo_to_chave(plano_nome, 'CNPJ' if eh_cnpj else 'CPF')
            plano_label = labels.get(chave, plano_nome or '-')
            dacc = 'SIM' if (v.forma_pagamento and 'DÉBITO' in (v.forma_pagamento.nome or '').upper()) else 'NÃO'
            dt_inst_m1 = (v.data_instalacao_fisica or v.data_instalacao) if use_effective_date_for_display else v.data_instalacao
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': 'SIM' if eh_cnpj else 'NÃO',
                'plano': plano_label,
                'dt_pedido': v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '',
                'dt_inst': dt_inst_m1.strftime('%d/%m/%Y') if dt_inst_m1 else '',
                'os': v.ordem_servico or '',
                'situacao': 'INSTALADA (Churn M-1)',
                'vendedor': consultor.username,
                'churn': 'SIM',
                'adiantada': 'NÃO',
            })

        qtd_a_descontar_boleto = sum(d.get('quantidade', 1) for d in detalhes_descontos if (d.get('tipo_exibicao') or '').lower() == 'boleto')
        qtd_a_descontar_cnpj = sum(d.get('quantidade', 1) for d in detalhes_descontos if (d.get('tipo_exibicao') or '').lower() == 'adiant_cnpj')
        qtd_a_descontar = qtd_a_descontar_boleto + qtd_a_descontar_cnpj + qtd_churn_m0 + qtd_churn_m1

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
                'detalhes_descontos': detalhes_descontos,
                'qtd_a_descontar': qtd_a_descontar,
                'qtd_a_descontar_boleto': qtd_a_descontar_boleto,
                'qtd_a_descontar_cnpj': qtd_a_descontar_cnpj,
            },
            'extrato': extrato,
        })

    return {
        'periodo': f"{mes:02d}/{ano}",
        'ano_mes': ano * 100 + mes,
        'vendedores': resultado,
    }


def get_vendas_ids_desconto_churn_mes(ano, mes):
    """
    Retorna os IDs das Vendas que entram no desconto churn (M0 + M-1) para o mês de comissão (ano, mes).
    M0: vendas instaladas no mês da comissão que batem com churn do mês. M-1: vendas instaladas no mês anterior que batem com churn M-1.
    Usado ao fechar o mês para marcar desconto_churn_aplicado_em e não descontar duas vezes.
    """
    from .models import Venda, ImportacaoChurn

    def _norm_os_variantes(val):
        if val is None or (isinstance(val, str) and not val.strip()):
            return set()
        s = str(val).strip()
        for prefix in ('OS-', 'OS', 'os-', 'os'):
            if s.upper().startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix):].strip()
                break
        if not s:
            return set()
        n = s.zfill(8) if len(s) <= 8 else s
        return {n, n.lstrip('0') or '0'}

    ano_mes = ano * 100 + mes
    mes_ant = (ano * 100 + mes - 1) if mes > 1 else ((ano - 1) * 100 + 12)
    variantes_m0 = [str(ano_mes), f"{ano_mes // 100}-{ano_mes % 100:02d}", f"{ano_mes // 100}/{ano_mes % 100:02d}"]
    variantes_m1 = [str(mes_ant), f"{mes_ant // 100}-{mes_ant % 100:02d}", f"{mes_ant // 100}/{mes_ant % 100:02d}"]
    churns_m0 = list(ImportacaoChurn.objects.filter(anomes_gross__in=variantes_m0).exclude(nr_ordem__isnull=True).exclude(nr_ordem='').values_list('nr_ordem', flat=True))
    churns_m1 = list(ImportacaoChurn.objects.filter(anomes_gross__in=variantes_m1).exclude(nr_ordem__isnull=True).exclude(nr_ordem='').values_list('nr_ordem', flat=True))
    set_os_m0 = set()
    for os_val in churns_m0:
        set_os_m0.update(_norm_os_variantes(os_val))
    set_os_m1 = set()
    for os_val in churns_m1:
        set_os_m1.update(_norm_os_variantes(os_val))

    data_inicio = datetime(ano, mes, 1)
    data_fim = datetime(ano, mes + 1, 1) if mes < 12 else datetime(ano + 1, 1, 1)
    data_inicio_ant = datetime(ano, mes - 1, 1) if mes > 1 else datetime(ano - 1, 12, 1)
    data_fim_ant = datetime(ano, mes, 1) if mes > 1 else datetime(ano, 1, 1)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    consultores = list(User.objects.filter(is_active=True).values_list('id', flat=True))

    ids_marcar = []
    # M0: vendas instaladas no mês da comissão que batem com churn do mês
    vendas_m0 = Venda.objects.filter(
        vendedor_id__in=consultores,
        ativo=True,
        status_esteira__nome__iexact='INSTALADA',
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
        desconto_churn_aplicado_em__isnull=True,
    ).exclude(ordem_servico__isnull=True).exclude(ordem_servico='').only('id', 'ordem_servico')
    for v in vendas_m0:
        if _norm_os_variantes(v.ordem_servico) & set_os_m0:
            ids_marcar.append(v.id)
    # M-1: vendas instaladas no mês anterior que batem com churn M-1 (ex.: dez/25 descontado em jan/26)
    vendas_m1 = Venda.objects.filter(
        vendedor_id__in=consultores,
        ativo=True,
        status_esteira__nome__iexact='INSTALADA',
        data_instalacao__gte=data_inicio_ant,
        data_instalacao__lt=data_fim_ant,
        desconto_churn_aplicado_em__isnull=True,
    ).exclude(ordem_servico__isnull=True).exclude(ordem_servico='').only('id', 'ordem_servico')
    for v in vendas_m1:
        if _norm_os_variantes(v.ordem_servico) & set_os_m1:
            ids_marcar.append(v.id)
    return ids_marcar
