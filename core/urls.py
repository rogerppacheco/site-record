from django.urls import path, include
from rest_framework.routers import DefaultRouter

# IMPORTANDO AS VIEWS (Note a mudança na última linha do import)
from .views import (
    IndexView, 
    AreaInternaView, 
    GovernancaView, 
    PresencaView, 
    CrmVendasView, 
    ConsultaCpfView, 
    ConsultaTratamentoView, 
    AuditoriaView, 
    SalvarOsabView, 
    SalvarChurnView,
    calendario_fiscal_view,
    RegraAutomacaoViewSet  # <--- CORRIGIDO: Era ConfiguracaoEnvioViewSet
)

# Configuração do Router
router = DefaultRouter()
# Registra a nova rota com o novo nome
router.register(r'regras-automacao', RegraAutomacaoViewSet)

urlpatterns = [
    # --- Rotas de Páginas (Frontend) ---
    path('', IndexView.as_view(), name='index'),
    path('area-interna/', AreaInternaView.as_view(), name='area-interna'),
    path('governanca/', GovernancaView.as_view(), name='governanca'),
    path('presenca/', PresencaView.as_view(), name='presenca'),
    path('crm-vendas/', CrmVendasView.as_view(), name='crm-vendas'),
    path('consulta-cpf/', ConsultaCpfView.as_view(), name='consulta-cpf'),
    path('consulta-tratamento/', ConsultaTratamentoView.as_view(), name='consulta-tratamento'),
    path('auditoria/', AuditoriaView.as_view(), name='auditoria'),
    path('salvar-osab/', SalvarOsabView.as_view(), name='salvar-osab'),
    path('salvar-churn/', SalvarChurnView.as_view(), name='salvar-churn'),

    # --- Rotas do Calendário ---
    path('calendario/', calendario_fiscal_view, name='calendario_fiscal_atual'),
    path('calendario/<int:ano>/<int:mes>/', calendario_fiscal_view, name='calendario_fiscal'),

    # --- Rotas da API ---
    path('api/', include(router.urls)),
    path('api/', include('crm_app.urls')),
]