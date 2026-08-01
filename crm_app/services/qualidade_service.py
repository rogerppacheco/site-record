"""Serviço do módulo Qualidade (FPD + bônus M-10).

Centraliza permissões, consultas por lente (vencimento | instalação),
sincronização de faltantes, órfãos FPD e envio de cobrança (WhatsApp/e-mail).
Views devem permanecer enxutas e delegar a este serviço.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Optional

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count, Q, QuerySet
from django.db.models.functions import TruncMonth
from django.utils import timezone

from crm_app.models import (
    Cliente,
    ContratoM10,
    FaturaM10,
    ImportacaoFPD,
    SafraM10,
    StatusCRM,
    Venda,
)
from crm_app.utils import is_member
from crm_app.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HistoricoEnvioQualidade (quando existir no models.py):
#   contrato = FK(ContratoM10, related_name='historico_envios_qualidade')
#   fatura = FK(FaturaM10, null=True, blank=True)
#   canal = CharField choices WHATSAPP | EMAIL
#   destinatario = CharField
#   mensagem = TextField
#   enviado_por = FK(Usuario, null=True)
#   sucesso = BooleanField(default=True)
#   erro = TextField(null=True, blank=True)
#   criado_em = DateTimeField(auto_now_add=True)
# ---------------------------------------------------------------------------
try:
    from crm_app.models import HistoricoEnvioQualidade  # type: ignore[attr-defined]
except ImportError:
    HistoricoEnvioQualidade = None  # type: ignore[misc, assignment]

GRUPOS_QUALIDADE: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    'Qualidade',
    'Auditoria',
]
GRUPOS_VALOR_BONUS: list[str] = ['Diretoria', 'Admin']

VALOR_BONUS_M10: int = 150

LENTE_VENCIMENTO = 'vencimento'
LENTE_INSTALACAO = 'instalacao'

_MESES_PT: dict[int, str] = {
    1: 'Janeiro',
    2: 'Fevereiro',
    3: 'Março',
    4: 'Abril',
    5: 'Maio',
    6: 'Junho',
    7: 'Julho',
    8: 'Agosto',
    9: 'Setembro',
    10: 'Outubro',
    11: 'Novembro',
    12: 'Dezembro',
}


def pode_acessar_qualidade(user: Any) -> bool:
    """True se o usuário pertence a algum grupo autorizado no módulo Qualidade."""
    return is_member(user, GRUPOS_QUALIDADE)


def pode_ver_valor_bonus(user: Any) -> bool:
    """Valor R$ do bônus M-10 só para Diretoria e Admin (padrão já usado no M-10)."""
    return is_member(user, GRUPOS_VALOR_BONUS)


def mes_range(yyyy_mm: str) -> tuple[date, date]:
    """Converte YYYY-MM em (início inclusivo, fim exclusivo) do mês."""
    if not yyyy_mm or len(yyyy_mm) != 7 or yyyy_mm[4] != '-':
        raise ValueError(f'Formato de mês inválido: {yyyy_mm!r}. Use YYYY-MM.')
    ano, mes = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    if mes < 1 or mes > 12:
        raise ValueError(f'Mês inválido: {yyyy_mm!r}.')
    inicio = date(ano, mes, 1)
    fim = inicio + relativedelta(months=1)
    return inicio, fim


def _label_mes(yyyy_mm: str) -> str:
    ano, mes = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    return f'{_MESES_PT.get(mes, f"{mes:02d}")}/{ano}'


def _saudacao_periodo() -> str:
    hora = timezone.localtime().hour
    return 'bom dia' if hora < 12 else 'boa tarde'


def _contrato_tem_campo(nome: str) -> bool:
    return any(f.name == nome for f in ContratoM10._meta.get_fields())


def _eh_orfao(contrato: ContratoM10) -> bool:
    if _contrato_tem_campo('orfao'):
        return bool(getattr(contrato, 'orfao', False))
    obs = (contrato.observacao or '').lower()
    return 'órfão' in obs or 'orfao' in obs


def pode_tratar_contrato(contrato: ContratoM10) -> bool:
    """Cobrança só após vínculo: órfão ou sem CPF bloqueiam tratamento."""
    if _eh_orfao(contrato):
        return False
    cpf = (contrato.cpf_cliente or '').strip()
    return bool(cpf)


def _recalcular_totais_safra(safra_str: str) -> None:
    """Recalcula totais da SafraM10 (instalados, ativos, elegíveis, valor bônus).

    Mesma regra de ``_recalcular_totais_safra_m10`` nas views: elegível =
    ATIVO + sem downgrade + todas as faturas cadastradas pagas
    (fallback FPD paga quando não há faturas).
    """
    try:
        data_inicio, data_fim = mes_range(safra_str)
    except ValueError:
        return

    total_instalados = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
    ).count()
    total_ativos = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
        status_contrato='ATIVO',
    ).count()

    contratos_safra = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
    ).annotate(
        total_faturas=Count('faturas', distinct=True),
        faturas_pagas=Count('faturas', filter=Q(faturas__status='PAGO'), distinct=True),
    )
    elegiveis = 0
    for c in contratos_safra:
        total_f = c.total_faturas or 0
        pagas = c.faturas_pagas or 0
        if total_f == 0 and c.status_fatura_fpd and str(c.status_fatura_fpd).lower().startswith('paga'):
            total_f, pagas = 1, 1
        if (
            c.status_contrato == 'ATIVO'
            and not c.teve_downgrade
            and total_f > 0
            and pagas == total_f
        ):
            elegiveis += 1

    SafraM10.objects.filter(mes_referencia=data_inicio).update(
        total_instalados=total_instalados,
        total_ativos=total_ativos,
        total_elegivel_bonus=elegiveis,
        valor_bonus_total=elegiveis * VALOR_BONUS_M10,
    )


def _contrato_elegivel_dinamico(contrato: ContratoM10) -> bool:
    total_f = getattr(contrato, 'total_faturas', None)
    pagas = getattr(contrato, 'faturas_pagas', None)
    if total_f is None:
        total_f = contrato.faturas.count()
    if pagas is None:
        pagas = contrato.faturas.filter(status='PAGO').count()
    if total_f == 0 and contrato.status_fatura_fpd and str(contrato.status_fatura_fpd).lower().startswith('paga'):
        total_f, pagas = 1, 1
    return (
        contrato.status_contrato == 'ATIVO'
        and not contrato.teve_downgrade
        and total_f > 0
        and pagas == total_f
    )


def _corte_safra_instalacao_tratavel() -> date:
    """Primeiro dia do mês a partir do qual a safra de instalação ainda é tratável.

    Regra: a safra permanece em tratamento enquanto não completou 10 meses
    desde o mês de instalação (ciclo das 10 faturas). Ex.: em jul/2026,
    entram safras com instalação >= set/2025.
    """
    hoje = timezone.localdate()
    return (hoje.replace(day=1) - relativedelta(months=9))


def listar_periodos(lente: str) -> list[dict[str, Any]]:
    """Lista meses disponíveis na lente, ordenados do mais recente ao mais antigo.

    - ``vencimento``: meses distintos de ``data_vencimento`` da fatura 1.
    - ``instalacao``: só safras que ainda não completaram 10 meses (tratáveis).
    """
    lente_norm = (lente or LENTE_VENCIMENTO).strip().lower()
    periodos: dict[str, dict[str, Any]] = {}

    if lente_norm == LENTE_INSTALACAO:
        corte = _corte_safra_instalacao_tratavel()
        for safra in SafraM10.objects.filter(mes_referencia__gte=corte).order_by('-mes_referencia'):
            mes_key = safra.mes_referencia.strftime('%Y-%m')
            periodos[mes_key] = {
                'mes': mes_key,
                'label': _label_mes(mes_key),
                'total': safra.total_instalados or 0,
                'ativos': safra.total_ativos or 0,
                'elegiveis': safra.total_elegivel_bonus or 0,
                'tratavel': True,
            }

        qs = (
            ContratoM10.objects.filter(data_instalacao__gte=corte)
            .annotate(mes_ref=TruncMonth('data_instalacao'))
            .values('mes_ref')
            .annotate(
                total=Count('id'),
                ativos=Count('id', filter=Q(status_contrato='ATIVO')),
                elegiveis=Count('id', filter=Q(elegivel_bonus=True)),
            )
        )
        for row in qs:
            mes_ref: date | None = row['mes_ref']
            if not mes_ref:
                continue
            mes_key = mes_ref.strftime('%Y-%m')
            periodos[mes_key] = {
                'mes': mes_key,
                'label': _label_mes(mes_key),
                'total': row['total'],
                'ativos': row['ativos'],
                'elegiveis': row['elegiveis'],
                'tratavel': True,
            }
    else:
        qs = (
            FaturaM10.objects.filter(numero_fatura=1)
            .exclude(data_vencimento__isnull=True)
            .annotate(mes_ref=TruncMonth('data_vencimento'))
            .values('mes_ref')
            .annotate(
                total=Count('id'),
                pagas=Count('id', filter=Q(status='PAGO')),
                abertas=Count('id', filter=~Q(status='PAGO')),
            )
        )
        for row in qs:
            mes_ref = row['mes_ref']
            if not mes_ref:
                continue
            mes_key = mes_ref.strftime('%Y-%m')
            periodos[mes_key] = {
                'mes': mes_key,
                'label': _label_mes(mes_key),
                'total': row['total'],
                'abertas': row['abertas'],
                'pagas': row['pagas'],
            }

    return sorted(periodos.values(), key=lambda p: p['mes'], reverse=True)


def _aplicar_filtros_contratos(
    queryset: QuerySet[ContratoM10],
    filtros: dict[str, Any],
) -> QuerySet[ContratoM10]:
    vendedor = filtros.get('vendedor')
    if vendedor:
        queryset = queryset.filter(vendedor_id=vendedor)

    status = filtros.get('status') or filtros.get('status_contrato')
    if status:
        queryset = queryset.filter(status_contrato=status)

    elegivel = filtros.get('elegivel')
    if elegivel is not None and elegivel != '':
        if isinstance(elegivel, str):
            queryset = queryset.filter(elegivel_bonus=(elegivel.lower() in ('true', '1', 'sim')))
        else:
            queryset = queryset.filter(elegivel_bonus=bool(elegivel))

    orfao = filtros.get('orfao')
    if orfao is not None and orfao != '' and _contrato_tem_campo('orfao'):
        if isinstance(orfao, str):
            queryset = queryset.filter(orfao=(orfao.lower() in ('true', '1', 'sim')))
        else:
            queryset = queryset.filter(orfao=bool(orfao))

    status_tratamento_id = filtros.get('status_tratamento_id') or filtros.get('status_tratamento')
    if status_tratamento_id not in (None, ''):
        if str(status_tratamento_id).lower() in ('null', 'vazio', 'sem'):
            queryset = queryset.filter(status_tratamento__isnull=True)
        elif str(status_tratamento_id).isdigit():
            queryset = queryset.filter(status_tratamento_id=int(status_tratamento_id))

    status_fatura1 = filtros.get('status_fatura1')
    if status_fatura1:
        queryset = queryset.filter(
            faturas__numero_fatura=1,
            faturas__status=status_fatura1,
        ).distinct()

    busca = filtros.get('q') or filtros.get('busca')
    if busca:
        busca_digits = re.sub(r'\D', '', str(busca))
        filtros_busca = (
            Q(numero_contrato__icontains=busca)
            | Q(numero_contrato_definitivo__icontains=busca)
            | Q(cliente_nome__icontains=busca)
            | Q(ordem_servico__icontains=busca)
        )
        if busca_digits:
            filtros_busca |= Q(cpf_cliente__icontains=busca_digits)
        queryset = queryset.filter(filtros_busca)

    return queryset


def _q_fatura1_atrasada(hoje: date) -> Q:
    """1ª fatura em débito vencido (atrasado ou não pago com vencimento passado)."""
    return Q(faturas__numero_fatura=1) & (
        Q(faturas__status='ATRASADO')
        | (
            Q(faturas__status__in=['NAO_PAGO', 'AGUARDANDO', 'OUTROS'])
            & Q(faturas__data_vencimento__lt=hoje)
        )
    )


def _q_fatura1_em_aberto(hoje: date) -> Q:
    """1ª fatura em aberto ainda no prazo (não paga e vencimento >= hoje)."""
    return (
        Q(faturas__numero_fatura=1)
        & Q(faturas__status__in=['NAO_PAGO', 'AGUARDANDO', 'OUTROS'])
        & Q(faturas__data_vencimento__gte=hoje)
    )


def _aplicar_filtro_fila(queryset: QuerySet[ContratoM10], fila: str) -> QuerySet[ContratoM10]:
    """Filas de tratamento: atrasados (débito) x em aberto (no prazo)."""
    hoje = timezone.localdate()
    if fila == 'atrasados':
        return queryset.filter(_q_fatura1_atrasada(hoje)).distinct()
    if fila in ('abertos', 'em_aberto'):
        return queryset.filter(_q_fatura1_em_aberto(hoje)).distinct()
    return queryset


def contagens_filas_tratamento(queryset: QuerySet[ContratoM10]) -> dict[str, int]:
    """Contagens das filas sem aplicar o filtro de fila atual."""
    hoje = timezone.localdate()
    return {
        'atrasados': queryset.filter(_q_fatura1_atrasada(hoje)).distinct().count(),
        'abertos': queryset.filter(_q_fatura1_em_aberto(hoje)).distinct().count(),
        'todos': queryset.count(),
    }


def _fatura_envio_id(contrato: ContratoM10, faturas_por_contrato: dict[int, list[FaturaM10]]) -> Optional[int]:
    """Fatura em aberto mais antiga (menor número); fallback fatura 1."""
    faturas = faturas_por_contrato.get(contrato.id, [])
    abertas = [f for f in faturas if f.status != 'PAGO']
    if abertas:
        abertas.sort(key=lambda f: (f.numero_fatura or 99, f.data_vencimento or date.max))
        return abertas[0].id
    for f in faturas:
        if f.numero_fatura == 1:
            return f.id
    return None


def _vendedor_nome(contrato: ContratoM10) -> str:
    """Exibe o nickname (username) do vendedor — padrão operacional do time."""
    if not contrato.vendedor:
        return '-'
    nick = (contrato.vendedor.username or '').strip()
    if nick:
        return nick
    nome = f'{contrato.vendedor.first_name or ""} {contrato.vendedor.last_name or ""}'.strip()
    return nome or '-'


def listar_status_tratamento_qualidade() -> list[dict[str, Any]]:
    """Opções cadastradas em Cadastros Gerais (StatusCRM tipo Qualidade)."""
    return list(
        StatusCRM.objects.filter(tipo='Qualidade')
        .order_by('nome')
        .values('id', 'nome', 'cor', 'estado')
    )


def atualizar_status_tratamento_contrato(
    contrato_id: int,
    status_id: Optional[int],
) -> dict[str, Any]:
    """Atualiza o status de tratamento do BO no ContratoM10."""
    contrato = ContratoM10.objects.filter(pk=contrato_id).first()
    if not contrato:
        raise ValueError('Contrato não encontrado')

    if status_id in (None, '', 0, '0', 'null'):
        contrato.status_tratamento = None
        contrato.save(update_fields=['status_tratamento', 'atualizado_em'])
        return {
            'ok': True,
            'contrato_id': contrato.id,
            'status_tratamento_id': None,
            'status_tratamento_nome': None,
            'status_tratamento_cor': None,
        }

    status_obj = StatusCRM.objects.filter(pk=int(status_id), tipo='Qualidade').first()
    if not status_obj:
        raise ValueError('Status de Qualidade inválido. Cadastre em Cadastros Gerais → Status (tipo Qualidade).')

    contrato.status_tratamento = status_obj
    contrato.save(update_fields=['status_tratamento', 'atualizado_em'])
    return {
        'ok': True,
        'contrato_id': contrato.id,
        'status_tratamento_id': status_obj.id,
        'status_tratamento_nome': status_obj.nome,
        'status_tratamento_cor': status_obj.cor,
    }


def dashboard_qualidade(
    lente: str,
    mes: str,
    user: Any,
    filtros: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Monta KPIs + lista paginada de contratos para a lente/mês informados."""
    filtros = filtros or {}
    lente_norm = (lente or LENTE_VENCIMENTO).strip().lower()
    data_inicio, data_fim = mes_range(mes)
    ver_bonus = pode_ver_valor_bonus(user)

    status_display_map = dict(FaturaM10.STATUS_CHOICES)

    if lente_norm == LENTE_INSTALACAO:
        queryset = ContratoM10.objects.filter(
            data_instalacao__gte=data_inicio,
            data_instalacao__lt=data_fim,
        )
    else:
        contrato_ids = (
            FaturaM10.objects.filter(
                numero_fatura=1,
                data_vencimento__gte=data_inicio,
                data_vencimento__lt=data_fim,
            )
            .values_list('contrato_id', flat=True)
            .distinct()
        )
        queryset = ContratoM10.objects.filter(id__in=contrato_ids)

    # Órfãos ficam fora do tratamento por padrão (contam em "Faltam no CRM" / modal órfãos)
    if filtros.get('orfao') in (None, '') and _contrato_tem_campo('orfao'):
        queryset = queryset.filter(orfao=False)

    queryset = (
        _aplicar_filtros_contratos(queryset, filtros)
        .select_related('vendedor', 'venda', 'venda__cliente', 'status_tratamento')
        .annotate(
            total_faturas=Count('faturas', distinct=True),
            faturas_pagas=Count('faturas', filter=Q(faturas__status='PAGO'), distinct=True),
        )
        .order_by('-data_instalacao', 'id')
    )

    filas = contagens_filas_tratamento(queryset)
    reconciliacao = reconciliar_fpd_com_painel(mes, filas, lente=lente_norm)
    fila = (filtros.get('fila') or 'todos').strip().lower()
    if fila and fila != 'todos':
        queryset = _aplicar_filtro_fila(queryset, fila)

    contratos_list = list(queryset)
    for c in contratos_list:
        if c.total_faturas == 0 and c.status_fatura_fpd and str(c.status_fatura_fpd).lower().startswith('paga'):
            c.total_faturas = 1
            c.faturas_pagas = 1

    ids_contratos = [c.id for c in contratos_list]
    faturas_qs = FaturaM10.objects.filter(contrato_id__in=ids_contratos).order_by(
        'contrato_id', 'numero_fatura'
    )
    faturas_por_contrato: dict[int, list[FaturaM10]] = {}
    faturas1_map: dict[int, FaturaM10] = {}
    for f in faturas_qs:
        faturas_por_contrato.setdefault(f.contrato_id, []).append(f)
        if f.numero_fatura == 1:
            faturas1_map[f.contrato_id] = f

    total = len(contratos_list)
    ativos = sum(1 for c in contratos_list if c.status_contrato == 'ATIVO')
    elegiveis = sum(1 for c in contratos_list if _contrato_elegivel_dinamico(c))
    valor_total = elegiveis * VALOR_BONUS_M10 if ver_bonus else 0

    if lente_norm == LENTE_VENCIMENTO:
        f1_ids = [faturas1_map[c.id].id for c in contratos_list if c.id in faturas1_map]
        f1_qs = FaturaM10.objects.filter(id__in=f1_ids) if f1_ids else FaturaM10.objects.none()
        total_f1 = f1_qs.count()
        pagas_f1 = f1_qs.filter(status='PAGO').count()
        abertas_f1 = total_f1 - pagas_f1
        taxa = round((abertas_f1 / total_f1 * 100) if total_f1 > 0 else 0, 1)
        kpis: dict[str, Any] = {
            'total': total,
            'geradas': total_f1,
            'pagas': pagas_f1,
            'abertas': abertas_f1,
            'taxa_fpd': taxa,
            'ativos': ativos,
            'elegiveis': elegiveis,
            'valor_total': valor_total,
            'pode_ver_valor_bonus': ver_bonus,
        }
    else:
        taxa_permanencia = round((ativos / total * 100) if total > 0 else 0, 1)
        kpis = {
            'total': total,
            'instalados': total,
            'ativos': ativos,
            'elegiveis': elegiveis,
            'valor_total': valor_total,
            'taxa_permanencia': taxa_permanencia,
            'pode_ver_valor_bonus': ver_bonus,
        }

    try:
        page = max(1, int(filtros.get('page', 1) or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = max(1, min(250, int(filtros.get('page_size', 100) or 100)))
    except (TypeError, ValueError):
        page_size = 100
    start = (page - 1) * page_size
    end = start + page_size
    total_pages = (total + page_size - 1) // page_size if total else 0

    contratos_data: list[dict[str, Any]] = []
    for c in contratos_list[start:end]:
        is_elegivel = _contrato_elegivel_dinamico(c)
        f1 = faturas1_map.get(c.id)
        status_fatura1 = f1.status if f1 else (c.status_fatura_fpd or None)
        status_fatura1_display = (
            status_display_map.get(f1.status, f1.status) if f1 else (c.status_fatura_fpd or '-')
        )
        orfao = _eh_orfao(c)
        contato = enriquecer_contato_contrato(c)
        valor_bonus: Optional[int]
        if not ver_bonus:
            valor_bonus = None
        else:
            valor_bonus = VALOR_BONUS_M10 if is_elegivel else 0

        data_venc_f1 = f1.data_vencimento.isoformat() if f1 and f1.data_vencimento else None
        st = getattr(c, 'status_tratamento', None)
        contratos_data.append({
            'id': c.id,
            'ordem_servico': c.ordem_servico or '-',
            'cliente_nome': c.cliente_nome,
            'vendedor_nome': _vendedor_nome(c),
            'status_contrato': c.status_contrato,
            'status_fatura1': status_fatura1,
            'status_fatura1_display': status_fatura1_display,
            'data_vencimento_f1': data_venc_f1,
            'status_tratamento_id': st.id if st else None,
            'status_tratamento_nome': st.nome if st else None,
            'status_tratamento_cor': st.cor if st else None,
            'faturas_pagas': c.faturas_pagas,
            'total_faturas': c.total_faturas,
            'elegivel': is_elegivel,
            'valor_bonus': valor_bonus,
            'orfao': orfao,
            'pode_tratar': pode_tratar_contrato(c),
            'telefone': contato.get('telefone') or contato.get('telefone1'),
            'email': contato.get('email'),
            'fatura_envio_id': _fatura_envio_id(c, faturas_por_contrato),
        })

    return {
        'lente': lente_norm,
        'mes': mes,
        'label': _label_mes(mes),
        'kpis': kpis,
        'filas': filas,
        'reconciliacao': reconciliacao,
        'fila': fila if fila else 'todos',
        'status_tratamento_opcoes': listar_status_tratamento_qualidade(),
        'contratos': contratos_data,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'total': total,
        'pode_ver_valor_bonus': ver_bonus,
    }


def reconciliar_fpd_com_painel(
    mes: str,
    filas: dict[str, int],
    *,
    lente: str = 'vencimento',
) -> dict[str, Any]:
    """Compara FPD ABERTA da planilha importada com atrasados + em aberto do painel."""
    data_inicio, data_fim = mes_range(mes)
    painel = int(filas.get('atrasados') or 0) + int(filas.get('abertos') or 0)

    qs_fpd_abertas = ImportacaoFPD.objects.filter(
        indicador='FPD',
        ds_sit_fatura__iexact='ABERTA',
        dt_venc_orig__gte=data_inicio,
        dt_venc_orig__lt=data_fim,
    )
    fpd_abertas = qs_fpd_abertas.count()
    fpd_abertas_matched = qs_fpd_abertas.filter(match_status='MATCHED').count()
    faltam_crm = ImportacaoFPD.objects.filter(
        match_status='FALTA_CRM',
        indicador='FPD',
        dt_venc_orig__gte=data_inicio,
        dt_venc_orig__lt=data_fim,
    ).count()
    faltam_crm_abertas = ImportacaoFPD.objects.filter(
        match_status='FALTA_CRM',
        indicador='FPD',
        ds_sit_fatura__iexact='ABERTA',
        dt_venc_orig__gte=data_inicio,
        dt_venc_orig__lt=data_fim,
    ).count()

    return {
        'mes': mes,
        'lente': lente,
        'fpd_abertas_planilha': fpd_abertas,
        'fpd_abertas_vinculadas': fpd_abertas_matched,
        'painel_atrasados_abertos': painel,
        'diferenca': fpd_abertas_matched - painel,
        'faltam_crm_fpd': faltam_crm,
        'faltam_crm_fpd_abertas': faltam_crm_abertas,
        'bate': fpd_abertas_matched == painel,
    }


def listar_faltam_no_crm(
    *,
    indicador: Optional[str] = None,
    mes: Optional[str] = None,
    q: Optional[str] = None,
    apenas_abertas: bool = False,
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    """Linhas da planilha FPD/SPD/TPD sem ContratoM10/Venda no CRM."""
    qs = ImportacaoFPD.objects.filter(match_status='FALTA_CRM').order_by(
        '-atualizada_em', 'nr_ordem'
    )

    if indicador:
        ind = str(indicador).strip().upper()
        if ind in ('FPD', 'SPD', 'TPD'):
            qs = qs.filter(indicador=ind)

    if mes:
        data_inicio, data_fim = mes_range(mes)
        qs = qs.filter(dt_venc_orig__gte=data_inicio, dt_venc_orig__lt=data_fim)

    if apenas_abertas:
        qs = qs.filter(ds_sit_fatura__iexact='ABERTA')

    if q:
        q_clean = str(q).strip()
        qs = qs.filter(
            Q(nr_ordem__icontains=q_clean)
            | Q(id_contrato__icontains=q_clean)
            | Q(nr_fatura__icontains=q_clean)
            | Q(cd_vendedor_original__icontains=q_clean)
            | Q(municipio__icontains=q_clean)
        )

    total = qs.count()
    page = max(1, int(page or 1))
    page_size = max(1, min(250, int(page_size or 100)))
    start = (page - 1) * page_size
    end = start + page_size
    rows = list(qs[start:end])

    itens = []
    for r in rows:
        itens.append({
            'id': r.id,
            'nr_ordem': r.nr_ordem,
            'indicador': r.indicador,
            'numero_fatura_m10': r.numero_fatura_m10,
            'id_contrato': r.id_contrato,
            'nr_fatura': r.nr_fatura,
            'ds_status_fatura': r.ds_status_fatura,
            'ds_sit_fatura': r.ds_sit_fatura,
            'faixa': r.faixa,
            'nr_dias_atraso': r.nr_dias_atraso,
            'dt_venc_orig': r.dt_venc_orig.isoformat() if r.dt_venc_orig else None,
            'dt_pagamento': r.dt_pagamento.isoformat() if r.dt_pagamento else None,
            'vl_fatura': str(r.vl_fatura) if r.vl_fatura is not None else '0',
            'municipio': r.municipio,
            'uf': r.uf,
            'cd_vendedor_original': r.cd_vendedor_original,
            'nm_pdv': r.nm_pdv,
            'nm_gc': r.nm_gc,
            'atualizada_em': r.atualizada_em.isoformat() if r.atualizada_em else None,
            'dica_match': (
                'Buscar venda pelo nr_ordem (O.S.) no CRM / OSAB; '
                'confirmar se a venda está INSTALADA e se a O.S. está preenchida.'
            ),
        })

    base_totais = ImportacaoFPD.objects.filter(match_status='FALTA_CRM')
    if mes:
        data_inicio, data_fim = mes_range(mes)
        base_totais = base_totais.filter(
            dt_venc_orig__gte=data_inicio, dt_venc_orig__lt=data_fim
        )
    totais_indicador = {
        row['indicador']: row['c']
        for row in base_totais.values('indicador').annotate(c=Count('id'))
    }

    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'total_pages': (total + page_size - 1) // page_size if total else 0,
        'totais_indicador': totais_indicador,
        'itens': itens,
    }


def sincronizar_faltantes(mes_yyyy_mm: str, user: Any) -> dict[str, Any]:
    """Cria ContratoM10 a partir de Vendas INSTALADAS do mês ainda sem contrato.

    Espelha a lógica de ``PopularSafraM10View``: garante SafraM10, cria faltantes
    e recalcula totais. Retorna contagens da operação.
    """
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para sincronizar faltantes no Qualidade.')

    data_inicio, data_fim = mes_range(mes_yyyy_mm)
    safra, safra_criada = SafraM10.objects.get_or_create(
        mes_referencia=data_inicio,
        defaults={
            'total_instalados': 0,
            'total_ativos': 0,
            'total_elegivel_bonus': 0,
            'valor_bonus_total': 0,
        },
    )

    vendas = (
        Venda.objects.filter(
            data_instalacao__gte=data_inicio,
            data_instalacao__lt=data_fim,
            data_instalacao__isnull=False,
            ativo=True,
            status_esteira__nome__iexact='INSTALADA',
        )
        .order_by('data_criacao')
        .select_related('cliente', 'vendedor', 'status_esteira', 'plano')
    )

    contratos_criados = 0
    contratos_duplicados = 0

    for venda in vendas:
        numero_contrato = venda.ordem_servico or f'VENDA_{venda.id}'
        if venda.ordem_servico:
            contrato_existe = ContratoM10.objects.filter(ordem_servico=venda.ordem_servico).exists()
        else:
            contrato_existe = ContratoM10.objects.filter(numero_contrato=numero_contrato).exists()

        if contrato_existe:
            contratos_duplicados += 1
            continue

        ContratoM10.objects.create(
            safra=mes_yyyy_mm,
            venda=venda,
            numero_contrato=numero_contrato,
            ordem_servico=venda.ordem_servico,
            cliente_nome=venda.cliente.nome_razao_social if venda.cliente else 'N/D',
            cpf_cliente=venda.cliente.cpf_cnpj if venda.cliente else '',
            vendedor=venda.vendedor,
            data_instalacao=venda.data_instalacao,
            plano_original=venda.plano.nome if venda.plano else 'N/D',
            plano_atual=venda.plano.nome if venda.plano else 'N/D',
            valor_plano=venda.plano.valor if venda.plano else 0,
            status_contrato='ATIVO',
            observacao=f'Importado de Venda #{venda.id} (sincronizar faltantes)',
        )
        contratos_criados += 1
        try:
            contrato_novo = ContratoM10.objects.get(numero_contrato=numero_contrato)
            contrato_novo.criar_ou_atualizar_faturas()
        except Exception:
            logger.exception('Falha ao criar faturas no sync OS=%s', venda.ordem_servico)

    total_contratos_safra = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
    ).count()
    total_ativos = ContratoM10.objects.filter(
        data_instalacao__gte=data_inicio,
        data_instalacao__lt=data_fim,
        status_contrato='ATIVO',
    ).count()
    safra.total_instalados = total_contratos_safra
    safra.total_ativos = total_ativos
    safra.save(update_fields=['total_instalados', 'total_ativos', 'atualizado_em'])
    _recalcular_totais_safra(mes_yyyy_mm)

    logger.info(
        '[Qualidade] sincronizar_faltantes mes=%s user=%s criados=%s duplicados=%s',
        mes_yyyy_mm,
        getattr(user, 'id', None),
        contratos_criados,
        contratos_duplicados,
    )
    return {
        'mes': mes_yyyy_mm,
        'safra_id': safra.id,
        'safra_criada': safra_criada,
        'contratos_criados': contratos_criados,
        'contratos_duplicados': contratos_duplicados,
        'total_contratos_safra': total_contratos_safra,
        'total_ativos': total_ativos,
    }


def criar_contrato_orfao_fpd(
    *,
    ordem_servico: Optional[str] = None,
    id_contrato: Optional[str] = None,
    cliente_nome: Optional[str] = None,
    dt_vencimento: Optional[date] = None,
    valor_fatura: Optional[Any] = None,
    status_fatura: Optional[str] = None,
) -> ContratoM10:
    """Cria ContratoM10 mínimo a partir de linha FPD sem match no sistema.

    Órfãos não podem ser tratados (cobrança) até haver CPF/vínculo com cliente.
    ``data_instalacao`` usa o vencimento FPD (ou hoje) só como placeholder.
    """
    os_clean = (ordem_servico or '').strip() or None
    id_clean = (id_contrato or '').strip() or None
    numero = id_clean or os_clean
    if not numero:
        raise ValueError('Informe ordem_servico ou id_contrato para criar órfão FPD.')

    if os_clean and ContratoM10.objects.filter(ordem_servico=os_clean).exists():
        return ContratoM10.objects.get(ordem_servico=os_clean)
    if ContratoM10.objects.filter(numero_contrato=numero).exists():
        return ContratoM10.objects.get(numero_contrato=numero)

    data_inst = dt_vencimento or timezone.localdate()
    nome = (cliente_nome or '').strip() or 'A identificar'

    kwargs: dict[str, Any] = {
        'venda': None,
        'numero_contrato': numero,
        'ordem_servico': os_clean,
        'numero_contrato_definitivo': id_clean,
        'cliente_nome': nome,
        'cpf_cliente': '',
        'vendedor': None,
        'data_instalacao': data_inst,
        'plano_original': 'N/D',
        'plano_atual': 'N/D',
        'valor_plano': 0,
        'status_contrato': 'ATIVO',
        'data_vencimento_fpd': dt_vencimento,
        'status_fatura_fpd': status_fatura,
        'valor_fatura_fpd': valor_fatura,
        'observacao': 'Órfão FPD — aguardando vínculo/CPF para tratamento',
    }
    if _contrato_tem_campo('orfao'):
        kwargs['orfao'] = True

    contrato = ContratoM10.objects.create(**kwargs)
    logger.info(
        '[Qualidade] contrato órfão criado id=%s os=%s numero=%s',
        contrato.id,
        os_clean,
        numero,
    )
    return contrato


def enriquecer_contato_contrato(contrato: ContratoM10) -> dict[str, Any]:
    """Obtém telefone(s) da Venda e e-mail do Cliente vinculados ao contrato."""
    telefone1 = None
    telefone2 = None
    email = None

    venda = getattr(contrato, 'venda', None)
    if venda is not None:
        telefone1 = (venda.telefone1 or '').strip() or None
        telefone2 = (venda.telefone2 or '').strip() or None
        cliente = getattr(venda, 'cliente', None)
        if cliente is not None:
            email = (cliente.email or '').strip() or None

    if not email and venda is None and contrato.cpf_cliente:
        cliente_alt = Cliente.objects.filter(cpf_cnpj=contrato.cpf_cliente).first()
        if cliente_alt:
            email = (cliente_alt.email or '').strip() or None

    if _contrato_tem_campo('telefone') and not telefone1:
        telefone1 = (getattr(contrato, 'telefone', None) or '').strip() or None
    if _contrato_tem_campo('email') and not email:
        email = (getattr(contrato, 'email', None) or '').strip() or None

    return {
        'telefone': telefone1 or telefone2,
        'telefone1': telefone1,
        'telefone2': telefone2,
        'email': email,
    }


def atualizar_contato(
    contrato_id: int,
    telefone: Optional[str] = None,
    email: Optional[str] = None,
) -> dict[str, Any]:
    """Atualiza telefone na Venda e e-mail no Cliente (quando houver vínculo).

    Se o ContratoM10 ganhar campos próprios de contato, também os persiste.
    """
    try:
        contrato = ContratoM10.objects.select_related('venda', 'venda__cliente').get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    atualizado: dict[str, Any] = {
        'contrato_id': contrato.id,
        'telefone': None,
        'email': None,
        'venda_atualizada': False,
        'cliente_atualizado': False,
    }

    tel = (telefone or '').strip() or None
    mail = (email or '').strip() or None

    venda = contrato.venda
    if tel and venda:
        venda.telefone1 = tel
        venda.save(update_fields=['telefone1', 'data_ultima_alteracao'])
        atualizado['venda_atualizada'] = True
        atualizado['telefone'] = tel
    elif tel and _contrato_tem_campo('telefone'):
        setattr(contrato, 'telefone', tel)
        contrato.save(update_fields=['telefone', 'atualizado_em'])
        atualizado['telefone'] = tel

    cliente: Optional[Cliente] = venda.cliente if venda else None
    if mail and cliente:
        cliente.email = mail
        cliente.save(update_fields=['email'])
        atualizado['cliente_atualizado'] = True
        atualizado['email'] = mail
    elif mail and _contrato_tem_campo('email'):
        setattr(contrato, 'email', mail)
        contrato.save(update_fields=['email', 'atualizado_em'])
        atualizado['email'] = mail

    if not atualizado['telefone'] or not atualizado['email']:
        contato = enriquecer_contato_contrato(contrato)
        atualizado['telefone'] = atualizado['telefone'] or contato.get('telefone')
        atualizado['email'] = atualizado['email'] or contato.get('email')

    return atualizado


def montar_mensagem_cobranca_roteiro1(
    contrato: ContratoM10,
    fatura: FaturaM10,
    nome_parceiro: str = 'Record PAP',
    nome_atendente: str = '_________',
) -> str:
    """Monta texto do Roteiro 1 da Jornada de Cobrança (2ª via + barras + PIX)."""
    nome_cliente = (contrato.cliente_nome or 'cliente').strip()
    saudacao = _saudacao_periodo()
    codigo_barras = (fatura.codigo_barras or '').strip() or '(código de barras indisponível)'
    codigo_pix = (fatura.codigo_pix or '').strip() or '(PIX indisponível)'

    return (
        f'Olá, {saudacao} Sr(a). {nome_cliente}.\n'
        f'Me chamo {nome_atendente}, sou especialista de qualidade do ({nome_parceiro}), '
        f'parceiro Oficial da Nio Fibra.\n'
        f'Identificamos um valor pendente referente ao seu plano Nio Fibra. '
        f'Segue a 2ª via da sua fatura, juntamente com o código de barras e a chave PIX.\n'
        f'Cód. de Barras:\n{codigo_barras}\n'
        f'PIX (Pagamento Instantâneo):\n{codigo_pix}\n'
        f'Destinatário: CLIENT CO SERVIÇOS DE RED\n'
        f'Caso o pagamento já tenha sido realizado, pedimos desculpas pelo incomodo e por favor, '
        f'desconsidere esta mensagem.\n'
        f'Lembramos que a confirmação do pagamento pode levar até 5 dias úteis.\n'
        f'Para agilizar a atualização do sistema, se possível, pedimos a gentileza de compartilhar '
        f'o comprovante de pagamento.\n'
        f'Você também pode acompanhar sua conta e faturas através do app Nio.\n'
        f'Instale o aplicativo no seu aparelho celular:\n'
        f'Disponível para Android e iOS:\n'
        f'Google Play Store (Android) https://play.google.com/store/apps/details?id=br.com.niointernet.app\n'
        f'Apple Store (iOS)  https://apps.apple.com/br/app/nio-internet/id6746278488\n'
        f'Você ainda pode realizar contato pelos canais de comunicação oficiais da Nio:\n'
        f'SAC:0800 001 1000\n'
        f'WhatsApp: 21-3605-1000\n\n'
        f'Obrigado e tenha um {saudacao}!'
    )


def _registrar_historico_envio(
    *,
    contrato: ContratoM10,
    fatura: Optional[FaturaM10],
    canal: str,
    destinatario: str,
    mensagem: str,
    user: Any,
    sucesso: bool,
    erro: Optional[str] = None,
) -> None:
    if HistoricoEnvioQualidade is None:
        return
    try:
        HistoricoEnvioQualidade.objects.create(
            contrato=contrato,
            fatura=fatura,
            canal=canal,
            destinatario=destinatario,
            mensagem=mensagem,
            enviado_por=user if getattr(user, 'pk', None) else None,
            sucesso=sucesso,
            erro=erro or '',
        )
    except Exception:
        logger.exception('[Qualidade] Falha ao registrar HistoricoEnvioQualidade')


def enviar_cobranca_whatsapp(
    contrato_id: int,
    fatura_id: int,
    user: Any,
    telefone_override: Optional[str] = None,
    *,
    modo: str = "auto",
) -> dict[str, Any]:
    """
    Envia cobrança via WhatsApp.

    modo:
      - auto: template Meta se habilitado; senão Roteiro 1 (PIX/barras)
      - template: só template (lembrete/vencida/recorrente conforme dias)
      - roteiro1: texto completo com 2ª via (janela 24h / após botão)
    """
    try:
        contrato = ContratoM10.objects.select_related('venda', 'venda__cliente', 'vendedor').get(
            pk=contrato_id
        )
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    if not pode_tratar_contrato(contrato):
        return {
            'ok': False,
            'erro': 'Contrato órfão ou sem CPF — tratamento bloqueado até vínculo.',
        }

    try:
        fatura = FaturaM10.objects.get(pk=fatura_id, contrato=contrato)
    except FaturaM10.DoesNotExist as exc:
        raise ValueError(f'Fatura {fatura_id} não encontrada para o contrato.') from exc

    contato = enriquecer_contato_contrato(contrato)
    telefone = (telefone_override or '').strip() or contato.get('telefone')
    if not telefone:
        return {'ok': False, 'erro': 'Telefone não informado. Informe e grave o contato do cliente.'}

    if telefone_override:
        atualizar_contato(contrato.id, telefone=telefone_override)

    nome_atendente = ''
    if user is not None:
        nome_atendente = (
            getattr(user, 'first_name', None)
            or getattr(user, 'username', None)
            or '_________'
        )
    mensagem = montar_mensagem_cobranca_roteiro1(
        contrato,
        fatura,
        nome_atendente=nome_atendente or '_________',
    )

    from crm_app.services.whatsapp.nio_templates import (
        TEMPLATE_FATURA_LEMBRETE_5D,
        TEMPLATE_FATURA_RECORRENTE,
        TEMPLATE_FATURA_VENCIDA_5D,
        enviar_template_fatura,
        templates_habilitados,
    )

    modo_eff = (modo or 'auto').strip().lower()
    usar_template = modo_eff == 'template' or (
        modo_eff == 'auto' and templates_habilitados()
    )

    canal = 'roteiro1'
    ok = False
    resp: Any = None
    try:
        if usar_template and modo_eff != 'roteiro1':
            hoje = timezone.localdate()
            venc = fatura.data_vencimento
            dias_ate = (venc - hoje).days
            dias_atraso = (hoje - venc).days
            nome_cli = (contrato.cliente_nome or 'Cliente').strip()
            if dias_ate >= 0:
                tpl = TEMPLATE_FATURA_LEMBRETE_5D
                incluir_atraso = False
            elif dias_atraso <= 7:
                tpl = TEMPLATE_FATURA_VENCIDA_5D
                incluir_atraso = False
            else:
                tpl = TEMPLATE_FATURA_RECORRENTE
                incluir_atraso = True
            ok, resp, canal = enviar_template_fatura(
                telefone,
                tpl,
                nome_cli,
                fatura,
                fallback_texto=mensagem,
                incluir_dias_atraso=incluir_atraso,
            )
        else:
            ok, resp = WhatsAppService.para_cliente().enviar_mensagem_texto(
                telefone, mensagem, variar=False
            )
            canal = 'roteiro1'
    except Exception as exc:
        logger.exception('[Qualidade] Erro WhatsApp contrato=%s', contrato_id)
        _registrar_historico_envio(
            contrato=contrato,
            fatura=fatura,
            canal='WHATSAPP',
            destinatario=telefone,
            mensagem=mensagem,
            user=user,
            sucesso=False,
            erro=str(exc),
        )
        return {'ok': False, 'erro': str(exc)}

    _registrar_historico_envio(
        contrato=contrato,
        fatura=fatura,
        canal='WHATSAPP',
        destinatario=telefone,
        mensagem=f'[{canal}] {mensagem[:500]}',
        user=user,
        sucesso=bool(ok),
        erro=None if ok else str(resp),
    )
    return {
        'ok': bool(ok),
        'telefone': telefone,
        'fatura_id': fatura.id,
        'mensagem': mensagem,
        'canal': canal,
        'resposta': resp,
        'erro': None if ok else (str(resp) if resp else 'Falha no envio WhatsApp'),
    }


def enviar_cobranca_email(
    contrato_id: int,
    fatura_id: int,
    user: Any,
    email_override: Optional[str] = None,
) -> dict[str, Any]:
    """Envia cobrança Roteiro 1 por e-mail. Bloqueia órfão ou sem CPF."""
    try:
        contrato = ContratoM10.objects.select_related('venda', 'venda__cliente', 'vendedor').get(
            pk=contrato_id
        )
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    if not pode_tratar_contrato(contrato):
        return {
            'ok': False,
            'erro': 'Contrato órfão ou sem CPF — tratamento bloqueado até vínculo.',
        }

    try:
        fatura = FaturaM10.objects.get(pk=fatura_id, contrato=contrato)
    except FaturaM10.DoesNotExist as exc:
        raise ValueError(f'Fatura {fatura_id} não encontrada para o contrato.') from exc

    contato = enriquecer_contato_contrato(contrato)
    destino = (email_override or '').strip() or contato.get('email')
    if not destino:
        return {'ok': False, 'erro': 'E-mail não informado. Informe e grave o contato do cliente.'}

    if email_override:
        atualizar_contato(contrato.id, email=email_override)

    nome_atendente = ''
    if user is not None:
        nome_atendente = (
            getattr(user, 'first_name', None)
            or getattr(user, 'username', None)
            or '_________'
        )
    mensagem = montar_mensagem_cobranca_roteiro1(
        contrato,
        fatura,
        nome_atendente=nome_atendente or '_________',
    )
    assunto = f'2ª via da fatura Nio Fibra — {contrato.cliente_nome or "cliente"}'
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(
        settings, 'EMAIL_HOST_USER', None
    )
    if not from_email:
        return {'ok': False, 'erro': 'Remetente de e-mail não configurado (DEFAULT_FROM_EMAIL).'}

    try:
        msg = EmailMultiAlternatives(
            subject=assunto,
            body=mensagem,
            from_email=from_email,
            to=[destino],
        )
        msg.attach_alternative(f'<pre style="font-family:sans-serif">{mensagem}</pre>', 'text/html')
        msg.send(fail_silently=False)
        ok = True
        erro = None
    except Exception as exc:
        logger.exception('[Qualidade] Erro e-mail contrato=%s', contrato_id)
        ok = False
        erro = str(exc)

    _registrar_historico_envio(
        contrato=contrato,
        fatura=fatura,
        canal='EMAIL',
        destinatario=destino,
        mensagem=mensagem,
        user=user,
        sucesso=ok,
        erro=erro,
    )
    return {
        'ok': ok,
        'email': destino,
        'fatura_id': fatura.id,
        'mensagem': mensagem,
        'erro': erro,
    }


STATUS_FATURA_EDITAVEIS: list[str] = ['PAGO', 'NAO_PAGO', 'AGUARDANDO', 'ATRASADO', 'OUTROS']


def detalhe_contrato_faturas(contrato_id: int) -> dict[str, Any]:
    """Retorna contrato + até 10 faturas para o painel de edição do BO."""
    try:
        contrato = ContratoM10.objects.select_related('vendedor', 'venda', 'venda__cliente').get(
            pk=contrato_id
        )
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    # Garante esqueleto 1–10 criando só as faltantes (não sobrescreve datas já editadas)
    existentes = set(
        contrato.faturas.values_list('numero_fatura', flat=True)
    )
    if contrato.data_instalacao and len(existentes) < 10:
        for i in range(1, 11):
            if i in existentes:
                continue
            try:
                FaturaM10.objects.create(
                    contrato=contrato,
                    numero_fatura=i,
                    data_vencimento=contrato.calcular_vencimento_fatura_n(i),
                    data_disponibilidade=contrato.calcular_data_disponibilidade(i),
                    valor=contrato.valor_plano or 0,
                    status='NAO_PAGO',
                )
            except Exception:
                logger.exception(
                    '[Qualidade] Falha ao criar fatura %s contrato=%s', i, contrato_id
                )

    faturas_qs = contrato.faturas.all().order_by('numero_fatura')
    faturas: list[dict[str, Any]] = []
    pagas = 0
    for f in faturas_qs:
        if f.status == 'PAGO':
            pagas += 1
        tem_pdf = bool(f.arquivo_pdf) or bool(f.pdf_url)
        faturas.append({
            'id': f.id,
            'numero_fatura': f.numero_fatura,
            'status': f.status,
            'status_display': f.get_status_display(),
            'data_vencimento': f.data_vencimento.isoformat() if f.data_vencimento else '',
            'data_pagamento': f.data_pagamento.isoformat() if f.data_pagamento else '',
            'data_promessa_pagamento': (
                f.data_promessa_pagamento.isoformat() if f.data_promessa_pagamento else ''
            ),
            'valor': float(f.valor) if f.valor is not None else 0,
            'codigo_pix': f.codigo_pix or '',
            'codigo_barras': f.codigo_barras or '',
            'tem_pdf': tem_pdf,
            'pdf_url': f.pdf_url or '',
            'download_url': f'/api/qualidade/faturas/{f.id}/pdf/' if tem_pdf else '',
        })

    total = len(faturas)
    elegivel = _contrato_elegivel_dinamico(contrato)
    return {
        'id': contrato.id,
        'ordem_servico': contrato.ordem_servico or '-',
        'cliente_nome': contrato.cliente_nome,
        'cpf_cliente': contrato.cpf_cliente or '',
        'vendedor_nome': _vendedor_nome(contrato),
        'status_contrato': contrato.status_contrato,
        'orfao': _eh_orfao(contrato),
        'pode_tratar': pode_tratar_contrato(contrato),
        'faturas_pagas': pagas,
        'total_faturas': total,
        'elegivel': elegivel,
        'faturas': faturas,
        'status_choices': [
            {'value': v, 'label': lbl} for v, lbl in FaturaM10.STATUS_CHOICES
        ],
    }


def salvar_faturas_contrato(
    contrato_id: int,
    faturas_payload: list[dict[str, Any]],
    user: Any,
) -> dict[str, Any]:
    """Atualiza status, valor, vencimento, pagamento, PIX e código de barras em lote.

    Recalcula elegibilidade ao final.
    """
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para editar faturas no Qualidade.')

    try:
        contrato = ContratoM10.objects.get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    atualizadas = 0
    erros: list[str] = []

    for item in faturas_payload or []:
        fatura_id = item.get('id')
        if not fatura_id:
            continue
        try:
            fatura = FaturaM10.objects.get(pk=fatura_id, contrato=contrato)
        except FaturaM10.DoesNotExist:
            erros.append(f'Fatura {fatura_id} não pertence ao contrato.')
            continue

        campos: list[str] = []
        if 'status' in item and item['status']:
            st = str(item['status']).upper()
            if st in STATUS_FATURA_EDITAVEIS:
                fatura.status = st
                campos.append('status')
            else:
                erros.append(f'Status inválido na fatura {fatura.numero_fatura}: {st}')

        if 'valor' in item and item['valor'] is not None and item['valor'] != '':
            try:
                fatura.valor = float(str(item['valor']).replace(',', '.'))
                campos.append('valor')
            except (TypeError, ValueError):
                erros.append(f'Valor inválido na fatura {fatura.numero_fatura}')

        if 'data_vencimento' in item:
            raw = item.get('data_vencimento') or None
            if raw:
                try:
                    fatura.data_vencimento = date.fromisoformat(str(raw)[:10])
                    campos.append('data_vencimento')
                except ValueError:
                    erros.append(f'Vencimento inválido na fatura {fatura.numero_fatura}')

        if 'data_pagamento' in item:
            raw = item.get('data_pagamento') or None
            if raw:
                try:
                    fatura.data_pagamento = date.fromisoformat(str(raw)[:10])
                    campos.append('data_pagamento')
                except ValueError:
                    erros.append(f'Pagamento inválido na fatura {fatura.numero_fatura}')
            elif raw == '' or raw is None:
                if fatura.data_pagamento is not None:
                    fatura.data_pagamento = None
                    campos.append('data_pagamento')

        if 'data_promessa_pagamento' in item:
            raw = item.get('data_promessa_pagamento') or None
            if raw:
                try:
                    fatura.data_promessa_pagamento = date.fromisoformat(str(raw)[:10])
                    campos.append('data_promessa_pagamento')
                except ValueError:
                    erros.append(f'Promessa inválida na fatura {fatura.numero_fatura}')
            else:
                if fatura.data_promessa_pagamento is not None:
                    fatura.data_promessa_pagamento = None
                    campos.append('data_promessa_pagamento')

        if 'codigo_pix' in item:
            fatura.codigo_pix = (item.get('codigo_pix') or '').strip() or None
            campos.append('codigo_pix')

        if 'codigo_barras' in item:
            fatura.codigo_barras = (item.get('codigo_barras') or '').strip() or None
            campos.append('codigo_barras')

        # Se marcou PAGO e não tem data_pagamento, usa hoje
        if fatura.status == 'PAGO' and not fatura.data_pagamento:
            fatura.data_pagamento = timezone.localdate()
            if 'data_pagamento' not in campos:
                campos.append('data_pagamento')

        if campos:
            campos.append('atualizado_em')
            fatura.save(update_fields=list(dict.fromkeys(campos)))
            atualizadas += 1

            # Espelha fatura 1 nos campos FPD do contrato
            if fatura.numero_fatura == 1:
                contrato.data_vencimento_fpd = fatura.data_vencimento
                contrato.data_pagamento_fpd = fatura.data_pagamento
                contrato.status_fatura_fpd = fatura.status
                contrato.valor_fatura_fpd = fatura.valor
                contrato.save(update_fields=[
                    'data_vencimento_fpd', 'data_pagamento_fpd',
                    'status_fatura_fpd', 'valor_fatura_fpd', 'atualizado_em',
                ])

    elegivel = contrato.calcular_elegibilidade()
    if contrato.safra:
        _recalcular_totais_safra(contrato.safra)

    logger.info(
        '[Qualidade] salvar_faturas contrato=%s user=%s atualizadas=%s elegivel=%s',
        contrato_id,
        getattr(user, 'id', None),
        atualizadas,
        elegivel,
    )
    return {
        'ok': True,
        'atualizadas': atualizadas,
        'elegivel': elegivel,
        'erros': erros,
        'detalhe': detalhe_contrato_faturas(contrato_id),
    }


def _parse_data_nio(raw: Any) -> Optional[date]:
    """Normaliza due_date_raw / data_vencimento vindos da API Nio."""
    if not raw:
        return None
    if hasattr(raw, 'strftime'):
        return raw  # type: ignore[return-value]
    if isinstance(raw, str) and len(raw) >= 8:
        try:
            from datetime import datetime as dt
            s = raw[:10].replace('/', '-')
            if '-' in s and len(s) >= 10:
                return dt.strptime(s[:10], '%Y-%m-%d').date()
            digits = re.sub(r'\D', '', raw)[:8]
            if len(digits) == 8:
                return dt.strptime(digits, '%Y%m%d').date()
        except Exception:
            return None
    return None


def _mes_ref_yyyy_mm(d: Optional[date], reference_month: Any = None) -> str:
    if d:
        return d.strftime('%Y-%m')
    ref = str(reference_month or '').strip()
    if len(ref) == 6 and ref.isdigit():
        return f'{ref[:4]}-{ref[4:6]}'
    if len(ref) == 7 and ref[4] == '-':
        return ref
    return ''


def buscar_opcoes_nio_fatura(
    contrato_id: int,
    numero_fatura: int,
    user: Any,
) -> dict[str, Any]:
    """Consulta a Nio e devolve todas as opções para o BO escolher.

    Destaca as que batem com o mês da fatura local (vencimento ou referência).
    Não vincula automaticamente — o usuário precisa aceitar.
    """
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para buscar na Nio.')

    try:
        contrato = ContratoM10.objects.get(pk=contrato_id)
    except ContratoM10.DoesNotExist as exc:
        raise ValueError(f'Contrato {contrato_id} não encontrado.') from exc

    cpf = re.sub(r'\D', '', (contrato.cpf_cliente or ''))
    if len(cpf) < 11:
        raise ValueError('CPF do cliente ausente ou inválido — não é possível buscar na Nio.')

    fatura = FaturaM10.objects.filter(contrato=contrato, numero_fatura=numero_fatura).first()
    if not fatura:
        raise ValueError(f'Fatura {numero_fatura} não encontrada neste contrato.')

    venc_local = fatura.data_vencimento or contrato.calcular_vencimento_fatura_n(numero_fatura)
    mes_alvo = _mes_ref_yyyy_mm(venc_local)

    from crm_app.nio_api import consultar_dividas_nio

    api_result = consultar_dividas_nio(cpf, offset=0, limit=50, headless=True)
    invoices = api_result.get('invoices') or []

    opcoes: list[dict[str, Any]] = []
    for idx, inv in enumerate(invoices):
        dv = _parse_data_nio(inv.get('due_date_raw') or inv.get('data_vencimento'))
        mes_nio = _mes_ref_yyyy_mm(dv, inv.get('reference_month'))
        match_mes = bool(mes_alvo and mes_nio and mes_alvo == mes_nio)
        diff_dias = abs((dv - venc_local).days) if dv and venc_local else None
        opcoes.append({
            'opcao_id': idx,
            'valor': inv.get('amount'),
            'data_vencimento': dv.isoformat() if dv else '',
            'data_vencimento_display': dv.strftime('%d/%m/%Y') if dv else '—',
            'mes_referencia': mes_nio,
            'codigo_pix': inv.get('pix') or inv.get('codigo_pix') or '',
            'codigo_barras': inv.get('barcode') or inv.get('codigo_barras') or '',
            'status_nio': inv.get('status') or '',
            'product': inv.get('product') or '',
            'match_mes': match_mes,
            'diff_dias_vencimento': diff_dias,
            'recomendado': match_mes or (diff_dias is not None and diff_dias <= 3),
            # IDs internos para buscar PDF no aceite
            'debt_id': inv.get('debt_id') or '',
            'invoice_id': str(inv.get('invoice_id') or ''),
            'reference_month_raw': inv.get('reference_month') or '',
        })

    # Recomendadas primeiro
    opcoes.sort(key=lambda o: (not o['recomendado'], o.get('diff_dias_vencimento') is None, o.get('diff_dias_vencimento') or 999))

    return {
        'ok': True,
        'contrato_id': contrato.id,
        'numero_fatura': numero_fatura,
        'fatura_id': fatura.id,
        'cpf': cpf,
        'mes_alvo': mes_alvo,
        'vencimento_local': venc_local.isoformat() if venc_local else '',
        'vencimento_local_display': venc_local.strftime('%d/%m/%Y') if venc_local else '—',
        'sem_dividas': len(opcoes) == 0,
        'mensagem': 'CPF sem dívidas no momento.' if not opcoes else '',
        'opcoes': opcoes,
        'token': api_result.get('token') or '',
        'api_base': api_result.get('api_base') or '',
        'session_id': api_result.get('session_id') or '',
    }


def aplicar_opcao_nio_fatura(
    contrato_id: int,
    fatura_id: int,
    opcao: dict[str, Any],
    user: Any,
    *,
    token: str = '',
    api_base: str = '',
    session_id: str = '',
    cpf: str = '',
) -> dict[str, Any]:
    """Vincula valor, vencimento, PIX, barras e PDF da opção Nio aceita pelo BO."""
    if not pode_acessar_qualidade(user):
        raise PermissionError('Sem permissão para aplicar dados da Nio.')

    try:
        contrato = ContratoM10.objects.get(pk=contrato_id)
        fatura = FaturaM10.objects.get(pk=fatura_id, contrato=contrato)
    except (ContratoM10.DoesNotExist, FaturaM10.DoesNotExist) as exc:
        raise ValueError('Contrato/fatura não encontrados.') from exc

    campos: list[str] = []

    if opcao.get('valor') not in (None, ''):
        try:
            fatura.valor = float(str(opcao['valor']).replace(',', '.'))
            campos.append('valor')
        except (TypeError, ValueError):
            pass

    dv = opcao.get('data_vencimento')
    if dv:
        try:
            fatura.data_vencimento = date.fromisoformat(str(dv)[:10])
            campos.append('data_vencimento')
        except ValueError:
            pass

    if opcao.get('codigo_pix'):
        fatura.codigo_pix = str(opcao['codigo_pix']).strip()
        campos.append('codigo_pix')
    if opcao.get('codigo_barras'):
        fatura.codigo_barras = str(opcao['codigo_barras']).strip()
        campos.append('codigo_barras')

    # PDF sob demanda no aceite
    pdf_url = opcao.get('pdf_url') or ''
    if not pdf_url and token and api_base and session_id and opcao.get('invoice_id'):
        try:
            import requests
            from crm_app.nio_api import get_invoice_pdf_url

            cpf_limpo = re.sub(r'\D', '', cpf or contrato.cpf_cliente or '')
            sess = requests.Session()
            pdf_url = get_invoice_pdf_url(
                api_base,
                token,
                session_id,
                opcao.get('debt_id') or '',
                str(opcao.get('invoice_id') or ''),
                cpf_limpo,
                str(opcao.get('reference_month_raw') or ''),
                sess,
            ) or ''
        except Exception:
            logger.exception('[Qualidade] Falha ao obter PDF Nio fatura=%s', fatura_id)

    if pdf_url:
        fatura.pdf_url = pdf_url
        campos.append('pdf_url')

    if campos:
        campos.append('atualizado_em')
        fatura.save(update_fields=list(dict.fromkeys(campos)))

    if fatura.numero_fatura == 1:
        contrato.data_vencimento_fpd = fatura.data_vencimento
        contrato.valor_fatura_fpd = fatura.valor
        contrato.status_fatura_fpd = fatura.status
        contrato.save(update_fields=[
            'data_vencimento_fpd', 'valor_fatura_fpd', 'status_fatura_fpd', 'atualizado_em',
        ])

    contrato.calcular_elegibilidade()

    return {
        'ok': True,
        'fatura_id': fatura.id,
        'pdf_url': fatura.pdf_url or '',
        'detalhe': detalhe_contrato_faturas(contrato_id),
    }
