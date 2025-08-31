from django.urls import path
from .views import (
    IndexView,
    AreaInternaView,
    GovernancaView,
    PresencaView,
    CrmVendasView,
    ConsultaCpfView,
    ConsultaTratamentoView,
)

# Este nome 'core' é importante para que o Django possa encontrar os arquivos estáticos
app_name = 'core'

urlpatterns = [
    # A rota vazia ('') corresponde à raiz do site (index.html)
    path('', IndexView.as_view(), name='index'),
    
    # --- CORREÇÃO AQUI: Removemos o .html e adicionamos a barra / ---
    path('area-interna/', AreaInternaView.as_view(), name='area-interna'),
    path('governanca/', GovernancaView.as_view(), name='governanca'),
    path('presenca/', PresencaView.as_view(), name='presenca'),
    path('crm-vendas/', CrmVendasView.as_view(), name='crm-vendas'),
    path('consulta-cpf/', ConsultaCpfView.as_view(), name='consulta-cpf'),
    path('consulta-tratamento/', ConsultaTratamentoView.as_view(), name='consulta-tratamento'),
]