# usuarios/urls.py

from django.urls import path
# A correção está na lista de importação abaixo:
from .views import (
    UserListCreateView,
    UserRetrieveUpdateDestroyView,
    PerfilListCreateView, # <<< NOME CORRIGIDO AQUI
    PerfilRetrieveUpdateDestroyView,
    SupervisoresListView,
    PerfilPermissoesView,
    UserReativarView  # <-- ESSA VIEW PRECISA SER IMPORTADA AQUI
)

urlpatterns = [
    # Rotas para usuários
    path('usuarios/', UserListCreateView.as_view(), name='user-list-create'),
    path('usuarios/<int:pk>/', UserRetrieveUpdateDestroyView.as_view(), name='user-detail'),
    path('usuarios/<int:pk>/reativar/', UserReativarView.as_view(), name='user-reactivate'),

    # Rotas para perfis
    path('perfis/', PerfilListCreateView.as_view(), name='perfil-list-create'),
    path('perfis/<int:pk>/', PerfilRetrieveUpdateDestroyView.as_view(), name='perfil-detail'),
    path('perfis/<int:pk>/permissoes/', PerfilPermissoesView.as_view(), name='perfil-permissoes'),
    
    # Rota para supervisores
    path('supervisores/', SupervisoresListView.as_view(), name='supervisores-list'),
]