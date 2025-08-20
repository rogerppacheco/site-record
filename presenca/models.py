# presenca/models.py
from django.db import models

class MotivoAusencia(models.Model):
    motivo = models.CharField(max_length=255, unique=True)
    gera_desconto = models.BooleanField(default=False)

    class Meta:
        db_table = 'motivos_ausencia'  # Aponta para a tabela antiga

    def __str__(self):
        return self.motivo

class Presenca(models.Model):
    # O campo 'colaborador' agora aponta para a coluna 'vendedor_id' no banco de dados
    colaborador = models.ForeignKey(
        'usuarios.Usuario', 
        on_delete=models.CASCADE, 
        related_name='presencas',
        db_column='vendedor_id'  # Mapeia para a coluna antiga
    )
    data = models.DateField()
    motivo = models.ForeignKey(MotivoAusencia, on_delete=models.SET_NULL, null=True, blank=True)
    observacao = models.TextField(blank=True, null=True)
    status = models.BooleanField(default=True)
    
    # O campo 'lancado_por' já corresponde ao nome da coluna antiga
    lancado_por = models.ForeignKey(
        'usuarios.Usuario', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='presencas_lancadas'
    )

    class Meta:
        unique_together = ('colaborador', 'data')
        db_table = 'registros_presenca'  # Aponta para a tabela antiga

    def __str__(self):
        estado = "Presente" if self.status else f"Ausente ({self.motivo})"
        return f"{self.colaborador.username} - {self.data} - {estado}"

class DiaNaoUtil(models.Model):
    data = models.DateField(unique=True)
    descricao = models.CharField(max_length=255)

    class Meta:
        db_table = 'dias_nao_uteis'  # Aponta para a tabela antiga

    def __str__(self):
        return f"{self.data} - {self.descricao}"