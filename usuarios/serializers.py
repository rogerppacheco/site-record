from rest_framework import serializers
from .models import Usuario, Perfil, PermissaoPerfil
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import Permission, Group

User = get_user_model()

# --- SERIALIZERS DE SEGURANÇA (ADICIONADOS) ---

class TrocaSenhaSerializer(serializers.Serializer):
    """
    Serializer para a troca obrigatória de senha.
    """
    nova_senha = serializers.CharField(required=True, min_length=6)
    confirmacao_senha = serializers.CharField(required=True, min_length=6)

    def validate(self, data):
        if data['nova_senha'] != data['confirmacao_senha']:
            raise serializers.ValidationError("As senhas não conferem.")
        return data

class ResetSenhaSolicitacaoSerializer(serializers.Serializer):
    """
    Serializer para solicitar reset via "Esqueci minha senha".
    """
    cpf = serializers.CharField(required=True)
    whatsapp = serializers.CharField(required=True)

# --- SERIALIZERS DE PERMISSÃO E GRUPO (MANTIDOS) ---

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['id', 'name', 'codename']

class GroupSerializer(serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(many=True, queryset=Permission.objects.all())
    permissions_details = PermissionSerializer(source='permissions', many=True, read_only=True)

    class Meta:
        model = Group
        fields = ['id', 'name', 'permissions', 'permissions_details']

# --- SERIALIZERS LEGADOS E AUXILIARES ---

class RecursoSerializer(serializers.Serializer):
    recurso = serializers.CharField()
    def to_representation(self, instance):
        return instance

class PerfilSerializer(serializers.ModelSerializer):
    class Meta:
        model = Perfil
        fields = '__all__'

class PermissaoPerfilSerializer(serializers.ModelSerializer):
    class Meta:
        model = PermissaoPerfil
        fields = ['id', 'perfil', 'recurso', 'pode_ver', 'pode_criar', 'pode_editar', 'pode_excluir']
        extra_kwargs = {
            'perfil': {'write_only': True}
        }

# --- SERIALIZERS DE USUÁRIO ---

class UsuarioSerializer(serializers.ModelSerializer):
    perfil_nome = serializers.CharField(source='perfil.nome', read_only=True)
    supervisor_nome = serializers.CharField(source='supervisor.get_full_name', read_only=True, default=None)
    nome_completo = serializers.CharField(source='get_full_name', read_only=True)
    groups = GroupSerializer(many=True, read_only=True)
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'password', 'first_name', 'last_name', 'nome_completo', 'email', 'cpf',
            'perfil', 'perfil_nome', 'groups',
            'supervisor', 'supervisor_nome',
            'valor_almoco', 'valor_passagem', 'chave_pix', 'nome_da_conta',
            'meta_comissao', 'desconto_boleto', 'desconto_inclusao_viabilidade',
            'desconto_instalacao_antecipada', 'adiantamento_cnpj', 'desconto_inss_fixo',
            'is_active', 'is_staff',
            'canal',
            'participa_controle_presenca',
            'tel_whatsapp',
            'obriga_troca_senha' # <--- ADICIONADO PARA O FRONTEND VER
        ]

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        instance = self.Meta.model(**validated_data)
        if password is not None:
            instance.set_password(password)
        
        # Novos usuários devem trocar a senha por padrão
        instance.obriga_troca_senha = True 
        instance.save()
        return instance

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password is not None:
            instance.set_password(password)
            instance.save()
        return instance

class UserProfileSerializer(serializers.ModelSerializer):
    perfil_nome = serializers.CharField(source='perfil.nome', read_only=True)
    supervisor_nome = serializers.CharField(source='supervisor.get_full_name', read_only=True, default=None)
    nome_completo = serializers.CharField(source='get_full_name', read_only=True)
    groups = GroupSerializer(many=True, read_only=True)

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'first_name', 'last_name', 'nome_completo', 'email', 'cpf',
            'perfil', 'perfil_nome', 'groups',
            'supervisor', 'supervisor_nome',
            'is_active', 'is_staff',
            'tel_whatsapp',
            'obriga_troca_senha'
        ]

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username

        # Adiciona o perfil legado
        if hasattr(user, 'perfil') and user.perfil is not None:
            token['perfil'] = user.perfil.nome
        else:
            token['perfil'] = None
            
        # Adiciona o primeiro grupo como perfil principal
        if user.groups.exists():
            token['grupo_principal'] = user.groups.first().name

        # --- SEGURANÇA: Adiciona flag no Token ---
        token['obriga_troca_senha'] = user.obriga_troca_senha

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        if not self.user.is_active:
            raise serializers.ValidationError("Este usuário está inativo e não pode fazer login.")

        data['token'] = data.pop('access')

        user_profile = None
        if hasattr(self.user, 'perfil') and self.user.perfil is not None:
            user_profile = self.user.perfil.nome

        # --- RETORNA A FLAG PARA O JAVASCRIPT ---
        data['obriga_troca_senha'] = self.user.obriga_troca_senha 

        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'perfil': user_profile,
            'groups': [g.name for g in self.user.groups.all()],
            'obriga_troca_senha': self.user.obriga_troca_senha
        }

        return data