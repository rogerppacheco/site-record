# gestao_equipes/urls.py

from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from usuarios.views import LoginView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    # ROTA DE ADMIN
    path('admin/', admin.site.urls),

    # =======================================================================
    # ROTAS DA API (BACKEND)
    # =======================================================================
    
    # Rotas de Autenticação
    path('api/auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    path('api/', include('usuarios.urls')),
    path('api/presenca/', include('presenca.urls')),
    path('api/crm/', include('crm_app.urls')),
    path('api/osab/', include('osab.urls')),
    path('api/relatorios/', include('relatorios.urls')),

    # =======================================================================
    # ROTAS DO FRONTEND
    # =======================================================================
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    path('area-interna/', TemplateView.as_view(template_name='area-interna.html'), name='area-interna'),
    path('auditoria/', TemplateView.as_view(template_name='auditoria.html'), name='auditoria'),
    path('crm-vendas/', TemplateView.as_view(template_name='crm_vendas.html'), name='crm_vendas'),
    path('governanca/', TemplateView.as_view(template_name='governanca.html'), name='governanca'),
    path('presenca/', TemplateView.as_view(template_name='presenca.html'), name='presenca'),
    path('esteira/', TemplateView.as_view(template_name='esteira.html'), name='esteira'),
    path('comissionamento/', TemplateView.as_view(template_name='comissionamento.html'), name='comissionamento'),
    path('salvar-osab/', TemplateView.as_view(template_name='salvar_osab.html'), name='salvar-osab'),
    path('salvar-churn/', TemplateView.as_view(template_name='salvar_churn.html'), name='salvar-churn'),
    
    # --- ROTA ADICIONADA AQUI ---
    path('salvar-ciclo-pagamento/', TemplateView.as_view(template_name='salvar_ciclo_pagamento.html'), name='salvar-ciclo-pagamento'),
]