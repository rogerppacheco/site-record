from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError

class Perfil(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Perfil"
        verbose_name_plural = "Perfis"

    def __str__(self):
        return self.nome

class Usuario(AbstractUser):
    # --- CANAIS ---
    # Adicionado DIGITAL, RECEPTIVO e PARCEIRO para o Dashboard
    CANAL_CHOICES = [
        ('PAP', 'PAP'),
        ('DIGITAL', 'Digital'),
        ('RECEPTIVO', 'Receptivo'),
        ('PARCEIRO', 'Parceiro'),
        ('TELAG', 'TelAg'), # Mantido para compatibilidade se já usado
        ('INTERNO', 'Interno'),   # Mantido para compatibilidade se já usado
    ]
    canal = models.CharField(
        max_length=20, 
        choices=CANAL_CHOICES, 
        blank=True, 
        null=True, 
        default='PAP',
        verbose_name="Canal de Venda"
    )
    
    # --- CLUSTER ---
    CLUSTER_CHOICES = [
        ('CLUSTER_1', 'CLUSTER 1'),
        ('CLUSTER_2', 'CLUSTER 2'),
        ('CLUSTER_3', 'CLUSTER 3'),
    ]
    cluster = models.CharField(
        max_length=20,
        choices=CLUSTER_CHOICES,
        blank=True,
        null=True,
        verbose_name="Cluster"
    )
    
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

    # --- WHATSAPP ---
    tel_whatsapp = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        verbose_name="WhatsApp do Consultor",
        help_text="Número com DDD (apenas números). O sistema verificará se possui WhatsApp."
    )

    # --- SEGURANÇA ---
    obriga_troca_senha = models.BooleanField(
        default=False, 
        verbose_name="Obrigar troca de senha?",
        help_text="Se marcado, o usuário deverá trocar a senha no próximo login."
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
        
        # Só valida se o número mudou ou se é novo, para não travar edições irrelevantes
        # Mas como não temos acesso fácil ao 'dirty fields' aqui sem biblioteca extra,
        # validamos sempre que tiver número. 
        # Em produção, o try/except garante que não quebre se a API cair.
        
        if self.tel_whatsapp:
            try:
                # Importação local para evitar circular import
                from crm_app.whatsapp_service import WhatsAppService
                service = WhatsAppService()
                
                # Verifica apenas se configurado para evitar travamento em dev/migração
                if service.token and service.instance_id:
                    # Pequena otimização: se for rodar migration ou shell, pode pular
                    # mas aqui deixamos para garantir integridade via Admin
                    existe = service.verificar_numero_existe(self.tel_whatsapp)
                    if not existe:
                        raise ValidationError({
                            'tel_whatsapp': f"O número {self.tel_whatsapp} não possui uma conta de WhatsApp válida segundo a API."
                        })
            except ImportError:
                pass # Se crm_app não estiver pronto
            except ValidationError:
                raise # Repassa o erro de validação para o form
            except Exception as e:
                # Logar erro silenciosamente em produção se API falhar, para não impedir salvamento
                pass

    def save(self, *args, **kwargs):
        # Chama a validação antes de salvar
        # self.full_clean() 
        # COMENTADO: full_clean() chama clean(), que chama a API do Zap. 
        # Isso pode deixar o save() muito lento ou quebrar imports em massa.
        # Melhor deixar a validação apenas no Formulário/Admin/Serializer.
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