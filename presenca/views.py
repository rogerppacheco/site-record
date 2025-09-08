# presenca/views.py

from rest_framework import viewsets, status, generics
from rest_framework.response import Response
from .models import MotivoAusencia, Presenca, DiaNaoUtil
from .serializers import MotivoAusenciaSerializer, PresencaSerializer, DiaNaoUtilSerializer
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer
# --- 1. Importe a nova classe de permissão ---
from usuarios.permissions import CheckAPIPermission


class MotivoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar os Motivos de Ausência.
    """
    queryset = MotivoAusencia.objects.all().order_by('motivo')
    serializer_class = MotivoAusenciaSerializer


class PresencaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar as Presenças com permissões dinâmicas.
    """
    serializer_class = PresencaSerializer
    
    # --- 2. Adicione as novas permissões ---
    # A API agora verificará as permissões do banco de dados antes de executar qualquer código aqui.
    permission_classes = [CheckAPIPermission]
    resource_name = 'presenca' # O nome que você usará na tela de Governança

    def get_queryset(self):
        """
        Este método agora foca apenas em FILTRAR os dados que o usuário
        tem permissão para ver, já que o acesso foi garantido pela permission_classes.
        """
        user = self.request.user
        data_selecionada = self.request.query_params.get('data')

        # A consulta base não muda
        queryset = Presenca.objects.all()
        if data_selecionada:
            queryset = queryset.filter(data=data_selecionada)
        
        # --- 3. Simplificação da lógica de filtragem ---
        # A verificação de 'Diretoria' e 'Admin' não é mais necessária aqui,
        # pois a classe de permissão já deu acesso total a eles.
        # Agora, se o usuário for um líder, ele verá os dados de sua equipe.
        if hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = user.liderados.values_list('id', flat=True)
            all_ids = list(liderados_ids) + [user.id] # Inclui o próprio supervisor na lista
            return queryset.filter(colaborador_id__in=all_ids)
        
        # Se não for um líder, ele verá apenas os seus próprios registros de presença.
        return queryset.filter(colaborador=user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        validated_data = serializer.validated_data
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


class DiaNaoUtilViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar os Dias Não Úteis.
    """
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