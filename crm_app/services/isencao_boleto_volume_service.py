"""
Regra global: isentar desconto de boleto na folha por volume de instaladas.

Quando ativa, vendedores com qtd_total_instalada do mês >= limiar não sofrem
o deflator de boleto no líquido (mesmo comportamento de desconta_boleto_pap=False).
"""
from __future__ import annotations

from typing import Any, Optional

from crm_app.models import ConfigIsencaoBoletoVolume

_DEFAULT_ATIVO = True
_DEFAULT_MIN = 30


def get_config_isencao_boleto_volume() -> ConfigIsencaoBoletoVolume:
    config = ConfigIsencaoBoletoVolume.objects.first()
    if not config:
        config = ConfigIsencaoBoletoVolume.objects.create(
            ativo=_DEFAULT_ATIVO,
            min_vendas_instaladas=_DEFAULT_MIN,
        )
    return config


def serializar_config_isencao_boleto_volume(
    config: Optional[ConfigIsencaoBoletoVolume] = None,
) -> dict[str, Any]:
    cfg = config or get_config_isencao_boleto_volume()
    return {
        'ativo': bool(cfg.ativo),
        'min_vendas_instaladas': int(cfg.min_vendas_instaladas or _DEFAULT_MIN),
        'atualizado_em': cfg.atualizado_em.isoformat() if cfg.atualizado_em else None,
    }


def deve_isentar_desconto_boleto_por_volume(
    qtd_instalada: int,
    config: Optional[ConfigIsencaoBoletoVolume] = None,
) -> bool:
    """
    True quando a regra global está ativa e a produção instalada do mês
    atingiu o limiar (>= min_vendas_instaladas).
    """
    try:
        qtd = int(qtd_instalada or 0)
    except (TypeError, ValueError):
        qtd = 0
    if qtd <= 0:
        return False
    cfg = config
    if cfg is None:
        try:
            cfg = get_config_isencao_boleto_volume()
        except Exception:
            return False
    if not bool(getattr(cfg, 'ativo', False)):
        return False
    try:
        limiar = int(getattr(cfg, 'min_vendas_instaladas', None) or _DEFAULT_MIN)
    except (TypeError, ValueError):
        limiar = _DEFAULT_MIN
    if limiar <= 0:
        return False
    return qtd >= limiar
