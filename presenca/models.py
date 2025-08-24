# presenca/models.py
from django.db import models

class MotivoAusencia(models.Model):
    motivo = models.CharField(max_length=255, unique=True)
    gera_desconto = models.BooleanField(default=False)

    # A classe Meta com 'db_table' foi removida daqui

    def __str__(self):
        return self.motivo

class Presenca(models.Model):
    # A opção 'db_column' foi removida do campo abaixo
    colaborador = models.ForeignKey(
        'usuarios.Usuario', 
        on_delete=models.CASCADE, 
        related_name='presencas'
    )
    data = models.DateField()
    motivo = models.ForeignKey(MotivoAusencia, on_delete=models.SET_NULL, null=True, blank=True)
    observacao = models.TextField(blank=True, null=True)
    status = models.BooleanField(default=True)
    
    lancado_por = models.ForeignKey(
        'usuarios.Usuario', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='presencas_lancadas'
    )

    class Meta:
        unique_together = ('colaborador', 'data')
        # A linha 'db_table' foi removida daqui

    def __str__(self):
        estado = "Presente" if self.status else f"Ausente ({self.motivo})"
        return f"{self.colaborador.username} - {self.data} - {estado}"

class DiaNaoUtil(models.Model):
    data = models.DateField(unique=True)
    descricao = models.CharField(max_length=255)

    # A classe Meta com 'db_table' foi removida daqui

    def __str__(self):
        return f"{self.data} - {self.descricao}"