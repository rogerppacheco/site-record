# crm_app/scheduler.py
"""
Agendador de tarefas automáticas (faturas Nio, performance, boas-vindas, Sonax).

Produção: processo dedicado — python manage.py run_scheduler
Não iniciar junto com Gunicorn (evita competir com HTTP/webhooks).
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.core.management import call_command
import logging
import signal

logger = logging.getLogger(__name__)

_scheduler_instance = None


def buscar_faturas_automatico():
    try:
        logger.info("🤖 Iniciando busca automática de faturas no Nio...")
        call_command('buscar_faturas_nio_automatico')
        logger.info("✅ Busca automática concluída com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro na busca automática: {str(e)}")


def processar_envio_performance_agendado():
    try:
        logger.info("📊 Verificando envios programados de Performance...")
        from crm_app.tasks import processar_envio_performance
        processar_envio_performance()
        logger.info("✅ Verificação de envios de Performance concluída!")
    except Exception as e:
        logger.error(f"❌ Erro ao processar envios de Performance: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


def processar_fila_boas_vindas():
    try:
        call_command('processar_fila_boas_vindas', '--limite', '5')
    except Exception as e:
        logger.error(f"❌ Erro ao processar fila boas-vindas: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


def _processar_fallback_sonax_auditoria():
    try:
        from crm_app.tasks import processar_fallback_auditoria_ligacoes_sonax
        processar_fallback_auditoria_ligacoes_sonax(
            limite=int(getattr(settings, "SONAX_AUDITORIA_FALLBACK_LIMIT", 15)),
            grace_seconds=int(getattr(settings, "SONAX_AUDITORIA_FALLBACK_GRACE_SECONDS", 90)),
        )
    except Exception as e:
        logger.error(f"❌ Erro no fallback Sonax auditoria: {str(e)}")


def sync_status_esteira_pap_automatico():
    try:
        logger.info("🌙 Verificando sync automático da esteira (PAP)...")
        call_command('sync_status_esteira_pap', '--modo', 'automatico')
    except Exception as e:
        logger.error(f"❌ Erro no sync automático da esteira: {str(e)}")


def preaquecer_cache_folha_comissionamento():
    """Pré-calcula folha do mês corrente para popular cache antes do horário comercial."""
    try:
        from django.utils import timezone
        from crm_app.services.folha_comissionamento_cache import calcular_folha_mes_com_cache

        hoje = timezone.now()
        logger.info("📋 Pré-aquecendo cache da folha %02d/%d...", hoje.month, hoje.year)
        calcular_folha_mes_com_cache(hoje.year, hoje.month)
        logger.info("✅ Cache da folha pré-aquecido.")
    except Exception as e:
        logger.error(f"❌ Erro ao pré-aquecer cache da folha: {e}")


def lembrete_presenca_supervisor_10h():
    try:
        from presenca.services.lembrete_presenca_service import enviar_lembrete_supervisores, SLOT_10H
        enviar_lembrete_supervisores(SLOT_10H)
    except Exception as e:
        logger.error("❌ Erro no lembrete presença 10h: %s", e)


def lembrete_presenca_supervisor_11h():
    try:
        from presenca.services.lembrete_presenca_service import enviar_lembrete_supervisores, SLOT_11H
        enviar_lembrete_supervisores(SLOT_11H)
    except Exception as e:
        logger.error("❌ Erro no lembrete presença 11h: %s", e)


def aplicar_faltas_presenca_12h():
    try:
        from presenca.services.lembrete_presenca_service import aplicar_faltas_automaticas_12h
        aplicar_faltas_automaticas_12h()
    except Exception as e:
        logger.error("❌ Erro na falta automática presença 12h: %s", e)


def processar_relatorio_esteira_gc_agendado():
    try:
        from crm_app.services.relatorio_esteira_gc_service import processar_envio_relatorio_esteira_gc
        processar_envio_relatorio_esteira_gc()
    except Exception as e:
        logger.error("❌ Erro no relatório esteira GC: %s", e)
        import traceback
        logger.error("Traceback: %s", traceback.format_exc())


def _registrar_jobs(scheduler):
    scheduler.add_job(
        buscar_faturas_automatico,
        trigger=CronTrigger.from_crontab('5 0 * * *'),
        id='buscar_faturas_diario',
        name='Busca automática de faturas Nio (00:05)',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        processar_envio_performance_agendado,
        trigger=IntervalTrigger(minutes=1),
        id='processar_envio_performance',
        name='Processar envios programados de Performance (a cada minuto)',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        processar_relatorio_esteira_gc_agendado,
        trigger=IntervalTrigger(minutes=1),
        id='processar_relatorio_esteira_gc',
        name='Relatório esteira GC ao WhatsApp (a cada minuto)',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        processar_fila_boas_vindas,
        trigger=IntervalTrigger(minutes=5),
        id='processar_fila_boas_vindas',
        name='Processar fila de boas-vindas (a cada 5 min)',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _processar_fallback_sonax_auditoria,
        trigger=IntervalTrigger(
            minutes=int(getattr(settings, "SONAX_AUDITORIA_FALLBACK_INTERVAL_MINUTES", 2))
        ),
        id="processar_fallback_sonax_auditoria",
        name="Fallback Sonax auditoria (status + gravação)",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        sync_status_esteira_pap_automatico,
        trigger=CronTrigger.from_crontab('0 22 * * *'),
        id='sync_status_esteira_pap_noturno',
        name='Sync esteira PAP — início 22:00 (America/Sao_Paulo)',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        preaquecer_cache_folha_comissionamento,
        trigger=CronTrigger.from_crontab('0 6 * * *'),
        id='preaquecer_cache_folha',
        name='Pré-aquecer cache folha comissionamento (06:00)',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        preaquecer_cache_folha_comissionamento,
        trigger=CronTrigger.from_crontab('0 12 * * *'),
        id='preaquecer_cache_folha_meiodia',
        name='Pré-aquecer cache folha comissionamento (12:00)',
        replace_existing=True,
        max_instances=1,
    )
    tz_sp = getattr(settings, "TIME_ZONE", "America/Sao_Paulo")
    scheduler.add_job(
        lembrete_presenca_supervisor_10h,
        trigger=CronTrigger.from_crontab('0 10 * * 1-5', timezone=tz_sp),
        id='lembrete_presenca_supervisor_10h',
        name='Lembrete presença supervisor (10:00 seg-sex)',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        lembrete_presenca_supervisor_11h,
        trigger=CronTrigger.from_crontab('0 11 * * 1-5', timezone=tz_sp),
        id='lembrete_presenca_supervisor_11h',
        name='Lembrete presença supervisor (11:00 seg-sex)',
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        aplicar_faltas_presenca_12h,
        trigger=CronTrigger.from_crontab('0 12 * * 1-5', timezone=tz_sp),
        id='aplicar_faltas_presenca_12h',
        name='Falta automática presença (12:00 seg-sex)',
        replace_existing=True,
        max_instances=1,
    )


def _log_jobs(scheduler):
    jobs = scheduler.get_jobs()
    logger.info("[OK] %s tarefa(s) agendada(s):", len(jobs))
    for job in jobs:
        logger.info("  - %s: %s", job.name, job.trigger)


def create_scheduler(*, blocking=False):
    """Cria scheduler com jobs registrados (não inicia)."""
    cls = BlockingScheduler if blocking else BackgroundScheduler
    scheduler = cls()
    _registrar_jobs(scheduler)
    return scheduler


def start_scheduler(blocking=False):
    """Inicia o agendador. Com blocking=True, bloqueia até encerrar o processo."""
    global _scheduler_instance
    scheduler = create_scheduler(blocking=blocking)
    scheduler.start()
    _scheduler_instance = scheduler
    logger.info("[OK] Agendador iniciado (blocking=%s)", blocking)
    _log_jobs(scheduler)
    return scheduler


def run_blocking_scheduler():
    """Processo dedicado (manage.py run_scheduler / serviço Railway scheduler)."""
    scheduler = create_scheduler(blocking=True)

    def _shutdown(signum=None, frame=None):
        logger.info("[SCHEDULER] Sinal %s — encerrando...", signum)
        if scheduler.running:
            scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("[SCHEDULER] Processo dedicado iniciado. Ctrl+C ou SIGTERM para parar.")
    _log_jobs(scheduler)
    scheduler.start()


# Compatibilidade com código legado que importava init_scheduler / scheduler global
scheduler = None


def init_scheduler():
    """Deprecated: use run_blocking_scheduler / manage.py run_scheduler."""
    global scheduler
    logger.warning(
        "[SCHEDULER] init_scheduler() está obsoleto; use: python manage.py run_scheduler"
    )
    scheduler = start_scheduler(blocking=False)
    return scheduler
