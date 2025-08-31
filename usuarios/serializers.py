# usuarios/serializers.py

from rest_framework import serializers
from .models import Usuario, Perfil, PermissaoPerfil
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

# Serializer para o token JWT (mantido como está)
class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['perfil'] = user.perfil.nome if user.perfil else None
        return token

# --- VERSÃO CORRIGIDA E COMPLETA DO SERIALIZER DE USUÁRIO ---
class UsuarioSerializer(serializers.ModelSerializer):
    # Campo para LEITURA do NOME do perfil (útil para listagens)
    perfil_nome = serializers.CharField(source='perfil.nome', read_only=True, allow_null=True)
    
    # Campo para LEITURA do NOME COMPLETO do supervisor
    supervisor_nome = serializers.CharField(source='supervisor.get_full_name', read_only=True, allow_null=True)

    # Campo customizado para o nome completo (sua lógica original mantida)
    nome_completo = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        # A MÁGICA ESTÁ AQUI:
        # - 'perfil' e 'supervisor' agora representam os IDs, tanto para leitura quanto para escrita.
        # - 'perfil_nome' e 'supervisor_nome' são usados apenas para exibir os nomes.
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'is_active',
            'nome_completo',
            'cpf',
            
            'perfil',           # <--- CORREÇÃO: Representa o ID do perfil
            'perfil_nome',      # <--- Campo auxiliar para o NOME do perfil
            
            'supervisor',       # <--- CORREÇÃO: Representa o ID do supervisor
            'supervisor_nome',  # <--- Campo auxiliar para o NOME do supervisor
            
            'valor_almoco', 'valor_passagem', 'chave_pix', 'nome_da_conta',
            'meta_comissao', 'desconto_boleto', 'desconto_inclusao_viabilidade',
            'desconto_instalacao_antecipada', 'adiantamento_cnpj', 'desconto_inss_fixo',
            'password'
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            # O campo 'perfil' agora precisa ser obrigatório na escrita (envio do ID)
            'perfil': {'required': True}, 
        }

    def get_nome_completo(self, obj):
        full_name = obj.get_full_name()
        return full_name if full_name.strip() else obj.username

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = Usuario.objects.create(**validated_data)
        if password is not None:
            user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password is not None:
            instance.set_password(password)
        instance.save()
        return instance

# --- O RESTANTE DO SEU ARQUIVO PERMANECE IGUAL ---

# Serializer para o modelo Perfil
class PerfilSerializer(serializers.ModelSerializer):
    class Meta:
        model = Perfil
        fields = ['id', 'nome', 'descricao']

# Crie uma classe manager para o serializer many=True
class PermissaoPerfilListSerializer(serializers.ListSerializer):
    def create(self, validated_data):
        if not isinstance(validated_data, list):
            raise serializers.ValidationError("Os dados para criação devem ser uma lista.")
        
        permissoes = []
        for item_data in validated_data:
            perfil_id_valor = item_data.get('perfil_id')
            if not perfil_id_valor:
                raise serializers.ValidationError("O ID do perfil é obrigatório para cada permissão.")
            
            try:
                perfil_instance = Perfil.objects.get(id=perfil_id_valor)
            except Perfil.DoesNotExist:
                raise serializers.ValidationError(f"Perfil com ID {perfil_id_valor} não encontrado.")
            
            permissoes.append(
                PermissaoPerfil(
                    perfil=perfil_instance,
                    recurso=item_data.get('recurso'),
                    pode_ver=item_data.get('pode_ver', False),
                    pode_criar=item_data.get('pode_criar', False),
                    pode_editar=item_data.get('pode_editar', False),
                    pode_excluir=item_data.get('pode_excluir', False)
                )
            )
        
        for permissao in permissoes:
            permissao.save()
        
        return permissoes

# Serializer para o modelo PermissaoPerfil
class PermissaoPerfilSerializer(serializers.ModelSerializer):
    perfil_id = serializers.IntegerField(write_only=True)
    perfil = serializers.PrimaryKeyRelatedField(queryset=Perfil.objects.all(), required=False)

    class Meta:
        model = PermissaoPerfil
        fields = ['id', 'perfil_id', 'perfil', 'recurso', 'pode_ver', 'pode_criar', 'pode_editar', 'pode_excluir']