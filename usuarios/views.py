# usuarios/views.py
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import Usuario, Perfil, PermissaoPerfil # CORREÇÃO: Importa 'Usuario'
from .serializers import (
    UsuarioSerializer,
    PerfilSerializer,
    PermissaoPerfilSerializer,
    MyTokenObtainPairSerializer
)
import logging

logger = logging.getLogger(__name__)

class MyTokenObtainPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer

class UserListCreateView(generics.ListCreateAPIView):
    queryset = Usuario.objects.all() # CORREÇÃO: Usa 'Usuario'
    serializer_class = UsuarioSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            is_active_bool = is_active.lower() in ['true', '1']
            queryset = queryset.filter(is_active=is_active_bool)
        return queryset

class UserRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Usuario.objects.all() # CORREÇÃO: Usa 'Usuario'
    serializer_class = UsuarioSerializer

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save()

# CÓDIGO NOVO E CORRIGIDO
class UserReativarView(APIView):
    def put(self, request, pk, format=None):  # <-- ALTERAÇÃO AQUI
        try:
            user = Usuario.objects.get(id=pk) # <-- E AQUI
        except Usuario.DoesNotExist:
            return Response({"error": "Usuário não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        user.is_active = True
        user.save()
        serializer = UsuarioSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)

class SupervisoresListView(generics.ListAPIView):
    serializer_class = UsuarioSerializer

    def get_queryset(self):
        return Usuario.objects.filter( # CORREÇÃO: Usa 'Usuario'
            perfil__nome__in=['Diretoria', 'Gerente', 'Supervisor'],
            is_active=True
        )

class PerfilListCreateView(generics.ListCreateAPIView):
    queryset = Perfil.objects.all()
    serializer_class = PerfilSerializer

class PerfilRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Perfil.objects.all()
    serializer_class = PerfilSerializer
    lookup_field = 'id'

class PerfilPermissoesView(APIView):
    def get(self, request, pk, format=None):
        permissoes = PermissaoPerfil.objects.filter(perfil_id=pk)
        serializer = PermissaoPerfilSerializer(permissoes, many=True)
        return Response(serializer.data)

    def put(self, request, pk, format=None):
        try:
            perfil = Perfil.objects.get(pk=pk)
        except Perfil.DoesNotExist:
            return Response({"error": "Perfil não encontrado."}, status=status.HTTP_404_NOT_FOUND)

        PermissaoPerfil.objects.filter(perfil=perfil).delete()
        permissoes_data = request.data
        
        if not isinstance(permissoes_data, list):
             return Response({"error": "O corpo da requisição deve ser uma lista de permissões."}, status=status.HTTP_400_BAD_REQUEST)

        permissoes_criadas = []
        for item_data in permissoes_data:
            permissoes_criadas.append(
                PermissaoPerfil(
                    perfil=perfil,
                    recurso=item_data.get('recurso'),
                    pode_ver=item_data.get('pode_ver', False),
                    pode_criar=item_data.get('pode_criar', False),
                    pode_editar=item_data.get('pode_editar', False),
                    pode_excluir=item_data.get('pode_excluir', False)
                )
            )
        
        PermissaoPerfil.objects.bulk_create(permissoes_criadas)
        serializer = PermissaoPerfilSerializer(permissoes_criadas, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)