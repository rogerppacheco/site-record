# relatorios/urls.py
from django.urls import path
from .views import (
    RelatorioPrevisaoView, 
    RelatorioDescontosView, 
    RelatorioFinalView
)

urlpatterns = [
    # A URL para o relatório final foi mantida como 'semanal/'
    path('semanal/', RelatorioFinalView.as_view(), name='relatorio-final'),

    # Novas URLs para os novos relatórios
    path('previsao/', RelatorioPrevisaoView.as_view(), name='relatorio-previsao'),
    path('descontos/', RelatorioDescontosView.as_view(), name='relatorio-descontos'),
]