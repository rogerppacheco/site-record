# usuarios/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser

class Perfil(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nome

class Usuario(AbstractUser):
    # Campos de identificação
    cpf = models.CharField(max_length=14, blank=True, null=True, unique=True)
    
    # Relações
    perfil = models.ForeignKey(Perfil, on_delete=models.SET_NULL, null=True, blank=True, related_name='usuarios')
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='liderados')
    
    # Campos financeiros
    valor_almoco = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    valor_passagem = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    chave_pix = models.CharField(max_length=255, blank=True, null=True)
    nome_da_conta = models.CharField(max_length=255, blank=True, null=True)

    # Campos de comissionamento
    meta_comissao = models.IntegerField(default=0)
    desconto_boleto = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_inclusao_viabilidade = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_instalacao_antecipada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    adiantamento_cnpj = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    desconto_inss_fixo = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

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