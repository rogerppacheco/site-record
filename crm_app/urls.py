from django.urls import path, include
from rest_framework.routers import DefaultRouter

# --- CORREÇÃO IMPORTANTE AQUI ---
# Importamos as views de login/senha do app 'usuarios', onde elas estão definidas.
from usuarios.views import LoginView, DefinirNovaSenhaView

from .views import (
    # ViewSets
    VendaViewSet, 
    ClienteViewSet, 
    ComissaoOperadoraViewSet,
    ComunicadoViewSet,

    # Views Genéricas (List/Detail)
    OperadoraListCreateView, OperadoraDetailView,
    PlanoListCreateView, PlanoDetailView,
    FormaPagamentoListCreateView, FormaPagamentoDetailView,
    StatusCRMListCreateView, StatusCRMDetailView,
    MotivoPendenciaListCreateView, MotivoPendenciaDetailView,
    RegraComissaoListCreateView, RegraComissaoDetailView,
    CampanhaListCreateView, CampanhaDetailView,
    
    # Dashboards e Importações
    DashboardResumoView,
    VendasStatusCountView,
    ListaVendedoresView,
    ComissionamentoView,
    FecharPagamentoView,
    ReabrirPagamentoView,
    GerarRelatorioPDFView,
    EnviarExtratoEmailView,
    ImportacaoOsabView, ImportacaoOsabDetailView,
    ImportacaoChurnView, ImportacaoChurnDetailView,
    ImportacaoCicloPagamentoView,
    PerformanceVendasView,
    
    # WhatsApp e Novos Recursos
    api_verificar_whatsapp,
    enviar_comissao_whatsapp,
    ImportarKMLView,        
    WebhookWhatsAppView,    
)

router = DefaultRouter()
router.register(r'vendas', VendaViewSet, basename='venda')
router.register(r'clientes', ClienteViewSet, basename='cliente')
router.register(r'comissoes-operadora', ComissaoOperadoraViewSet, basename='comissao-operadora')
router.register(r'comunicados', ComunicadoViewSet, basename='comunicados')

urlpatterns = [
    path('', include(router.urls)),
    
    # --- Auth ---
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/definir-senha/', DefinirNovaSenhaView.as_view(), name='definir-senha'),

    # --- Cadastros Gerais ---
    path('operadoras/', OperadoraListCreateView.as_view(), name='operadora-list'),
    path('operadoras/<int:pk>/', OperadoraDetailView.as_view(), name='operadora-detail'),
    
    path('planos/', PlanoListCreateView.as_view(), name='plano-list'),
    path('planos/<int:pk>/', PlanoDetailView.as_view(), name='plano-detail'),

    path('formas-pagamento/', FormaPagamentoListCreateView.as_view(), name='forma-pagamento-list'),
    path('formas-pagamento/<int:pk>/', FormaPagamentoDetailView.as_view(), name='forma-pagamento-detail'),

    path('campanhas/', CampanhaListCreateView.as_view(), name='campanha-list'),
    path('campanhas/<int:pk>/', CampanhaDetailView.as_view(), name='campanha-detail'),

    path('status/', StatusCRMListCreateView.as_view(), name='status-list'),
    path('status/<int:pk>/', StatusCRMDetailView.as_view(), name='status-detail'),
    
    path('motivos-pendencia/', MotivoPendenciaListCreateView.as_view(), name='motivo-list'),
    path('motivos-pendencia/<int:pk>/', MotivoPendenciaDetailView.as_view(), name='motivo-detail'),

    path('regras-comissao/', RegraComissaoListCreateView.as_view(), name='regra-list'),
    path('regras-comissao/<int:pk>/', RegraComissaoDetailView.as_view(), name='regra-detail'),

    # --- Dashboards e Utilitários ---
    path('dashboard-resumo/', DashboardResumoView.as_view(), name='dashboard-resumo'),
    path('vendas-status-count/', VendasStatusCountView.as_view(), name='vendas-status-count'),
    path('lista-vendedores/', ListaVendedoresView.as_view(), name='lista-vendedores'),
    
    # --- Comissionamento ---
    path('comissionamento/', ComissionamentoView.as_view(), name='comissionamento'),
    path('fechar-pagamento/', FecharPagamentoView.as_view(), name='fechar-pagamento'),
    path('reabrir-pagamento/', ReabrirPagamentoView.as_view(), name='reabrir-pagamento'),
    path('gerar-relatorio-pdf/', GerarRelatorioPDFView.as_view(), name='gerar-relatorio-pdf'),
    path('enviar-extrato-email/', EnviarExtratoEmailView.as_view(), name='enviar-extrato-email'),
    path('comissionamento/whatsapp/', enviar_comissao_whatsapp, name='enviar-whatsapp-comissao'),
    
    # --- Importações ---
    path('import/osab/', ImportacaoOsabView.as_view(), name='importacao-osab'),
    path('import/osab/<int:pk>/', ImportacaoOsabDetailView.as_view(), name='importacao-osab-detail'),
    path('import/churn/', ImportacaoChurnView.as_view(), name='importacao-churn'),
    path('import/churn/<int:pk>/', ImportacaoChurnDetailView.as_view(), name='importacao-churn-detail'),
    path('import/ciclo-pagamento/', ImportacaoCicloPagamentoView.as_view(), name='importacao-ciclo-pagamento'),
    
    # --- Novos Recursos ---
    path('importar-kml/', ImportarKMLView.as_view(), name='importar-kml'),
    path('webhook-whatsapp/', WebhookWhatsAppView.as_view(), name='webhook-whatsapp'),
    
    # --- Performance ---
    path('relatorios/performance-vendas/', PerformanceVendasView.as_view(), name='performance-vendas'),

    # --- WhatsApp Auxiliar ---
    path('verificar-zap/<str:telefone>/', api_verificar_whatsapp, name='verificar-zap'),
]