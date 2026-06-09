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


def carregar_faixa_adiantamento_regras_faixa():
    """
    Faixa base para adiantamentos na folha.
    Regra solicitada: usar SEMPRE a primeira faixa de finalidade COMISSAO.
    """
    from .models import RegraComissaoFaixa

    faixa = RegraComissaoFaixa.objects.filter(finalidade='COMISSAO').order_by('id').first()
    return faixa


def valor_comissao_tabela_adiantamento(venda, faixa_adiantamento, chave):
    """Valor por venda conforme primeira faixa COMISSAO ou fallback plano.comissao_base."""
    if faixa_adiantamento and chave:
        v = get_valor_from_faixa(faixa_adiantamento, chave)
        if v is not None:
            return float(v)
    if venda.plano and venda.plano.comissao_base is not None:
        return float(venda.plano.comissao_base)
    return 0.0


def valor_adiantamento_exibicao_folha(venda, faixa_adiantamento, chave, origem=None):
    """
    Valor de comissão antecipada na folha/extrato.
    Adiantamento sábado: snapshot da esteira (adiantamento_sabado_valor).
    Adiantamento comissão (esteira): tabela de governança.
    """
    if origem is None:
        origem = origem_adiantamento_comissao_venda(venda)
    if origem in ('sabado', 'sabado_quitado_instalacao', 'sabado_pendente'):
        val = getattr(venda, 'adiantamento_sabado_valor', None)
        if val is not None and float(val) > 0:
            return float(val)
    return valor_comissao_tabela_adiantamento(venda, faixa_adiantamento, chave)


def data_instalacao_efetiva_folha(venda):
    """
    Data de instalação usada na folha (OSAB + física no cliente):
    - OSAB e física preenchidas → data física (no cliente)
    - Só OSAB → OSAB
    - Só física → física
    """
    osab = getattr(venda, 'data_instalacao', None)
    fis = getattr(venda, 'data_instalacao_fisica', None)
    if osab and fis:
        return fis
    if osab:
        return osab
    return fis


def annotate_data_folha_comissao(queryset):
    """
    Anota data_folha_comissao com a mesma regra de data_instalacao_efetiva_folha (SQL).
    """
    from django.db.models import Case, When, F, Q, DateField

    data_folha = Case(
        When(
            Q(data_instalacao__isnull=False) & Q(data_instalacao_fisica__isnull=False),
            then=F('data_instalacao_fisica'),
        ),
        When(data_instalacao__isnull=False, then=F('data_instalacao')),
        default=F('data_instalacao_fisica'),
        output_field=DateField(),
    )
    return queryset.annotate(data_folha_comissao=data_folha)


def vendas_instaladas_folha_periodo(consultor, data_inicio, data_fim):
    """Vendas INSTALADAS cujo mês de referência na folha cai em [data_inicio, data_fim)."""
    from .models import Venda

    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    base = Venda.objects.filter(
        vendedor=consultor,
        ativo=True,
        status_esteira__nome__iexact='INSTALADA',
    )
    return (
        annotate_data_folha_comissao(base)
        .filter(
            data_folha_comissao__isnull=False,
            data_folha_comissao__gte=di,
            data_folha_comissao__lt=df,
        )
        .select_related('plano', 'cliente', 'forma_pagamento', 'status_tratamento', 'status_esteira')
        .order_by('data_folha_comissao', 'id')
    )


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


def origem_adiantamento_comissao_venda(venda) -> str | None:
    """
    Classifica a origem do adiantamento quando a venda foi antecipada.
    None se não houver antecipação de comissão na folha.
    """
    from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

    sab_marcado = bool(getattr(venda, 'adiantamento_sabado_marcado', False))
    sab_quitado = bool(getattr(venda, 'adiantamento_sabado_quitado_em', None))

    if comissao_ja_adiantada_venda(venda):
        if sab_marcado and sab_quitado:
            return 'sabado_quitado_instalacao'
        if sab_marcado:
            return 'sabado'
        if sab_quitado:
            return 'sabado_quitado_instalacao'
        return 'esteira_comissao'

    if sab_marcado and not sab_quitado:
        return 'sabado_pendente'
    return None


def label_tipo_comissao_extrato(base_tipo: str | None, origem_adiant: str | None = None) -> str:
    """Rótulo legível para coluna TIPO COMISSÃO do extrato."""
    base = (base_tipo or '').lower()
    if base == 'a_pagar':
        return 'A pagar'
    if base == 'churn':
        return 'Churn (desconto)'
    if base == 'referencia':
        if origem_adiant == 'sabado_pendente':
            return 'Referência — adiant. sábado'
        return 'Referência (tabela)'
    if base == 'antecipada':
        return {
            'esteira_comissao': 'Antecipada — comissão (esteira)',
            'sabado': 'Antecipada — sábado',
            'sabado_quitado_instalacao': 'Antecipada — sábado (quitado na instalação)',
            'sabado_pendente': 'Antecipada — sábado',
        }.get(origem_adiant or '', 'Antecipada — comissão (esteira)')
    return '—'


def valor_comissao_linha_extrato(
    venda,
    *,
    faixa_regra,
    faixa_adiantamento,
    config,
    usar_manual,
    instalada_na_folha=False,
    churn_m1=False,
):
    """
    Valor e tipo de comissão exibidos no extrato por venda.
    Retorna (valor float|None, rótulo tipo comissão, código base).
    """
    from crm_app.services.cnpj_mei_service import tipo_cliente_comissao
    from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

    plano_nome = venda.plano.nome if venda.plano else ''
    chave = plano_tipo_to_chave(plano_nome, tipo_cliente_comissao(venda))
    origem = origem_adiantamento_comissao_venda(venda)
    if not chave:
        val = None
        if origem in ('sabado', 'sabado_quitado_instalacao', 'sabado_pendente'):
            vs = getattr(venda, 'adiantamento_sabado_valor', None)
            if vs is not None and float(vs) > 0:
                val = float(vs)
        base = 'antecipada' if comissao_ja_adiantada_venda(venda) else 'referencia'
        return val, label_tipo_comissao_extrato(base, origem), base

    tabela = valor_comissao_tabela_adiantamento(venda, faixa_adiantamento, chave)
    val_adiant = valor_adiantamento_exibicao_folha(venda, faixa_adiantamento, chave, origem)

    if churn_m1:
        if usar_manual:
            vu = get_valor_manual(config, chave)
        else:
            vu = get_valor_from_faixa(faixa_regra, chave) if faixa_regra else None
        base = 'churn'
        return (float(vu) if vu is not None else tabela), label_tipo_comissao_extrato(base, origem), base

    if instalada_na_folha:
        if comissao_ja_adiantada_venda(venda):
            base = 'antecipada'
            return val_adiant, label_tipo_comissao_extrato(base, origem), base
        if usar_manual:
            vu = get_valor_manual(config, chave)
        else:
            vu = get_valor_from_faixa(faixa_regra, chave) if faixa_regra else None
        if vu is not None:
            base = 'a_pagar'
            return float(vu), label_tipo_comissao_extrato(base, origem), base
        base = 'referencia'
        return tabela, label_tipo_comissao_extrato(base, origem), base

    base = 'referencia'
    val_ref = val_adiant if origem == 'sabado_pendente' else tabela
    return val_ref, label_tipo_comissao_extrato(base, origem), base


def calcular_folha_mes(ano, mes, vendedor_id=None, use_effective_date_for_display=False):
    """
    Calcula a folha de comissão do mês no formato Excel.
    Mês de referência: data_instalacao_efetiva_folha (OSAB + física → usa física).
    use_effective_date_for_display: legado; o extrato usa sempre a data efetiva da folha em dt_inst.
    Retorna: {
      "periodo": "01/2026",
      "ano_mes": 202601,
      "vendedores": [
        {
          "vendedor_id", "vendedor_nome",
          "resumo": { "total_qtd_instalada_a_pagar", "por_plano": [...], "comissao_total_geral", "ajustes": {...}, "liquido" },
          "extrato": [ { "venda_id", "nome", "dacc", "cnpj", "plano", "dt_pedido", "dt_inst", "os", "situacao", "vendedor", "churn", "valor_comissao", "comissao_tipo" }, ... ]
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

    faixa_adiantamento = carregar_faixa_adiantamento_regras_faixa()

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

    def _normalizar_perfil_comissao(valor):
        v = (valor or '').strip().upper()
        if not v:
            return None
        if v == 'SUPERVISOR':
            return 'Supervisor'
        if v == 'VENDEDOR':
            return 'Vendedor'
        return None

    def _perfil_comissao_do_consultor(consultor, config):
        # Prioridade: perfil real do usuário -> regra do mês -> padrão Vendedor
        perfil_usuario = getattr(getattr(consultor, 'perfil', None), 'nome', None)
        perfil_resolvido = _normalizar_perfil_comissao(perfil_usuario)
        if perfil_resolvido:
            return perfil_resolvido
        perfil_config = _normalizar_perfil_comissao(getattr(config, 'perfil_comissao', None))
        if perfil_config:
            return perfil_config
        return 'Vendedor'

    def encontrar_faixa(consultor, qtd_vendas):
        # 1) Regra individual do vendedor
        listas = regras_faixa_vendedor.get(consultor.id, [])
        for r in sorted(listas, key=lambda x: _safe_min_max(x)[0], reverse=True):
            min_v, max_v = _safe_min_max(r)
            if min_v <= qtd_vendas <= max_v:
                return r
        # 2) Regra por perfil
        config = configs.get(consultor.id)
        perfil = _perfil_comissao_do_consultor(consultor, config)
        for r in regras_faixa_perfil:
            if r.perfil != perfil:
                continue
            min_v, max_v = _safe_min_max(r)
            if min_v <= qtd_vendas <= max_v:
                return r
        return None

    resultado = []
    for consultor in consultores:
        vendas = vendas_instaladas_folha_periodo(consultor, data_inicio, data_fim)
        # Vendas instaladas no mês anterior (para desconto M-1: churn dez descontado na comissão jan)
        vendas_m1 = vendas_instaladas_folha_periodo(consultor, data_inicio_ant, data_fim_ant)

        config = configs.get(consultor.id)
        # Adiant. Comissão = Sim na esteira: não entra em QTD A PAGAR nem na comissão do mês (já adiantada).
        from crm_app.services.adiantamento_sabado_service import comissao_ja_adiantada_venda

        set_adiant_comissao_esteira = {v.id for v in vendas if comissao_ja_adiantada_venda(v)}
        vendas_para_pagar = [v for v in vendas if v.id not in set_adiant_comissao_esteira]
        qtd_instalada_a_pagar = len(vendas_para_pagar)
        faixa_regra = encontrar_faixa(consultor, qtd_instalada_a_pagar)
        usar_manual = config and config.usar_valor_manual

        # Por plano (chave): qtd a pagar, qtd antecipada (esteira), total já adiantado (primeira faixa COMISSAO)
        por_plano = defaultdict(
            lambda: {'qtd': 0, 'qtd_antecipada': 0, 'valor_unit': None, 'total': 0.0, 'total_antecipado': 0.0}
        )
        comissao_total_geral = Decimal('0')
        qtd_adiant_sem_chave_excel = 0
        valor_adiant_sem_chave_excel = 0.0
        info_adiantamento_origem = {
            'adiantamento_sabado': {'quantidade': 0, 'valor_total': 0.0},
            'adiantamento_sabado_quitado_instalacao': {'quantidade': 0, 'valor_total': 0.0},
            'adiantamento_esteira_instalados': {'quantidade': 0, 'valor_total': 0.0},
            'adiantamento_nao_classificado': {'quantidade': 0, 'valor_total': 0.0},
        }
        from crm_app.services.cnpj_mei_service import (
            CLASSIFICACAO_MEI,
            classificacao_mei_venda,
            tipo_cliente_comissao,
        )

        por_plano_cnpj_mei = defaultdict(int)
        qtd_cnpj_mei_total = 0
        qtd_cnpj_nmei_total = 0
        qtd_cpf_total = 0

        for v in vendas:
            tipo_cliente = tipo_cliente_comissao(v)
            plano_nome = v.plano.nome if v.plano else ''
            chave = plano_tipo_to_chave(plano_nome, tipo_cliente)
            doc_limpo_v = ''.join(filter(str.isdigit, (v.cliente.cpf_cnpj or '') if v.cliente else ''))
            if len(doc_limpo_v) == 14:
                if classificacao_mei_venda(v) == CLASSIFICACAO_MEI:
                    qtd_cnpj_mei_total += 1
                    if chave:
                        por_plano_cnpj_mei[chave] += 1
                else:
                    qtd_cnpj_nmei_total += 1
            elif len(doc_limpo_v) == 11:
                qtd_cpf_total += 1
            if comissao_ja_adiantada_venda(v):
                o_ant = origem_adiantamento_comissao_venda(v) or 'esteira_comissao'
                va = valor_adiantamento_exibicao_folha(v, faixa_adiantamento, chave, o_ant)
                if chave:
                    por_plano[chave]['qtd_antecipada'] += 1
                    por_plano[chave]['total_antecipado'] += va
                else:
                    qtd_adiant_sem_chave_excel += 1
                    valor_adiant_sem_chave_excel += va
                if not chave:
                    chave_origem = 'adiantamento_nao_classificado'
                else:
                    _map_origem = {
                        'esteira_comissao': 'adiantamento_esteira_instalados',
                        'sabado': 'adiantamento_sabado',
                        'sabado_quitado_instalacao': 'adiantamento_sabado_quitado_instalacao',
                        'sabado_pendente': 'adiantamento_sabado',
                    }
                    o = origem_adiantamento_comissao_venda(v) or 'esteira_comissao'
                    chave_origem = _map_origem.get(o, 'adiantamento_nao_classificado')
                info_adiantamento_origem[chave_origem]['quantidade'] += 1
                info_adiantamento_origem[chave_origem]['valor_total'] += float(va or 0)
                continue
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

        # Montar lista por_plano no formato do Excel (500MB PAP, 700MB PAP, ...) + qtd_antecipada
        labels = {
            '500MB_PAP': '500MB PAP', '700MB_PAP': '700MB PAP', '1GB_PAP': '1GB PAP',
            '500MB_CNPJ': '500MB CNPJ', '700MB_CNPJ': '700MB CNPJ', '1GB_CNPJ': '1GB CNPJ',
        }
        por_plano_lista = []
        for chave in CHAVES_PLANO:
            d = por_plano.get(
                chave,
                {'qtd': 0, 'qtd_antecipada': 0, 'valor_unit': None, 'total': 0, 'total_antecipado': 0.0},
            )
            por_plano_lista.append({
                'plano': labels.get(chave, chave),
                'qtd_instalada_a_pagar': d['qtd'],
                'qtd_cnpj_mei': por_plano_cnpj_mei.get(chave, 0),
                'qtd_antecipada': d.get('qtd_antecipada', 0),
                'valor_total_antecipado': round(float(d.get('total_antecipado', 0) or 0), 2),
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
        lancamentos = list(
            LancamentoFinanceiro.objects.filter(
                usuario=consultor,
                data__gte=data_inicio.date(),
                data__lt=data_fim.date(),
            ).order_by('data', 'id')
        )
        total_descontos = Decimal('0')
        detalhes_descontos = []
        detalhes_bonus_lancamentos = []
        for l in lancamentos:
            if getattr(l, 'tipo', None) == 'BONUS_PREMIACAO':
                motivo_bp = (l.descricao or '').strip() or 'Bônus/Premiação'
                detalhes_bonus_lancamentos.append(
                    {'motivo': motivo_bp, 'valor': float(l.valor)}
                )
                continue
            if getattr(l, 'tipo', None) == 'ADIANTAMENTO_COMISSAO':
                # Folha usa apenas a marcação na esteira + primeira faixa COMISSAO; não é desconto.
                continue
            qtd = getattr(l, 'quantidade_vendas', None) or 1
            if getattr(l, 'tipo', None) == 'ADIANTAMENTO_CNPJ':
                venda_ids_cnpj = (l.metadados or {}).get('venda_ids') or []
                if venda_ids_cnpj:
                    qtd = len(venda_ids_cnpj)
            desc = (l.descricao or l.get_tipo_display() or 'Desconto')
            # Exibir desconto direto (sem "Processamento Auto:") e classificar para separar boleto / adiant. CNPJ / adiant. comissão
            if getattr(l, 'tipo', None) == 'ADIANTAMENTO_CNPJ':
                motivo_limpo = 'Adiant. CNPJ'
            elif desc.startswith('Processamento Auto:'):
                resto = desc.replace('Processamento Auto:', '').strip()
                mapa = {
                    'BOLETO': 'Desconto Boleto',
                    'CNPJ': 'Adiant. CNPJ',
                    'VIABILIDADE': 'Desconto Inclusão',
                    'ANTECIPACAO': 'Desconto Antecipação',
                    'ADIANT_SABADO': 'Desconto adiantamento sábado',
                }
                partes = [mapa.get(p.strip(), p.strip()) for p in resto.split(',') if p.strip()]
                motivo_limpo = ', '.join(partes) if partes else resto
            else:
                motivo_limpo = desc
            # tipo_exibicao: boleto | adiant_cnpj | adiant_comissao | outros (para agrupar na UI)
            lt = getattr(l, 'tipo', None)
            if lt == 'ADIANTAMENTO_CNPJ':
                tipo_exibicao = 'adiant_cnpj'
            else:
                tipo_exibicao = 'outros'
            if tipo_exibicao == 'outros' and desc.startswith('Processamento Auto:'):
                ru = desc.upper()
                has_boleto = 'BOLETO' in ru
                has_cnpj = 'CNPJ' in ru
                has_ant = 'ANTECIPACAO' in ru
                if has_cnpj:
                    tipo_exibicao = 'adiant_cnpj'
                elif has_boleto and has_ant:
                    tipo_exibicao = 'processamento_auto_misto'
                elif has_boleto:
                    tipo_exibicao = 'boleto'
                elif has_ant:
                    tipo_exibicao = 'antecipacao_instalacao'
            # Boleto/antecipação/misto entram só pelo cálculo do mês (abaixo), não pelo lançamento automático
            if tipo_exibicao in ('boleto', 'antecipacao_instalacao', 'processamento_auto_misto'):
                continue
            total_descontos += l.valor
            detalhes_descontos.append(
                {
                    'motivo': motivo_limpo,
                    'valor': float(l.valor),
                    'tipo_exibicao': tipo_exibicao,
                    'quantidade': qtd,
                }
            )
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
            from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

            tipo_cliente = tipo_cliente_comissao(v)
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
            from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

            tipo_cliente = tipo_cliente_comissao(v)
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

        # Boleto e antecipação de instalação: vendas instaladas no mês × Desc. Boleto / Desc. Antecip. (cadastro do colaborador).
        # "Desconta Boleto PAP?" vem da Config. Comissão do mês em Regras por vendedor (vale também com comissão manual).
        desconta_boleto_pap = bool(getattr(config, 'desconta_boleto_pap', True)) if config else True
        qtd_vendas_boleto_mes = sum(
            1
            for v in vendas
            if (
                v.forma_pagamento
                and 'BOLETO' in (v.forma_pagamento.nome or '').upper()
                and not comissao_ja_adiantada_venda(v)
            )
        )
        qtd_vendas_antecip_mes = sum(1 for v in vendas if getattr(v, 'antecipou_instalacao', False))
        unit_bo = float(getattr(consultor, 'desconto_boleto', None) or 0)
        unit_ant = float(getattr(consultor, 'desconto_instalacao_antecipada', None) or 0)
        valor_boleto_cheio = (Decimal(str(unit_bo)) * qtd_vendas_boleto_mes).quantize(Decimal('0.01'))
        valor_ant_cheio = (Decimal(str(unit_ant)) * qtd_vendas_antecip_mes).quantize(Decimal('0.01'))
        valor_boleto_efetivo = valor_boleto_cheio if desconta_boleto_pap else Decimal('0')
        if qtd_vendas_boleto_mes > 0:
            total_descontos += valor_boleto_efetivo
            detalhes_descontos.append(
                {
                    'motivo': 'Descontos vendas no boleto',
                    'valor': float(valor_boleto_cheio),
                    'tipo_exibicao': 'folha_boleto_vendas',
                    'quantidade': qtd_vendas_boleto_mes,
                }
            )
        if qtd_vendas_antecip_mes > 0:
            total_descontos += valor_ant_cheio
            detalhes_descontos.append(
                {
                    'motivo': 'Desconto antecipação de instalação',
                    'valor': float(valor_ant_cheio),
                    'tipo_exibicao': 'folha_antecipacao_instalacao',
                    'quantidade': qtd_vendas_antecip_mes,
                }
            )

        # Adiantamento sábado: desconto na folha (cancelada ou safra com outra OS instalada/cancelada).
        from crm_app.services.adiantamento_sabado_service import calcular_descontos_adiantamento_sabado_folha

        descontos_sab = calcular_descontos_adiantamento_sabado_folha(consultor, data_inicio, data_fim)
        valor_sab_cancel = Decimal('0')
        qtd_sab_cancel = 0
        motivos_sab = {}
        for item in descontos_sab:
            val_sab = Decimal(str(item['valor']))
            if val_sab <= 0:
                continue
            valor_sab_cancel += val_sab
            qtd_sab_cancel += 1
            motivos_sab[item['motivo']] = motivos_sab.get(item['motivo'], 0) + 1
        if qtd_sab_cancel > 0:
            total_descontos += valor_sab_cancel
            for motivo, qtd in motivos_sab.items():
                val_motivo = sum(
                    Decimal(str(x['valor']))
                    for x in descontos_sab
                    if x['motivo'] == motivo
                )
                detalhes_descontos.append(
                    {
                        'motivo': motivo,
                        'valor': float(val_motivo),
                        'tipo_exibicao': 'folha_adiant_sabado_cancel',
                        'quantidade': qtd,
                    }
                )

        total_bonus = Decimal('0')
        detalhes_bonus = []
        if config:
            prem = getattr(config, 'premiação', None) or 0
            prem_dec = Decimal(str(prem)) if prem else Decimal('0')
            if prem_dec > 0:
                detalhes_bonus.append(
                    {
                        'motivo': 'Premiação (Regras por vendedor)',
                        'valor': float(prem_dec),
                    }
                )
                total_bonus += prem_dec
            bcc = config.bonus_cartao_credito or 0
            bcc_dec = Decimal(str(bcc)) if bcc else Decimal('0')
            if bcc_dec > 0:
                detalhes_bonus.append(
                    {
                        'motivo': 'Bônus cartão crédito (Regras por vendedor)',
                        'valor': float(bcc_dec),
                    }
                )
                total_bonus += bcc_dec
        for item in detalhes_bonus_lancamentos:
            total_bonus += Decimal(str(item['valor']))
            detalhes_bonus.append(item)

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

        from crm_app.services.cnpj_mei_service import classificacao_mei_venda, tipo_cliente_comissao

        def _campos_extrato_mei(venda):
            doc = (venda.cliente.cpf_cnpj or '') if venda.cliente else ''
            doc_limpo = ''.join(filter(str.isdigit, doc))
            eh_cnpj = len(doc_limpo) == 14
            plano_nome = venda.plano.nome if venda.plano else ''
            chave = plano_tipo_to_chave(plano_nome, tipo_cliente_comissao(venda))
            mei = classificacao_mei_venda(venda) if eh_cnpj else None
            return {
                'plano_label': labels.get(chave, plano_nome or '-'),
                'cnpj': 'SIM' if eh_cnpj else 'NÃO',
                'classificacao_mei': mei if mei else '-',
            }

        extrato = []
        for v in vendas:
            campos = _campos_extrato_mei(v)
            dacc = 'SIM' if (v.forma_pagamento and 'DÉBITO' in (v.forma_pagamento.nome or '').upper()) else 'NÃO'
            churn_status = 'SIM' if _norm_os_variantes(v.ordem_servico) & set_os_churn_mes_extrato else 'NÃO'
            dt_inst = getattr(v, 'data_folha_comissao', None) or data_instalacao_efetiva_folha(v)
            val_com, tipo_com_label, tipo_com_cod = valor_comissao_linha_extrato(
                v,
                faixa_regra=faixa_regra,
                faixa_adiantamento=faixa_adiantamento,
                config=config,
                usar_manual=usar_manual,
                instalada_na_folha=True,
            )
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': campos['cnpj'],
                'classificacao_mei': campos['classificacao_mei'],
                'plano': campos['plano_label'],
                'dt_pedido': v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '',
                'dt_inst': dt_inst.strftime('%d/%m/%Y') if dt_inst else '',
                'os': v.ordem_servico or '',
                'situacao': (
                    v.status_esteira.nome
                    if v.status_esteira
                    else (v.status_tratamento.nome if getattr(v, 'status_tratamento', None) else 'INSTALADA')
                ),
                'vendedor': consultor.username,
                'churn': churn_status,
                'adiantada': 'SIM' if comissao_ja_adiantada_venda(v) else 'NÃO',
                'valor_comissao': round(float(val_com), 2) if val_com is not None else None,
                'comissao_tipo': tipo_com_label,
                'comissao_tipo_codigo': tipo_com_cod,
            })
        # Incluir no extrato as vendas churn M-1 (mês anterior), para aparecerem na lista com CHURN=SIM
        for v in vendas_m1:
            if not v.ordem_servico or getattr(v, 'desconto_churn_aplicado_em', None) is not None:
                continue
            variantes = _norm_os_variantes(v.ordem_servico)
            if not (variantes & set_os_churn_m1):
                continue
            campos = _campos_extrato_mei(v)
            dacc = 'SIM' if (v.forma_pagamento and 'DÉBITO' in (v.forma_pagamento.nome or '').upper()) else 'NÃO'
            dt_inst_m1 = getattr(v, 'data_folha_comissao', None) or data_instalacao_efetiva_folha(v)
            val_com, tipo_com_label, tipo_com_cod = valor_comissao_linha_extrato(
                v,
                faixa_regra=faixa_regra,
                faixa_adiantamento=faixa_adiantamento,
                config=config,
                usar_manual=usar_manual,
                churn_m1=True,
            )
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': campos['cnpj'],
                'classificacao_mei': campos['classificacao_mei'],
                'plano': campos['plano_label'],
                'dt_pedido': v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '',
                'dt_inst': dt_inst_m1.strftime('%d/%m/%Y') if dt_inst_m1 else '',
                'os': v.ordem_servico or '',
                'situacao': 'INSTALADA (Churn M-1)',
                'vendedor': consultor.username,
                'churn': 'SIM',
                'adiantada': 'NÃO',
                'valor_comissao': round(float(val_com), 2) if val_com is not None else None,
                'comissao_tipo': tipo_com_label,
                'comissao_tipo_codigo': tipo_com_cod,
            })
        # Após a listagem de instaladas (como já existe hoje), incluir também as vendas
        # criadas no mês com status diferente de INSTALADA.
        vendas_criadas_mes_outros_status = (
            Venda.objects.filter(
                vendedor=consultor,
                ativo=True,
                data_criacao__gte=data_inicio,
                data_criacao__lt=data_fim,
            )
            .exclude(status_esteira__nome__iexact='INSTALADA')
            .select_related('plano', 'cliente', 'forma_pagamento', 'status_esteira', 'status_tratamento')
            .order_by('data_criacao', 'id')
        )
        for v in vendas_criadas_mes_outros_status:
            campos = _campos_extrato_mei(v)
            dacc = 'SIM' if (v.forma_pagamento and 'DÉBITO' in (v.forma_pagamento.nome or '').upper()) else 'NÃO'
            status_nome = (
                v.status_esteira.nome
                if v.status_esteira
                else (v.status_tratamento.nome if getattr(v, 'status_tratamento', None) else '-')
            )
            val_com, tipo_com_label, tipo_com_cod = valor_comissao_linha_extrato(
                v,
                faixa_regra=faixa_regra,
                faixa_adiantamento=faixa_adiantamento,
                config=config,
                usar_manual=usar_manual,
                instalada_na_folha=False,
            )
            extrato.append({
                'venda_id': v.id,
                'nome': (v.cliente.nome_razao_social or '')[:80] if v.cliente else '',
                'dacc': dacc,
                'cnpj': campos['cnpj'],
                'classificacao_mei': campos['classificacao_mei'],
                'plano': campos['plano_label'],
                'dt_pedido': v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '',
                'dt_inst': '',
                'os': v.ordem_servico or '',
                'situacao': status_nome,
                'vendedor': consultor.username,
                'churn': 'NÃO',
                'adiantada': 'NÃO',
                'valor_comissao': round(float(val_com), 2) if val_com is not None else None,
                'comissao_tipo': tipo_com_label,
                'comissao_tipo_codigo': tipo_com_cod,
            })

        qtd_a_descontar_boleto = sum(
            d.get('quantidade', 1)
            for d in detalhes_descontos
            if (d.get('tipo_exibicao') or '').lower() == 'folha_boleto_vendas'
        )
        qtd_a_descontar_antecip = sum(
            d.get('quantidade', 1)
            for d in detalhes_descontos
            if (d.get('tipo_exibicao') or '').lower() == 'folha_antecipacao_instalacao'
        )
        qtd_a_descontar_sab_cancel = sum(
            d.get('quantidade', 1)
            for d in detalhes_descontos
            if (d.get('tipo_exibicao') or '').lower() == 'folha_adiant_sabado_cancel'
        )
        qtd_a_descontar_cnpj = sum(d.get('quantidade', 1) for d in detalhes_descontos if (d.get('tipo_exibicao') or '').lower() == 'adiant_cnpj')
        qtd_a_descontar = (
            qtd_a_descontar_boleto
            + qtd_a_descontar_antecip
            + qtd_a_descontar_sab_cancel
            + qtd_a_descontar_cnpj
            + qtd_churn_m0
            + qtd_churn_m1
        )

        tot_q_adiant = sum(int(x.get('qtd_antecipada', 0) or 0) for x in por_plano_lista) + qtd_adiant_sem_chave_excel
        tot_q_pagar_antecip = int(qtd_instalada_a_pagar) + int(tot_q_adiant)
        tot_v_adiant = sum(float(x.get('valor_total_antecipado', 0) or 0) for x in por_plano_lista) + float(
            valor_adiant_sem_chave_excel
        )
        info_por_plano_adiant = [
            {
                'plano': x['plano'],
                'qtd': int(x.get('qtd_antecipada', 0) or 0),
                'valor_total': float(x.get('valor_total_antecipado', 0) or 0),
            }
            for x in por_plano_lista
            if (x.get('qtd_antecipada', 0) or 0) > 0
        ]
        if qtd_adiant_sem_chave_excel > 0:
            info_por_plano_adiant.append(
                {
                    'plano': 'Plano fora da grade (fallback)',
                    'qtd': qtd_adiant_sem_chave_excel,
                    'valor_total': round(valor_adiant_sem_chave_excel, 2),
                }
            )
        info_comissao_adiantada = {
            'quantidade_total': int(tot_q_adiant),
            'valor_total': round(tot_v_adiant, 2),
            'por_plano': info_por_plano_adiant,
            'por_origem': {
                k: {
                    'quantidade': int(v['quantidade']),
                    'valor_total': round(float(v['valor_total']), 2),
                }
                for k, v in info_adiantamento_origem.items()
            },
        }

        resultado.append({
            'vendedor_id': consultor.id,
            'vendedor_nome': consultor.username,
            'resumo': {
                'total_qtd_instalada_a_pagar': qtd_instalada_a_pagar,
                'total_qtd_instalada_antecipada': int(tot_q_adiant),
                'total_qtd_vendas_folha': tot_q_pagar_antecip,
                'total_qtd_ja_pago': 0,
                'total_qtd_churn_30': 0,
                'faixa_aplicada': faixa_aplicada,
                'por_plano': por_plano_lista,
                'comissao_total_geral': float(comissao_total_geral),
                'ajustes': ajustes,
                'total_descontos': float(total_descontos),
                'total_bonus': float(total_bonus),
                'liquido': float(liquido),
                'detalhes_bonus': detalhes_bonus,
                'detalhes_descontos': detalhes_descontos,
                'desconta_boleto_pap': desconta_boleto_pap,
                'qtd_a_descontar': qtd_a_descontar,
                'qtd_a_descontar_boleto': qtd_a_descontar_boleto,
                'qtd_a_descontar_antecip': qtd_a_descontar_antecip,
                'qtd_a_descontar_cnpj': qtd_a_descontar_cnpj,
                'info_comissao_adiantada': info_comissao_adiantada,
                'cnpj_comissao_visual': {
                    'qtd_cpf': qtd_cpf_total,
                    'qtd_cnpj_mei': qtd_cnpj_mei_total,
                    'qtd_cnpj_nmei': qtd_cnpj_nmei_total,
                },
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
    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    dia = data_inicio_ant.date() if hasattr(data_inicio_ant, 'date') else data_inicio_ant
    dfa = data_fim_ant.date() if hasattr(data_fim_ant, 'date') else data_fim_ant
    # M0: vendas instaladas no mês da comissão que batem com churn do mês
    base_m0 = Venda.objects.filter(
        vendedor_id__in=consultores,
        ativo=True,
        status_esteira__nome__iexact='INSTALADA',
        desconto_churn_aplicado_em__isnull=True,
    ).exclude(ordem_servico__isnull=True).exclude(ordem_servico='')
    vendas_m0 = annotate_data_folha_comissao(base_m0).filter(
        data_folha_comissao__isnull=False,
        data_folha_comissao__gte=di,
        data_folha_comissao__lt=df,
    ).only('id', 'ordem_servico', 'data_instalacao', 'data_instalacao_fisica')
    for v in vendas_m0:
        if _norm_os_variantes(v.ordem_servico) & set_os_m0:
            ids_marcar.append(v.id)
    # M-1: vendas instaladas no mês anterior que batem com churn M-1 (ex.: dez/25 descontado em jan/26)
    base_m1 = Venda.objects.filter(
        vendedor_id__in=consultores,
        ativo=True,
        status_esteira__nome__iexact='INSTALADA',
        desconto_churn_aplicado_em__isnull=True,
    ).exclude(ordem_servico__isnull=True).exclude(ordem_servico='')
    vendas_m1 = annotate_data_folha_comissao(base_m1).filter(
        data_folha_comissao__isnull=False,
        data_folha_comissao__gte=dia,
        data_folha_comissao__lt=dfa,
    ).only('id', 'ordem_servico', 'data_instalacao', 'data_instalacao_fisica')
    for v in vendas_m1:
        if _norm_os_variantes(v.ordem_servico) & set_os_m1:
            ids_marcar.append(v.id)
    return ids_marcar
