# crm_app/views.py

from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from django.db.models import Count, Q

# A classe de permissão customizada será mantida para as outras views que não apresentaram erro.
from usuarios.permissions import CheckAPIPermission

from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia,
    RegraComissao, Cliente, Venda
)
from .serializers import (
    OperadoraSerializer, PlanoSerializer, FormaPagamentoSerializer,
    StatusCRMSerializer, MotivoPendenciaSerializer, RegraComissaoSerializer,
    VendaSerializer, VendaCreateSerializer, ClienteSerializer,
    VendaUpdateSerializer
)

# --- VIEWS DE CADASTROS GERAIS (VIEWS NÃO MODIFICADAS) ---

class OperadoraListCreateView(generics.ListCreateAPIView):
    queryset = Operadora.objects.filter(ativo=True)
    serializer_class = OperadoraSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'operadoras'

class OperadoraDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Operadora.objects.all()
    serializer_class = OperadoraSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'operadoras'

# --- VIEWS DE PLANOS (CORRIGIDAS) ---

class PlanoListCreateView(generics.ListCreateAPIView):
    queryset = Plano.objects.filter(ativo=True)
    serializer_class = PlanoSerializer
    # CORREÇÃO: Alterado para permitir que qualquer usuário autenticado acesse.
    permission_classes = [permissions.IsAuthenticated] 
    # resource_name = 'planos' # Removido pois era usado pela permissão customizada

class PlanoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Plano.objects.all()
    serializer_class = PlanoSerializer
    # CORREÇÃO: Alterado para permitir que qualquer usuário autenticado acesse.
    permission_classes = [permissions.IsAuthenticated]
    # resource_name = 'planos' # Removido

# --- VIEWS DE FORMAS DE PAGAMENTO (CORRIGIDAS) ---

class FormaPagamentoListCreateView(generics.ListCreateAPIView):
    queryset = FormaPagamento.objects.filter(ativo=True)
    serializer_class = FormaPagamentoSerializer
    # CORREÇÃO: Alterado para permitir que qualquer usuário autenticado acesse.
    permission_classes = [permissions.IsAuthenticated]
    # resource_name = 'formas_pagamento' # Removido

class FormaPagamentoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FormaPagamento.objects.all()
    serializer_class = FormaPagamentoSerializer
    # CORREÇÃO: Alterado para permitir que qualquer usuário autenticado acesse.
    permission_classes = [permissions.IsAuthenticated]
    # resource_name = 'formas_pagamento' # Removido

# --- VIEWS DE STATUS E MOTIVOS (VIEWS NÃO MODIFICADAS) ---

class StatusCRMListCreateView(generics.ListCreateAPIView):
    serializer_class = StatusCRMSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'status_crm'

    def get_queryset(self):
        queryset = StatusCRM.objects.all()
        tipo = self.request.query_params.get('tipo', None)
        if tipo:
            queryset = queryset.filter(tipo__iexact=tipo)
        return queryset.order_by('nome')

class StatusCRMDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = StatusCRM.objects.all()
    serializer_class = StatusCRMSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'status_crm'

class MotivoPendenciaListCreateView(generics.ListCreateAPIView):
    queryset = MotivoPendencia.objects.all()
    serializer_class = MotivoPendenciaSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'motivos_pendencia'

class MotivoPendenciaDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = MotivoPendencia.objects.all()
    serializer_class = MotivoPendenciaSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'motivos_pendencia'

class RegraComissaoListCreateView(generics.ListCreateAPIView):
    queryset = RegraComissao.objects.all()
    serializer_class = RegraComissaoSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'regras_comissao'

class RegraComissaoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = RegraComissao.objects.all()
    serializer_class = RegraComissaoSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'regras_comissao'


# --- VIEWSET DE VENDAS (COM LÓGICA DE PERMISSÃO CORRIGIDA E VALIDADA) ---
class VendaViewSet(viewsets.ModelViewSet):
    # A permissão base agora apenas verifica se o usuário está autenticado.
    # A lógica de filtragem de dados está corretamente implementada no método get_queryset.
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return VendaCreateSerializer
        if self.action in ['update', 'partial_update']:
            return VendaUpdateSerializer
        return VendaSerializer

    def get_queryset(self):
        user = self.request.user
        
        # Inicia a queryset base com otimizações para evitar múltiplas consultas ao banco de dados.
        queryset = Venda.objects.select_related(
            'vendedor', 'cliente', 'plano', 'forma_pagamento', 'status_tratamento', 'status_esteira'
        ).order_by('-data_criacao')

        # Obtém o nome do perfil do usuário de forma segura.
        perfil_nome = user.perfil.nome if hasattr(user, 'perfil') and user.perfil else None
        
        # PONTO DA CORREÇÃO 1: Superusuários e perfis de gestão veem todas as vendas.
        if user.is_superuser or perfil_nome in ['Diretoria', 'BackOffice']:
            return queryset

        # Lógica adicional para supervisores: veem as vendas deles e de suas equipes.
        if hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = user.liderados.values_list('id', flat=True)
            all_ids = list(liderados_ids) + [user.id]
            return queryset.filter(vendedor_id__in=all_ids)
        
        # PONTO DA CORREÇÃO 2: Vendedores (e outros perfis) veem apenas suas próprias vendas como padrão.
        return queryset.filter(vendedor=user)

    def perform_create(self, serializer):
        cpf_cnpj = serializer.validated_data.pop('cliente_cpf_cnpj')
        nome = serializer.validated_data.pop('cliente_nome_razao_social')
        email = serializer.validated_data.pop('cliente_email', None)
        
        cliente, created = Cliente.objects.get_or_create(
            cpf_cnpj=cpf_cnpj,
            defaults={'nome_razao_social': nome, 'email': email}
        )
        if not created:
            cliente.nome_razao_social = nome
            if email:
                cliente.email = email
            cliente.save()

        try:
            status_inicial = StatusCRM.objects.get(nome__iexact="SEM TRATAMENTO", tipo__iexact="Tratamento")
        except StatusCRM.DoesNotExist:
            status_inicial = None

        serializer.save(
            vendedor=self.request.user,
            cliente=cliente,
            status_tratamento=status_inicial
        )

# --- VIEWSET DE BUSCA DE CLIENTES ---
class ClienteViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClienteSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'clientes' # Alterado para ser mais específico

    def get_queryset(self):
        queryset = Cliente.objects.all().annotate(vendas_count=Count('vendas'))
        
        search_query = self.request.query_params.get('search', None)
        if search_query:
            queryset = queryset.filter(
                Q(cpf_cnpj__icontains=search_query) | 
                Q(nome_razao_social__icontains=search_query)
            )
        return queryset