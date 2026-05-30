"""Consulta 'Posso antecipar?' ao vendedor na esteira de vendas (WhatsApp + parse da resposta)."""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

HORAS_LIMITE_RESPOSTA = 72


def _normalizar_texto_resposta(texto: str) -> str:
    nfd = unicodedata.normalize('NFD', (texto or '').strip())
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn').upper()


def _normalizar_telefone_chave(telefone: str) -> str:
    if not telefone:
        return ''
    tel = re.sub(r'\D', '', str(telefone))
    if tel.startswith('55') and len(tel) > 12:
        tel = tel[2:]
    return tel


def _extrair_venda_id_da_mensagem(mensagem: str) -> Optional[int]:
    if not mensagem:
        return None
    m = re.search(r'(?:#|protocolo\s*:?\s*)(\d+)', mensagem, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def parse_resposta_posso_antecipar_vendedor(mensagem: str) -> dict:
    """
    Interpreta resposta do vendedor.
    Padrão esperado: Sim, manhã | Sim, tarde | Não
    Retorna: pode (True/False/None), turno (MANHA/TARDE/None), resposta_completa, observacao.
    """
    original = (mensagem or '').strip()
    norm = _normalizar_texto_resposta(original)

    pode = None
    turno = None

    tem_nao = bool(re.search(r'(?:^|\b)NAO(?:\b|,|\s|$)', norm))
    tem_sim = bool(re.search(r'(?:^|\b)SIM(?:\b|,|\s|$)', norm))

    if re.match(r'^\s*NAO\b', norm):
        pode = False
    elif re.match(r'^\s*SIM\b', norm):
        pode = True
    elif tem_nao and not tem_sim:
        pode = False
    elif tem_sim and not tem_nao:
        pode = True

    if re.search(r'\bMANHA\b', norm):
        turno = 'MANHA'
    elif re.search(r'\bTARDE\b', norm):
        turno = 'TARDE'

    obs = original
    for pat in (
        r'(?i)\bsim\b',
        r'(?i)\bnao\b',
        r'(?i)\bnão\b',
        r'(?i)\bmanha\b',
        r'(?i)\bmanhã\b',
        r'(?i)\btarde\b',
        r'[,;:\-\.]+',
        r'(?i)\bprotocolo\b',
        r'#\d+',
    ):
        obs = re.sub(pat, ' ', obs)
    obs = re.sub(r'\s+', ' ', obs).strip()
    if not obs or obs.lower() in ('s', 'n'):
        obs = ''

    return {
        'pode': pode,
        'turno': turno,
        'resposta_completa': original,
        'observacao': obs[:2000] if obs else '',
    }


def montar_mensagem_posso_antecipar(venda) -> str:
    nome_cliente = ''
    if getattr(venda, 'cliente', None):
        nome_cliente = (venda.cliente.nome_razao_social or '').strip()
    os_txt = (getattr(venda, 'ordem_servico', None) or '').strip() or '—'
    header = f'Olá! Sobre o pedido *#{venda.id}*'
    if nome_cliente:
        header += f' — cliente *{nome_cliente}*'
    header += f' (O.S. *{os_txt}*):'

    return '\n'.join([
        header,
        '',
        'Posso tentar antecipar este pedido?',
        '',
        'É uma *tentativa* — *não prometer* para o cliente, só verificar se ele pode atender *hoje ou amanhã*.',
        '',
        'Responda *apenas*:',
        '• *Sim, manhã*',
        '• *Sim, tarde*',
        '• *Não*',
        '',
        f'Protocolo: #{venda.id}',
    ])


def _telefone_vendedor(venda) -> Optional[str]:
    vendedor = getattr(venda, 'vendedor', None)
    if not vendedor:
        return None
    for campo in ('tel_whatsapp', 'tel_whatsapp_2', 'tel_whatsapp_3'):
        tel = (getattr(vendedor, campo, None) or '').strip()
        if tel:
            return tel
    return None


def _mensagem_confirmacao_resposta(venda, parsed: dict) -> str:
    vid = venda.id
    if parsed.get('pode') is True:
        turno = parsed.get('turno')
        if turno == 'MANHA':
            resumo = 'Sim, manhã'
        elif turno == 'TARDE':
            resumo = 'Sim, tarde'
        else:
            resumo = 'Sim'
    elif parsed.get('pode') is False:
        resumo = 'Não'
    else:
        resumo = 'Recebida (formato não padrão)'
    return f'Resposta registrada para o pedido *#{vid}*: *{resumo}*. Obrigado!'


def _chaves_telefone_busca(telefone: str) -> list[str]:
    base = _normalizar_telefone_chave(telefone)
    if not base:
        return []
    chaves = [base]
    if base.startswith('55') and len(base) > 11:
        chaves.append(base[2:])
    elif len(base) >= 10:
        chaves.append('55' + base)
    nacional = base[2:] if base.startswith('55') and len(base) > 11 else base
    if len(nacional) == 10:
        chaves.append(nacional[:2] + '9' + nacional[2:])
    if len(nacional) == 11 and len(nacional) > 2 and nacional[2] == '9':
        chaves.append(nacional[:2] + nacional[3:])
    return list(dict.fromkeys(chaves))


def buscar_solicitacao_pendente_por_telefone(telefone: str, mensagem: str = ''):
    """Localiza solicitação pendente mais recente para o telefone do vendedor."""
    from datetime import timedelta

    from crm_app.models import PossoAnteciparVendedorEnviado

    chaves_norm = _chaves_telefone_busca(telefone)
    if not chaves_norm:
        return None

    limite = timezone.now() - timedelta(hours=HORAS_LIMITE_RESPOSTA)
    qs = (
        PossoAnteciparVendedorEnviado.objects.filter(
            telefone__in=chaves_norm,
            respondido_em__isnull=True,
            data_envio__gte=limite,
        )
        .select_related('venda', 'venda__vendedor')
        .order_by('-data_envio')
    )

    venda_id = _extrair_venda_id_da_mensagem(mensagem)
    if venda_id:
        sol = qs.filter(venda_id=venda_id).first()
        if sol:
            return sol

    return qs.first()


def registrar_resposta_posso_antecipar(solicitacao, mensagem: str) -> dict:
    """Grava resposta do vendedor na venda e marca solicitação como respondida."""
    parsed = parse_resposta_posso_antecipar_vendedor(mensagem)
    agora = timezone.now()
    venda = solicitacao.venda

    campos = [
        'vendedor_pode_antecipar',
        'vendedor_pode_antecipar_turno',
        'vendedor_resposta_posso_antecipar',
        'vendedor_obs_posso_antecipar',
        'data_resposta_posso_antecipar',
    ]

    venda.vendedor_resposta_posso_antecipar = (parsed['resposta_completa'] or '')[:2000] or None
    venda.data_resposta_posso_antecipar = agora
    if parsed['pode'] is not None:
        venda.vendedor_pode_antecipar = parsed['pode']
    if parsed['turno']:
        venda.vendedor_pode_antecipar_turno = parsed['turno']
    if parsed['observacao']:
        venda.vendedor_obs_posso_antecipar = parsed['observacao']
    venda.save(update_fields=campos)

    solicitacao.respondido_em = agora
    solicitacao.save(update_fields=['respondido_em'])

    return parsed


def tentar_enviar_posso_antecipar_vendedor(venda, *, usuario=None) -> dict:
    """
    Envia WhatsApp ao vendedor responsável pela venda.
    Retorna dict: ok, enviado, detail, mensagem.
    """
    from crm_app.models import PossoAnteciparVendedorEnviado
    from crm_app.whatsapp_service import WhatsAppService

    resultado = {'ok': True, 'enviado': False, 'detail': '', 'mensagem': ''}

    if not getattr(venda, 'vendedor_id', None):
        resultado['ok'] = False
        resultado['detail'] = 'Venda sem vendedor vinculado.'
        return resultado

    telefone = _telefone_vendedor(venda)
    if not telefone:
        resultado['ok'] = False
        resultado['detail'] = 'Vendedor sem WhatsApp cadastrado.'
        return resultado

    mensagem = montar_mensagem_posso_antecipar(venda)
    resultado['mensagem'] = mensagem

    try:
        ok, _ = WhatsAppService().enviar_mensagem_texto(telefone, mensagem, variar=False)
        if not ok:
            resultado['ok'] = False
            resultado['detail'] = 'Falha ao enviar mensagem (API WhatsApp).'
            return resultado

        tel_chave = _normalizar_telefone_chave(telefone)
        agora = timezone.now()
        PossoAnteciparVendedorEnviado.objects.create(
            telefone=tel_chave or telefone,
            venda=venda,
            vendedor=venda.vendedor,
            solicitado_por=usuario,
        )
        venda.data_solicitacao_posso_antecipar = agora
        venda.save(update_fields=['data_solicitacao_posso_antecipar'])

        resultado['enviado'] = True
        resultado['detail'] = 'Mensagem enviada ao vendedor.'
    except Exception as exc:
        resultado['ok'] = False
        resultado['detail'] = str(exc)
        logger.exception('Erro ao enviar posso antecipar venda #%s', venda.id)

    return resultado


def processar_resposta_posso_antecipar_vendedor(telefone_remetente, mensagem_texto) -> bool:
    """
    Se o vendedor respondeu a uma consulta pendente, registra e confirma.
    Retorna True se processou (encerrar fluxo do webhook).
    """
    if not (mensagem_texto or '').strip():
        return False

    solicitacao = buscar_solicitacao_pendente_por_telefone(telefone_remetente, mensagem_texto)
    if not solicitacao:
        return False

    try:
        parsed = registrar_resposta_posso_antecipar(solicitacao, mensagem_texto)
        from crm_app.whatsapp_service import WhatsAppService
        from crm_app.whatsapp_webhook_handler import formatar_telefone

        msg = _mensagem_confirmacao_resposta(solicitacao.venda, parsed)
        tel = formatar_telefone(telefone_remetente)
        if tel:
            WhatsAppService().enviar_mensagem_texto(tel, msg, variar=False)
        logger.info(
            '[PossoAntecipar] Resposta registrada venda #%s: pode=%s turno=%s',
            solicitacao.venda_id,
            parsed.get('pode'),
            parsed.get('turno'),
        )
        return True
    except Exception:
        logger.exception('[PossoAntecipar] Erro ao processar resposta do vendedor')
        return False
