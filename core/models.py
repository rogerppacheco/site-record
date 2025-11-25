from django.db import models

class DiaFiscal(models.Model):
    data = models.DateField(unique=True)
    
    # Peso para Vendas Brutas (Ex: 1.0 para dia cheio, 0.5 sábado, 0.0 feriado)
    peso_venda = models.DecimalField(
        max_digits=3, decimal_places=2, default=1.00, verbose_name="Peso Venda (DU_VB)"
    )
    
    # Peso para Instalação/Gross (Ex: 0.0 se a equipe técnica não trabalha)
    peso_instalacao = models.DecimalField(
        max_digits=3, decimal_places=2, default=1.00, verbose_name="Peso Instalação (DU_GROSS)"
    )
    
    feriado = models.BooleanField(default=False, verbose_name="É Feriado?")
    observacao = models.CharField(max_length=100, blank=True, null=True, verbose_name="Obs")

    class Meta:
        ordering = ['data']
        verbose_name = "Dia Fiscal"
        verbose_name_plural = "Calendário Fiscal"

    def __str__(self):
        return f"{self.data.strftime('%d/%m/%Y')} - VB: {self.peso_venda} | Gross: {self.peso_instalacao}"