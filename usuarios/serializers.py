from rest_framework import serializers
from .models import Usuario, Perfil, PermissaoPerfil
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import Permission, Group
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

# --- SERIALIZERS DE SEGURANÇA ---

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

# --- SERIALIZERS DE PERMISSÃO E GRUPO ---

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

# --- SERIALIZERS AUXILIARES ---

class RecursoSerializer(serializers.Serializer):
    recurso = serializers.CharField()
    def to_representation(self, instance):
        return instance

class PerfilSerializer(serializers.ModelSerializer):
    def validate_cod_perfil(self, value):
        if not value:
            raise serializers.ValidationError("O campo 'cod_perfil' é obrigatório.")
        if Perfil.objects.filter(cod_perfil=value).exists():
            raise serializers.ValidationError("Já existe um perfil com este código.")
        return value

    class Meta:
        model = Perfil
        fields = ['id', 'nome', 'cod_perfil']

class UsuarioLiderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ['id', 'username', 'first_name', 'last_name', 'email']

class UsuarioSerializer(serializers.ModelSerializer):
    # Campos de leitura
    nome_completo = serializers.CharField(source='get_full_name', read_only=True)
    perfil_detalhe = PerfilSerializer(source='perfil', read_only=True)
    supervisor_detalhe = UsuarioLiderSerializer(source='supervisor', read_only=True)
    groups_detalhe = GroupSerializer(source='groups', many=True, read_only=True)
    supervisor_nome = serializers.SerializerMethodField()

    # MÉTODO PARA OBTER O NOME DO LÍDER
    def get_supervisor_nome(self, obj):
        if obj.supervisor:
            nome = f"{obj.supervisor.first_name} {obj.supervisor.last_name}".strip()
            return nome if nome else obj.supervisor.username
        return "-"

    # ...existing code...

    class Meta:
        model = Usuario
        fields = [
            'id', 'username', 'first_name', 'last_name', 'nome_completo', 'email', 'cpf',
            'matricula_pap', 'senha_pap',
            'perfil', 'perfil_detalhe',
            'groups', 'groups_detalhe',
            'supervisor', 'supervisor_detalhe', 'supervisor_nome',
            'valor_almoco', 'valor_passagem', 'chave_pix', 'nome_da_conta',
            'meta_comissao', 'desconto_boleto', 'desconto_inclusao_viabilidade',
            'desconto_instalacao_antecipada', 
            'adiantamento_cnpj', 'desconto_inss_fixo',
            'is_active', 'is_staff',
            'canal',
            'cluster',
            'participa_controle_presenca',
            'tel_whatsapp',
            'obriga_troca_senha',
            'password'
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'perfil': {'required': False, 'allow_null': True},
            'supervisor': {'required': False, 'allow_null': True},
        }

    def to_representation(self, instance):
        """
        Transforma a resposta para o Frontend.
        Quando o front pede a lista, ele recebe o objeto Perfil inteiro (com nome),
        não apenas o ID.
        """
        ret = super().to_representation(instance)
        
        # Injeta os detalhes do perfil (com tratamento de erro caso perfil não exista)
        try:
            if instance.perfil_id and instance.perfil:
                ret['perfil'] = PerfilSerializer(instance.perfil).data
        except Exception:
            # Se o perfil não existir (ID inválido), não inclui no retorno
            pass
        
        # Injeta os detalhes do supervisor (Líder)
        try:
            if instance.supervisor_id and instance.supervisor:
                ret['supervisor'] = UsuarioLiderSerializer(instance.supervisor).data
        except Exception:
            # Se o supervisor não existir, não inclui no retorno
            pass
            
        return ret

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        groups = validated_data.pop('groups', [])
        
        # Garantir que campos com default não sejam None
        if 'meta_comissao' in validated_data and validated_data['meta_comissao'] is None:
            validated_data['meta_comissao'] = 0
        
        instance = self.Meta.model(**validated_data)
        if password:
            instance.set_password(password)
            instance.obriga_troca_senha = True
        # Sincronizar campo perfil baseado no primeiro grupo (antes de salvar)
        if groups:
            try:
                self._sincronizar_perfil_do_group(instance, groups[0])
            except Exception as e:
                # Se houver erro na sincronização, apenas loga e continua (não bloqueia)
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Erro ao sincronizar perfil do grupo: {e}")
        instance.save()
        if groups:
            instance.groups.set(groups)
        return instance

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        groups = validated_data.pop('groups', None)
        
        # Garantir que campos com default não sejam None
        if 'meta_comissao' in validated_data and validated_data['meta_comissao'] is None:
            validated_data['meta_comissao'] = 0
        
        # Atualiza campos normais (groups já foi removido do validated_data)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Processar groups separadamente
        if groups is not None:
            instance.groups.set(groups)
            # Sincronizar campo perfil baseado no primeiro grupo
            try:
                self._sincronizar_perfil_do_group(instance, groups[0] if groups else None)
            except Exception as e:
                # Se houver erro na sincronização, apenas loga e continua (não bloqueia)
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Erro ao sincronizar perfil do grupo: {e}")
            
        # Atualiza senha se fornecida
        if password:
            instance.set_password(password)
            
        instance.save()
        return instance
    
    def _sincronizar_perfil_do_group(self, usuario, group_id):
        """
        Sincroniza o campo perfil (ForeignKey) baseado no Group atribuído.
        Busca um Perfil com nome igual ao nome do Group.
        """
        from django.contrib.auth.models import Group
        from usuarios.models import Perfil
        
        if not group_id:
            # Se não há grupo, limpa o perfil
            usuario.perfil = None
            return
        
        try:
            group = Group.objects.get(id=group_id)
            # Busca um Perfil com o mesmo nome do Group (case-insensitive)
            try:
                perfil = Perfil.objects.get(nome__iexact=group.name)
                usuario.perfil = perfil
            except Perfil.DoesNotExist:
                # Se não encontrar Perfil com esse nome, limpa o campo
                usuario.perfil = None
                # Log para debug
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Perfil '{group.name}' não encontrado para Group '{group.name}'. Campo perfil limpo.")
            except Perfil.MultipleObjectsReturned:
                # Se houver múltiplos perfis com o mesmo nome, pega o primeiro
                perfil = Perfil.objects.filter(nome__iexact=group.name).first()
                usuario.perfil = perfil
        except Group.DoesNotExist:
            # Se o Group não existir, limpa o perfil
            usuario.perfil = None
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Group com ID {group_id} não encontrado. Campo perfil limpo.")

# --- SERIALIZER DE PERFIL DO USUÁRIO (LEITURA) ---

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

# --- SERIALIZER DE LOGIN (CUSTOMIZADO) ---

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['user_name'] = user.get_full_name() if hasattr(user, 'get_full_name') else user.username
        # Adiciona o perfil legado (com tratamento de erro caso perfil não exista)
        perfil_nome = 'Vendedor'  # Padrão
        try:
            # Prioridade 1: Campo perfil do modelo Usuario
            if hasattr(user, 'perfil_id') and user.perfil_id:
                user.perfil  # Tenta acessar para verificar se existe
                if user.perfil:
                    perfil_nome = user.perfil.nome
        except Exception:
            pass
        
        # Prioridade 2: Se não encontrou perfil, usa o primeiro Group como fallback
        if perfil_nome == 'Vendedor' and user.groups.exists():
            perfil_nome = user.groups.first().name
        
        token['perfil'] = perfil_nome
        token['user_role'] = perfil_nome  # Compatibilidade com frontend
        
        # Adiciona o primeiro grupo como perfil principal
        if user.groups.exists():
            token['grupo_principal'] = user.groups.first().name
        # --- SEGURANÇA: Adiciona flag no Token ---
        token['obriga_troca_senha'] = user.obriga_troca_senha
        return token

    def validate(self, attrs):
        # Permitir login com username OU email
        username_input = attrs.get('username', '')
        password = attrs.get('password', '')
        
        logger.warning(f"[LOGIN] Input: username_input='{username_input}', password_len={len(password) if password else 0}")
        
        # Tentar primeiro com o valor fornecido (username ou email)
        self.user = None
        try:
            # Tenta com username primeiro (case-insensitive)
            self.user = User.objects.get(username__iexact=username_input)
            logger.warning(f"[LOGIN] Found user by username: {self.user.username}")
        except User.DoesNotExist:
            logger.warning(f"[LOGIN] User not found by username, trying email...")
            try:
                # Se não encontrar, tenta com email (case-insensitive)
                self.user = User.objects.get(email__iexact=username_input)
                logger.warning(f"[LOGIN] Found user by email: {self.user.username}")
            except User.DoesNotExist:
                logger.warning(f"[LOGIN] User not found by email either")
                pass
        
        # Se encontrou usuário, atualizar attrs para autenticação do Django
        if self.user:
            attrs['username'] = self.user.username
            logger.warning(f"[LOGIN] Updated attrs username to: {attrs['username']}")
        
        try:
            logger.warning(f"[LOGIN] Calling super().validate()...")
            data = super().validate(attrs)
            logger.warning(f"[LOGIN] super().validate() succeeded")
        except Exception as e:
            logger.warning(f"[LOGIN] super().validate() failed: {type(e).__name__}: {str(e)}")
            raise

        if self.user and not self.user.is_active:
            raise serializers.ValidationError("Este usuário está inativo e não pode fazer login.")

        data['token'] = data.pop('access')

        user_profile = None
        if self.user:
            try:
                # Tenta acessar o perfil, mas não falha se não existir
                if self.user.perfil_id:  # Verifica se há um ID antes de acessar
                    user_profile = self.user.perfil.nome
            except Exception as e:
                logger.warning(f"[LOGIN] Erro ao acessar perfil: {e}")
                user_profile = None

        # --- RETORNA A FLAG PARA O JAVASCRIPT ---
        if self.user:
            data['obriga_troca_senha'] = self.user.obriga_troca_senha 

            data['user'] = {
                'id': self.user.id,
                'username': self.user.username,
                'perfil': user_profile,
                'groups': [g.name for g in self.user.groups.all()],
                'obriga_troca_senha': self.user.obriga_troca_senha
            }
        
        return data