"""Quitação de adiantamento sábado ao instalar (evita pagamento duplicado na folha)."""
from __future__ import annotations

import logging
from datetime import datetime, time

from django.utils import timezone

logger = logging.getLogger(__name__)


def _nome_status(status_esteira) -> str:
    return (status_esteira.nome if status_esteira else '') or ''


def status_esteira_eh_instalada(status_esteira) -> bool:
    return 'INSTALADA' in _nome_status(status_esteira).upper()


def status_esteira_eh_cancelada(status_esteira) -> bool:
    return 'CANCEL' in _nome_status(status_esteira).upper()


def status_esteira_eh_agendado_ou_pendenciada(status_esteira) -> bool:
    nome = _nome_status(status_esteira).upper()
    if status_esteira_eh_instalada(status_esteira):
        return False
    return 'AGENDADO' in nome or 'PENDEN' in nome


def comissao_ja_adiantada_venda(venda) -> bool:
    """
    Venda não deve entrar em QTD A PAGAR na folha.
    Reemissão instalada sem adiantamento sábado próprio paga normalmente.
    Estorno já aplicado na folha e depois instalada → paga comissão normal.
    """
    if getattr(venda, 'reemissao', False) and not getattr(venda, 'adiantamento_sabado_marcado', False):
        return False
    if (
        getattr(venda, 'flag_desc_adiantamento_sabado', False)
        and status_esteira_eh_instalada(venda.status_esteira)
        and not getattr(venda, 'adiantamento_sabado_quitado_em', None)
    ):
        return False
    if getattr(venda, 'antecipacao_comissao', False):
        return True
    if getattr(venda, 'adiantamento_sabado_quitado_em', None):
        return True
    return False


def venda_elegivel_estorno_adiantamento_sabado(venda) -> bool:
    """Adiantamento sábado vira estorno quando a venda não instalou (uma vez só, flag_desc=False)."""
    if not getattr(venda, 'adiantamento_sabado_marcado', False):
        return False
    if getattr(venda, 'flag_desc_adiantamento_sabado', False):
        return False
    if getattr(venda, 'adiantamento_sabado_quitado_em', None):
        return False
    val = getattr(venda, 'adiantamento_sabado_valor', None)
    if not val or float(val) <= 0:
        return False
    if status_esteira_eh_instalada(venda.status_esteira):
        return False
    if (
        status_esteira_eh_cancelada(venda.status_esteira)
        or status_esteira_eh_agendado_ou_pendenciada(venda.status_esteira)
    ):
        return True
    return False


def _data_abertura_os(venda):
    """Data de abertura da O.S. (fallback: data_criacao) para enquadrar o estorno no mês da folha."""
    dt = getattr(venda, 'data_abertura', None) or getattr(venda, 'data_criacao', None)
    if not dt:
        return None
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.date() if hasattr(dt, 'date') else dt


def venda_entra_estorno_adiantamento_sabado_mes(venda, data_inicio, data_fim) -> bool:
    """
    Mês M da folha:
    - CANCELADA: cancelamento (data_ultima_alteracao) em M.
    - AGENDADO/PENDENCIADA: sem instalar e com data de abertura da O.S. em M.
    """
    if not venda_elegivel_estorno_adiantamento_sabado(venda):
        return False

    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim

    if status_esteira_eh_cancelada(venda.status_esteira):
        if not venda.data_ultima_alteracao:
            return False
        dalt = timezone.localtime(venda.data_ultima_alteracao).date()
        return di <= dalt < df

    if status_esteira_eh_agendado_ou_pendenciada(venda.status_esteira):
        dab = _data_abertura_os(venda)
        if not dab:
            return False
        return di <= dab < df

    return False


def motivo_estorno_adiantamento_sabado(venda) -> str:
    if status_esteira_eh_cancelada(venda.status_esteira):
        return 'Desconto adiantamento sábado (cancelado)'
    return 'Desconto adiantamento sábado (não instalado)'


def calcular_descontos_adiantamento_sabado_folha(consultor, data_inicio, data_fim):
    """
    Estorno automático na folha do mês:
    - AGENDADO/PENDENCIADA com adiantamento sábado, sem instalar, O.S. aberta no mês;
    - CANCELADA no mês (mesma regra de valor, flag_desc evita repetir).
    Valor: adiantamento_sabado_valor (manual ou tabela ao marcar).
    """
    from crm_app.models import Venda

    di = data_inicio.date() if hasattr(data_inicio, 'date') else data_inicio
    df = data_fim.date() if hasattr(data_fim, 'date') else data_fim
    if not di or not df:
        return []

    vendas = (
        Venda.objects.filter(
            vendedor=consultor,
            ativo=True,
            adiantamento_sabado_marcado=True,
            flag_desc_adiantamento_sabado=False,
            adiantamento_sabado_quitado_em__isnull=True,
        )
        .exclude(adiantamento_sabado_valor__isnull=True)
        .exclude(adiantamento_sabado_valor=0)
        .select_related('status_esteira')
    )

    descontos = []
    for v in vendas:
        if not venda_entra_estorno_adiantamento_sabado_mes(v, di, df):
            continue
        val = float(v.adiantamento_sabado_valor or 0)
        if val <= 0:
            continue
        descontos.append({
            'venda_id': v.id,
            'valor': val,
            'motivo': motivo_estorno_adiantamento_sabado(v),
        })
    return descontos


def get_vendas_ids_desconto_adiantamento_sabado_mes(ano, mes):
    """IDs com estorno na folha do mês — usado ao fechar para marcar flag_desc (uma vez só)."""
    from crm_app.models import Venda

    data_inicio = datetime(ano, mes, 1)
    data_fim = datetime(ano, mes + 1, 1) if mes < 12 else datetime(ano + 1, 1, 1)
    di = data_inicio.date()
    df = data_fim.date()

    ids = []
    qs = (
        Venda.objects.filter(
            ativo=True,
            adiantamento_sabado_marcado=True,
            flag_desc_adiantamento_sabado=False,
            adiantamento_sabado_quitado_em__isnull=True,
            vendedor_id__isnull=False,
        )
        .exclude(adiantamento_sabado_valor__isnull=True)
        .exclude(adiantamento_sabado_valor=0)
        .select_related('status_esteira')
    )
    for v in qs:
        if venda_entra_estorno_adiantamento_sabado_mes(v, di, df):
            ids.append(v.id)
    return ids


def quitado_em_a_partir_data_instalacao(venda):
    """Timestamp de quitação alinhado à data de instalação (retrofit / consistência)."""
    dt = getattr(venda, 'data_instalacao', None)
    if not dt:
        return timezone.now()
    if hasattr(dt, 'date'):
        dt = dt.date()
    naive = datetime.combine(dt, time(18, 0, 0))
    tz = timezone.get_current_timezone()
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, tz)
    return naive


def quitar_adiantamento_sabado_na_instalacao(
    venda,
    status_esteira_antes=None,
    *,
    quitado_em=None,
) -> bool:
    """
    Ao instalar venda com adiantamento sábado: marca antecipação e quitação sem novo lançamento.
    Se já houve estorno na folha (flag_desc), não quita — comissão paga normal na instalação.
    """
    if not status_esteira_eh_instalada(venda.status_esteira):
        return False
    if status_esteira_antes is not None:
        if status_esteira_eh_instalada(status_esteira_antes):
            return False
    if not getattr(venda, 'adiantamento_sabado_marcado', False):
        return False
    if getattr(venda, 'flag_desc_adiantamento_sabado', False):
        return False

    ts = quitado_em or venda.adiantamento_sabado_quitado_em or quitado_em_a_partir_data_instalacao(venda)

    from crm_app.models import Venda

    # Já quitada mas antecipacao_comissao foi zerada (ex.: desmarcar/remarcar na esteira).
    if venda.adiantamento_sabado_quitado_em and not venda.antecipacao_comissao:
        updated = Venda.objects.filter(
            pk=venda.pk,
            adiantamento_sabado_marcado=True,
            antecipacao_comissao=False,
        ).update(antecipacao_comissao=True)
        if updated:
            venda.antecipacao_comissao = True
            logger.info(
                'Antecipação resincronizada após quitação sábado — venda #%s',
                venda.pk,
            )
        return bool(updated)

    if venda.adiantamento_sabado_quitado_em:
        return False

    updated = Venda.objects.filter(
        pk=venda.pk,
        adiantamento_sabado_marcado=True,
        adiantamento_sabado_quitado_em__isnull=True,
    ).update(
        antecipacao_comissao=True,
        adiantamento_sabado_quitado_em=ts,
    )
    if updated:
        venda.antecipacao_comissao = True
        venda.adiantamento_sabado_quitado_em = ts
        logger.info(
            'Adiantamento sábado quitado na instalação — venda #%s (quitado_em=%s)',
            venda.pk,
            ts,
        )
    return bool(updated)


def sincronizar_antecipacao_quitado_sabado(venda) -> bool:
    """Quitado_em preenchido mas antecipacao_comissao=False — repara folha sem remarcar sábado."""
    if not getattr(venda, 'adiantamento_sabado_quitado_em', None):
        return False
    if getattr(venda, 'antecipacao_comissao', False):
        return False
    if not status_esteira_eh_instalada(venda.status_esteira):
        return False
    from crm_app.models import Venda

    updated = Venda.objects.filter(pk=venda.pk, antecipacao_comissao=False).update(
        antecipacao_comissao=True,
    )
    if updated:
        venda.antecipacao_comissao = True
        logger.info('Antecipação resincronizada (quitado_em) — venda #%s', venda.pk)
    return bool(updated)


def garantir_quitacao_adiantamento_sabado_instalada(venda) -> bool:
    """
    Venda INSTALADA com adiantamento sábado marcado: garante antecipacao_comissao + quitado_em.
    Não aplica se já houve estorno na folha (instalação posterior paga comissão normal).
    """
    if not status_esteira_eh_instalada(venda.status_esteira):
        return False
    if not getattr(venda, 'adiantamento_sabado_marcado', False):
        return False
    if getattr(venda, 'flag_desc_adiantamento_sabado', False):
        return False
    if venda.antecipacao_comissao and venda.adiantamento_sabado_quitado_em:
        return False

    ts = venda.adiantamento_sabado_quitado_em or quitado_em_a_partir_data_instalacao(venda)
    from crm_app.models import Venda

    updated = Venda.objects.filter(pk=venda.pk).update(
        antecipacao_comissao=True,
        adiantamento_sabado_quitado_em=ts,
    )
    if updated:
        venda.antecipacao_comissao = True
        venda.adiantamento_sabado_quitado_em = ts
        logger.info(
            'Quitação sábado garantida em venda instalada — #%s (quitado_em=%s)',
            venda.pk,
            ts,
        )
    return bool(updated)


def valor_alvo_adiantamento_sabado_folha(
    venda,
    *,
    faixa_regra,
    config,
    usar_manual: bool,
) -> float | None:
    """
    Valor-alvo do adiantamento sábado para venda instalada na folha do mês.
    Usa Regras por Faixa (COMISSÃO) ou valores manuais da config do vendedor.
    """
    from crm_app.comissao_folha_service import (
        get_valor_from_faixa,
        get_valor_manual,
        plano_tipo_to_chave,
    )
    from crm_app.services.cnpj_mei_service import tipo_cliente_comissao

    plano_nome = venda.plano.nome if getattr(venda, 'plano', None) else ''
    chave = plano_tipo_to_chave(plano_nome, tipo_cliente_comissao(venda))
    if not chave:
        return None
    if usar_manual:
        return get_valor_manual(config, chave)
    if not faixa_regra:
        return None
    return get_valor_from_faixa(faixa_regra, chave)


def aplicar_complemento_adiantamento_sabado_folha(
    vendas_instaladas,
    *,
    faixa_regra_total,
    config,
    usar_manual: bool,
) -> int:
    """
    Ajusta adiantamento_sabado_valor nas vendas instaladas do mês para o valor
    da faixa alcançada (antecipadas + a pagar). Inclui rebaixa quando pago > faixa.
    Agendado/pendenciado/cancelado ficam fora (não estão na lista de instaladas).
    """
    from decimal import Decimal

    from crm_app.models import Venda

    pendentes_update = []
    for venda in vendas_instaladas:
        if not getattr(venda, 'adiantamento_sabado_marcado', False):
            continue
        if getattr(venda, 'flag_desc_adiantamento_sabado', False):
            continue
        val_atual = getattr(venda, 'adiantamento_sabado_valor', None)
        if val_atual is None or float(val_atual) <= 0:
            continue

        alvo = valor_alvo_adiantamento_sabado_folha(
            venda,
            faixa_regra=faixa_regra_total,
            config=config,
            usar_manual=usar_manual,
        )
        if alvo is None:
            continue

        alvo_dec = Decimal(str(round(float(alvo), 2)))
        atual_dec = Decimal(str(val_atual)).quantize(Decimal('0.01'))
        if alvo_dec == atual_dec:
            continue

        venda.adiantamento_sabado_valor = alvo_dec
        pendentes_update.append(venda)
        logger.info(
            'Complemento adiant. sábado folha — venda #%s: %s → %s (faixa=%s, manual=%s)',
            venda.pk,
            atual_dec,
            alvo_dec,
            getattr(faixa_regra_total, 'faixa_nome', None) if faixa_regra_total else None,
            usar_manual,
        )

    if pendentes_update:
        Venda.objects.bulk_update(pendentes_update, ['adiantamento_sabado_valor'])
    return len(pendentes_update)


def quitar_adiantamento_sabado_pos_bulk(vendas) -> int:
    """
    Após bulk_update (OSAB etc.) que altera status_esteira sem disparar signals.
    status_esteira_antes omitido: só quita se ainda pendente (adiantamento_sabado_quitado_em vazio).
    """
    count = 0
    for venda in vendas:
        try:
            if quitar_adiantamento_sabado_na_instalacao(venda, status_esteira_antes=None):
                count += 1
        except Exception:
            logger.exception(
                'Erro ao quitar adiantamento sábado pós-bulk — venda #%s',
                getattr(venda, 'pk', '?'),
            )
    return count
