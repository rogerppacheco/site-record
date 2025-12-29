from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter

# --- IMPORTS DAS VIEWS NECESSÁRIAS ---
from usuarios.views import LoginView
from core.views import calendario_fiscal_view, RegraAutomacaoViewSet
from crm_app.views import (
    page_painel_performance, 
    page_cdoi_novo, 
    listar_grupos_whatsapp_api  # Importando a função de grupos
)

# --- CONFIGURAÇÃO DO ROUTER PARA REGRAS DE AUTOMAÇÃO ---
# Isso garante que a rota /api/regras-automacao/ exista na raiz da API
router = DefaultRouter()
router.register(r'regras-automacao', RegraAutomacaoViewSet, basename='regras-automacao')

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # API AUTH
    path('api/auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', include('djoser.urls.jwt')),
    path('login/', LoginView.as_view(), name='login_direct'),

    # --- ROTAS DE CORREÇÃO (PARA O FRONTEND FUNCIONAR) ---
    # 1. Registra as rotas do router (inclui /api/regras-automacao/)
    path('api/', include(router.urls)),
    
    # 2. Rota específica para grupos do WhatsApp que estava dando 404
    path('api/whatsapp/groups/', listar_grupos_whatsapp_api, name='whatsapp-groups-direct'),

    # APIS DO SISTEMA (Back-end)
    path('api/', include('djoser.urls')),
    path('api/', include('usuarios.urls')), 
    path('api/presenca/', include('presenca.urls')),
    path('api/crm/', include('crm_app.urls')),
    path('api/osab/', include('osab.urls')),
    path('api/relatorios/', include('relatorios.urls')),
    path('api/core/', include('core.urls')), 

    # PÁGINAS FRONTEND (HTML para o usuário)
    path('', TemplateView.as_view(template_name='public/index.html'), name='home'),
    path('area-interna/', TemplateView.as_view(template_name='public/area-interna.html'), name='area-interna'),
    path('record-informa/', TemplateView.as_view(template_name='public/record_informa.html'), name='record-informa'),
    path('auditoria/', TemplateView.as_view(template_name='public/auditoria.html'), name='auditoria'),
    path('crm-vendas/', TemplateView.as_view(template_name='public/crm_vendas.html'), name='crm_vendas'),
    path('governanca/', TemplateView.as_view(template_name='public/governanca.html'), name='governanca'),
    path('presenca/', TemplateView.as_view(template_name='public/presenca.html'), name='presenca'),
    path('esteira/', TemplateView.as_view(template_name='public/esteira.html'), name='esteira'),
    path('comissionamento/', TemplateView.as_view(template_name='public/comissionamento.html'), name='comissionamento'),

    # Central de Importações
    path('importacoes/', TemplateView.as_view(template_name='public/importacoes.html'), name='central-importacoes'),

    # Telas de Importação Específicas
    path('salvar-osab/', TemplateView.as_view(template_name='public/salvar_osab.html'), name='salvar-osab'),
    path('salvar-churn/', TemplateView.as_view(template_name='public/salvar_churn.html'), name='salvar-churn'),
    path('salvar-ciclo-pagamento/', TemplateView.as_view(template_name='public/salvar_ciclo_pagamento.html'), name='salvar-ciclo-pagamento'),
    path('importar-mapa/', TemplateView.as_view(template_name='public/importar_mapa.html'), name='importar-mapa'),
    path('importar-dfv/', TemplateView.as_view(template_name='public/importar_dfv.html'), name='page-importar-dfv'),
    path('importar-legado/', TemplateView.as_view(template_name='public/importar_legado.html'), name='importar-legado'),

    # CALENDÁRIO & PAINEL DE PERFORMANCE
    path('calendario/', calendario_fiscal_view, name='calendario_fiscal_atual'),
    path('calendario/<int:ano>/<int:mes>/', calendario_fiscal_view, name='calendario_fiscal'),
    path('painel-performance/', page_painel_performance, name='painel_performance'),

    # --- NOVO: RECORD VERTICAL (CDOI) ---
    path('cdoi-novo/', page_cdoi_novo, name='page_cdoi_novo'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)