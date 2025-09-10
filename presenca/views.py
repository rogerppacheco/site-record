# presenca/views.py

from rest_framework import viewsets, status, generics
from rest_framework.response import Response
from .models import MotivoAusencia, Presenca, DiaNaoUtil
from .serializers import MotivoAusenciaSerializer, PresencaSerializer, DiaNaoUtilSerializer
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer
from usuarios.permissions import CheckAPIPermission


class MotivoViewSet(viewsets.ModelViewSet):
    queryset = MotivoAusencia.objects.all().order_by('motivo')
    serializer_class = MotivoAusenciaSerializer


class PresencaViewSet(viewsets.ModelViewSet):
    serializer_class = PresencaSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'presenca' 

    def get_queryset(self):
        user = self.request.user
        data_selecionada = self.request.query_params.get('data')
        queryset = Presenca.objects.all()
        if data_selecionada:
            queryset = queryset.filter(data=data_selecionada)
        
        if user.is_superuser or (hasattr(user, 'perfil') and user.perfil and user.perfil.nome == 'Diretoria'):
            return queryset
        
        if hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = user.liderados.values_list('id', flat=True)
            all_ids = list(liderados_ids) + [user.id]
            return queryset.filter(colaborador_id__in=all_ids)
        
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

    # --- CORREÇÃO APLICADA AQUI ---
    def update(self, request, *args, **kwargs):
        """
        Lida com a ATUALIZAÇÃO de um registro de presença existente.
        """
        # "partial=True" permite a atualização parcial (PATCH)
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


class MinhaEquipeListView(generics.ListAPIView):
    serializer_class = UsuarioSerializer
    def get_queryset(self):
        user = self.request.user
        return user.liderados.all().order_by('first_name')


class TodosUsuariosListView(generics.ListAPIView):
    queryset = Usuario.objects.filter(is_active=True).order_by('first_name')
    serializer_class = UsuarioSerializer