# gestao_equipes/urls.py

from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from usuarios.views import LoginView  # Importando sua view de login customizada
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    # ROTA DE ADMIN
    path('admin/', admin.site.urls),

    # =======================================================================
    # ROTAS DA API (BACKEND)
    # Colocamos as rotas mais específicas primeiro para evitar conflitos.
    # =======================================================================
    
    # Rotas de Autenticação
    path('api/auth/login/', LoginView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # Inclui as rotas do app 'usuarios' (ex: /api/usuarios/, /api/perfis/)
    path('api/', include('usuarios.urls')),
    
    # Inclui as rotas do app 'presenca' sob o prefixo /api/presenca/
    path('api/presenca/', include('presenca.urls')),
    
    # Inclui as rotas do app 'crm_app' sob o prefixo /api/crm/
    path('api/crm/', include('crm_app.urls')),

    # Inclui as rotas da nova app 'osab' para o upload
    path('api/osab/', include('osab.urls')),
    
    # Inclui as rotas do app 'relatorios'
    path('api/relatorios/', include('relatorios.urls')),

    # =======================================================================
    # ROTAS DO FRONTEND
    # Estas rotas servem os arquivos HTML para a interface do usuário.
    # =======================================================================
    path('', TemplateView.as_view(template_name='index.html'), name='home'),
    path('area-interna/', TemplateView.as_view(template_name='area-interna.html'), name='area-interna'),
    path('auditoria/', TemplateView.as_view(template_name='auditoria.html'), name='auditoria'),
    path('crm-vendas/', TemplateView.as_view(template_name='crm_vendas.html'), name='crm_vendas'),
    path('governanca/', TemplateView.as_view(template_name='governanca.html'), name='governanca'),
    path('presenca/', TemplateView.as_view(template_name='presenca.html'), name='presenca'),

    # --- CORREÇÃO APLICADA AQUI ---
    # Adicionando a rota para a nova página de upload de OSAB
    path('salvar-osab/', TemplateView.as_view(template_name='salvar_osab.html'), name='salvar-osab'),
]