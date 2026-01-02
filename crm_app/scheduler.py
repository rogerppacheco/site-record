# crm_app/scheduler.py
"""
Agendador de tarefas automáticas para busca de faturas
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
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


def start_scheduler():
    """
    Inicia o agendador de tarefas
    Executa 1x por dia às 00:05 (meia-noite e cinco)
    """
    logger.info("⚙️  Agendador configurado para executar diariamente às 00:05")
    
    scheduler = BackgroundScheduler()
    
    # Agendamento para meia-noite e cinco (00:05)
    scheduler.add_job(
        buscar_faturas_automatico,
        trigger=CronTrigger.from_crontab('5 0 * * *'),  # Todo dia às 00:05
        id='buscar_faturas_diario',
        name='Busca automática de faturas Nio (00:05)',
        replace_existing=True,
        max_instances=1,  # Previne execuções simultâneas
    )
    
    scheduler.start()
    logger.info("✅ Agendador iniciado com sucesso!")
    
    # Log dos jobs agendados
    jobs = scheduler.get_jobs()
    logger.info(f"📋 {len(jobs)} tarefa(s) agendada(s):")
    for job in jobs:
        logger.info(f"  - {job.name}: {job.trigger}")
    
    return scheduler


# Scheduler global
scheduler = None


def init_scheduler():
    """Inicializa o scheduler se ainda não estiver rodando"""
    global scheduler
    if scheduler is None:
        scheduler = start_scheduler()
    return scheduler
