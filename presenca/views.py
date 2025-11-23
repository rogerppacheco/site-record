# site-record/presenca/views.py

from rest_framework import viewsets, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated 
from .models import MotivoAusencia, Presenca, DiaNaoUtil
from .serializers import MotivoAusenciaSerializer, PresencaSerializer, DiaNaoUtilSerializer
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer

class MotivoViewSet(viewsets.ModelViewSet):
    queryset = MotivoAusencia.objects.all().order_by('motivo')
    serializer_class = MotivoAusenciaSerializer
    permission_classes = [IsAuthenticated]

class PresencaViewSet(viewsets.ModelViewSet):
    serializer_class = PresencaSerializer
    permission_classes = [IsAuthenticated]
    resource_name = 'presenca' 

    def get_queryset(self):
        user = self.request.user
        data_selecionada = self.request.query_params.get('data')
        queryset = Presenca.objects.all()
        
        if data_selecionada:
            queryset = queryset.filter(data=data_selecionada)
        
        # 1. Diretoria e Superusuário veem tudo (Verificação Moderna via Grupos)
        if user.is_superuser or user.groups.filter(name='Diretoria').exists():
            return queryset
        
        # 2. Supervisor vê sua equipe e a si mesmo
        if hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = list(user.liderados.values_list('id', flat=True))
            all_ids = liderados_ids + [user.id]
            return queryset.filter(colaborador_id__in=all_ids)
        
        # 3. Usuário comum vê apenas a si mesmo
        return queryset.filter(colaborador=user)

    def create(self, request, *args, **kwargs):
        """
        CORREÇÃO PRINCIPAL (UPSERT): 
        Verifica se já existe registro para este colaborador nesta data.
        - Se existir: Atualiza (não dá erro 400).
        - Se não existir: Cria novo.
        """
        data = request.data.copy()
        colaborador_id = data.get('colaborador')
        data_registro = data.get('data')

        # Busca registro existente
        registro_existente = Presenca.objects.filter(
            colaborador_id=colaborador_id, 
            data=data_registro
        ).first()

        if registro_existente:
            # ATUALIZA (Edita) o registro existente
            serializer = self.get_serializer(registro_existente, data=data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save(editado_por=request.user)
            # Retorna 200 OK (Atualizado)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            # CRIA um novo registro
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save(lancado_por=request.user)
            # Retorna 201 Created (Criado)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False) 
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
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