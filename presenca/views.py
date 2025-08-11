# presenca/views.py
from rest_framework import generics, status
from rest_framework.response import Response
from .models import MotivoAusencia, Presenca, DiaNaoUtil
from .serializers import MotivoAusenciaSerializer, PresencaSerializer, DiaNaoUtilSerializer
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer


class MotivoAusenciaListCreate(generics.ListCreateAPIView):
    queryset = MotivoAusencia.objects.all().order_by('motivo')
    serializer_class = MotivoAusenciaSerializer

class PresencaListCreate(generics.ListCreateAPIView):
    serializer_class = PresencaSerializer

    def get_queryset(self):
        user = self.request.user
        data_selecionada = self.request.query_params.get('data')

        queryset = Presenca.objects.all()
        if data_selecionada:
            queryset = queryset.filter(data=data_selecionada)
        
        # --- LÓGICA DE PERMISSÃO CORRIGIDA ---
        # Se o usuário for Diretor ou Admin, retorna todos os registros da data.
        if user.perfil and user.perfil.nome in ['Diretoria', 'Admin']:
            return queryset

        # Para outros perfis (ex: Supervisor), mantém a lógica de ver apenas a própria equipe.
        if hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = user.liderados.values_list('id', flat=True)
            all_ids = list(liderados_ids) + [user.id]
            return queryset.filter(colaborador_id__in=all_ids)
        
        # Se não for líder de ninguém, vê apenas o seu.
        return queryset.filter(colaborador=user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        validated_data = serializer.validated_data
        # CORREÇÃO: Usamos 'colaborador' em vez de 'usuario'
        colaborador = validated_data.get('colaborador')
        data = validated_data.get('data')
        
        defaults = {
            'status': validated_data.get('status'),
            'motivo': validated_data.get('motivo'),
            'observacao': validated_data.get('observacao'),
            'lancado_por': request.user
        }
        
        instance, created = Presenca.objects.update_or_create(
            colaborador=colaborador, data=data, defaults=defaults
        )
        
        response_serializer = self.get_serializer(instance)
        headers = self.get_success_headers(response_serializer.data)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(response_serializer.data, status=status_code, headers=headers)

class PresencaRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Presenca.objects.all()
    serializer_class = PresencaSerializer

class MinhaEquipeListView(generics.ListAPIView):
    serializer_class = UsuarioSerializer
    def get_queryset(self):
        user = self.request.user
        return user.liderados.all().order_by('first_name')
class TodosUsuariosListView(generics.ListAPIView):
    """
    Retorna uma lista de todos os usuários ativos no sistema.
    """
    queryset = Usuario.objects.filter(is_active=True).order_by('first_name')
    serializer_class = UsuarioSerializer

class DiaNaoUtilListCreate(generics.ListCreateAPIView):
    queryset = DiaNaoUtil.objects.all().order_by('-data')
    serializer_class = DiaNaoUtilSerializer

class DiaNaoUtilDestroy(generics.DestroyAPIView):
    queryset = DiaNaoUtil.objects.all()
    serializer_class = DiaNaoUtilSerializer