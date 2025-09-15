# site-record/usuarios/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UsuarioViewSet,
    PerfilViewSet,
    RecursoViewSet
)

# O router é a forma padrão de registrar ViewSets.
# Ele cria automaticamente as URLs para as ações padrão.
router = DefaultRouter()
router.register(r'usuarios', UsuarioViewSet, basename='usuario')
router.register(r'perfis', PerfilViewSet, basename='perfil')
# --- LINHA DE CORREÇÃO ADICIONADA ABAIXO ---
# Registra o ViewSet de recursos, que criará a URL /recursos/
router.register(r'recursos', RecursoViewSet, basename='recurso')

# Aqui definimos as URLs finais da nossa aplicação.
urlpatterns = [
    # Inclui todas as URLs geradas pelo router (usuarios, perfis e recursos).
    path('', include(router.urls)),
]