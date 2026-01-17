from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
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
    serializer_class = CustomTokenObtainPairSerializer

class GrupoViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all().order_by('name')
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]

class PermissaoViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PermissionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # Desabilita paginação para retornar todas as permissões
    
    def get_queryset(self):
        meus_apps = ['crm_app', 'usuarios', 'presenca', 'osab', 'relatorios']
        return Permission.objects.filter(content_type__app_label__in=meus_apps).distinct().order_by('content_type__model', 'codename')
    
    def list(self, request, *args, **kwargs):
        """
        Sobrescreve o método list para garantir que todas as permissões sejam retornadas
        sem paginação, mesmo que a paginação global esteja habilitada.
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class PerfilViewSet(viewsets.ModelViewSet):
    queryset = Perfil.objects.all().order_by('nome')
    serializer_class = PerfilSerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)
        response = super().list(request, *args, **kwargs)
        # logger.debug(f"[DEBUG PERFIS] Perfis retornados: {response.data}")
        return response

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

class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = Usuario.objects.all().select_related('supervisor', 'perfil').prefetch_related('groups').order_by('first_name')
    serializer_class = UsuarioSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    # --- Performance ---
    # Se você quiser ativar paginação padrão aqui futuramente, descomente:
    # pagination_class = PageNumberPagination 

    def get_queryset(self):
        """
        Processa o parâmetro is_active da query string para filtrar usuários ativos/inativos.
        """
        queryset = super().get_queryset()
        
        is_active_param = self.request.query_params.get('is_active')
        if is_active_param is not None:
            is_active_value = is_active_param.lower() in ('true', '1')
            queryset = queryset.filter(is_active=is_active_value)
        
        # Filtro textual simples (opcional, mas bom para performance no frontend novo)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(first_name__icontains=search) | queryset.filter(username__icontains=search)

        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def lideres(self, request):
        usuarios = Usuario.objects.filter(is_active=True).values('id', 'username', 'first_name', 'last_name')
        data = []
        for u in usuarios:
            nome = f"{u['first_name']} {u['last_name']}".strip()
            if not nome:
                nome = u['username']
            else:
                nome = f"{nome} ({u['username']})"
            data.append({
                'id': u['id'], 
                'username': u['username'],
                'nome_exibicao': nome
            })
        return Response(data)

    @action(detail=False, methods=['post'])
    def trocar_senha(self, request):
        serializer = TrocaSenhaSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            user.set_password(serializer.validated_data['nova_senha'])
            user.obriga_troca_senha = False
            user.save()
            return Response({'status': 'senha alterada'})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def solicitar_reset_senha(self, request):
        serializer = ResetSenhaSolicitacaoSerializer(data=request.data)
        if serializer.is_valid():
            return Response({'mensagem': 'Solicitação recebida.'})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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

    # --- NOVO ENDPOINT DE VALIDAÇÃO ASSÍNCRONA ---
    @action(detail=False, methods=['post'], url_path='validar-whatsapp')
    def validar_whatsapp(self, request):
        """
        Endpoint leve para verificar WhatsApp sem travar o banco ou a interface.
        Uso: POST /api/usuarios/validar-whatsapp/ { "telefone": "31999999999" }
        """
        telefone = request.data.get('telefone')
        
        # 1. Limpeza básica
        telefone_limpo = "".join(filter(str.isdigit, str(telefone or "")))
        
        if len(telefone_limpo) < 10 or len(telefone_limpo) > 13:
             return Response({
                 "valido": False, 
                 "mensagem": "Formato inválido. Digite DDD + Número (ex: 31999999999)."
             }, status=200)

        # 2. Validação na API do WhatsApp (Z-API)
        try:
            service = WhatsAppService()
            if not service.token or not service.instance_id:
                return Response({
                    "valido": True, 
                    "aviso": "API WhatsApp não configurada no servidor. Validação ignorada."
                }, status=200)
            
            # Adiciona o 55 se não tiver
            if len(telefone_limpo) <= 11:
                telefone_api = f"55{telefone_limpo}"
            else:
                telefone_api = telefone_limpo

            existe = service.verificar_numero_existe(telefone_api)
            
            if existe:
                return Response({
                    "valido": True, 
                    "mensagem": "WhatsApp confirmado!"
                })
            else:
                return Response({
                    "valido": False, 
                    "mensagem": "Número não possui WhatsApp ativo."
                })
                
        except Exception as e:
            # Retornamos sucesso com aviso para não bloquear o usuário caso a API caia
            return Response({
                "valido": True, 
                "aviso": f"Erro de conexão na validação: {str(e)}"
            })