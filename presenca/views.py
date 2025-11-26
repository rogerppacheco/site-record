from rest_framework import viewsets, status, generics
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated 
from django.http import Http404

# CORREÇÃO 1: Importar MotivoAusencia em vez de Motivo
from .models import MotivoAusencia, Presenca, DiaNaoUtil

# CORREÇÃO 2: Importar MotivoAusenciaSerializer em vez de MotivoSerializer
from .serializers import MotivoAusenciaSerializer, PresencaSerializer, DiaNaoUtilSerializer
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer

class MotivoViewSet(viewsets.ModelViewSet):
    # CORREÇÃO 3: Usar MotivoAusencia e MotivoAusenciaSerializer
    queryset = MotivoAusencia.objects.all().order_by('motivo')
    serializer_class = MotivoAusenciaSerializer
    permission_classes = [IsAuthenticated]

class PresencaViewSet(viewsets.ModelViewSet):
    serializer_class = PresencaSerializer
    permission_classes = [IsAuthenticated]
    resource_name = 'presenca' 

    # --- DEBUGGER: Espião de Requisição ---
    def dispatch(self, request, *args, **kwargs):
        """
        Este método roda ANTES de tudo. Vamos verificar se o ID existe no banco.
        """
        print("\n" + "="*50)
        print(f"DEBUG: Recebendo requisição {request.method} em {request.path}")
        print(f"DEBUG: Usuário Logado: {request.user} (ID: {request.user.id})")
        
        # Verifica se tem um ID na URL (ex: /38/)
        pk = kwargs.get('pk')
        if pk:
            print(f"DEBUG: Buscando Registro ID: {pk}...")
            exists = Presenca.objects.filter(pk=pk).exists()
            if exists:
                obj = Presenca.objects.get(pk=pk)
                print(f"DEBUG: [SUCESSO] O registro {pk} EXISTE no banco.")
                print(f"DEBUG: Detalhes -> Data: {obj.data} | Colaborador: {obj.colaborador}")
            else:
                print(f"DEBUG: [ERRO] O registro {pk} NÃO EXISTE no banco de dados.")
                print("DEBUG: Isso explica o erro 404. O Frontend está tentando apagar algo que já sumiu.")
        
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        user = self.request.user
        queryset = Presenca.objects.all()
        
        # Se for DELETE ou UPDATE, retorna tudo para não bloquear o acesso pelo ID
        if self.action in ['destroy', 'update', 'partial_update', 'retrieve']:
            return queryset

        # --- Filtros de Segurança (Apenas para Listagem) ---
        if user.is_superuser or user.groups.filter(name__in=['Diretoria', 'Admin', 'BackOffice']).exists():
            pass 
        elif hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = list(user.liderados.values_list('id', flat=True))
            all_ids = liderados_ids + [user.id]
            queryset = queryset.filter(colaborador_id__in=all_ids)
        else:
            queryset = queryset.filter(colaborador=user)

        # --- Filtro de Data (Apenas para Listagem) ---
        if self.action == 'list':
            data_selecionada = self.request.query_params.get('data')
            if data_selecionada:
                queryset = queryset.filter(data=data_selecionada)
        
        return queryset

    def destroy(self, request, *args, **kwargs):
        print("DEBUG: Entrou no método destroy (Exclusão)")
        try:
            pk = kwargs.get('pk')
            # Força a busca direta para garantir
            instance = Presenca.objects.get(pk=pk)
            self.perform_destroy(instance)
            print(f"DEBUG: Registro {pk} excluído com sucesso!")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Presenca.DoesNotExist:
            print("DEBUG: Falha no destroy - Objeto não encontrado.")
            return Response({"detail": "Registro não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"DEBUG: Erro genérico: {e}")
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        colaborador_id = data.get('colaborador')
        data_registro = data.get('data')
        registro_existente = Presenca.objects.filter(colaborador_id=colaborador_id, data=data_registro).first()

        if registro_existente:
            serializer = self.get_serializer(registro_existente, data=data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save(editado_por=request.user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save(lancado_por=request.user)
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
        return user.liderados.filter(is_active=True).order_by('first_name')

class TodosUsuariosListView(generics.ListAPIView):
    queryset = Usuario.objects.filter(is_active=True, participa_controle_presenca=True).order_by('first_name')
    serializer_class = UsuarioSerializer
    permission_classes = [IsAuthenticated]