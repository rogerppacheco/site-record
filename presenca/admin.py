# presenca/admin.py

from django.contrib import admin
from .models import Presenca, MotivoAusencia, DiaNaoUtil

@admin.register(MotivoAusencia)
class MotivoAusenciaAdmin(admin.ModelAdmin):
    list_display = ('motivo', 'gera_desconto')
    search_fields = ('motivo',)

@admin.register(DiaNaoUtil)
class DiaNaoUtilAdmin(admin.ModelAdmin):
    list_display = ('data', 'descricao')
    search_fields = ('descricao',)
    list_filter = ('data',)

@admin.register(Presenca)
class PresencaAdmin(admin.ModelAdmin):
    # CORREÇÃO: Usando os nomes de campo corretos do modelo 'Presenca'
    # 'usuario' foi renomeado para 'colaborador'
    # 'presente' foi renomeado para 'status'
    # 'motivo_ausencia' foi renomeado para 'motivo'
    list_display = ('colaborador', 'data', 'status', 'motivo', 'lancado_por')
    list_filter = ('data', 'status', 'colaborador__username') # Filtra pelo username dentro do campo 'colaborador'
    search_fields = ('colaborador__username', 'data', 'observacao')
    
    # CORREÇÃO: O campo no modelo é 'colaborador', não 'usuario'
    autocomplete_fields = ['colaborador', 'motivo', 'lancado_por'] 

    # Define a ordem dos campos no formulário de edição
    fieldsets = (
        (None, {
            'fields': ('colaborador', 'data', 'status')
        }),
        ('Detalhes da Ausência', {
            'classes': ('collapse',),
            'fields': ('motivo', 'observacao'),
        }),
        ('Metadados', {
            'fields': ('lancado_por',),
        }),
    )