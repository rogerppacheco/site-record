# crm_app/scheduler.py
"""
Agendador de tarefas automáticas para busca de faturas e envio de performance
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)


def buscar_faturas_automatico():
    """
    Executa busca automática de faturas no site da Nio
    Processa todas as faturas disponíveis de todas as safras ativas
    """
    try:
        logger.info("🤖 Iniciando busca automática de faturas no Nio...")
        call_command('buscar_faturas_nio_automatico')
        logger.info("✅ Busca automática concluída com sucesso!")
    except Exception as e:
        logger.error(f"❌ Erro na busca automática: {str(e)}")


def processar_envio_performance_agendado():
    """
    Processa envios programados do Painel de Performance
    Verifica regras de agendamento e envia tabelas via WhatsApp
    """
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
    """
    Processa a fila de envio de boas-vindas.
    Envia mensagens cujo horário agendado já passou (distribuídas 8h-16h).
    """
    try:
        call_command('processar_fila_boas_vindas', '--limite', '5')
    except Exception as e:
        logger.error(f"❌ Erro ao processar fila boas-vindas: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


def start_scheduler():
    """
    Inicia o agendador de tarefas
    - Busca de faturas: 1x por dia às 00:05
    - Envio de Performance: A cada minuto (verifica horários programados)
    """
    logger.info("[OK] Iniciando agendador de tarefas...")
    
    scheduler = BackgroundScheduler()
    
    # 1. Agendamento para busca de faturas - meia-noite e cinco (00:05)
    scheduler.add_job(
        buscar_faturas_automatico,
        trigger=CronTrigger.from_crontab('5 0 * * *'),  # Todo dia às 00:05
        id='buscar_faturas_diario',
        name='Busca automática de faturas Nio (00:05)',
        replace_existing=True,
        max_instances=1,  # Previne execuções simultâneas
    )
    
    # 2. Agendamento para envio de Performance - a cada minuto
    # A função processar_envio_performance() verifica internamente se é hora de enviar
    scheduler.add_job(
        processar_envio_performance_agendado,
        trigger=IntervalTrigger(minutes=1),  # A cada minuto
        id='processar_envio_performance',
        name='Processar envios programados de Performance (a cada minuto)',
        replace_existing=True,
        max_instances=1,  # Previne execuções simultâneas
    )

    # 3. Fila de boas-vindas - a cada 5 min (envia 1 msg a cada 20-30 min via agendamento)
    scheduler.add_job(
        processar_fila_boas_vindas,
        trigger=IntervalTrigger(minutes=5),  # A cada 5 min
        id='processar_fila_boas_vindas',
        name='Processar fila de boas-vindas (a cada 5 min)',
        replace_existing=True,
        max_instances=1,
    )
    
    scheduler.start()
    logger.info("[OK] Agendador iniciado com sucesso!")
    
    # Log dos jobs agendados
    jobs = scheduler.get_jobs()
    logger.info(f"[INFO] {len(jobs)} tarefa(s) agendada(s):")
    for job in jobs:
        logger.info(f"  - {job.name}: {job.trigger}")
    
    return scheduler


# Scheduler global
scheduler = None


def init_scheduler():
    """Inicializa o scheduler se ainda não estiver rodando"""
    global scheduler
    if scheduler is None or not scheduler.running:
        logger.info("[SCHEDULER] Inicializando scheduler...")
        scheduler = start_scheduler()
        logger.info(f"[SCHEDULER] Scheduler inicializado. Status: running={scheduler.running}")
    else:
        logger.info("[SCHEDULER] Scheduler já está rodando, pulando inicialização")
    return scheduler
