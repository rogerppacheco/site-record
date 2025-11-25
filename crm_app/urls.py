from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    OperadoraListCreateView, OperadoraDetailView,
    PlanoListCreateView, PlanoDetailView,
    FormaPagamentoListCreateView, FormaPagamentoDetailView,
    StatusCRMListCreateView, StatusCRMDetailView,
    MotivoPendenciaListCreateView, MotivoPendenciaDetailView,
    RegraComissaoListCreateView, RegraComissaoDetailView,
    VendaViewSet, ClienteViewSet, VendasStatusCountView,
    ImportacaoOsabView, ImportacaoOsabDetailView,
    ImportacaoChurnView, ImportacaoChurnDetailView,
    ImportacaoCicloPagamentoView,
    PerformanceVendasView,
    DashboardResumoView,
    ListaVendedoresView,
    ComissionamentoView,
    FecharPagamentoView,
    ReabrirPagamentoView,
    GerarRelatorioPDFView,
    EnviarExtratoEmailView,
    # Importar as views de campanha
    CampanhaListCreateView, CampanhaDetailView 
)

router = DefaultRouter()
router.register(r'vendas', VendaViewSet, basename='venda')
router.register(r'clientes', ClienteViewSet, basename='cliente')

urlpatterns = [
    # --- CADASTROS BÁSICOS ---
    path('operadoras/', OperadoraListCreateView.as_view(), name='operadora-list-create'),
    path('operadoras/<int:pk>/', OperadoraDetailView.as_view(), name='operadora-detail'),
    
    path('planos/', PlanoListCreateView.as_view(), name='plano-list-create'),
    path('planos/<int:pk>/', PlanoDetailView.as_view(), name='plano-detail'),
    
    path('formas-pagamento/', FormaPagamentoListCreateView.as_view(), name='formapagamento-list-create'),
    path('formas-pagamento/<int:pk>/', FormaPagamentoDetailView.as_view(), name='formapagamento-detail'),
    
    # --- NOVA ROTA DE CAMPANHAS ---
    path('campanhas/', CampanhaListCreateView.as_view(), name='campanha-list-create'),
    path('campanhas/<int:pk>/', CampanhaDetailView.as_view(), name='campanha-detail'),
    # ------------------------------

    path('status/', StatusCRMListCreateView.as_view(), name='statuscrm-list-create'),
    path('status/<int:pk>/', StatusCRMDetailView.as_view(), name='statuscrm-detail'),

    path('motivos-pendencia/', MotivoPendenciaListCreateView.as_view(), name='motivopendencia-list-create'),
    path('motivos-pendencia/<int:pk>/', MotivoPendenciaDetailView.as_view(), name='motivopendencia-detail'),
    
    path('regras-comissao/', RegraComissaoListCreateView.as_view(), name='regracomissao-list-create'),
    path('regras-comissao/<int:pk>/', RegraComissaoDetailView.as_view(), name='regracomissao-detail'),

    # --- DASHBOARD E ANALYTICS ---
    path('vendas/status-counts/', VendasStatusCountView.as_view(), name='vendas-status-counts'),
    path('dashboard-resumo/', DashboardResumoView.as_view(), name='dashboard-resumo'),
    path('lista-vendedores/', ListaVendedoresView.as_view(), name='lista-vendedores'),
    
    # --- ROTAS COMISSIONAMENTO ---
    path('comissionamento/', ComissionamentoView.as_view(), name='comissionamento'),
    path('comissionamento/fechar/', FecharPagamentoView.as_view(), name='fechar-pagamento'),
    path('comissionamento/reabrir/', ReabrirPagamentoView.as_view(), name='reabrir-pagamento'),
    path('comissionamento/pdf/', GerarRelatorioPDFView.as_view(), name='gerar-pdf-comissao'),
    path('comissionamento/email/', EnviarExtratoEmailView.as_view(), name='enviar-email-comissao'),

    # --- IMPORTAÇÕES ---
    path('import/osab/', ImportacaoOsabView.as_view(), name='importacao-osab'),
    path('import/osab/<int:pk>/', ImportacaoOsabDetailView.as_view(), name='importacao-osab-detail'),
    
    path('import/churn/', ImportacaoChurnView.as_view(), name='importacao-churn'),
    path('import/churn/<int:pk>/', ImportacaoChurnDetailView.as_view(), name='importacao-churn-detail'),
    
    path('import/ciclo-pagamento/', ImportacaoCicloPagamentoView.as_view(), name='importacao-ciclo-pagamento'),
    
    # --- RELATÓRIOS ---
    path('relatorios/performance-vendas/', PerformanceVendasView.as_view(), name='performance-vendas'),
    
    # --- ROTAS DO ROUTER (Vendas, Clientes, etc) ---
    path('', include(router.urls)),
]