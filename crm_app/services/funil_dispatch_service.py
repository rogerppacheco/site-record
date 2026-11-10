"""Fila de envio em massa de templates do Funil (selecionados / filtrados / automático)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, time as dtime
from typing import Any, Optional

from django.db.models import Q
from django.utils import timezone

from crm_app.models import ConfigDisparoFunil, FunilDisparoLote, FunilTemplateEnvio
from crm_app.services import funil_template_envio_service as tmpl

logger = logging.getLogger(__name__)

INTERVALO_SEGUNDOS = 2.4
ABAS = (FunilTemplateEnvio.ABA_INTERESSE, FunilTemplateEnvio.ABA_CHURN, FunilTemplateEnvio.ABA_BIO)


def _serializar_lote(lote: FunilDisparoLote) -> dict:
    return {
        'id': lote.pk,
        'aba': lote.aba,
        'modo': lote.modo,
        'status': lote.status,
        'total': lote.total,
        'enviados': lote.enviados,
        'falhas': lote.falhas,
        'pulados': lote.pulados,
        'cursor': lote.cursor,
        'mensagem': lote.mensagem or '',
        'criado_em': lote.criado_em.isoformat() if lote.criado_em else None,
        'iniciado_em': lote.iniciado_em.isoformat() if lote.iniciado_em else None,
        'finalizado_em': lote.finalizado_em.isoformat() if lote.finalizado_em else None,
    }


def serializar_config(cfg: ConfigDisparoFunil) -> dict:
    return {
        'aba': cfg.aba,
        'ativo': bool(cfg.ativo),
        'hora_inicio': cfg.hora_inicio.strftime('%H:%M') if cfg.hora_inicio else '09:00',
        'hora_fim': cfg.hora_fim.strftime('%H:%M') if cfg.hora_fim else '18:00',
        'qtd_diaria': cfg.qtd_diaria,
        'limite_por_ciclo': cfg.limite_por_ciclo,
        'enviados_hoje': _enviados_hoje(cfg.aba),
        'atualizado_em': cfg.atualizado_em.isoformat() if cfg.atualizado_em else None,
    }


def obter_ou_criar_config(aba: str) -> ConfigDisparoFunil:
    aba = (aba or '').strip().upper()
    if aba not in ABAS:
        raise ValueError(f'Aba inválida: {aba}')
    cfg, _ = ConfigDisparoFunil.objects.get_or_create(aba=aba)
    return cfg


def listar_configs() -> list[dict]:
    out = []
    for aba in ABAS:
        out.append(serializar_config(obter_ou_criar_config(aba)))
    return out


def atualizar_config(aba: str, dados: dict, usuario=None) -> ConfigDisparoFunil:
    cfg = obter_ou_criar_config(aba)
    if 'ativo' in dados:
        cfg.ativo = bool(dados.get('ativo'))
    if dados.get('hora_inicio'):
        cfg.hora_inicio = _parse_hora(dados['hora_inicio']) or cfg.hora_inicio
    if dados.get('hora_fim'):
        cfg.hora_fim = _parse_hora(dados['hora_fim']) or cfg.hora_fim
    if dados.get('qtd_diaria') is not None:
        cfg.qtd_diaria = max(0, int(dados['qtd_diaria']))
    if dados.get('limite_por_ciclo') is not None:
        cfg.limite_por_ciclo = max(1, min(200, int(dados['limite_por_ciclo'])))
    if usuario is not None and getattr(usuario, 'pk', None):
        cfg.atualizado_por = usuario
    cfg.save()
    return cfg


def _parse_hora(valor) -> Optional[dtime]:
    if isinstance(valor, dtime):
        return valor
    s = str(valor or '').strip()
    if not s:
        return None
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    return None


def _enviados_hoje(aba: str) -> int:
    hoje = timezone.localdate()
    inicio = timezone.make_aware(datetime.combine(hoje, dtime.min))
    return FunilTemplateEnvio.objects.filter(
        aba=aba,
        sucesso=True,
        enviado_em__gte=inicio,
    ).count()


def dentro_da_janela(cfg: ConfigDisparoFunil, agora=None) -> bool:
    agora = agora or timezone.localtime()
    h = agora.time()
    ini = cfg.hora_inicio or dtime(9, 0)
    fim = cfg.hora_fim or dtime(18, 0)
    if ini <= fim:
        return ini <= h <= fim
    # Janela que cruza meia-noite
    return h >= ini or h <= fim


def cota_restante(cfg: ConfigDisparoFunil) -> int:
    return max(0, int(cfg.qtd_diaria or 0) - _enviados_hoje(cfg.aba))


def _refs_interesse_por_filtros(filtros: dict, limite: int = 5000) -> list[str]:
    from crm_app.historico_pap_api import filtrar_pedidos_funil

    qp = {**(filtros or {}), 'tipo': 'INTERESSE'}
    f = filtrar_pedidos_funil(qp)
    return [str(pk) for pk in f['qs_tipo'].order_by('-capturado_em').values_list('id', flat=True)[:limite]]


def _refs_churn_por_filtros(filtros: dict, limite: int = 5000) -> list[str]:
    """Devolve churn_ids candidatos a partir dos filtros da aba."""
    from crm_app.models import ImportacaoChurn

    qs = ImportacaoChurn.objects.all().order_by('-dt_retirada', '-id')
    busca = str((filtros or {}).get('busca') or (filtros or {}).get('q') or '').strip()
    mes = str((filtros or {}).get('mes_referencia') or '').strip()
    if mes and mes.lower() not in ('todos', 'all'):
        anomes = mes.replace('-', '')[:6]
        if anomes.isdigit():
            qs = qs.filter(Q(anomes_retirada=anomes) | Q(anomes_retirada=anomes.lstrip('0') or anomes))
    if busca:
        qs = qs.filter(
            Q(numero_pedido__icontains=busca)
            | Q(nr_ordem__icontains=busca)
            | Q(motivo_retirada__icontains=busca)
        )
    return [str(pk) for pk in qs.values_list('id', flat=True)[:limite]]


def _refs_bio_por_filtros(filtros: dict, limite: int = 5000) -> list[str]:
    from datetime import timedelta
    from crm_app.services import repescagem_bio_service as bio

    hoje = timezone.localdate()
    de = (filtros or {}).get('de')
    ate = (filtros or {}).get('ate')
    try:
        inicio = datetime.strptime(str(de), '%Y-%m-%d').date() if de else (hoje - timedelta(days=30))
    except ValueError:
        inicio = hoje - timedelta(days=30)
    try:
        fim = datetime.strptime(str(ate), '%Y-%m-%d').date() if ate else hoje
    except ValueError:
        fim = hoje
    base = bio.montar_base(inicio, fim)
    cpf = ''.join(c for c in str((filtros or {}).get('cpf') or '') if c.isdigit())
    busca = str((filtros or {}).get('busca') or (filtros or {}).get('q') or '').strip().lower()
    rep = str((filtros or {}).get('rep') or (filtros or {}).get('repescavel') or '').strip().upper()
    situacao = str((filtros or {}).get('situacao') or (filtros or {}).get('bio') or '').strip().upper()
    out = []
    for b in base:
        if rep == 'SIM' and not b.get('repescavel'):
            continue
        if rep == 'NAO' and b.get('repescavel'):
            continue
        if situacao and situacao not in ('REPESCAR',) and b.get('situacao') != situacao:
            continue
        if situacao == 'REPESCAR' and not b.get('repescavel'):
            continue
        if cpf and cpf not in (b.get('cpf') or ''):
            continue
        if busca:
            blob = ' '.join([
                str(b.get('nome_cliente') or ''),
                str(b.get('cpf') or ''),
                str(b.get('vendedor') or ''),
                str(b.get('protocolo') or ''),
            ]).lower()
            if busca not in blob:
                continue
        if b.get('repescavel') or not rep:
            out.append(str(b.get('cpf') or ''))
        if len(out) >= limite:
            break
    return [x for x in out if x]


def resolver_refs(aba: str, modo: str, ids: list | None, filtros: dict | None) -> list[str]:
    aba = (aba or '').strip().upper()
    modo = (modo or '').strip().upper()
    if modo == FunilDisparoLote.MODO_IDS:
        return [str(x).strip() for x in (ids or []) if str(x).strip()]
    filtros = filtros or {}
    if aba == FunilTemplateEnvio.ABA_INTERESSE:
        return _refs_interesse_por_filtros(filtros)
    if aba == FunilTemplateEnvio.ABA_CHURN:
        return _refs_churn_por_filtros(filtros)
    if aba == FunilTemplateEnvio.ABA_BIO:
        return _refs_bio_por_filtros(filtros)
    return []


def iniciar_lote(
    *,
    aba: str,
    modo: str,
    ids: list | None = None,
    filtros: dict | None = None,
    usuario=None,
) -> FunilDisparoLote:
    aba = (aba or '').strip().upper()
    modo = (modo or '').strip().upper()
    if aba not in ABAS:
        raise ValueError(f'Aba não suportada para disparo: {aba}')
    if modo not in (FunilDisparoLote.MODO_IDS, FunilDisparoLote.MODO_FILTROS, FunilDisparoLote.MODO_AUTO):
        raise ValueError(f'Modo inválido: {modo}')

    refs = resolver_refs(aba, modo, ids, filtros)
    if not refs:
        raise ValueError('Nenhum item para enviar com esses critérios.')

    lote = FunilDisparoLote.objects.create(
        aba=aba,
        modo=modo,
        status=FunilDisparoLote.STATUS_DISPARANDO,
        ref_ids=refs,
        filtros=filtros or {},
        total=len(refs),
        mensagem=f'Fila com {len(refs)} item(ns)…',
        criado_por=usuario if getattr(usuario, 'is_authenticated', False) else None,
        iniciado_em=timezone.now(),
    )
    return lote


def pausar_lote(lote_id: int) -> FunilDisparoLote:
    lote = FunilDisparoLote.objects.get(pk=lote_id)
    if lote.status == FunilDisparoLote.STATUS_DISPARANDO:
        lote.status = FunilDisparoLote.STATUS_PAUSADO
        lote.mensagem = 'Disparo pausado.'
        lote.save(update_fields=['status', 'mensagem', 'atualizado_em'])
    return lote


def retomar_lote(lote_id: int) -> FunilDisparoLote:
    lote = FunilDisparoLote.objects.get(pk=lote_id)
    if lote.status == FunilDisparoLote.STATUS_PAUSADO:
        lote.status = FunilDisparoLote.STATUS_DISPARANDO
        lote.mensagem = 'Disparo retomado…'
        lote.finalizado_em = None
        lote.save(update_fields=['status', 'mensagem', 'finalizado_em', 'atualizado_em'])
    return lote


def _enviar_ref(aba: str, ref: str, usuario=None) -> dict:
    if aba == FunilTemplateEnvio.ABA_INTERESSE:
        return tmpl.enviar_interesse_por_pedido_id(int(ref), usuario=usuario, force=False)
    if aba == FunilTemplateEnvio.ABA_CHURN:
        return tmpl.enviar_churn_por_id(int(ref), usuario=usuario, force=False)
    if aba == FunilTemplateEnvio.ABA_BIO:
        return tmpl.enviar_bio_por_cpf(str(ref), usuario=usuario, force=False)
    return {'ok': False, 'detail': f'Aba inválida: {aba}'}


def processar_lote(lote: FunilDisparoLote, *, limite: int = 40) -> FunilDisparoLote:
    if lote.status != FunilDisparoLote.STATUS_DISPARANDO:
        return lote

    cfg = obter_ou_criar_config(lote.aba)
    if lote.modo == FunilDisparoLote.MODO_AUTO:
        if not cfg.ativo or not dentro_da_janela(cfg):
            lote.mensagem = 'Fora da janela ou autoenvio desligado.'
            lote.save(update_fields=['mensagem', 'atualizado_em'])
            return lote
        restante = cota_restante(cfg)
        if restante <= 0:
            lote.status = FunilDisparoLote.STATUS_CONCLUIDO
            lote.mensagem = 'Cota diária atingida.'
            lote.finalizado_em = timezone.now()
            lote.save(update_fields=['status', 'mensagem', 'finalizado_em', 'atualizado_em'])
            return lote
        limite = min(limite, cfg.limite_por_ciclo or limite, restante)
    else:
        # Manual também respeita janela/cota se config ativa
        if cfg.ativo:
            if not dentro_da_janela(cfg):
                lote.mensagem = 'Aguardando janela de horário configurada.'
                lote.save(update_fields=['mensagem', 'atualizado_em'])
                return lote
            restante = cota_restante(cfg)
            if restante <= 0:
                lote.mensagem = 'Cota diária atingida — pause ou aumente o limite.'
                lote.save(update_fields=['mensagem', 'atualizado_em'])
                return lote
            limite = min(limite, restante, cfg.limite_por_ciclo or limite)

    refs = list(lote.ref_ids or [])
    processados = 0
    while lote.cursor < len(refs) and processados < limite:
        ref = refs[lote.cursor]
        lote.cursor += 1
        processados += 1
        try:
            result = _enviar_ref(lote.aba, ref, usuario=lote.criado_por)
            if result.get('ok'):
                lote.enviados += 1
            else:
                detail = str(result.get('detail') or '')
                if 'Já enviado' in detail or 'Não elegível' in detail or 'não elegível' in detail.lower():
                    lote.pulados += 1
                else:
                    lote.falhas += 1
        except Exception as exc:
            logger.exception('[FunilDisparo] falha ref=%s aba=%s', ref, lote.aba)
            lote.falhas += 1
            lote.mensagem = str(exc)[:200]
        if processados < limite and lote.cursor < len(refs):
            time.sleep(INTERVALO_SEGUNDOS)

    if lote.cursor >= len(refs):
        lote.status = FunilDisparoLote.STATUS_CONCLUIDO
        lote.finalizado_em = timezone.now()
        lote.mensagem = (
            f'Concluído: {lote.enviados} enviado(s), {lote.falhas} falha(s), {lote.pulados} pulado(s).'
        )
    else:
        lote.mensagem = (
            f'Progresso {lote.cursor}/{lote.total}: '
            f'{lote.enviados} ok, {lote.falhas} falha, {lote.pulados} pulado.'
        )
    lote.save()
    return lote


def processar_lotes_em_disparo(limite_por_lote: int = 40) -> int:
    n = 0
    qs = FunilDisparoLote.objects.filter(status=FunilDisparoLote.STATUS_DISPARANDO).order_by('id')[:5]
    for lote in qs:
        processar_lote(lote, limite=limite_por_lote)
        n += 1
    # Autoenvio: cria/avança lotes AUTO por aba com config ativa
    for aba in ABAS:
        try:
            cfg = obter_ou_criar_config(aba)
        except Exception:
            continue
        if not cfg.ativo or not dentro_da_janela(cfg) or cota_restante(cfg) <= 0:
            continue
        ativo = FunilDisparoLote.objects.filter(
            aba=aba,
            modo=FunilDisparoLote.MODO_AUTO,
            status=FunilDisparoLote.STATUS_DISPARANDO,
        ).first()
        if ativo:
            continue
        try:
            refs = resolver_refs(aba, FunilDisparoLote.MODO_FILTROS, None, {'rep': 'SIM'} if aba == 'BIO' else {})
            if not refs:
                continue
            # Limita à cota restante do dia
            refs = refs[: cota_restante(cfg)]
            lote = FunilDisparoLote.objects.create(
                aba=aba,
                modo=FunilDisparoLote.MODO_AUTO,
                status=FunilDisparoLote.STATUS_DISPARANDO,
                ref_ids=refs,
                filtros={'auto': True},
                total=len(refs),
                mensagem='Autoenvio iniciado…',
                iniciado_em=timezone.now(),
            )
            processar_lote(lote, limite=cfg.limite_por_ciclo or limite_por_lote)
            n += 1
        except Exception:
            logger.exception('[FunilDisparo] autoenvio falhou aba=%s', aba)
    return n
