# site-record/usuarios/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UsuarioViewSet,
    GrupoViewSet,
    PermissaoViewSet,
    PerfilViewSet,
    RecursoViewSet
)

router = DefaultRouter()
router.register(r'usuarios', UsuarioViewSet, basename='usuario')
router.register(r'grupos', GrupoViewSet, basename='grupo')
router.register(r'permissoes', PermissaoViewSet, basename='permissao')
router.register(r'perfis', PerfilViewSet, basename='perfil')
router.register(r'recursos', RecursoViewSet, basename='recurso')

urlpatterns = [
    path('', include(router.urls)),
]