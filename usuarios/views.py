from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth.models import ContentType, Group, Permission
from django.db import transaction
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import Usuario, Perfil, PermissaoPerfil
from .serializers import (
    UsuarioSerializer,
    PerfilSerializer,
    UserProfileSerializer,
    RecursoSerializer,
    CustomTokenObtainPairSerializer,
    # Novos serializers para a modernização
    GroupSerializer,
    PermissionSerializer
)

class LoginView(TokenObtainPairView):
    """
    View para o login de usuários.
    """
    serializer_class = CustomTokenObtainPairSerializer

class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = Usuario.objects.all().order_by('first_name', 'last_name')
    serializer_class = UsuarioSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Filtra os usuários com base no parâmetro 'is_active'.
        """
        # Atualizado para carregar os grupos (perfis modernos) de forma eficiente
        queryset = Usuario.objects.select_related('perfil', 'supervisor').prefetch_related('groups').all()
        
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=(is_active.lower() == 'true'))
        return queryset.order_by('first_name', 'last_name')

    def destroy(self, request, *args, **kwargs):
        """
        Sobrescreve o método destroy para inativar o usuário em vez de deletar.
        """
        instance = self.get_object()
        try:
            instance.is_active = False
            instance.save()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response(
                {"detail": f"Ocorreu um erro ao inativar o usuário: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['put'], url_path='reativar')
    def reativar(self, request, pk=None):
        """
        Ação para reativar um usuário inativo.
        """
        usuario = self.get_object()
        usuario.is_active = True
        usuario.save()
        serializer = self.get_serializer(usuario)
        return Response(serializer.data)

# --- NOVAS VIEWSETS (MODERNIZAÇÃO PARA GRUPOS DO DJANGO) ---

class GrupoViewSet(viewsets.ModelViewSet):
    """
    Gerencia os Grupos do Django (Novos Perfis de Acesso).
    """
    queryset = Group.objects.all().order_by('name')
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]

class PermissaoViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Lista as permissões disponíveis no sistema para serem vinculadas aos grupos.
    """
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Filtra apenas permissões dos seus aplicativos para não poluir a lista
        # com permissões internas do Django (como sessões, content types, etc).
        meus_apps = ['crm_app', 'usuarios', 'presenca', 'osab', 'relatorios']
        return Permission.objects.filter(content_type__app_label__in=meus_apps).order_by('content_type__model', 'codename')

# --- VIEWSETS LEGADOS (MANTIDOS PARA COMPATIBILIDADE) ---

class PerfilViewSet(viewsets.ModelViewSet):
    """
    Mantido para compatibilidade com dados antigos.
    Recomenda-se migrar o uso para GrupoViewSet.
    """
    queryset = Perfil.objects.all().order_by('nome')
    serializer_class = PerfilSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['get', 'put'], url_path='permissoes')
    def permissoes(self, request, pk=None):
        # Lógica antiga mantida caso ainda seja usada por algum componente legado
        perfil = self.get_object()

        if request.method == 'GET':
            permissions = perfil.permissoes.all()
            codenames = []
            for p in permissions:
                if p.pode_ver: codenames.append(f"can_view_{p.recurso}")
                if p.pode_criar: codenames.append(f"can_add_{p.recurso}")
                if p.pode_editar: codenames.append(f"can_change_{p.recurso}")
                if p.pode_excluir: codenames.append(f"can_delete_{p.recurso}")
            return Response(codenames)

        elif request.method == 'PUT':
            permissoes_data = request.data.get('permissoes', [])
            recursos_para_atualizar = {}
            for p_data in permissoes_data:
                recurso = p_data.get('recurso')
                acao = p_data.get('acao')
                ativo = p_data.get('ativo')
                if recurso not in recursos_para_atualizar:
                    recursos_para_atualizar[recurso] = {'pode_ver': False, 'pode_criar': False, 'pode_editar': False, 'pode_excluir': False}
                
                if acao == 'view': recursos_para_atualizar[recurso]['pode_ver'] = ativo
                elif acao == 'add': recursos_para_atualizar[recurso]['pode_criar'] = ativo
                elif acao == 'change': recursos_para_atualizar[recurso]['pode_editar'] = ativo
                elif acao == 'delete': recursos_para_atualizar[recurso]['pode_excluir'] = ativo

            try:
                with transaction.atomic():
                    perfil.permissoes.all().delete()
                    for recurso, permissoes in recursos_para_atualizar.items():
                        if any(permissoes.values()):
                            PermissaoPerfil.objects.create(perfil=perfil, recurso=recurso, **permissoes)
            except Exception as e:
                 return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({'status': 'permissões atualizadas'}, status=status.HTTP_200_OK)

class UserProfileView(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

class RecursoViewSet(viewsets.ViewSet):
    """
    View legada para listar nomes de recursos do sistema antigo.
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        app_models = {
            'crm_app': ['venda', 'cliente', 'plano', 'operadora'],
            'presenca': ['presenca'],
            'usuarios': ['usuario', 'perfil']
        }
        recursos_formatados = []
        for app, models in app_models.items():
            for model in models:
                recursos_formatados.append(f"{app}_{model}")
        return Response(recursos_formatados)