from django.apps import AppConfig

class CrmAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'crm_app'

    def ready(self):
        # Importa os sinais quando o app estiver pronto para rodar
        import crm_app.signals