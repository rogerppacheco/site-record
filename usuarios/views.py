from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth.models import ContentType
from django.db import transaction  # Importado para garantir a integridade dos dados
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import Usuario, Perfil, PermissaoPerfil  # Adicionado PermissaoPerfil
from .serializers import (
    UsuarioSerializer,
    PerfilSerializer,
    # PermissionSerializer não é mais necessário aqui diretamente, mas pode ser usado pelo serializer
    UserProfileSerializer,
    RecursoSerializer,
    CustomTokenObtainPairSerializer
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
        queryset = Usuario.objects.select_related('perfil', 'supervisor').all()
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

class PerfilViewSet(viewsets.ModelViewSet):
    queryset = Perfil.objects.all().order_by('nome')
    serializer_class = PerfilSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['get', 'put'], url_path='permissoes')
    def permissoes(self, request, pk=None):
        perfil = self.get_object()

        if request.method == 'GET':
            # CORREÇÃO: Lê as permissões do seu modelo PermissaoPerfil
            # e constrói a lista de "codenames" que o frontend espera.
            permissions = perfil.permissoes.all()
            codenames = []
            for p in permissions:
                if p.pode_ver:
                    codenames.append(f"can_view_{p.recurso}")
                if p.pode_criar:
                    codenames.append(f"can_add_{p.recurso}")
                if p.pode_editar:
                    codenames.append(f"can_change_{p.recurso}") # Django usa 'change' para 'editar'
                if p.pode_excluir:
                    codenames.append(f"can_delete_{p.recurso}")
            return Response(codenames)

        elif request.method == 'PUT':
            # CORREÇÃO: Atualiza ou cria as permissões no seu modelo PermissaoPerfil.
            permissoes_data = request.data.get('permissoes', [])
            
            # Agrupa as ações por recurso para eficiência
            recursos_para_atualizar = {}
            for p_data in permissoes_data:
                recurso = p_data.get('recurso')
                acao = p_data.get('acao')
                ativo = p_data.get('ativo')
                if recurso not in recursos_para_atualizar:
                    recursos_para_atualizar[recurso] = {
                        'pode_ver': False,
                        'pode_criar': False,
                        'pode_editar': False,
                        'pode_excluir': False
                    }
                
                if acao == 'view':
                    recursos_para_atualizar[recurso]['pode_ver'] = ativo
                elif acao == 'add':
                    recursos_para_atualizar[recurso]['pode_criar'] = ativo
                elif acao == 'change':
                    recursos_para_atualizar[recurso]['pode_editar'] = ativo
                elif acao == 'delete':
                    recursos_para_atualizar[recurso]['pode_excluir'] = ativo

            try:
                with transaction.atomic():
                    # Deleta as permissões existentes para este perfil para depois recriá-las
                    perfil.permissoes.all().delete()
                    
                    # Cria as novas permissões com base no que foi enviado
                    for recurso, permissoes in recursos_para_atualizar.items():
                        # Só cria a linha no banco se pelo menos uma permissão estiver ativa
                        if any(permissoes.values()):
                            PermissaoPerfil.objects.create(
                                perfil=perfil,
                                recurso=recurso,
                                **permissoes
                            )
            except Exception as e:
                 return Response(
                     {"detail": f"Ocorreu um erro ao salvar as permissões: {str(e)}"},
                     status=status.HTTP_500_INTERNAL_SERVER_ERROR
                 )

            return Response({'status': 'permissões atualizadas'}, status=status.HTTP_200_OK)

class UserProfileView(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

class RecursoViewSet(viewsets.ViewSet):
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