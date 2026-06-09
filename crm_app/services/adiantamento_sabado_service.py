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
    Usa QuerySet.update para não re-disparar post_save.
    """
    if not status_esteira_eh_instalada(venda.status_esteira):
        return False
    if status_esteira_antes is not None:
        if status_esteira_eh_instalada(status_esteira_antes):
            return False
    if not getattr(venda, 'adiantamento_sabado_marcado', False):
        return False
    if venda.adiantamento_sabado_quitado_em:
        return False

    ts = quitado_em or quitado_em_a_partir_data_instalacao(venda)

    from crm_app.models import Venda

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
