from django.apps import AppConfig
import os


class CrmAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'crm_app'

    def ready(self):
        # Importa os sinais quando o app estiver pronto para rodar
        import crm_app.signals
        import crm_app.signals_m10  # Novos signals para M-10 automático
        import crm_app.signals_m10_automacao  # Automação de M-10 com FPD
        
        # Inicia o scheduler de tarefas automáticas
        # Previne inicialização dupla em reload do runserver
        if os.environ.get('RUN_MAIN') == 'true' or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            try:
                from crm_app.scheduler import init_scheduler
                init_scheduler()
            except Exception as e:
                print(f"⚠️  Erro ao iniciar scheduler: {str(e)}")
