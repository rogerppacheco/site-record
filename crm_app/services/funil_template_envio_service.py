"""Elegibilidade, preflight e envio de templates Meta no Funil (WhatsAtende #247)."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any, Optional

from django.db.models import Q
from django.utils import timezone

from crm_app.models import FunilTemplateEnvio, Venda
from crm_app.services.mailing_import_service import normalizar_telefone_e164, primeiro_nome
from crm_app.services.whatsapp.nio_templates import (
    TEMPLATE_CONSULTA_VIABILIDADE,
    TEMPLATE_REATIVACAO_CONTRATO,
    TEMPLATE_SELFIE_PENDENTE,
    enviar_template_funil,
    templates_habilitados,
)

logger = logging.getLogger(__name__)

ABA_INTERESSE = FunilTemplateEnvio.ABA_INTERESSE
ABA_CHURN = FunilTemplateEnvio.ABA_CHURN
ABA_BIO = FunilTemplateEnvio.ABA_BIO

DEDUP_HORAS = 48
_DIGITS = re.compile(r'\D')


def _cpf_limpo(valor: Any) -> str:
    return _DIGITS.sub('', str(valor or ''))[:14]


def _endereco_resumo(*partes: Any) -> str:
    bits = [str(p).strip() for p in partes if p and str(p).strip()]
    return ', '.join(bits)[:80] if bits else ''


def _telefone_ok(valor: Any) -> tuple[str, bool]:
    e164, ok = normalizar_telefone_e164(valor)
    return (e164 if ok else ''), bool(ok and e164)


def _cpf_tem_venda_crm(cpf: str) -> bool:
    digitos = _cpf_limpo(cpf)
    if len(digitos) < 11:
        return False
    return Venda.objects.filter(
        Q(cliente__cpf_cnpj__icontains=digitos[-11:])
        | Q(cliente__cpf_cnpj=digitos)
    ).exists()


def _dedup_recente(cpf: str, template: str) -> Optional[FunilTemplateEnvio]:
    digitos = _cpf_limpo(cpf)
    if not digitos:
        return None
    limite = timezone.now() - timedelta(hours=DEDUP_HORAS)
    return (
        FunilTemplateEnvio.objects.filter(
            cpf=digitos,
            template_nome=template,
            sucesso=True,
            enviado_em__gte=limite,
        )
        .order_by('-enviado_em')
        .first()
    )


def _canal_pronto() -> tuple[bool, str]:
    if not templates_habilitados():
        return False, 'Templates Meta desabilitados na configuração WhatsApp.'
    from django.conf import settings
    wid = str(getattr(settings, 'WHATSATENDE_WHATSAPP_ID_FUNIL', '') or '').strip()
    token = str(getattr(settings, 'WHATSATENDE_TOKEN_FUNIL', '') or '').strip()
    if not wid or not token:
        return False, (
            'Conexão WhatsAtende Funil (#247) não configurada '
            '(WHATSATENDE_WHATSAPP_ID_FUNIL / WHATSATENDE_TOKEN_FUNIL).'
        )
    return True, ''


def _extrair_message_id(resp: Any) -> str:
    try:
        from crm_app.services.whatsapp.status_entrega_service import extrair_message_id_resposta
        return (extrair_message_id_resposta(resp) or '')[:191]
    except Exception:
        if isinstance(resp, dict):
            msgs = resp.get('messages') or []
            if msgs and isinstance(msgs[0], dict):
                return str(msgs[0].get('id') or '')[:191]
        return ''


# ---------------------------------------------------------------------------
# BIO
# ---------------------------------------------------------------------------

def montar_contexto_bio(linha: dict, *, resolver_nome: bool = True) -> dict:
    """linha = item de montar_base / API bio."""
    template = TEMPLATE_SELFIE_PENDENTE
    cpf = _cpf_limpo(linha.get('cpf'))
    tel, tel_ok = _telefone_ok(linha.get('telefone'))
    protocolo = str(linha.get('protocolo') or '').strip()
    prot_label = ''
    if protocolo:
        prot_label = protocolo if protocolo.upper().startswith('PROT') else f'Prot. {protocolo}'

    nome = str(linha.get('nome_cliente') or '').strip()
    nome_fonte = 'crm' if nome else ''
    if resolver_nome and not nome and cpf:
        from crm_app.services.assertiva_localize_service import obter_nome_por_cpf
        nome_assertiva = obter_nome_por_cpf(cpf)
        if nome_assertiva:
            nome = nome_assertiva
            nome_fonte = 'assertiva'

    motivos = []
    if not linha.get('repescavel'):
        motivos.append('Não está marcado como repescável.')
    if not tel_ok:
        motivos.append('Sem telefone válido (venda ou GED).')
    if not prot_label:
        motivos.append('Sem protocolo GED.')
    if not nome:
        motivos.append('Sem nome (CRM/Assertiva).')

    params = [primeiro_nome(nome), prot_label] if nome and prot_label else []
    dedup = _dedup_recente(cpf, template) if not motivos else None
    if dedup:
        motivos.append(f'Já enviado há menos de {DEDUP_HORAS}h (#{dedup.pk}).')

    return {
        'aba': ABA_BIO,
        'ref_id': cpf or str(linha.get('protocolo') or ''),
        'cpf': cpf,
        'telefone': tel,
        'template_nome': template,
        'body_params': params,
        'preview': {
            'nome': primeiro_nome(nome) if nome else '',
            'protocolo': prot_label,
            'nome_fonte': nome_fonte,
        },
        'elegivel': len(motivos) == 0,
        'motivo_inelegivel': ' '.join(motivos),
    }


# ---------------------------------------------------------------------------
# CHURN
# ---------------------------------------------------------------------------

def montar_contexto_churn(linha: dict, venda: Optional[Venda] = None) -> dict:
    template = TEMPLATE_REATIVACAO_CONTRATO
    cpf = _cpf_limpo(linha.get('cpf_cliente'))
    situacao = str(linha.get('situacao_nio') or '').upper()
    nome = str(linha.get('nome_cliente') or '').strip()
    if not nome and venda and venda.cliente_id:
        nome = venda.cliente.nome_razao_social or ''

    tel_raw = ''
    endereco = ''
    if venda:
        tel_raw = venda.telefone1 or ''
        endereco = _endereco_resumo(
            venda.logradouro,
            getattr(venda, 'numero_residencia', None) or getattr(venda, 'numero', None),
            venda.bairro,
            venda.cidade,
        )
    tel, tel_ok = _telefone_ok(tel_raw or linha.get('telefone'))

    contrato = str(linha.get('pedido') or '').strip()
    if not contrato and venda:
        contrato = (venda.ordem_servico or getattr(venda, 'numero_pedido', '') or '')[:40]

    motivos = []
    if situacao != 'ADIMPLENTE':
        motivos.append(f'Situação Nio não é ADIMPLENTE ({situacao or "—"}).')
    if linha.get('sem_venda_crm') or not (linha.get('venda_id') or venda):
        motivos.append('Sem venda cruzada no CRM.')
    if not tel_ok:
        motivos.append('Sem telefone válido na venda.')
    if not nome:
        motivos.append('Sem nome do cliente.')
    if not endereco:
        motivos.append('Sem endereço na venda.')
    if not contrato:
        motivos.append('Sem O.S./pedido para o template.')

    params = [primeiro_nome(nome), contrato, endereco] if not motivos else []
    dedup = _dedup_recente(cpf, template) if not motivos else None
    if dedup:
        motivos.append(f'Já enviado há menos de {DEDUP_HORAS}h (#{dedup.pk}).')

    return {
        'aba': ABA_CHURN,
        'ref_id': str(linha.get('churn_id') or linha.get('venda_id') or cpf),
        'cpf': cpf,
        'telefone': tel,
        'template_nome': template,
        'body_params': params,
        'preview': {
            'nome': primeiro_nome(nome) if nome else '',
            'contrato': contrato,
            'endereco': endereco,
        },
        'elegivel': len(motivos) == 0,
        'motivo_inelegivel': ' '.join(motivos),
    }


# ---------------------------------------------------------------------------
# INTERESSE
# ---------------------------------------------------------------------------

def montar_contexto_interesse(mapped: dict, *, pedido_id: Any = None) -> dict:
    template = TEMPLATE_CONSULTA_VIABILIDADE
    cpf = _cpf_limpo(mapped.get('cpf') or mapped.get('documento'))
    nome = str(mapped.get('cliente') or '').strip()
    tel_raw = mapped.get('celular_principal') or mapped.get('celular_2') or ''
    tel, tel_ok = _telefone_ok(tel_raw)
    endereco = _endereco_resumo(
        mapped.get('logradouro'),
        mapped.get('numero'),
        mapped.get('bairro'),
        mapped.get('cidade'),
    )
    pedido = str(mapped.get('pedido') or '').strip()

    motivos = []
    tipo = str(mapped.get('tipo_venda') or '').upper()
    if tipo and tipo != 'INTERESSE':
        motivos.append(f'Tipo não é INTERESSE ({tipo}).')
    if not tel_ok:
        motivos.append('Sem celular no pedido PAP.')
    if not nome:
        motivos.append('Sem nome do cliente no PAP.')
    if not endereco:
        motivos.append('Sem endereço no pedido PAP.')
    if not pedido:
        motivos.append('Sem número de pedido.')
    if cpf and _cpf_tem_venda_crm(cpf):
        motivos.append('CPF já possui venda no CRM.')

    params = [primeiro_nome(nome), endereco, pedido] if not motivos else []
    dedup = _dedup_recente(cpf, template) if not motivos else None
    if dedup:
        motivos.append(f'Já enviado há menos de {DEDUP_HORAS}h (#{dedup.pk}).')

    return {
        'aba': ABA_INTERESSE,
        'ref_id': str(pedido_id or pedido or cpf),
        'cpf': cpf,
        'telefone': tel,
        'template_nome': template,
        'body_params': params,
        'preview': {
            'nome': primeiro_nome(nome) if nome else '',
            'endereco': endereco,
            'pedido': pedido,
        },
        'elegivel': len(motivos) == 0,
        'motivo_inelegivel': ' '.join(motivos),
    }


def validar_params(template: str, params: list) -> tuple[bool, str]:
    esperados = {
        TEMPLATE_CONSULTA_VIABILIDADE: 3,
        TEMPLATE_REATIVACAO_CONTRATO: 3,
        TEMPLATE_SELFIE_PENDENTE: 2,
    }
    n = esperados.get(template)
    if n is None:
        return False, f'Template não suportado: {template}'
    if len(params) != n:
        return False, f'Template {template} exige {n} variável(is); recebeu {len(params)}.'
    for i, p in enumerate(params, 1):
        if not str(p or '').strip() or str(p).strip() == '-':
            return False, f'Variável {{{{{i}}}}} vazia ou inválida.'
    return True, ''


def enviar_contexto(ctx: dict, *, usuario=None, force: bool = False) -> dict:
    pronto, motivo_canal = _canal_pronto()
    if not pronto:
        return {'ok': False, 'detail': motivo_canal, 'contexto': ctx}

    if not ctx.get('elegivel') and not force:
        return {'ok': False, 'detail': ctx.get('motivo_inelegivel') or 'Não elegível.', 'contexto': ctx}

    ok_params, motivo_params = validar_params(ctx['template_nome'], ctx.get('body_params') or [])
    if not ok_params:
        return {'ok': False, 'detail': motivo_params, 'contexto': ctx}

    if not force:
        dedup = _dedup_recente(ctx.get('cpf') or '', ctx['template_nome'])
        if dedup:
            return {
                'ok': False,
                'detail': f'Já enviado há menos de {DEDUP_HORAS}h (envio #{dedup.pk}).',
                'contexto': ctx,
            }

    # Sem fallback texto — só template oficial Meta
    ok, resp = enviar_template_funil(ctx['telefone'], ctx['template_nome'], ctx['body_params'])
    mid = _extrair_message_id(resp) if ok else ''
    envio = FunilTemplateEnvio.objects.create(
        aba=ctx['aba'],
        ref_id=str(ctx.get('ref_id') or '')[:64],
        cpf=_cpf_limpo(ctx.get('cpf')),
        telefone=ctx.get('telefone') or '',
        template_nome=ctx['template_nome'],
        body_params=ctx.get('body_params') or [],
        message_id=mid,
        status_entrega=FunilTemplateEnvio.STATUS_ACEITO if ok else FunilTemplateEnvio.STATUS_FALHOU,
        sucesso=bool(ok),
        erro='' if ok else str(resp)[:2000],
        enviado_por=usuario if getattr(usuario, 'is_authenticated', False) else None,
    )
    return {
        'ok': bool(ok),
        'detail': 'Enviado.' if ok else str(resp)[:500],
        'envio_id': envio.pk,
        'message_id': mid,
        'contexto': ctx,
    }


def preflight_bio_linha(linha: dict) -> dict:
    # Preflight leve: não chama Assertiva (só no envio real)
    return montar_contexto_bio(linha, resolver_nome=False)


def resumo_envio_listagem(ctx: dict, *, assertiva_no_envio: bool = False) -> dict:
    """Campos leves para a UI do Funil (botão Enviar + motivo)."""
    elegivel = bool(ctx.get('elegivel'))
    motivo = (ctx.get('motivo_inelegivel') or '').strip()
    # Bio sem nome: Assertiva resolve no clique — botão fica habilitado.
    if assertiva_no_envio and not elegivel and motivo == 'Sem nome (CRM/Assertiva).':
        return {
            'elegivel_envio': True,
            'motivo_inelegivel': '',
            'preview_envio': ctx.get('preview') or {},
            'assertiva_no_envio': True,
            'template_nome': ctx.get('template_nome') or '',
        }
    return {
        'elegivel_envio': elegivel,
        'motivo_inelegivel': '' if elegivel else motivo,
        'preview_envio': ctx.get('preview') or {},
        'assertiva_no_envio': False,
        'template_nome': ctx.get('template_nome') or '',
    }


def enriquecer_linha_bio(linha: dict) -> dict:
    ctx = preflight_bio_linha(linha)
    so_nome = (not ctx['elegivel']) and (ctx.get('motivo_inelegivel') or '').strip() == 'Sem nome (CRM/Assertiva).'
    out = dict(linha)
    out.update(resumo_envio_listagem(ctx, assertiva_no_envio=so_nome))
    return out


def enriquecer_linha_churn(linha: dict, venda: Optional[Venda] = None) -> dict:
    ctx = montar_contexto_churn(linha, venda=venda)
    out = dict(linha)
    out.update(resumo_envio_listagem(ctx))
    return out


def enriquecer_linha_interesse(mapped: dict, *, pedido_id: Any = None) -> dict:
    ctx = montar_contexto_interesse(mapped, pedido_id=pedido_id)
    return resumo_envio_listagem(ctx)


def enviar_bio_por_cpf(cpf: str, *, usuario=None, force: bool = False) -> dict:
    from crm_app.services import repescagem_bio_service as bio
    from django.utils import timezone as tz
    hoje = tz.localdate()
    inicio = hoje - timedelta(days=30)
    base = bio.montar_base(inicio, hoje)
    digitos = _cpf_limpo(cpf)
    linha = next((b for b in base if b.get('cpf') == digitos), None)
    if not linha:
        return {'ok': False, 'detail': 'CPF não encontrado na base Bio do período.'}
    ctx = montar_contexto_bio(linha, resolver_nome=True)
    return enviar_contexto(ctx, usuario=usuario, force=force)


def enviar_churn_por_id(churn_id: int, *, usuario=None, force: bool = False) -> dict:
    from crm_app.models import ImportacaoChurn
    try:
        churn = ImportacaoChurn.objects.get(pk=churn_id)
    except ImportacaoChurn.DoesNotExist:
        return {'ok': False, 'detail': 'Churn não encontrado.'}

    pedido = (churn.numero_pedido or churn.nr_ordem or '').strip()
    from crm_app.churn_os_utils import build_venda_lookup_por_os, encontrar_venda_por_churn

    vendas_qs = Venda.objects.filter(ativo=True).select_related('cliente')
    lookup = build_venda_lookup_por_os(vendas_qs)
    venda = encontrar_venda_por_churn(churn, lookup)
    if not venda and pedido:
        venda = (
            Venda.objects.select_related('cliente')
            .filter(Q(ordem_servico=pedido) | Q(numero_pedido=pedido))
            .order_by('-id')
            .first()
        )

    situacao = 'NAO_CONSULTADO'
    try:
        from crm_app.models import ChurnConsultaDebitoNio
        cpf_v = (venda.cliente.cpf_cnpj if venda and venda.cliente_id else '') or ''
        digitos = _cpf_limpo(cpf_v)
        if digitos:
            deb = (
                ChurnConsultaDebitoNio.objects.filter(cpf__icontains=digitos[-11:])
                .order_by('-consultado_em')
                .first()
            )
            if deb:
                situacao = deb.situacao or situacao
    except Exception:
        pass

    linha = {
        'churn_id': churn.pk,
        'venda_id': venda.pk if venda else None,
        'pedido': (venda.ordem_servico if venda else None) or pedido,
        'cpf_cliente': (venda.cliente.cpf_cnpj if venda and venda.cliente_id else '') or '',
        'nome_cliente': (venda.cliente.nome_razao_social if venda and venda.cliente_id else ''),
        'situacao_nio': situacao,
        'sem_venda_crm': venda is None,
    }
    ctx = montar_contexto_churn(linha, venda=venda)
    return enviar_contexto(ctx, usuario=usuario, force=force)


def enviar_interesse_por_pedido_id(pedido_id: int, *, usuario=None, force: bool = False) -> dict:
    from crm_app.models import HistoricoPapPedido
    from crm_app.historico_pap import map_pedido_api
    try:
        p = HistoricoPapPedido.objects.get(pk=pedido_id)
    except HistoricoPapPedido.DoesNotExist:
        return {'ok': False, 'detail': 'Pedido PAP não encontrado.'}
    mapped = map_pedido_api(p.payload or {}, p.tipo_venda)
    mapped['tipo_venda'] = p.tipo_venda or mapped.get('tipo_venda')
    ctx = montar_contexto_interesse(mapped, pedido_id=p.pk)
    return enviar_contexto(ctx, usuario=usuario, force=force)
