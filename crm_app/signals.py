from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import Venda, ContratoM10
from .whatsapp_service import WhatsAppService
import logging

logger = logging.getLogger(__name__)

@receiver(pre_save, sender=Venda)
def verificar_mudanca_status(sender, instance, **kwargs):
    """
    Antes de salvar, captura o status atual do banco de dados para comparar depois.
    """
    if instance.pk:
        try:
            old_instance = Venda.objects.get(pk=instance.pk)
            # Armazena temporariamente na instância em memória
            instance._old_status_tratamento = old_instance.status_tratamento
            instance._old_status_esteira = old_instance.status_esteira
        except Venda.DoesNotExist:
            pass

@receiver(post_save, sender=Venda)
def disparar_whatsapp_cadastrada(sender, instance, created, **kwargs):
    """
    Após salvar, verifica se o status mudou para 'CADASTRADA' e envia msg ao vendedor.
    """
    if created:
        return  # Ignora vendas novas recém-criadas (só dispara na mudança)

    # Recupera os valores antigos guardados no pre_save
    old_tratamento = getattr(instance, '_old_status_tratamento', None)
    new_tratamento = instance.status_tratamento

    old_esteira = getattr(instance, '_old_status_esteira', None)
    new_esteira = instance.status_esteira

    gatilho_acionado = False

    # 1. Verifica mudança no Status de Tratamento (Auditoria)
    # Se o novo status é CADASTRADA e o antigo NÃO ERA CADASTRADA
    if new_tratamento and new_tratamento.nome.upper() == "CADASTRADA":
        if not old_tratamento or old_tratamento.nome.upper() != "CADASTRADA":
            gatilho_acionado = True

    # 2. Verifica mudança no Status de Esteira (caso use este campo também)
    elif new_esteira and new_esteira.nome.upper() == "CADASTRADA":
        if not old_esteira or old_esteira.nome.upper() != "CADASTRADA":
            gatilho_acionado = True

    if gatilho_acionado:
        logger.info(f"Venda #{instance.id} mudou para CADASTRADA.")

        # Verifica se tem vendedor vinculado
        if not instance.vendedor:
            logger.warning(f"Venda #{instance.id} sem vendedor. WhatsApp cancelado.")
            return

        # Verifica se o vendedor tem o WhatsApp cadastrado no perfil
        telefone_vendedor = instance.vendedor.tel_whatsapp
        
        if not telefone_vendedor:
            logger.warning(f"Vendedor {instance.vendedor.username} não tem 'Tel WhatsApp' cadastrado.")
            return

        try:
            logger.info(f"Enviando WhatsApp para vendedor {instance.vendedor.username} ({telefone_vendedor})...")
            service = WhatsAppService()
            
            # Chama o método de envio passando explicitamente o telefone do vendedor
            service.enviar_mensagem_cadastrada(instance, telefone_destino=telefone_vendedor)
            
        except Exception as e:
            logger.error(f"Erro ao enviar WhatsApp na venda #{instance.id}: {e}")


# Signal para criar/atualizar faturas automaticamente ao salvar contrato M-10
@receiver(post_save, sender=ContratoM10)
def criar_faturas_automatico(sender, instance, created, **kwargs):
    """
    Após salvar um ContratoM10, cria ou atualiza as 10 faturas com datas de vencimento calculadas
    """
    try:
        if instance.data_instalacao:
            instance.criar_ou_atualizar_faturas()
            logger.info(f"✅ Faturas criadas/atualizadas para contrato {instance.numero_contrato}")
    except Exception as e:
        logger.error(f"❌ Erro ao criar/atualizar faturas para {instance.numero_contrato}: {e}")
