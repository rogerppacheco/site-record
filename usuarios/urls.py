# site-record/usuarios/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UsuarioViewSet,
    PerfilViewSet,
    RecursosListView 
)

# O router é a forma padrão de registrar ViewSets.
# Ele cria automaticamente as URLs para:
# - /usuarios/ (listar e criar)
# - /usuarios/{id}/ (detalhe, atualizar, deletar)
# - e as ações customizadas como 'reativar'.
router = DefaultRouter()
router.register(r'usuarios', UsuarioViewSet, basename='usuario')
router.register(r'perfis', PerfilViewSet, basename='perfil')

# Aqui definimos as URLs finais da nossa aplicação.
urlpatterns = [
    # Inclui todas as URLs geradas pelo router.
    path('', include(router.urls)),
    
    # Adiciona a nossa nova URL para a lista de recursos de permissão.
    path('recursos/', RecursosListView.as_view(), name='lista-recursos'),
]