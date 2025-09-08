# presenca/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PresencaViewSet, 
    MotivoViewSet, 
    DiaNaoUtilViewSet,
    MinhaEquipeListView,
    TodosUsuariosListView
)

# O DefaultRouter do Django REST Framework cria as rotas da API automaticamente
# para os ViewSets. Ele vai gerar as URLs para listagem, detalhe, criação, etc.
router = DefaultRouter()
router.register(r'presencas', PresencaViewSet, basename='presenca')
router.register(r'motivos', MotivoViewSet, basename='motivo')
router.register(r'dias-nao-uteis', DiaNaoUtilViewSet, basename='dianaoutil')

# As urlpatterns da aplicação 'presenca'
urlpatterns = [
    # Inclui todas as rotas geradas pelo router (ex: /motivos/, /presencas/, etc.)
    path('', include(router.urls)),
    
    # Rotas adicionais que não são baseadas em ViewSets
    path('minha-equipe/', MinhaEquipeListView.as_view(), name='minha-equipe'),
    path('todos-usuarios/', TodosUsuariosListView.as_view(), name='todos-usuarios'),
]