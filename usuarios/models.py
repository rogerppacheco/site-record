from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError

class Perfil(models.Model):
    cod_perfil = models.CharField(max_length=50, unique=True, blank=False, null=False, verbose_name="Código do Perfil")
    nome = models.CharField(max_length=100, unique=True)
    descricao = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Perfil"
        verbose_name_plural = "Perfis"

    def __str__(self):
        return self.nome

class Usuario(AbstractUser):
    matricula_pap = models.CharField(max_length=50, blank=True, null=True, verbose_name="Matrícula PAP")
    senha_pap = models.CharField(max_length=128, blank=True, null=True, verbose_name="Senha PAP")
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
    is_active = models.BooleanField(default=True, db_index=True)
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
        help_text="Número com DDD (apenas números). O sistema verificará se possui WhatsApp via validação assíncrona."
    )

    # --- SEGURANÇA ---
    obriga_troca_senha = models.BooleanField(
        default=False, 
        verbose_name="Obrigar troca de senha?",
        help_text="Se marcado, o usuário deverá trocar a senha no próximo login."
    )

    # --- AUTOMAÇÃO PAP ---
    autorizar_venda_sem_auditoria = models.BooleanField(
        default=False,
        verbose_name="Autorizar venda sem auditoria?",
        help_text="Se marcado, o vendedor pode realizar vendas pelo WhatsApp usando automação do PAP."
    )
    autorizar_venda_automatica = models.BooleanField(
        default=False,
        verbose_name="Autorizar venda Automática",
        help_text="Se marcado, o vendedor poderá informar se a O.S. foi gerada automaticamente ao cadastrar vendas."
    )

    class Meta(AbstractUser.Meta):
        pass

    def __str__(self):
        return self.username

    def clean(self):
        """
        Validação padrão do Django.
        OBS: A validação de existência do WhatsApp na API externa (Z-API) foi REMOVIDA daqui 
        para não bloquear o salvamento. Ela deve ser feita via endpoint dedicado no Frontend.
        """
        super().clean()

    def save(self, *args, **kwargs):
        # Salva diretamente sem chamadas externas bloqueantes
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