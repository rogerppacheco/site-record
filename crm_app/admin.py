from django.contrib import admin
from .models import SafraM10, ContratoM10, FaturaM10


@admin.register(SafraM10)
class SafraM10Admin(admin.ModelAdmin):
    list_display = ('mes_referencia', 'total_instalados', 'total_ativos', 'total_elegivel_bonus', 'valor_bonus_total')
    list_filter = ('mes_referencia',)
    search_fields = ('mes_referencia',)


@admin.register(ContratoM10)
class ContratoM10Admin(admin.ModelAdmin):
    list_display = ('numero_contrato', 'cliente_nome', 'vendedor', 'data_instalacao', 'status_contrato', 'elegivel_bonus')
    list_filter = ('status_contrato', 'elegivel_bonus', 'safra', 'teve_downgrade')
    search_fields = ('numero_contrato', 'cliente_nome')
    raw_id_fields = ('vendedor', 'venda', 'safra')


@admin.register(FaturaM10)
class FaturaM10Admin(admin.ModelAdmin):
    list_display = ('contrato', 'numero_fatura', 'valor', 'data_vencimento', 'status')
    list_filter = ('status', 'numero_fatura')
    search_fields = ('contrato__numero_contrato', 'numero_fatura_operadora')
    raw_id_fields = ('contrato',)
