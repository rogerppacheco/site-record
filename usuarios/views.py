from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView  # <--- ESTA LINHA ERA A QUE FALTAVA
from django.contrib.auth.models import ContentType, Group, Permission
from django.db import transaction
from django.utils.crypto import get_random_string
from rest_framework_simplejwt.views import TokenObtainPairView
from crm_app.whatsapp_service import WhatsAppService 
import re

from .models import Usuario, Perfil, PermissaoPerfil
from .serializers import (
    UsuarioSerializer,
    PerfilSerializer,
    UserProfileSerializer,
    RecursoSerializer,
    CustomTokenObtainPairSerializer,
    GroupSerializer,
    PermissionSerializer,
    TrocaSenhaSerializer,
    ResetSenhaSolicitacaoSerializer
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
        # Atualizado para carregar os grupos de forma eficiente
        queryset = Usuario.objects.select_related('perfil', 'supervisor').prefetch_related('groups').all()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=(is_active.lower() == 'true'))
        return queryset.order_by('first_name', 'last_name')

    def destroy(self, request, *args, **kwargs):
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
        usuario = self.get_object()
        usuario.is_active = True
        usuario.save()
        serializer = self.get_serializer(usuario)
        return Response(serializer.data)

    # --- NOVA SEGURANÇA: ESQUECI A SENHA ---
    @action(detail=False, methods=['post'], permission_classes=[AllowAny], authentication_classes=[], url_path='esqueci-senha')
    def solicitar_reset_senha(self, request):
        serializer = ResetSenhaSolicitacaoSerializer(data=request.data)
        if serializer.is_valid():
            cpf_informado = re.sub(r'\D', '', serializer.validated_data['cpf'])
            zap_informado = re.sub(r'\D', '', serializer.validated_data['whatsapp'])

            # Busca usuário de forma segura
            usuario = None
            for u in Usuario.objects.all():
                if u.cpf and re.sub(r'\D', '', u.cpf) == cpf_informado:
                    usuario = u
                    break
            
            if not usuario:
                return Response({"detail": "CPF não encontrado."}, status=404)

            if not usuario.tel_whatsapp:
                return Response({"detail": "Usuário sem WhatsApp cadastrado. Contate o suporte."}, status=400)
            
            zap_banco = re.sub(r'\D', '', usuario.tel_whatsapp)
            
            # Verifica se os números batem
            if zap_informado not in zap_banco and zap_banco not in zap_informado:
                 return Response({"detail": "O WhatsApp informado não confere com o cadastro."}, status=400)

            # Gera Senha Provisória
            senha_provisoria = get_random_string(length=8)
            usuario.set_password(senha_provisoria)
            usuario.obriga_troca_senha = True
            usuario.save()

            # Envia via WhatsApp
            wa_service = WhatsAppService()
            msg = (
                f"🔒 *Recuperação de Senha*\n\n"
                f"Olá {usuario.first_name}, sua senha provisória é:\n"
                f"*{senha_provisoria}*\n\n"
                f"Acesse o sistema e defina uma nova senha imediatamente."
            )
            
            sucesso, resposta = wa_service.enviar_mensagem_texto(usuario.tel_whatsapp, msg)
            
            if sucesso:
                return Response({"detail": "Senha provisória enviada para seu WhatsApp!"})
            else:
                return Response({"detail": "Erro ao enviar WhatsApp. Tente novamente."}, status=503)
        
        return Response(serializer.errors, status=400)

    # --- NOVA SEGURANÇA: DEFINIR SENHA DEFINITIVA ---
    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated], url_path='definir-senha')
    def definir_nova_senha(self, request):
        serializer = TrocaSenhaSerializer(data=request.data)
        if serializer.is_valid():
            usuario = request.user
            nova_senha = serializer.validated_data['nova_senha']
            
            usuario.set_password(nova_senha)
            usuario.obriga_troca_senha = False 
            usuario.save()
            
            return Response({"detail": "Senha alterada com sucesso!"})
        
        return Response(serializer.errors, status=400)

# --- OUTRAS VIEWSETS ---

class GrupoViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all().order_by('name')
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]

class PermissaoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        meus_apps = ['crm_app', 'usuarios', 'presenca', 'osab', 'relatorios']
        return Permission.objects.filter(content_type__app_label__in=meus_apps).order_by('content_type__model', 'codename')

class PerfilViewSet(viewsets.ModelViewSet):
    queryset = Perfil.objects.all().order_by('nome')
    serializer_class = PerfilSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['get', 'put'], url_path='permissoes')
    def permissoes(self, request, pk=None):
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

# CLASSE ADICIONADA PARA EVITAR ERRO DE IMPORTAÇÃO NO URLS.PY
class DefinirNovaSenhaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TrocaSenhaSerializer(data=request.data)
        if serializer.is_valid():
            usuario = request.user
            nova_senha = serializer.validated_data['nova_senha']
            
            usuario.set_password(nova_senha)
            usuario.obriga_troca_senha = False 
            usuario.save()
            
            return Response({"detail": "Senha alterada com sucesso!"})
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)