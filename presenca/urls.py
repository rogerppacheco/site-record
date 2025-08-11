# presenca/urls.py
from django.urls import path
from .views import (
    MotivoAusenciaListCreate, 
    PresencaListCreate, 
    MinhaEquipeListView,
    TodosUsuariosListView, # <-- 1. IMPORTE A NOVA VIEW
    DiaNaoUtilListCreate,
    DiaNaoUtilDestroy,
    PresencaRetrieveUpdateDestroyView # <-- Importe a nova view
)

urlpatterns = [
    path('motivos/', MotivoAusenciaListCreate.as_view(), name='motivo-list-create'),
    path('presencas/', PresencaListCreate.as_view(), name='presenca-list-create'),
    # --- ADICIONE A NOVA ROTA PARA EDIÇÃO/DELEÇÃO ---
    path('presencas/<int:pk>/', PresencaRetrieveUpdateDestroyView.as_view(), name='presenca-detail'),
    path('minha-equipe/', MinhaEquipeListView.as_view(), name='minha-equipe'),
    path('todos-usuarios/', TodosUsuariosListView.as_view(), name='todos-usuarios'),
    path('dias-nao-uteis/', DiaNaoUtilListCreate.as_view(), name='dias-nao-uteis-list-create'),
    path('dias-nao-uteis/<int:pk>/', DiaNaoUtilDestroy.as_view(), name='dias-nao-uteis-destroy'),
]