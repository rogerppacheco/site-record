# site-record/usuarios/views.py

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, views
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from collections import defaultdict

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
            permissoes = PermissaoPerfil.objects.filter(perfil=perfil)
            
            # Monta uma lista de codenames que o frontend espera, ex: "can_view_presenca"
            codenames_ativos = []
            for p in permissoes:
                if p.pode_ver: codenames_ativos.append(f"can_view_{p.recurso}")
                if p.pode_criar: codenames_ativos.append(f"can_add_{p.recurso}")
                if p.pode_editar: codenames_ativos.append(f"can_change_{p.recurso}")
                if p.pode_excluir: codenames_ativos.append(f"can_delete_{p.recurso}")
            
            return Response(codenames_ativos)

        if request.method == 'PUT':
            permissoes_data = request.data.get('permissoes', [])
            
            # Agrupa as permissões por recurso para facilitar o processamento
            permissoes_agrupadas = defaultdict(dict)
            for p_data in permissoes_data:
                recurso = p_data.get('recurso')
                acao = p_data.get('acao') # 'view', 'add', 'change', 'delete'
                ativo = p_data.get('ativo', False)
                
                if recurso and acao:
                    # Mapeia a ação do frontend para o campo do modelo
                    campo_modelo = {
                        'view': 'pode_ver',
                        'add': 'pode_criar',
                        'change': 'pode_editar',
                        'delete': 'pode_excluir'
                    }.get(acao)
                    
                    if campo_modelo:
                        permissoes_agrupadas[recurso][campo_modelo] = ativo

            # Apaga as permissões antigas para começar do zero
            PermissaoPerfil.objects.filter(perfil=perfil).delete()

            # Cria as novas permissões
            permissoes_para_criar = []
            for recurso, campos in permissoes_agrupadas.items():
                permissoes_para_criar.append(
                    PermissaoPerfil(perfil=perfil, recurso=recurso, **campos)
                )

            if permissoes_para_criar:
                PermissaoPerfil.objects.bulk_create(permissoes_para_criar)

            return Response({'status': 'Permissões atualizadas com sucesso'}, status=status.HTTP_200_OK)