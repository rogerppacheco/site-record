from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    VendaViewSet, 
    ClienteViewSet, 
    RegraComissaoViewSet,
    PlanoViewSet,
    FormaPagamentoViewSet,
    StatusCRMListCreateView,
    StatusCRMDetailView,
    MotivoPendenciaListCreateView,
    MotivoPendenciaDetailView,
    DashboardResumoView,
    OperadoraListCreateView,
    OperadoraDetailView,
    CampanhaListCreateView,
    CampanhaDetailView,
    VendasStatusCountView,
    ListaVendedoresView,
    ComissionamentoView,
    FecharPagamentoView,
    ReabrirPagamentoView,
    GerarRelatorioPDFView,
    EnviarExtratoEmailView,
    ImportacaoOsabView,
    ImportacaoChurnView,
    ImportacaoCicloPagamentoView,
    PerformanceVendasView,
    api_verificar_whatsapp,
    enviar_comissao_whatsapp
)

router = DefaultRouter()
router.register(r'vendas', VendaViewSet, basename='venda')
router.register(r'clientes', ClienteViewSet, basename='cliente')
router.register(r'regras-comissao', RegraComissaoViewSet, basename='regracomissao')
router.register(r'planos', PlanoViewSet, basename='plano')
router.register(r'formas-pagamento', FormaPagamentoViewSet, basename='formapagamento')

# Como Status e Motivos não são ViewSets completos no seu código original (são ListCreate/RetrieveUpdate), 
# eles geralmente são mapeados manualmente ou adaptados para ViewSets.
# Mas para manter compatibilidade com seu frontend, vamos manter as rotas manuais abaixo para eles,
# E usar o router apenas para os que são ViewSets de verdade.

urlpatterns = [
    path('', include(router.urls)),
    
    # Rotas Manuais para Views Genéricas (ListCreate / RetrieveUpdateDestroy)
    path('operadoras/', OperadoraListCreateView.as_view(), name='operadora-list'),
    path('operadoras/<int:pk>/', OperadoraDetailView.as_view(), name='operadora-detail'),
    
    path('campanhas/', CampanhaListCreateView.as_view(), name='campanha-list'),
    path('campanhas/<int:pk>/', CampanhaDetailView.as_view(), name='campanha-detail'),

    path('status/', StatusCRMListCreateView.as_view(), name='status-list'),
    path('status/<int:pk>/', StatusCRMDetailView.as_view(), name='status-detail'),
    
    path('motivos-pendencia/', MotivoPendenciaListCreateView.as_view(), name='motivo-list'),
    path('motivos-pendencia/<int:pk>/', MotivoPendenciaDetailView.as_view(), name='motivo-detail'),

    # Dashboards e Utilitários
    path('dashboard-resumo/', DashboardResumoView.as_view(), name='dashboard-resumo'),
    path('vendas-status-count/', VendasStatusCountView.as_view(), name='vendas-status-count'),
    path('lista-vendedores/', ListaVendedoresView.as_view(), name='lista-vendedores'),
    
    # Comissionamento
    path('comissionamento/', ComissionamentoView.as_view(), name='comissionamento'),
    path('fechar-pagamento/', FecharPagamentoView.as_view(), name='fechar-pagamento'),
    path('reabrir-pagamento/', ReabrirPagamentoView.as_view(), name='reabrir-pagamento'),
    path('gerar-relatorio-pdf/', GerarRelatorioPDFView.as_view(), name='gerar-relatorio-pdf'),
    path('enviar-extrato-email/', EnviarExtratoEmailView.as_view(), name='enviar-extrato-email'),
    
    # Importações
    path('importacao-osab/', ImportacaoOsabView.as_view(), name='importacao-osab'),
    path('importacao-churn/', ImportacaoChurnView.as_view(), name='importacao-churn'),
    path('importacao-ciclo-pagamento/', ImportacaoCicloPagamentoView.as_view(), name='importacao-ciclo'),
    
    # Performance
    path('performance-vendas/', PerformanceVendasView.as_view(), name='performance-vendas'),

    # WhatsApp
    path('verificar-whatsapp/<str:telefone>/', api_verificar_whatsapp, name='verificar-whatsapp'),
    path('enviar-comissao-whatsapp/', enviar_comissao_whatsapp, name='enviar-comissao-whatsapp'),
]