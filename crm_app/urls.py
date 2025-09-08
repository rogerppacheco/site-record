from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    OperadoraListCreateView, OperadoraDetailView,
    PlanoListCreateView, PlanoDetailView,
    FormaPagamentoListCreateView, FormaPagamentoDetailView,
    StatusCRMListCreateView, StatusCRMDetailView,
    MotivoPendenciaListCreateView, MotivoPendenciaDetailView,
    RegraComissaoListCreateView, RegraComissaoDetailView,
    VendaViewSet,
    ClienteViewSet # <-- CORREÇÃO: Importado corretamente
)

router = DefaultRouter()
router.register(r'vendas', VendaViewSet, basename='venda')
# CORREÇÃO: Nova rota de clientes registrada
router.register(r'clientes', ClienteViewSet, basename='cliente')

# Suas rotas existentes
urlpatterns = [
    path('operadoras/', OperadoraListCreateView.as_view(), name='operadora-list-create'),
    path('operadoras/<int:pk>/', OperadoraDetailView.as_view(), name='operadora-detail'),
    
    path('planos/', PlanoListCreateView.as_view(), name='plano-list-create'),
    path('planos/<int:pk>/', PlanoDetailView.as_view(), name='plano-detail'),
    
    path('formas-pagamento/', FormaPagamentoListCreateView.as_view(), name='formapagamento-list-create'),
    path('formas-pagamento/<int:pk>/', FormaPagamentoDetailView.as_view(), name='formapagamento-detail'),
    
    path('status/', StatusCRMListCreateView.as_view(), name='statuscrm-list-create'),
    path('status/<int:pk>/', StatusCRMDetailView.as_view(), name='statuscrm-detail'),
    
    path('motivos-pendencia/', MotivoPendenciaListCreateView.as_view(), name='motivopendencia-list-create'),
    path('motivos-pendencia/<int:pk>/', MotivoPendenciaDetailView.as_view(), name='motivopendencia-detail'),

    path('regras-comissao/', RegraComissaoListCreateView.as_view(), name='regracomissao-list-create'),
    path('regras-comissao/<int:pk>/', RegraComissaoDetailView.as_view(), name='regracomissao-detail'),
    
    # Inclui as rotas geradas pelo router (vendas e clientes)
    path('', include(router.urls)),
]