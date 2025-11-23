# site-record/presenca/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PresencaViewSet,
    MotivoViewSet,
    DiaNaoUtilViewSet,
    MinhaEquipeListView,
    TodosUsuariosListView
)

# O Router cria as URLs automaticamente para listagem e detalhes (ID)
router = DefaultRouter()

# --- CORREÇÃO CRUCIAL ---
# Registramos 'registros' no router. Isso cria automaticamente:
# - GET/POST em /api/presenca/registros/
# - PUT/DELETE em /api/presenca/registros/<id>/ (Essa rota estava faltando!)
router.register(r'registros', PresencaViewSet, basename='presenca')

router.register(r'motivos', MotivoViewSet, basename='motivo')
router.register(r'dias-nao-uteis', DiaNaoUtilViewSet, basename='dianaoutil')

urlpatterns = [
    path('', include(router.urls)),
    
    # Rotas de listagem personalizadas (apenas leitura)
    path('minha-equipe/', MinhaEquipeListView.as_view(), name='minha-equipe'),
    path('todos-usuarios/', TodosUsuariosListView.as_view(), name='todos-usuarios'),
]