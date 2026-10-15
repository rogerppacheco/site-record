"""Disparo em lote de templates de mailing (throttle + status)."""
from __future__ import annotations

import logging
import time
from typing import Optional

from django.db.models import F
from django.utils import timezone

from crm_app.models import MailingContato, MailingEnvio, MailingLote
from crm_app.services.mailing_templates import enviar_mailing_contato

logger = logging.getLogger(__name__)

# ~25 envios/minuto
INTERVALO_SEGUNDOS = 2.4
LOTE_POR_CICLO = 40


def _extrair_message_id(resp) -> str:
    try:
        from crm_app.services.whatsapp.status_entrega_service import extrair_message_id_resposta
        return (extrair_message_id_resposta(resp) or '')[:191]
    except Exception:
        if isinstance(resp, dict):
            msgs = resp.get('messages') or []
            if msgs and isinstance(msgs[0], dict):
                return str(msgs[0].get('id') or '')[:191]
        return ''


def iniciar_disparo(lote_id: int, usuario=None) -> MailingLote:
    lote = MailingLote.objects.get(pk=lote_id)
    if lote.status == MailingLote.STATUS_DISPARANDO:
        return lote
    if lote.status not in (
        MailingLote.STATUS_PRONTO,
        MailingLote.STATUS_PAUSADO,
        MailingLote.STATUS_CONCLUIDO,
    ):
        raise ValueError(f'Lote #{lote_id} não está pronto para disparo (status={lote.status}).')
    lote.status = MailingLote.STATUS_DISPARANDO
    lote.disparado_por = usuario if getattr(usuario, 'is_authenticated', False) else lote.disparado_por
    if not lote.disparo_iniciado_em:
        lote.disparo_iniciado_em = timezone.now()
    lote.disparo_finalizado_em = None
    lote.mensagem = 'Disparo em andamento…'
    lote.save(update_fields=[
        'status', 'disparado_por', 'disparo_iniciado_em', 'disparo_finalizado_em', 'mensagem', 'atualizado_em',
    ])
    return lote


def pausar_disparo(lote_id: int) -> MailingLote:
    lote = MailingLote.objects.get(pk=lote_id)
    if lote.status == MailingLote.STATUS_DISPARANDO:
        lote.status = MailingLote.STATUS_PAUSADO
        lote.mensagem = 'Disparo pausado.'
        lote.save(update_fields=['status', 'mensagem', 'atualizado_em'])
    return lote


def _qs_pendentes(lote: MailingLote):
    return (
        MailingContato.objects.filter(
            lote=lote,
            status=MailingContato.STATUS_NOVO,
            telefone_valido=True,
            opt_out=False,
        )
        .exclude(telefone_e164='')
        .order_by('id')
    )


def processar_ciclo(lote_id: int, *, limite: int = LOTE_POR_CICLO, sleep: bool = True) -> dict:
    """Envia até `limite` contatos de um lote em DISPARANDO. Retorna estatísticas do ciclo."""
    lote = MailingLote.objects.get(pk=lote_id)
    if lote.status != MailingLote.STATUS_DISPARANDO:
        return {'enviados': 0, 'falhas': 0, 'restantes': 0, 'status': lote.status}

    pendentes = list(_qs_pendentes(lote)[:limite])
    enviados = falhas = 0
    for contato in pendentes:
        lote.refresh_from_db(fields=['status'])
        if lote.status != MailingLote.STATUS_DISPARANDO:
            break
        try:
            ok, resp, canal, template = enviar_mailing_contato(contato)
            mid = _extrair_message_id(resp)
        except Exception as exc:
            logger.exception('[Mailing] Falha envio contato #%s', contato.pk)
            ok, resp, canal, template = False, str(exc), 'erro', ''
            mid = ''

        envio = MailingEnvio.objects.create(
            contato=contato,
            template_nome=template or '',
            message_id=mid,
            status_entrega=MailingEnvio.STATUS_ENTREGA_ACEITO if ok else MailingEnvio.STATUS_ENTREGA_FALHOU,
            sucesso=bool(ok),
            erro='' if ok else str(resp)[:2000],
        )
        if ok:
            contato.status = MailingContato.STATUS_ENVIADO
            enviados += 1
            MailingLote.objects.filter(pk=lote.pk).update(total_enviados=F('total_enviados') + 1)
        else:
            contato.status = MailingContato.STATUS_FALHOU
            falhas += 1
            MailingLote.objects.filter(pk=lote.pk).update(total_falhas=F('total_falhas') + 1)
        contato.save(update_fields=['status'])
        logger.info(
            '[Mailing] lote=%s contato=%s template=%s canal=%s ok=%s mid=%s',
            lote.pk, contato.pk, template, canal, ok, envio.message_id,
        )
        if sleep and INTERVALO_SEGUNDOS > 0:
            time.sleep(INTERVALO_SEGUNDOS)

    restantes = _qs_pendentes(lote).count()
    lote.refresh_from_db()
    if lote.status == MailingLote.STATUS_DISPARANDO and restantes == 0:
        lote.status = MailingLote.STATUS_CONCLUIDO
        lote.disparo_finalizado_em = timezone.now()
        lote.mensagem = (
            f'Disparo concluído. Enviados={lote.total_enviados}, falhas={lote.total_falhas}, '
            f'respostas={lote.total_respostas}.'
        )
        lote.save(update_fields=['status', 'disparo_finalizado_em', 'mensagem', 'atualizado_em'])
    return {
        'enviados': enviados,
        'falhas': falhas,
        'restantes': restantes,
        'status': lote.status,
    }


def processar_lotes_em_disparo() -> int:
    """Scheduler: processa um ciclo de cada lote DISPARANDO. Retorna qtd de lotes tocados."""
    ids = list(
        MailingLote.objects.filter(status=MailingLote.STATUS_DISPARANDO)
        .order_by('disparo_iniciado_em')
        .values_list('id', flat=True)[:5]
    )
    for lid in ids:
        try:
            processar_ciclo(lid)
        except Exception:
            logger.exception('[Mailing] Erro no ciclo do lote #%s', lid)
    return len(ids)
