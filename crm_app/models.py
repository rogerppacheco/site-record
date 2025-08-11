# crm_app/models.py
from django.db import models

class Operadora(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    cnpj = models.CharField(max_length=20, null=True, blank=True)
    status = models.BooleanField(default=True)
    def __str__(self): return self.nome

class Plano(models.Model):
    nome = models.CharField(max_length=255)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    comissao_base = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    operadora = models.ForeignKey(Operadora, on_delete=models.CASCADE, related_name='planos')
    beneficios = models.TextField(null=True, blank=True)
    status = models.BooleanField(default=True)
    def __str__(self): return f"{self.nome} ({self.operadora.nome})"

class FormaPagamento(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    status = models.BooleanField(default=True)
    def __str__(self): return self.nome

class StatusCRM(models.Model):
    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50)
    estado = models.CharField(max_length=100, null=True, blank=True)
    cor = models.CharField(max_length=7, default='#FFFFFF')
    def __str__(self): return f"[{self.tipo}] {self.nome}"

class MotivoPendencia(models.Model):
    nome = models.CharField(max_length=255)
    tipo_pendencia = models.CharField(max_length=100)
    def __str__(self): return f"[{self.tipo_pendencia}] {self.nome}"