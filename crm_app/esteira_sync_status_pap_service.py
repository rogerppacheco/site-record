"""
Sincronização noturna/manual da esteira (AGENDADO/PENDENCIADA) via consulta PAP (fluxo STATUS).
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional, Tuple

from django.conf import settings
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone

logger = logging.getLogger(__name__)

TELEFONE_JOB = 'SYNC-ESTEIRA-PAP'


def _run_django_sync(func, timeout_seconds: int = 120):
    """Executa ORM Django em thread dedicada (evita SynchronousOnlyOperation após Playwright)."""
    import queue

    import django.db

    q = queue.Queue()

    def worker():
        try:
            django.db.close_old_connections()
            q.put(('ok', func()))
        except Exception as e:
            q.put(('err', e))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if not q.empty():
        kind, payload = q.get()
        if kind == 'err':
            raise payload
        return payload
    if t.is_alive():
        logger.error('[SYNC ESTEIRA] _run_django_sync expirou após %ss.', timeout_seconds)
        raise TimeoutError('django_sync_timeout')


def _cfg(nome: str, default):
    return getattr(settings, nome, default)


def _hora_inicio() -> int:
    return int(_cfg('SYNC_ESTEIRA_HORA_INICIO', 22))


def _hora_fim() -> int:
    return int(_cfg('SYNC_ESTEIRA_HORA_FIM', 7))


def _max_por_hora() -> int:
    return int(_cfg('SYNC_ESTEIRA_MAX_POR_HORA', 40))


def _dentro_janela_horario(agora=None) -> bool:
    """Janela 22h–07h (horário local)."""
    agora = agora or timezone.localtime()
    h = agora.hour
    ini, fim = _hora_inicio(), _hora_fim()
    if ini > fim:
        return h >= ini or h < fim
    return ini <= h < fim


def job_em_andamento() -> bool:
    encerrar_execucoes_orfas()
    from crm_app.models import SyncStatusEsteiraExecucao

    return SyncStatusEsteiraExecucao.objects.filter(
        status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO
    ).exists()


def execucao_em_andamento() -> Optional['SyncStatusEsteiraExecucao']:
    encerrar_execucoes_orfas()
    from crm_app.models import SyncStatusEsteiraExecucao

    return (
        SyncStatusEsteiraExecucao.objects.filter(
            status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO
        )
        .order_by('-iniciado_em')
        .first()
    )


def queryset_vendas_elegiveis():
    from crm_app.models import Venda

    hoje = timezone.localdate()
    amanha = hoje + timedelta(days=1)

    return (
        Venda.objects.filter(
            ativo=True,
            status_esteira__isnull=False,
            status_esteira__estado__iexact='ABERTO',
        )
        .filter(
            Q(status_esteira__nome__iexact='AGENDADO')
            | Q(status_esteira__nome__iexact='PENDENCIADA')
        )
        .exclude(ordem_servico__isnull=True)
        .exclude(ordem_servico='')
        .select_related('cliente', 'vendedor', 'status_esteira', 'motivo_pendencia')
        .annotate(
            _prio_data=Case(
                When(data_agendamento=hoje, then=Value(0)),
                When(data_agendamento=amanha, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
            _prio_status=Case(
                When(status_esteira__nome__iexact='AGENDADO', then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        )
        .order_by('_prio_data', '_prio_status', 'data_criacao')
    )


def _cpf_cnpj_venda(venda) -> str:
    from crm_app.utils import limpar_texto

    if not venda.cliente or not venda.cliente.cpf_cnpj:
        return ''
    return limpar_texto(venda.cliente.cpf_cnpj)


def _pausa_aleatoria_entre_pedidos():
    if random.random() < 0.45:
        lo = int(_cfg('SYNC_ESTEIRA_INTERVALO_CURTO_MIN_SEG', 120))
        hi = int(_cfg('SYNC_ESTEIRA_INTERVALO_CURTO_MAX_SEG', 300))
    else:
        lo = int(_cfg('SYNC_ESTEIRA_INTERVALO_LONGO_MIN_SEG', 300))
        hi = int(_cfg('SYNC_ESTEIRA_INTERVALO_LONGO_MAX_SEG', 600))
    seg = random.randint(lo, max(lo + 1, hi))
    logger.info('[SYNC ESTEIRA] Pausa %ss antes do próximo pedido.', seg)
    time.sleep(seg)


def _registrar_consulta_hora(consultas_hora: Deque[float]):
    agora = time.time()
    consultas_hora.append(agora)
    limite = agora - 3600
    while consultas_hora and consultas_hora[0] < limite:
        consultas_hora.popleft()


def _aguardar_limite_hora(consultas_hora: Deque[float]):
    while len(consultas_hora) >= _max_por_hora():
        if not consultas_hora:
            break
        espera = max(30, consultas_hora[0] + 3600 - time.time())
        logger.info('[SYNC ESTEIRA] Limite %s/hora — aguardando %.0fs.', _max_por_hora(), espera)
        time.sleep(min(espera, 120))


def _telefones_usuario(usuario) -> List[str]:
    out = []
    for attr in ('tel_whatsapp', 'tel_whatsapp_2', 'tel_whatsapp_3'):
        raw = (getattr(usuario, attr, None) or '').strip()
        dig = re.sub(r'\D', '', raw)
        if len(dig) >= 10:
            out.append(dig)
    return list(dict.fromkeys(out))


def _usuarios_diretoria_backoffice_admin():
    from usuarios.models import Usuario

    return (
        Usuario.objects.filter(is_active=True, groups__name__in=['BackOffice', 'Diretoria', 'Admin'])
        .distinct()
        .only('id', 'username', 'tel_whatsapp', 'tel_whatsapp_2', 'tel_whatsapp_3')
    )


def _enviar_whatsapp_vendedor(venda) -> bool:
    from crm_app.utils import montar_mensagem_whatsapp_esteira_vendedor
    from crm_app.whatsapp_service import WhatsAppService

    if not venda.vendedor or not venda.vendedor.tel_whatsapp:
        return False
    msg = montar_mensagem_whatsapp_esteira_vendedor(venda, prefixo_atualizacao=True)
    if not msg:
        return False
    try:
        ok, _ = WhatsAppService().enviar_mensagem_texto(venda.vendedor.tel_whatsapp, msg)
        return bool(ok)
    except Exception as e:
        logger.warning('[SYNC ESTEIRA] Falha WhatsApp vendedor venda #%s: %s', venda.id, e)
        return False


def _enviar_relatorio_destinatarios(texto: str) -> int:
    from crm_app.whatsapp_service import WhatsAppService

    svc = WhatsAppService()
    enviados = 0
    vistos = set()
    for u in _usuarios_diretoria_backoffice_admin():
        for tel in _telefones_usuario(u):
            if tel in vistos:
                continue
            vistos.add(tel)
            try:
                ok, _ = svc.enviar_mensagem_texto(tel, texto)
                if ok:
                    enviados += 1
            except Exception as e:
                logger.debug('[SYNC ESTEIRA] Falha relatório para %s: %s', u.username, e)
    return enviados


def _montar_relatorio_final(execucao, detalhes: List[dict]) -> str:
    modo = 'Manual' if execucao.modo == execucao.MODO_MANUAL else 'Automático'
    linhas = [
        f'📊 *Relatório sync esteira PAP* ({modo})',
        '',
        f'🆔 Execução #{execucao.id}',
        f'📦 Total elegível: {execucao.total_pedidos}',
        f'✅ Processados: {execucao.processados}',
        f'🔄 Atualizados: {execucao.atualizados}',
        f'➖ Sem alteração: {execucao.sem_alteracao}',
        f'❌ Erros: {execucao.erros}',
        f'⚠️ Ignorados (sem CPF/CNPJ): {execucao.ignorados_sem_cpf}',
    ]
    atualizados = [d for d in detalhes if d.get('alterou')]
    if atualizados:
        linhas.append('')
        linhas.append('*Atualizações:*')
        for item in atualizados[:25]:
            linhas.append(
                f"• OS {item.get('os', '?')} — {item.get('status_anterior', '?')} → {item.get('status_novo', '?')}"
            )
        if len(atualizados) > 25:
            linhas.append(f'… e mais {len(atualizados) - 25}.')
    erros = [d for d in detalhes if d.get('erro')]
    if erros:
        linhas.append('')
        linhas.append('*Erros:*')
        for item in erros[:15]:
            linhas.append(f"• Venda #{item.get('venda_id')} OS {item.get('os', '?')}: {item.get('erro', '?')[:80]}")
    ignorados = [d for d in detalhes if d.get('ignorado_sem_cpf')]
    if ignorados:
        linhas.append('')
        linhas.append(f'*Sem CPF/CNPJ:* {len(ignorados)} pedido(s).')
    return '\n'.join(linhas)


def _consultar_pap_pedido(
    venda,
    *,
    contador_uso_bo: Dict[int, int],
) -> Tuple[bool, str, list, Optional[str]]:
    from crm_app.pool_bo_pap import (
        TIPO_AUTOMACAO_STATUS,
        aguardar_login_bo,
        atualizar_historico_consulta_pap_resultado,
        liberar_bo,
    )
    from crm_app.services_pap_nio import PAPNioAutomation
    from crm_app.utils import limpar_texto, obter_os_prioridade_crm_por_cpf

    cpf = _cpf_cnpj_venda(venda)
    if len(cpf) not in (11, 14):
        return False, 'sem_cpf', [], None

    os_num = (venda.ordem_servico or '').strip()
    os_prioridade = obter_os_prioridade_crm_por_cpf(cpf)

    bo_usuario, msg_erro = aguardar_login_bo(
        TELEFONE_JOB,
        tipo_automacao=TIPO_AUTOMACAO_STATUS,
        timeout_seg=900,
        intervalo_seg=45,
        contador_uso_por_bo=contador_uso_bo,
    )
    if not bo_usuario:
        return False, msg_erro or 'login_indisponivel', [], None

    contador_uso_bo[bo_usuario.id] = contador_uso_bo.get(bo_usuario.id, 0) + 1
    automacao = None
    tempo_inicio = time.time()
    sucesso = False
    msg = ''
    detalhes: list = []
    try:
        headless = getattr(settings, 'PAP_HEADLESS', True)
        capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS', False)
        optimize_fast = getattr(settings, 'PAP_STATUS_FAST_MODE', True)
        automacao = PAPNioAutomation(
            matricula_pap=bo_usuario.matricula_pap,
            senha_pap=bo_usuario.senha_pap,
            vendedor_nome='Sync-Esteira',
            headless=headless,
            capture_screenshots=capture_screenshots,
            optimize_for_credit=optimize_fast,
        )
        sucesso, msg = automacao.iniciar_sessao()
        if not sucesso:
            _run_django_sync(
                lambda: atualizar_historico_consulta_pap_resultado(
                    vendedor_telefone=TELEFONE_JOB,
                    bo_usuario=bo_usuario,
                    tipo_automacao=TIPO_AUTOMACAO_STATUS,
                    sucesso=False,
                    mensagem_resultado=msg,
                )
            )
            return False, msg, [], None

        sucesso, msg, detalhes, _ = automacao.consulta_os_por_cpf_com_resultado(
            cpf,
            numero_os_filtro=os_num,
            os_prioridade_crm=os_prioridade,
        )
        tempo = round(time.time() - tempo_inicio, 1)
        if automacao:
            automacao._fechar_sessao()
            automacao = None
        _run_django_sync(
            lambda: atualizar_historico_consulta_pap_resultado(
                vendedor_telefone=TELEFONE_JOB,
                bo_usuario=bo_usuario,
                tipo_automacao=TIPO_AUTOMACAO_STATUS,
                sucesso=sucesso,
                mensagem_resultado=f'{msg} ({tempo}s)',
            )
        )
        return sucesso, msg, detalhes or [], None
    except Exception as e:
        logger.exception('[SYNC ESTEIRA] Erro PAP venda #%s: %s', venda.id, e)
        if automacao:
            try:
                automacao._fechar_sessao()
            except Exception:
                pass
        err_msg = str(e)[:500]
        _run_django_sync(
            lambda: atualizar_historico_consulta_pap_resultado(
                vendedor_telefone=TELEFONE_JOB,
                bo_usuario=bo_usuario,
                tipo_automacao=TIPO_AUTOMACAO_STATUS,
                sucesso=False,
                mensagem_resultado=err_msg,
            )
        )
        return False, str(e), [], None
    finally:
        _run_django_sync(lambda: liberar_bo(bo_usuario.id, TELEFONE_JOB))


def _processar_um_pedido(
    venda,
    *,
    contador_uso_bo: Dict[int, int],
    retry: bool = False,
) -> dict:
    from crm_app.models import Venda
    from crm_app.utils import sincronizar_venda_crm_apos_status_pap

    os_num = (venda.ordem_servico or '').strip()
    cpf = _cpf_cnpj_venda(venda)
    base = {
        'venda_id': venda.id,
        'os': os_num,
        'retry': retry,
        'alterou': False,
    }
    if len(cpf) not in (11, 14):
        return {**base, 'ignorado_sem_cpf': True}

    sucesso, msg, detalhes, _ = _consultar_pap_pedido(venda, contador_uso_bo=contador_uso_bo)
    if not sucesso:
        return {**base, 'erro': msg or 'falha_pap', 'retentar': True}

    if msg == 'no_results' or not detalhes:
        return {**base, 'sem_alteracao': True, 'detalhe': 'sem_resultado_pap'}

    pos_pap: dict = {}

    def _pos_pap():
        alteracoes = sincronizar_venda_crm_apos_status_pap(cpf, detalhes, os_filtro=os_num)
        if not alteracoes:
            pos_pap['resultado'] = {**base, 'sem_alteracao': True}
            return
        item = alteracoes[0]
        venda_atual = Venda.objects.select_related(
            'cliente', 'vendedor', 'status_esteira', 'motivo_pendencia'
        ).get(pk=venda.id)
        wpp = _enviar_whatsapp_vendedor(venda_atual)
        pos_pap['resultado'] = {
            **base,
            **item,
            'whatsapp_vendedor': wpp,
        }

    _run_django_sync(_pos_pap)
    return pos_pap.get('resultado', {**base, 'sem_alteracao': True})


def _atualizar_execucao(execucao, **kwargs):
    rj = kwargs.get('relatorio_json')
    if rj is None:
        rj = dict(execucao.relatorio_json or {})
    else:
        rj = dict(rj)
    rj['_heartbeat'] = timezone.now().isoformat()
    kwargs['relatorio_json'] = rj
    for k, v in kwargs.items():
        setattr(execucao, k, v)
    execucao.save(update_fields=list(kwargs.keys()))


def _minutos_sem_progresso(execucao) -> Optional[float]:
    hb = (execucao.relatorio_json or {}).get('_heartbeat')
    ref = execucao.iniciado_em
    if hb:
        try:
            parsed = datetime.fromisoformat(hb.replace('Z', '+00:00'))
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            ref = parsed
        except (TypeError, ValueError):
            pass
    if not ref:
        return None
    return (timezone.now() - ref).total_seconds() / 60.0


def _stale_minutos() -> int:
    return int(_cfg('SYNC_ESTEIRA_STALE_MINUTES', 75))


def encerrar_execucoes_orfas(*, motivo: str = '') -> int:
    """Marca como interrompido jobs em_andamento sem heartbeat recente (ex.: deploy matou a thread)."""
    from crm_app.models import SyncStatusEsteiraExecucao

    limite_min = _stale_minutos()
    encerradas = 0
    msg = motivo or (
        f'Encerrado automaticamente — sem progresso há mais de {limite_min} min '
        '(possível reinício do servidor ou travamento).'
    )
    for execucao in SyncStatusEsteiraExecucao.objects.filter(
        status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO,
    ):
        minutos = _minutos_sem_progresso(execucao)
        if minutos is None or minutos < limite_min:
            continue
        _atualizar_execucao(
            execucao,
            status=SyncStatusEsteiraExecucao.STATUS_INTERROMPIDO,
            finalizado_em=timezone.now(),
            mensagem_erro=msg[:2000],
        )
        encerradas += 1
        logger.warning(
            '[SYNC ESTEIRA] Execução órfã #%s encerrada (%.0f min sem progresso).',
            execucao.id,
            minutos,
        )
    return encerradas


def cancelar_execucao(execucao_id: int, *, usuario=None) -> Tuple[bool, str]:
    from crm_app.models import SyncStatusEsteiraExecucao

    encerrar_execucoes_orfas()
    try:
        execucao = SyncStatusEsteiraExecucao.objects.get(pk=execucao_id)
    except SyncStatusEsteiraExecucao.DoesNotExist:
        return False, 'Execução não encontrada.'
    if execucao.status != SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO:
        return False, 'Execução não está em andamento.'
    quem = getattr(usuario, 'username', None) or 'sistema'
    _atualizar_execucao(
        execucao,
        status=SyncStatusEsteiraExecucao.STATUS_INTERROMPIDO,
        finalizado_em=timezone.now(),
        mensagem_erro=f'Cancelado por {quem}.',
    )
    logger.info('[SYNC ESTEIRA] Execução #%s cancelada por %s.', execucao_id, quem)
    return True, ''


def executar_job(execucao_id: int) -> None:
    from crm_app.models import SyncStatusEsteiraExecucao

    try:
        execucao = SyncStatusEsteiraExecucao.objects.get(pk=execucao_id)
    except SyncStatusEsteiraExecucao.DoesNotExist:
        logger.error('[SYNC ESTEIRA] Execução #%s não encontrada.', execucao_id)
        return

    if execucao.status != SyncStatusEsteiraExecucao.STATUS_PENDENTE:
        logger.warning('[SYNC ESTEIRA] Execução #%s não está pendente (%s).', execucao_id, execucao.status)
        return

    vendas = list(queryset_vendas_elegiveis())
    fila: List = list(vendas)
    retentativas: List = []
    detalhes: List[dict] = []
    contador_uso_bo: Dict[int, int] = {}
    consultas_hora: Deque[float] = deque()

    _atualizar_execucao(
        execucao,
        status=SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO,
        total_pedidos=len(vendas),
        relatorio_json={'detalhes': []},
    )
    logger.info('[SYNC ESTEIRA] Iniciando execução #%s (%s) — %s pedidos.', execucao_id, execucao.modo, len(vendas))

    processados = atualizados = sem_alteracao = erros = ignorados = 0
    primeira = True

    while fila or retentativas:
        execucao.refresh_from_db()
        if execucao.status != SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO:
            logger.info('[SYNC ESTEIRA] Execução #%s interrompida externamente.', execucao_id)
            break

        if execucao.modo == SyncStatusEsteiraExecucao.MODO_AUTOMATICO and not _dentro_janela_horario():
            logger.info('[SYNC ESTEIRA] Fora da janela 22h–07h — encerrando execução automática.')
            break

        if retentativas:
            venda = retentativas.pop(0)
            retry = True
        else:
            venda = fila.pop(0)
            retry = False

        if not primeira:
            _pausa_aleatoria_entre_pedidos()
        primeira = False

        _aguardar_limite_hora(consultas_hora)

        try:
            resultado = _processar_um_pedido(venda, contador_uso_bo=contador_uso_bo, retry=retry)
        except Exception as e:
            logger.exception('[SYNC ESTEIRA] Falha inesperada venda #%s', venda.id)
            resultado = {
                'venda_id': venda.id,
                'os': venda.ordem_servico,
                'erro': str(e)[:300],
                'retentar': True,
            }

        processados += 1
        _registrar_consulta_hora(consultas_hora)

        if resultado.get('ignorado_sem_cpf'):
            ignorados += 1
        elif resultado.get('erro'):
            if resultado.get('retentar') and not retry:
                retentativas.append(venda)
                detalhes.append({**resultado, 'aguardando_retry': True})
            else:
                erros += 1
                detalhes.append(resultado)
        elif resultado.get('alterou'):
            atualizados += 1
            detalhes.append(resultado)
        else:
            sem_alteracao += 1
            detalhes.append(resultado)

        _atualizar_execucao(
            execucao,
            processados=processados,
            atualizados=atualizados,
            sem_alteracao=sem_alteracao,
            erros=erros,
            ignorados_sem_cpf=ignorados,
            relatorio_json={'detalhes': detalhes[-200:]},
        )

    status_final = SyncStatusEsteiraExecucao.STATUS_CONCLUIDO
    if execucao.status == SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO:
        if fila or retentativas:
            status_final = SyncStatusEsteiraExecucao.STATUS_INTERROMPIDO
    else:
        status_final = execucao.status

    _atualizar_execucao(
        execucao,
        status=status_final,
        finalizado_em=timezone.now(),
        processados=processados,
        atualizados=atualizados,
        sem_alteracao=sem_alteracao,
        erros=erros,
        ignorados_sem_cpf=ignorados,
        relatorio_json={'detalhes': detalhes},
    )

    try:
        texto = _montar_relatorio_final(execucao, detalhes)
        _enviar_relatorio_destinatarios(texto)
    except Exception as e:
        logger.exception('[SYNC ESTEIRA] Falha ao enviar relatório: %s', e)

    if erros or status_final == SyncStatusEsteiraExecucao.STATUS_INTERROMPIDO:
        try:
            alerta = (
                f'⚠️ *Sync esteira PAP* — execução #{execucao.id}\n\n'
                f'Status: {status_final}\n'
                f'Erros: {erros}\n'
                f'Pendentes na fila: {len(fila) + len(retentativas)}'
            )
            _enviar_relatorio_destinatarios(alerta)
        except Exception:
            pass

    logger.info(
        '[SYNC ESTEIRA] Execução #%s finalizada (%s). proc=%s att=%s err=%s',
        execucao_id,
        status_final,
        processados,
        atualizados,
        erros,
    )


def tentar_iniciar_automatico() -> bool:
    from crm_app.models import SyncStatusEsteiraExecucao

    if job_em_andamento():
        logger.info('[SYNC ESTEIRA] Automático ignorado — job manual/em andamento.')
        return False
    if not _dentro_janela_horario():
        logger.info('[SYNC ESTEIRA] Automático fora da janela horária.')
        return False
    execucao = SyncStatusEsteiraExecucao.objects.create(
        modo=SyncStatusEsteiraExecucao.MODO_AUTOMATICO,
        status=SyncStatusEsteiraExecucao.STATUS_PENDENTE,
    )
    executar_job(execucao.id)
    return True


def criar_e_iniciar_execucao_manual(*, usuario=None) -> Tuple[Optional[int], Optional[str]]:
    """Inicia sync manual em thread (API / interface)."""
    from crm_app.models import SyncStatusEsteiraExecucao

    if job_em_andamento():
        return None, 'Já existe uma sincronização em andamento.'

    execucao = SyncStatusEsteiraExecucao.objects.create(
        modo=SyncStatusEsteiraExecucao.MODO_MANUAL,
        status=SyncStatusEsteiraExecucao.STATUS_PENDENTE,
        iniciado_por=usuario,
    )

    def _runner():
        import django.db

        django.db.close_old_connections()
        try:
            executar_job(execucao.id)
        except Exception as e:
            logger.exception('[SYNC ESTEIRA] Erro fatal execução #%s: %s', execucao.id, e)
            SyncStatusEsteiraExecucao.objects.filter(pk=execucao.id).update(
                status=SyncStatusEsteiraExecucao.STATUS_ERRO,
                mensagem_erro=str(e)[:2000],
                finalizado_em=timezone.now(),
            )
            try:
                _enviar_relatorio_destinatarios(
                    f'❌ *Sync esteira PAP* falhou (#{execucao.id})\n\n{str(e)[:500]}'
                )
            except Exception:
                pass
        finally:
            django.db.close_old_connections()

    t = threading.Thread(target=_runner, name=f'sync-esteira-{execucao.id}', daemon=True)
    t.start()
    return execucao.id, None
