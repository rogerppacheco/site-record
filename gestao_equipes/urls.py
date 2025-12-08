from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from usuarios.views import LoginView
# Importe a nova view do calendário
from core.views import calendario_fiscal_view

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # API AUTH
    path('api/auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', include('djoser.urls.jwt')),
    path('login/', LoginView.as_view(), name='login_direct'),

    # APIS DO SISTEMA
    path('api/', include('djoser.urls')),
    
    # --- CORREÇÃO DO ERRO 404 (USUARIOS) ---
    # Inclui as rotas do app usuarios (onde estão UsuarioViewSet e GrupoViewSet)
    path('api/', include('usuarios.urls')), 
    # ---------------------------------------

    path('api/presenca/', include('presenca.urls')),
    path('api/crm/', include('crm_app.urls')),
    path('api/osab/', include('osab.urls')),
    path('api/relatorios/', include('relatorios.urls')),
    
    # Se o app core tiver API (DiaFiscal), inclua também:
    path('api/core/', include('core.urls')), 

    # PÁGINAS FRONTEND
    path('', TemplateView.as_view(template_name='public/index.html'), name='home'),
    path('area-interna/', TemplateView.as_view(template_name='public/area-interna.html'), name='area-interna'),
    path('record-informa/', TemplateView.as_view(template_name='public/record_informa.html'), name='record-informa'),
    path('auditoria/', TemplateView.as_view(template_name='public/auditoria.html'), name='auditoria'),
    path('crm-vendas/', TemplateView.as_view(template_name='public/crm_vendas.html'), name='crm_vendas'),
    path('governanca/', TemplateView.as_view(template_name='public/governanca.html'), name='governanca'),
    path('presenca/', TemplateView.as_view(template_name='public/presenca.html'), name='presenca'),
    path('esteira/', TemplateView.as_view(template_name='public/esteira.html'), name='esteira'),
    path('comissionamento/', TemplateView.as_view(template_name='public/comissionamento.html'), name='comissionamento'),

    # Telas de Importação
    path('salvar-osab/', TemplateView.as_view(template_name='public/salvar_osab.html'), name='salvar-osab'),
    path('salvar-churn/', TemplateView.as_view(template_name='public/salvar_churn.html'), name='salvar-churn'),
    path('salvar-ciclo-pagamento/', TemplateView.as_view(template_name='public/salvar_ciclo_pagamento.html'), name='salvar-ciclo-pagamento'),
    
    # --- CORREÇÃO DO ERRO 500 (CALENDÁRIO) ---
    # Aponta para a view Python, não TemplateView direta
    path('calendario/', calendario_fiscal_view, name='calendario_fiscal_atual'),
    path('calendario/<int:ano>/<int:mes>/', calendario_fiscal_view, name='calendario_fiscal'),
]