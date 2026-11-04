"""Tratamento unificado do Funil (todas as abas)."""
from __future__ import annotations

import re
from typing import Any, Optional

from django.db.models import QuerySet
from django.utils import timezone

from crm_app.models import FunilTratamento, MailingContato
from crm_app.services.mailing_import_service import normalizar_telefone_e164

_DIGITS = re.compile(r'\D')

ABA_INTERESSE = FunilTratamento.ABA_INTERESSE
ABA_PRE_VENDA = FunilTratamento.ABA_PRE_VENDA
ABA_VENDA = FunilTratamento.ABA_VENDA
ABA_CHURN = FunilTratamento.ABA_CHURN
ABA_BIO = FunilTratamento.ABA_BIO
ABA_MAILING = FunilTratamento.ABA_MAILING

ABAS_PAP = {ABA_INTERESSE, ABA_PRE_VENDA, ABA_VENDA}


def _cpf(valor: Any) -> str:
    return _DIGITS.sub('', str(valor or ''))[:14]


def _tel_ok(valor: Any) -> str:
    e164, ok = normalizar_telefone_e164(valor)
    return e164 if ok and e164 else ''


def wa_me(telefone: str) -> str:
    digits = _DIGITS.sub('', str(telefone or ''))
    return f'https://wa.me/{digits}' if digits else ''


def serializar(obj: Optional[FunilTratamento]) -> dict:
    if not obj:
        return {
            'tratado': False,
            'tratado_em': None,
            'tratado_por': '',
            'observacao': '',
            'telefone': '',
            'wa_url': '',
        }
    return {
        'tratado': obj.status == FunilTratamento.STATUS_TRATADO,
        'tratado_em': obj.tratado_em.isoformat() if obj.tratado_em else None,
        'tratado_por': (obj.tratado_por.username if obj.tratado_por_id else '') or '',
        'observacao': obj.observacao or '',
        'telefone': obj.telefone or '',
        'wa_url': wa_me(obj.telefone),
    }


def mapa_por_refs(aba: str, ref_ids: list[str]) -> dict[str, dict]:
    ids = [str(r) for r in ref_ids if r not in (None, '')]
    if not ids:
        return {}
    qs: QuerySet = FunilTratamento.objects.filter(aba=aba, ref_id__in=ids).select_related('tratado_por')
    return {t.ref_id: serializar(t) for t in qs}


def resolver_contexto(aba: str, ref_id: Any) -> dict:
    """Monta dados da linha para o modal Tratar (telefone, nome, protocolo)."""
    aba = str(aba or '').strip().upper()
    ref = str(ref_id or '').strip()
    if not aba or not ref:
        raise ValueError('Informe aba e id.')

    if aba in ABAS_PAP:
        from crm_app.historico_pap import map_pedido_api
        from crm_app.models import HistoricoPapPedido

        try:
            p = HistoricoPapPedido.objects.get(pk=int(ref))
        except (HistoricoPapPedido.DoesNotExist, TypeError, ValueError) as exc:
            raise ValueError('Pedido PAP não encontrado.') from exc
        mapped = map_pedido_api(p.payload or {}, p.tipo_venda)
        tel = _tel_ok(
            mapped.get('celular_principal')
            or mapped.get('celular_2')
            or (p.payload or {}).get('telefone')
        )
        return {
            'aba': aba,
            'ref_id': str(p.pk),
            'protocolo': str(mapped.get('pedido') or p.numero_pedido or ''),
            'nome': str(mapped.get('cliente') or ''),
            'documento': _cpf(mapped.get('cpf') or mapped.get('documento')),
            'telefone': tel,
        }

    if aba == ABA_CHURN:
        from crm_app.churn_os_utils import build_venda_lookup_por_os, encontrar_venda_por_churn
        from crm_app.models import ImportacaoChurn, Venda

        try:
            churn = ImportacaoChurn.objects.get(pk=int(ref))
        except (ImportacaoChurn.DoesNotExist, TypeError, ValueError) as exc:
            raise ValueError('Churn não encontrado.') from exc
        lookup = build_venda_lookup_por_os(Venda.objects.filter(ativo=True).select_related('cliente'))
        venda = encontrar_venda_por_churn(churn, lookup)
        nome = ''
        doc = ''
        tel = ''
        protocolo = (churn.numero_pedido or churn.nr_ordem or '')
        if venda:
            protocolo = venda.ordem_servico or protocolo
            tel = _tel_ok(venda.telefone1 or getattr(venda, 'telefone2', '') or '')
            if venda.cliente_id:
                nome = venda.cliente.nome_razao_social or ''
                doc = _cpf(venda.cliente.cpf_cnpj)
        return {
            'aba': aba,
            'ref_id': str(churn.pk),
            'protocolo': str(protocolo or ''),
            'nome': nome,
            'documento': doc,
            'telefone': tel,
        }

    if aba == ABA_BIO:
        from datetime import timedelta

        from crm_app.services import repescagem_bio_service as bio

        hoje = timezone.localdate()
        base = bio.montar_base(hoje - timedelta(days=30), hoje)
        digitos = _cpf(ref)
        linha = next((b for b in base if b.get('cpf') == digitos), None)
        if not linha:
            raise ValueError('CPF não encontrado na Repescagem Bio.')
        return {
            'aba': aba,
            'ref_id': digitos,
            'protocolo': str(linha.get('protocolo') or linha.get('ordem_servico') or ''),
            'nome': str(linha.get('nome_cliente') or ''),
            'documento': digitos,
            'telefone': _tel_ok(linha.get('telefone')),
        }

    if aba == ABA_MAILING:
        try:
            c = MailingContato.objects.select_related('lote').get(pk=int(ref))
        except (MailingContato.DoesNotExist, TypeError, ValueError) as exc:
            raise ValueError('Contato de mailing não encontrado.') from exc
        return {
            'aba': aba,
            'ref_id': str(c.pk),
            'protocolo': c.lote.nome if c.lote_id else '',
            'nome': c.nome or '',
            'documento': c.cpf or '',
            'telefone': c.telefone_e164 or '',
        }

    raise ValueError(f'Aba não suportada: {aba}')


def marcar_tratado(aba: str, ref_id: Any, *, usuario=None, observacao: str = '') -> dict:
    ctx = resolver_contexto(aba, ref_id)
    agora = timezone.now()
    obj, _ = FunilTratamento.objects.update_or_create(
        aba=ctx['aba'],
        ref_id=str(ctx['ref_id']),
        defaults={
            'protocolo': (ctx.get('protocolo') or '')[:80],
            'nome': (ctx.get('nome') or '')[:200],
            'documento': (ctx.get('documento') or '')[:14],
            'telefone': (ctx.get('telefone') or '')[:20],
            'status': FunilTratamento.STATUS_TRATADO,
            'observacao': (observacao or '')[:2000],
            'tratado_por': usuario if getattr(usuario, 'is_authenticated', False) else None,
            'tratado_em': agora,
        },
    )
    if ctx['aba'] == ABA_MAILING:
        MailingContato.objects.filter(pk=int(ctx['ref_id'])).update(
            status=MailingContato.STATUS_TRATADO,
            tratado_em=agora,
            tratado_por=usuario if getattr(usuario, 'is_authenticated', False) else None,
        )
    out = serializar(obj)
    out.update({
        'ok': True,
        'aba': ctx['aba'],
        'ref_id': ctx['ref_id'],
        'protocolo': ctx.get('protocolo') or '',
        'nome': ctx.get('nome') or '',
        'documento': ctx.get('documento') or '',
        'telefone': ctx.get('telefone') or out.get('telefone') or '',
        'wa_url': wa_me(ctx.get('telefone') or out.get('telefone') or ''),
    })
    return out


def anexar(aba: str, linhas: list[dict], ref_key: str) -> list[dict]:
    """Inclui tratamento + wa_url em cada linha da listagem do Funil."""
    refs = [str(item.get(ref_key) or '') for item in linhas]
    mapa = mapa_por_refs(aba, refs)
    for item in linhas:
        ref = str(item.get(ref_key) or '')
        trat = mapa.get(ref) or serializar(None)
        item['tratamento'] = trat
        tel = item.get('telefone') or trat.get('telefone') or ''
        if tel:
            item['telefone'] = tel
        item['wa_url'] = wa_me(tel)
    return linhas
