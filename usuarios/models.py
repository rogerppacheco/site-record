from django.db import models
from django.contrib.auth.models import AbstractUser

class Perfil(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    # Campo mantido da versão anterior para garantir a compatibilidade com a migração
    descricao = models.TextField(blank=True, null=True)

    class Meta:
        # O nome da tabela padrão do Django (usuarios_perfil) já corresponde ao desejado,
        # então a linha 'db_table' não é necessária.
        pass

    def __str__(self):
        return self.nome

class Usuario(AbstractUser):
    # --- NOVOS CAMPOS ADICIONADOS ---
    CANAL_CHOICES = [
        ('PAP', 'PAP'),
        ('TELAG', 'TELAG'),
        ('TIPO', 'TIPO'), # Adicione outros canais se necessário
    ]
    canal = models.CharField(max_length=10, choices=CANAL_CHOICES, blank=True, null=True, default='PAP')
    # --- FIM DOS NOVOS CAMPOS ---

    # Campos de identificação
    cpf = models.CharField(max_length=14, blank=True, null=True, unique=True)
    
    # Relações
    perfil = models.ForeignKey(Perfil, on_delete=models.SET_NULL, null=True, blank=True, related_name='usuarios')
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='liderados')
    
    # --- NOVOS CAMPOS FINANCEIROS (DA SUA VERSÃO) ---
    valor_almoco = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    valor_passagem = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    chave_pix = models.CharField(max_length=255, blank=True, null=True)
    nome_da_conta = models.CharField(max_length=255, blank=True, null=True)

    # --- NOVOS CAMPOS DE COMISSIONAMENTO (DA SUA VERSÃO) ---
    meta_comissao = models.IntegerField(default=0)
    desconto_boleto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_inclusao_viabilidade = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_instalacao_antecipada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    adiantamento_cnpj = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_inss_fixo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta(AbstractUser.Meta):
        # O nome da tabela padrão do Django (usuarios_usuario) já corresponde ao desejado.
        pass

    def __str__(self):
        return self.username

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