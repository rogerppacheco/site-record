"""Marca respostas de contatos de mailing (webhook inbound)."""
from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Optional

from django.db.models import F, Q
from django.utils import timezone

from crm_app.models import MailingContato, MailingLote
from crm_app.services.mailing_import_service import normalizar_telefone_e164

logger = logging.getLogger(__name__)

JANELA_DIAS = 30
OPT_OUT_TEXTOS = {
    'agora não', 'agora nao', 'não', 'nao', 'parar', 'stop', 'sair', 'cancelar',
}


def _variantes_telefone(telefone: str) -> list[str]:
    e164, _ = normalizar_telefone_e164(telefone)
    digitos = re.sub(r'\D', '', str(telefone or ''))
    out = []
    for v in (e164, digitos, digitos[-11:] if len(digitos) >= 11 else '', digitos[-10:] if len(digitos) >= 10 else ''):
        if v and v not in out:
            out.append(v)
        # com e sem 55
        if v.startswith('55') and len(v) > 2:
            local = v[2:]
            if local not in out:
                out.append(local)
        elif v and not v.startswith('55'):
            full = '55' + v
            if full not in out:
                out.append(full)
    return out


def processar_resposta_mailing(telefone: str, mensagem_texto: str = '') -> Optional[dict]:
    """
    Se o telefone bate em contato ENVIADO recente, marca RESPONDEU (ou opt-out).
    Retorna dict com contato_id ou None.
    """
    variantes = _variantes_telefone(telefone)
    if not variantes:
        return None

    limite = timezone.now() - timedelta(days=JANELA_DIAS)
    qs = (
        MailingContato.objects.filter(
            telefone_e164__in=variantes,
            status__in=[MailingContato.STATUS_ENVIADO, MailingContato.STATUS_RESPONDEU],
            telefone_valido=True,
        )
        .filter(Q(envios__enviado_em__gte=limite) | Q(criado_em__gte=limite))
        .select_related('lote')
        .distinct()
        .order_by('-id')
    )
    contato = qs.first()
    if not contato:
        # fallback: qualquer ENVIADO com telefone (sem janela de envio)
        contato = (
            MailingContato.objects.filter(
                telefone_e164__in=variantes,
                status=MailingContato.STATUS_ENVIADO,
                telefone_valido=True,
            )
            .select_related('lote')
            .order_by('-id')
            .first()
        )
    if not contato:
        return None

    texto = (mensagem_texto or '').strip()
    texto_l = texto.lower()
    if any(t in texto_l for t in OPT_OUT_TEXTOS) or texto_l in OPT_OUT_TEXTOS:
        contato.opt_out = True
        contato.status = MailingContato.STATUS_IGNORADO
        contato.resposta_texto = texto[:255]
        contato.respondido_em = timezone.now()
        contato.save(update_fields=['opt_out', 'status', 'resposta_texto', 'respondido_em'])
        logger.info('[Mailing] Opt-out contato #%s lote #%s', contato.pk, contato.lote_id)
        return {'contato_id': contato.pk, 'lote_id': contato.lote_id, 'opt_out': True}

    if contato.status != MailingContato.STATUS_RESPONDEU:
        contato.status = MailingContato.STATUS_RESPONDEU
        contato.resposta_texto = texto[:255]
        contato.respondido_em = timezone.now()
        contato.save(update_fields=['status', 'resposta_texto', 'respondido_em'])
        MailingLote.objects.filter(pk=contato.lote_id).update(total_respostas=F('total_respostas') + 1)
        logger.info('[Mailing] Resposta contato #%s lote #%s texto=%r', contato.pk, contato.lote_id, texto[:80])
    else:
        if texto:
            contato.resposta_texto = texto[:255]
            contato.save(update_fields=['resposta_texto'])

    return {
        'contato_id': contato.pk,
        'lote_id': contato.lote_id,
        'opt_out': False,
        'nome': contato.nome,
        'situacao': contato.situacao,
    }
