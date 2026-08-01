"""Helpers da importação FPD / SPD / TPD (planilha operadora → ContratoM10 / FaturaM10)."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd
from django.utils import timezone

from crm_app.fpd_status_mapping import (
    INDICADOR_PARA_NUMERO_FATURA,
    normalizar_indicador_fpd,
    normalizar_status_fpd,
    resolver_status_fatura_fpd,
)

logger = logging.getLogger(__name__)

MATCH_MATCHED = 'MATCHED'
MATCH_FALTA_CRM = 'FALTA_CRM'
MATCH_ORFAO = 'ORFAO'


def variacoes_ordem_servico(nr_ordem: str) -> list[str]:
    """Gera chaves de matching para O.S. (zeros, prefixo OS-, etc.)."""
    nr = (nr_ordem or '').strip()
    if not nr or nr.lower() == 'nan':
        return []
    if nr.replace('.', '').replace('-', '').isdigit():
        nr = nr.split('.')[0]
    if not nr:
        return []
    sem_zeros = nr.lstrip('0') or '0'
    variacoes = [
        nr,
        nr.zfill(8) if len(nr) <= 8 else nr,
        sem_zeros,
        f'OS-{nr}',
        f'OS-{sem_zeros}',
        f'OS-{nr.zfill(8)}' if len(nr) <= 8 else None,
    ]
    out: list[str] = []
    vistos: set[str] = set()
    for v in variacoes:
        if v and v not in vistos:
            vistos.add(v)
            out.append(v)
    return out


def normalizar_nr_ordem(valor: Any) -> Optional[str]:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if pd.isna(valor):
        return None
    nr = str(valor).strip()
    if not nr or nr.lower() == 'nan':
        return None
    if nr.replace('.', '').replace('-', '').isdigit():
        nr = nr.split('.')[0]
    return nr or None


def parse_data_excel(valor: Any, fallback: Optional[date] = None) -> Optional[date]:
    """Converte serial Excel ou datetime/string em date."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return fallback
    if pd.isna(valor):
        return fallback
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)):
        try:
            return (pd.Timestamp('1900-01-01') + pd.Timedelta(days=float(valor) - 2)).date()
        except Exception:
            return fallback
    try:
        return pd.to_datetime(valor).date()
    except Exception:
        return fallback


def extrair_campos_linha_fpd(row: Any, hoje: Optional[date] = None) -> dict[str, Any]:
    """Extrai e normaliza campos relevantes de uma linha da planilha FPD."""
    hoje = hoje or timezone.localdate()
    indicador_raw = row.get('indicador', 'FPD') if hasattr(row, 'get') else getattr(row, 'indicador', 'FPD')
    indicador = normalizar_indicador_fpd(indicador_raw)
    numero_fatura = INDICADOR_PARA_NUMERO_FATURA.get(indicador, 1)

    id_contrato = str(row.get('id_contrato', '') if hasattr(row, 'get') else '').strip()
    if id_contrato.lower() == 'nan':
        id_contrato = ''

    nr_fatura = str(row.get('nr_fatura', '') if hasattr(row, 'get') else '').strip()
    if nr_fatura.lower() == 'nan':
        nr_fatura = ''

    status_str = str(row.get('ds_status_fatura', 'NAO_PAGO') if hasattr(row, 'get') else 'NAO_PAGO')
    if status_str.lower() == 'nan':
        status_str = 'NAO_PAGO'
    status_str = status_str.strip()

    ds_sit = str(row.get('ds_sit_fatura', '') if hasattr(row, 'get') else '').strip()
    if ds_sit.lower() == 'nan':
        ds_sit = ''

    faixa = str(row.get('faixa', '') if hasattr(row, 'get') else '').strip()
    if faixa.lower() == 'nan':
        faixa = ''

    municipio = str(row.get('nm_municipio', '') if hasattr(row, 'get') else '').strip()
    if municipio.lower() == 'nan':
        municipio = ''

    uf = str(row.get('sg_uf', '') if hasattr(row, 'get') else '').strip()
    if uf.lower() == 'nan':
        uf = ''

    cd_vendedor = str(row.get('cd_tr_vdd_original', '') if hasattr(row, 'get') else '').strip()
    if cd_vendedor.lower() == 'nan':
        cd_vendedor = ''

    nm_pdv = str(row.get('nm_pdv_rel', '') if hasattr(row, 'get') else '').strip()
    if nm_pdv.lower() == 'nan':
        nm_pdv = ''

    nm_gc = str(row.get('nm_gc', '') if hasattr(row, 'get') else '').strip()
    if nm_gc.lower() == 'nan':
        nm_gc = ''

    vl_fatura = row.get('vl_fatura', 0) if hasattr(row, 'get') else 0
    nr_dias_atraso = row.get('nr_dias_atraso', 0) if hasattr(row, 'get') else 0

    dt_venc_date = parse_data_excel(row.get('dt_venc_orig') if hasattr(row, 'get') else None, fallback=hoje)
    dt_pgto_date = parse_data_excel(row.get('dt_pagamento') if hasattr(row, 'get') else None, fallback=None)

    vl_fatura_float = float(vl_fatura) if pd.notna(vl_fatura) else 0.0
    try:
        nr_dias_atraso_int = int(nr_dias_atraso) if pd.notna(nr_dias_atraso) else 0
    except (TypeError, ValueError):
        nr_dias_atraso_int = 0

    status = resolver_status_fatura_fpd(
        status_str,
        ds_sit_fatura=ds_sit,
        data_vencimento=dt_venc_date,
        dias_atraso=nr_dias_atraso_int,
        hoje=hoje,
    )

    return {
        'indicador': indicador,
        'numero_fatura': numero_fatura,
        'id_contrato': id_contrato,
        'nr_fatura': nr_fatura,
        'status_str': status_str,
        'status': status,
        'ds_sit_fatura': ds_sit.upper() if ds_sit else '',
        'faixa': faixa,
        'municipio': municipio,
        'uf': uf,
        'cd_vendedor_original': cd_vendedor,
        'nm_pdv': nm_pdv,
        'nm_gc': nm_gc,
        'vl_fatura': vl_fatura_float,
        'nr_dias_atraso': nr_dias_atraso_int,
        'dt_venc_date': dt_venc_date or hoje,
        'dt_pgto_date': dt_pgto_date,
    }


def buscar_venda_por_os(nr_ordem: str, vendas_dict: dict[str, Any]) -> Any:
    """Lookup em dicionário pré-carregado de Venda por variações de O.S."""
    for variacao in variacoes_ordem_servico(nr_ordem):
        venda = vendas_dict.get(variacao)
        if venda is not None:
            return venda
    return None


def criar_contrato_de_venda(venda: Any, id_contrato: Optional[str] = None) -> Any:
    """Cria ContratoM10 a partir de Venda INSTALADA encontrada no matching FPD."""
    from crm_app.models import ContratoM10

    numero_contrato = venda.ordem_servico or f'VENDA_{venda.id}'
    if venda.ordem_servico and ContratoM10.objects.filter(ordem_servico=venda.ordem_servico).exists():
        return ContratoM10.objects.get(ordem_servico=venda.ordem_servico)
    if ContratoM10.objects.filter(numero_contrato=numero_contrato).exists():
        return ContratoM10.objects.get(numero_contrato=numero_contrato)

    safra = ''
    if venda.data_instalacao:
        safra = venda.data_instalacao.strftime('%Y-%m')

    contrato = ContratoM10.objects.create(
        safra=safra,
        venda=venda,
        numero_contrato=numero_contrato,
        ordem_servico=venda.ordem_servico,
        numero_contrato_definitivo=(id_contrato or None),
        cliente_nome=venda.cliente.nome_razao_social if venda.cliente else 'N/D',
        cpf_cliente=venda.cliente.cpf_cnpj if venda.cliente else '',
        vendedor=venda.vendedor,
        data_instalacao=venda.data_instalacao or timezone.localdate(),
        plano_original=venda.plano.nome if venda.plano else 'N/D',
        plano_atual=venda.plano.nome if venda.plano else 'N/D',
        valor_plano=venda.plano.valor if venda.plano else 0,
        status_contrato='ATIVO',
        orfao=False,
        observacao=f'Criado no matching FPD a partir da Venda #{venda.id}',
    )
    try:
        contrato.criar_ou_atualizar_faturas()
    except Exception:
        logger.exception('Falha ao criar faturas no match FPD OS=%s', venda.ordem_servico)
    return contrato


def chave_importacao(nr_ordem: str, indicador: str) -> str:
    return f'{nr_ordem}|{(indicador or "FPD").upper()}'


def sincronizar_vencimentos_fpd_nas_faturas() -> dict[str, int]:
    """Corrige ``FaturaM10.data_vencimento`` com a data da planilha (ImportacaoFPD).

    A planilha FPD/SPD/TPD é a fonte da verdade. Útil após imports em que o signal
    de ContratoM10 sobrescreveu o vencimento com instalação+25.
    """
    from crm_app.models import FaturaM10, ImportacaoFPD

    # Última importação por (contrato, número da fatura)
    vistos: set[tuple[int, int]] = set()
    atualizados = 0
    sem_fatura = 0
    iguais = 0

    qs = (
        ImportacaoFPD.objects.filter(
            match_status=MATCH_MATCHED,
            contrato_m10_id__isnull=False,
            dt_venc_orig__isnull=False,
        )
        .order_by('-atualizada_em')
        .only('contrato_m10_id', 'numero_fatura_m10', 'dt_venc_orig', 'indicador')
    )

    batch_updates: list = []
    for imp in qs.iterator(chunk_size=2000):
        num = int(imp.numero_fatura_m10 or INDICADOR_PARA_NUMERO_FATURA.get(imp.indicador or 'FPD', 1))
        chave = (imp.contrato_m10_id, num)
        if chave in vistos:
            continue
        vistos.add(chave)

        fatura = FaturaM10.objects.filter(
            contrato_id=imp.contrato_m10_id, numero_fatura=num
        ).first()
        if not fatura:
            sem_fatura += 1
            continue
        if fatura.data_vencimento == imp.dt_venc_orig:
            iguais += 1
            continue
        fatura.data_vencimento = imp.dt_venc_orig
        batch_updates.append(fatura)
        if len(batch_updates) >= 500:
            FaturaM10.objects.bulk_update(batch_updates, ['data_vencimento'], batch_size=500)
            atualizados += len(batch_updates)
            batch_updates = []

    if batch_updates:
        FaturaM10.objects.bulk_update(batch_updates, ['data_vencimento'], batch_size=500)
        atualizados += len(batch_updates)

    # Espelha vencimento FPD no contrato a partir da fatura 1
    from crm_app.models import ContratoM10

    contratos_upd = []
    f1s = FaturaM10.objects.filter(
        numero_fatura=1,
        data_importacao_fpd__isnull=False,
    ).select_related('contrato')
    for f1 in f1s.iterator(chunk_size=2000):
        c = f1.contrato
        if c.data_vencimento_fpd != f1.data_vencimento:
            c.data_vencimento_fpd = f1.data_vencimento
            contratos_upd.append(c)
            if len(contratos_upd) >= 500:
                ContratoM10.objects.bulk_update(
                    contratos_upd, ['data_vencimento_fpd'], batch_size=500
                )
                contratos_upd = []
    if contratos_upd:
        ContratoM10.objects.bulk_update(contratos_upd, ['data_vencimento_fpd'], batch_size=500)

    resultado = {
        'contratos_faturas_vistos': len(vistos),
        'vencimentos_corrigidos': atualizados,
        'ja_iguais': iguais,
        'sem_fatura': sem_fatura,
    }
    logger.info('[FPD] sincronizar_vencimentos_fpd_nas_faturas %s', resultado)
    return resultado
