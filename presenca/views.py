# presenca/views.py

from rest_framework import viewsets, status, generics
from rest_framework.response import Response
# Importamos IsAuthenticated para garantir que basta estar logado
from rest_framework.permissions import IsAuthenticated 
from .models import MotivoAusencia, Presenca, DiaNaoUtil
from .serializers import MotivoAusenciaSerializer, PresencaSerializer, DiaNaoUtilSerializer
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer
# Removemos a dependência estrita do CheckAPIPermission para este módulo para destravar o Supervisor
# from usuarios.permissions import CheckAPIPermission 


class MotivoViewSet(viewsets.ModelViewSet):
    queryset = MotivoAusencia.objects.all().order_by('motivo')
    serializer_class = MotivoAusenciaSerializer
    permission_classes = [IsAuthenticated]


class PresencaViewSet(viewsets.ModelViewSet):
    serializer_class = PresencaSerializer
    # CORREÇÃO AQUI: Mudamos para IsAuthenticated.
    # O filtro de segurança real será feito no get_queryset (quem vê o quê).
    # Isso resolve o erro de "verificar conexão" para o Supervisor.
    permission_classes = [IsAuthenticated]
    resource_name = 'presenca' 

    def get_queryset(self):
        user = self.request.user
        data_selecionada = self.request.query_params.get('data')
        queryset = Presenca.objects.all()
        if data_selecionada:
            queryset = queryset.filter(data=data_selecionada)
        
        # 1. Se for Superusuário ou Diretoria, vê tudo
        if user.is_superuser or (hasattr(user, 'perfil') and user.perfil and user.perfil.nome == 'Diretoria'):
            return queryset
        
        # 2. Se for Supervisor (tem liderados), vê a si mesmo e aos liderados
        if hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = user.liderados.values_list('id', flat=True)
            # Concatena o ID do próprio supervisor com os dos liderados
            all_ids = list(liderados_ids) + [user.id]
            return queryset.filter(colaborador_id__in=all_ids)
        
        # 3. Se for usuário comum, só vê a si mesmo
        return queryset.filter(colaborador=user)

    def create(self, request, *args, **kwargs):
        """
        Lida com a CRIAÇÃO de um novo registro de presença.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Define quem está fazendo o lançamento original
        serializer.save(lancado_por=request.user)
        
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        """
        Lida com a ATUALIZAÇÃO de um registro de presença existente.
        """
        partial = kwargs.pop('partial', False) 
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        
        # Define quem está fazendo a edição
        serializer.save(editado_por=request.user)
        
        return Response(serializer.data)


class DiaNaoUtilViewSet(viewsets.ModelViewSet):
    queryset = DiaNaoUtil.objects.all().order_by('-data')
    serializer_class = DiaNaoUtilSerializer
    permission_classes = [IsAuthenticated]


class MinhaEquipeListView(generics.ListAPIView):
    serializer_class = UsuarioSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        # Retorna os liderados
        return user.liderados.all().order_by('first_name')


class TodosUsuariosListView(generics.ListAPIView):
    # Apenas usuários ativos e que participam do controle
    queryset = Usuario.objects.filter(is_active=True, participa_controle_presenca=True).order_by('first_name')
    serializer_class = UsuarioSerializer
    permission_classes = [IsAuthenticated]