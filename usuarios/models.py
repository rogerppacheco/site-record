from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError

class Perfil(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.TextField(blank=True, null=True)

    class Meta:
        pass

    def __str__(self):
        return self.nome

class Usuario(AbstractUser):
    # --- CANAIS ---
    CANAL_CHOICES = [
        ('PAP', 'PAP'),
        ('TELAG', 'TELAG'),
        ('TIPO', 'TIPO'),
    ]
    canal = models.CharField(max_length=10, choices=CANAL_CHOICES, blank=True, null=True, default='PAP')
    
    # --- IDENTIFICAÇÃO ---
    cpf = models.CharField(max_length=14, blank=True, null=True, unique=True)
    
    # --- RELAÇÕES ---
    perfil = models.ForeignKey(Perfil, on_delete=models.SET_NULL, null=True, blank=True, related_name='usuarios')
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='liderados')
    
    # --- FINANCEIRO ---
    valor_almoco = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    valor_passagem = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    chave_pix = models.CharField(max_length=255, blank=True, null=True)
    nome_da_conta = models.CharField(max_length=255, blank=True, null=True)

    # --- COMISSIONAMENTO ---
    meta_comissao = models.IntegerField(default=0)
    desconto_boleto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_inclusao_viabilidade = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_instalacao_antecipada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    adiantamento_cnpj = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_inss_fixo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    # --- CONTROLE DE PRESENÇA ---
    participa_controle_presenca = models.BooleanField(
        default=True,
        verbose_name="Participa do Controle de Presença?",
        help_text="Marque se este usuário deve aparecer na tela de controle de presença."
    )

    # --- NOVO CAMPO: WHATSAPP ---
    tel_whatsapp = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        verbose_name="WhatsApp do Consultor",
        help_text="Número com DDD (apenas números). O sistema verificará se possui WhatsApp."
    )

    class Meta(AbstractUser.Meta):
        pass

    def __str__(self):
        return self.username

    def clean(self):
        """
        Validação personalizada: Verifica na Z-API se o número tem WhatsApp.
        """
        super().clean()
        
        if self.tel_whatsapp:
            # Importação local para evitar ciclo de imports (crm_app <-> usuarios)
            try:
                from crm_app.whatsapp_service import WhatsAppService
                
                service = WhatsAppService()
                existe = service.verificar_numero_existe(self.tel_whatsapp)
                
                if not existe:
                    raise ValidationError({
                        'tel_whatsapp': f"O número {self.tel_whatsapp} não possui uma conta de WhatsApp válida segundo a API."
                    })
            except ImportError:
                pass # Evita erro se o app crm_app não estiver carregado ainda
            except Exception as e:
                # Se a API falhar (ex: sem internet), não impede o cadastro, mas loga se possível
                pass

    def save(self, *args, **kwargs):
        self.full_clean()  # Força a execução do clean() antes de salvar
        super().save(*args, **kwargs)

class PermissaoPerfil(models.Model):
    perfil = models.ForeignKey(Perfil, on_delete=models.CASCADE, related_name='permissoes')
    recurso = models.CharField(max_length=100, help_text="O nome do recurso (ex: 'operadoras', 'planos')")
    
    pode_ver = models.BooleanField(default=False)
    pode_criar = models.BooleanField(default=False)
    pode_editar = models.BooleanField(default=False)
    pode_excluir = models.BooleanField(default=False)

    class Meta:
        unique_together = ('perfil', 'recurso')
        verbose_name = "Permissão de Perfil"
        verbose_name_plural = "Permissões de Perfis"

    def __str__(self):
        return f"Permissões do {self.perfil.nome} para {self.recurso}"