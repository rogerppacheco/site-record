# presenca/models.py
from django.db import models
# from usuarios.models import Usuario  <-- REMOVEMOS ESTA LINHA PROBLEMÁTICA

class MotivoAusencia(models.Model):
    motivo = models.CharField(max_length=255, unique=True)
    gera_desconto = models.BooleanField(default=False)

    def __str__(self):
        return self.motivo

class Presenca(models.Model):
    # CORREÇÃO: Usamos uma string 'app_name.ModelName' em vez de importar a classe
    colaborador = models.ForeignKey('usuarios.Usuario', on_delete=models.CASCADE, related_name='presencas')
    data = models.DateField()
    motivo = models.ForeignKey(MotivoAusencia, on_delete=models.SET_NULL, null=True, blank=True)
    observacao = models.TextField(blank=True, null=True)
    status = models.BooleanField(default=True)
    
    # CORREÇÃO: Usamos a mesma técnica aqui
    lancado_por = models.ForeignKey('usuarios.Usuario', on_delete=models.SET_NULL, null=True, blank=True, related_name='presencas_lancadas')

    class Meta:
        unique_together = ('colaborador', 'data')

    def __str__(self):
        estado = "Presente" if self.status else f"Ausente ({self.motivo})"
        return f"{self.colaborador.username} - {self.data} - {estado}"

class DiaNaoUtil(models.Model):
    data = models.DateField(unique=True)
    descricao = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.data} - {self.descricao}"