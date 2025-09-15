from rest_framework import serializers
from .models import Usuario, Perfil, PermissaoPerfil
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import Permission

User = get_user_model()

# --- ADICIONADO PARA CORRIGIR O ERRO DE IMPORTAÇÃO ---
class PermissionSerializer(serializers.ModelSerializer):
    """
    Serializer para o modelo de Permissões do Django.
    """
    class Meta:
        model = Permission
        fields = ['id', 'name', 'codename']

# --- ADICIONADO PARA GARANTIR COMPATIBILIDADE COM A VIEW ---
class RecursoSerializer(serializers.Serializer):
    """
    Serializer simples para listar nomes de recursos.
    """
    recurso = serializers.CharField()
    def to_representation(self, instance):
        return instance

class PerfilSerializer(serializers.ModelSerializer):
    """
    Serializer para o modelo Perfil.
    """
    class Meta:
        model = Perfil
        fields = '__all__'

class PermissaoPerfilSerializer(serializers.ModelSerializer):
    """
    Serializer para o modelo PermissaoPerfil.
    """
    class Meta:
        model = PermissaoPerfil
        fields = ['id', 'perfil', 'recurso', 'pode_ver', 'pode_criar', 'pode_editar', 'pode_excluir']
        extra_kwargs = {
            'perfil': {'write_only': True}
        }

class UsuarioSerializer(serializers.ModelSerializer):
    """
    Serializer para o modelo Usuario com a correção para salvar senhas.
    """
    perfil_nome = serializers.CharField(source='perfil.nome', read_only=True)
    supervisor_nome = serializers.CharField(source='supervisor.get_full_name', read_only=True, default=None)
    nome_completo = serializers.CharField(source='get_full_name', read_only=True)

    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'password', 'first_name', 'last_name', 'nome_completo', 'email', 'cpf',
            'perfil', 'perfil_nome', 'supervisor', 'supervisor_nome',
            'valor_almoco', 'valor_passagem', 'chave_pix', 'nome_da_conta',
            'meta_comissao', 'desconto_boleto', 'desconto_inclusao_viabilidade',
            'desconto_instalacao_antecipada', 'adiantamento_cnpj', 'desconto_inss_fixo',
            'is_active', 'is_staff',
            'canal'
        ]

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        instance = self.Meta.model(**validated_data)
        if password is not None:
            instance.set_password(password)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password is not None:
            instance.set_password(password)
            instance.save()
        return instance

# --- CÓDIGO DE CORREÇÃO ADICIONADO ABAIXO ---
class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializer para o perfil do usuário.
    """
    perfil_nome = serializers.CharField(source='perfil.nome', read_only=True)
    supervisor_nome = serializers.CharField(source='supervisor.get_full_name', read_only=True, default=None)
    nome_completo = serializers.CharField(source='get_full_name', read_only=True)

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'first_name', 'last_name', 'nome_completo', 'email', 'cpf',
            'perfil', 'perfil_nome', 'supervisor', 'supervisor_nome',
            'is_active', 'is_staff'
        ]


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username

        if hasattr(user, 'perfil') and user.perfil is not None:
            token['perfil'] = user.perfil.nome
        else:
            token['perfil'] = None

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        if not self.user.is_active:
            raise serializers.ValidationError("Este usuário está inativo e não pode fazer login.")

        data['token'] = data.pop('access')

        user_profile = None
        if hasattr(self.user, 'perfil') and self.user.perfil is not None:
            user_profile = self.user.perfil.nome

        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'perfil': user_profile
        }

        return data