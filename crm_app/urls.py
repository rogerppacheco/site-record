# crm_app/urls.py
from django.urls import path
from .views import (
    OperadoraListCreateView,
    PlanoListCreateView,
    FormaPagamentoListCreateView,
    StatusCRMListCreateView,
    MotivoPendenciaListCreateView
)

urlpatterns = [
    path('operadoras/', OperadoraListCreateView.as_view(), name='operadoras-list'),
    path('planos/', PlanoListCreateView.as_view(), name='planos-list'),
    path('formas-pagamento/', FormaPagamentoListCreateView.as_view(), name='formas-pagamento-list'),
    path('status/', StatusCRMListCreateView.as_view(), name='status-crm-list'),
    path('motivos-pendencia/', MotivoPendenciaListCreateView.as_view(), name='motivos-pendencia-list'),
]