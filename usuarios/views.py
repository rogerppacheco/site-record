# site-record/usuarios/views.py

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, views
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView

# --- Importações dos seus módulos ---
from .models import Perfil, PermissaoPerfil
from .serializers import (
    CustomTokenObtainPairSerializer,
    UsuarioSerializer,
    PerfilSerializer,
    PermissaoPerfilSerializer
)
from .permissions import CheckAPIPermission


# View para fornecer a lista de recursos disponíveis para permissão
class RecursosListView(views.APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        recursos = [
            'clientes', 'dias_nao_uteis', 'formas_pagamento',
            'motivos_pendencia', 'operadoras', 'osab', 'planos', 'presenca',
            'regras_comissao', 'status_crm', 'usuarios', 'vendas',
        ]
        return Response(sorted(recursos))


# View customizada para o login
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


# ViewSet para o modelo de Usuário (com permissão dinâmica)
class UsuarioViewSet(viewsets.ModelViewSet):
    serializer_class = UsuarioSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'usuarios'

    def get_queryset(self):
        User = get_user_model()
        queryset = User.objects.all().order_by('first_name')
        is_active_param = self.request.query_params.get('is_active', None)
        if is_active_param is not None:
            is_active = is_active_param.lower() == 'true'
            queryset = queryset.filter(is_active=is_active)
        return queryset

    @action(detail=True, methods=['put'], url_path='desativar')
    def desativar(self, request, pk=None):
        usuario = self.get_object()
        usuario.is_active = False
        usuario.save()
        return Response({'status': 'usuário desativado'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['put'], url_path='reativar')
    def reativar(self, request, pk=None):
        usuario = self.get_object()
        usuario.is_active = True
        usuario.save()
        return Response({'status': 'usuário reativado'}, status=status.HTTP_200_OK)


# ViewSet para o modelo de Perfil
class PerfilViewSet(viewsets.ModelViewSet):
    queryset = Perfil.objects.all().order_by('nome')
    serializer_class = PerfilSerializer
    permission_classes = [IsAuthenticated]

    # =========================================================================
    # SUBSTITUA TODA A FUNÇÃO ABAIXO PELA VERSÃO CORRIGIDA
    # =========================================================================
    @action(detail=True, methods=['get', 'put'], url_path='permissoes')
    def gerenciar_permissoes(self, request, pk=None):
        perfil = self.get_object()

        if request.method == 'GET':
            # Busca todas as permissões salvas para o perfil
            permissoes = PermissaoPerfil.objects.filter(perfil=perfil)
            # Retorna a lista de nomes de permissão (ex: ['can_view_clientes', 'can_add_vendas'])
            # que é o formato que o frontend espera.
            nomes_codificados = list(permissoes.values_list('recurso', flat=True))
            return Response(nomes_codificados)

        if request.method == 'PUT':
            # 1. Apaga todas as permissões antigas para começar do zero
            PermissaoPerfil.objects.filter(perfil=perfil).delete()

            # 2. Processa os novos dados enviados pela tabela do frontend
            # Espera um formato como: {"permissoes": [{"recurso": "clientes", "acao": "view", "ativo": true}, ...]}
            permissoes_data = request.data.get('permissoes', [])
            
            permissoes_para_criar = []

            for p_data in permissoes_data:
                # Apenas cria a permissão se a checkbox estiver marcada ("ativo": true)
                if p_data.get('ativo'):
                    recurso = p_data.get('recurso')
                    acao = p_data.get('acao')
                    
                    if recurso and acao:
                        # Monta o nome completo da permissão (codename), ex: "can_view_clientes"
                        codename = f"can_{acao}_{recurso}"
                        
                        # Adiciona a nova permissão a uma lista para ser salva no banco de dados
                        permissoes_para_criar.append(
                            PermissaoPerfil(perfil=perfil, recurso=codename)
                        )

            # 3. Salva todas as novas permissões no banco de dados de uma só vez (mais eficiente)
            if permissoes_para_criar:
                PermissaoPerfil.objects.bulk_create(permissoes_para_criar)

            # Retorna um status de sucesso
            return Response({'status': 'Permissões atualizadas com sucesso'}, status=status.HTTP_201_CREATED)