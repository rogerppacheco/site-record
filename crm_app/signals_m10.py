# crm_app/signals_m10.py
"""
Signals para automatizar a sincronização do Bônus M-10 com Venda e FPD
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Venda, ContratoM10

@receiver(post_save, sender=Venda)
def criar_ou_atualizar_contrato_m10(sender, instance, created, **kwargs):
    """
    Signal: Quando uma Venda é criada/atualizada, automaticamente:
    1. Cria ou atualiza ContratoM10
    2. Sincroniza dados do FPD
    """
    # Só processar vendas ativas com data de instalação
    if not instance.ativo or not instance.data_instalacao or not instance.ordem_servico:
        return
    
    try:
        # Buscar ou criar ContratoM10
        contrato_m10, was_created = ContratoM10.objects.get_or_create(
            ordem_servico=instance.ordem_servico,
            defaults={
                'venda': instance,
            }
        )
        
        # Sempre atualizar a referência da venda (em caso de atualização)
        if contrato_m10.venda != instance:
            contrato_m10.venda = instance
            contrato_m10.save(update_fields=['venda'])
        
        # Tentar sincronizar com FPD
        contrato_m10.sincronizar_fpd()
        
        if was_created:
            print(f"✅ ContratoM10 criado para Venda {instance.ordem_servico}")
        
    except Exception as e:
        print(f"❌ Erro ao processar Venda {instance.id}: {str(e)}")


# Importar no apps.py para registrar o signal
# from .signals_m10 import *
