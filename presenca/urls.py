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

router = DefaultRouter()
router.register(r'presencas', PresencaViewSet, basename='presenca')
router.register(r'motivos', MotivoViewSet, basename='motivo')
router.register(r'dias-nao-uteis', DiaNaoUtilViewSet, basename='dianaoutil')

urlpatterns = [
    path('', include(router.urls)),
    
    # ROTA ESSENCIAL PARA O FRONTEND:
    path('registros/', PresencaViewSet.as_view({'get': 'list', 'post': 'create'}), name='presenca-registros'),
    
    path('minha-equipe/', MinhaEquipeListView.as_view(), name='minha-equipe'),
    path('todos-usuarios/', TodosUsuariosListView.as_view(), name='todos-usuarios'),
]