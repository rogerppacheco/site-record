# presenca/models.py
from django.db import models
from django.conf import settings

class MotivoAusencia(models.Model):
    motivo = models.CharField(max_length=255, unique=True)
    gera_desconto = models.BooleanField(default=False)

    def __str__(self):
        return self.motivo

class Presenca(models.Model):
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

    # --- CAMPOS NOVOS ADICIONADOS AQUI ---
    criado_em = models.DateTimeField(auto_now_add=True, null=True) # Registra a data/hora de criação
    editado_em = models.DateTimeField(auto_now=True, null=True)     # Registra a data/hora da última edição
    editado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='presencas_editadas'
    )

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