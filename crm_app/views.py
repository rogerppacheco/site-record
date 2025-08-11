# crm_app/views.py
from rest_framework import generics
from .models import Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia
from .serializers import (
    OperadoraSerializer, PlanoSerializer, FormaPagamentoSerializer,
    StatusCRMSerializer, MotivoPendenciaSerializer
)

class OperadoraListCreateView(generics.ListCreateAPIView):
    queryset = Operadora.objects.all()
    serializer_class = OperadoraSerializer

class PlanoListCreateView(generics.ListCreateAPIView):
    queryset = Plano.objects.select_related('operadora').all()
    serializer_class = PlanoSerializer

class FormaPagamentoListCreateView(generics.ListCreateAPIView):
    queryset = FormaPagamento.objects.all()
    serializer_class = FormaPagamentoSerializer

class StatusCRMListCreateView(generics.ListCreateAPIView):
    queryset = StatusCRM.objects.all()
    serializer_class = StatusCRMSerializer

class MotivoPendenciaListCreateView(generics.ListCreateAPIView):
    queryset = MotivoPendencia.objects.all()
    serializer_class = MotivoPendenciaSerializer