# usuarios/serializers.py

from rest_framework import serializers
# Certifique-se de que Perfil, PermissaoPerfil e Usuario estejam importados
from .models import Usuario, Perfil, PermissaoPerfil
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer # Mantenha esta importação se usar o MyTokenObtainPairSerializer na view


# Serializer para o token JWT
# Defina o serializer ANTES de ser usado pela view (embora a view importe, é boa prática)
class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Adicionar informações adicionais ao token, se necessário
        # token['username'] = user.username
        token['perfil'] = user.perfil.nome if user.perfil else None # Exemplo: adiciona o nome do perfil

        return token

# Serializer para o modelo Usuario
class UsuarioSerializer(serializers.ModelSerializer):
    # Campos para facilitar a exibição no frontend (leitura)
    perfil = serializers.CharField(source='perfil.nome', read_only=True, allow_null=True)
    
    # --- CORREÇÃO 1: Usar SerializerMethodField para o nome completo ---
    # Isso garante que, se o nome/sobrenome estiverem vazios, o username será usado.
    nome_completo = serializers.SerializerMethodField()
    
    # --- CORREÇÃO 2: Adicionar o nome do supervisor para exibição ---
    # Isso envia o nome do líder para o frontend, em vez de apenas o ID.
    supervisor_nome = serializers.CharField(source='supervisor.get_full_name', read_only=True, allow_null=True)

    # Campo para receber o ID do perfil ao criar/editar (escrita)
    perfil_id = serializers.PrimaryKeyRelatedField(
        queryset=Perfil.objects.all(), source='perfil', write_only=True
    )

    class Meta:
        model = Usuario
        # --- CORREÇÃO 3: Ajustar a lista de campos ---
        # Adicionamos 'supervisor_nome' e garantimos que a lista esteja correta.
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'is_active', 'perfil_id',
            'nome_completo',      # Campo customizado para leitura
            'cpf', 'perfil',      # Campo de leitura para o nome do perfil
            'supervisor',         # Campo de escrita para o ID do supervisor
            'supervisor_nome',    # Campo de leitura para o nome do supervisor
            'valor_almoco', 'valor_passagem', 'chave_pix', 'nome_da_conta',
            'meta_comissao', 'desconto_boleto', 'desconto_inclusao_viabilidade',
            'desconto_instalacao_antecipada', 'adiantamento_cnpj', 'desconto_inss_fixo',
            'password'
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'username': {'required': True},
            'email': {'required': True},
            'perfil_id': {'required': True},
        }

    # --- CORREÇÃO 1 (continuação): Lógica para o nome_completo ---
    def get_nome_completo(self, obj):
        full_name = obj.get_full_name()
        # Retorna o nome completo se ele existir, senão, retorna o username
        return full_name if full_name.strip() else obj.username

    def create(self, validated_data):
        # Remove o campo password dos validated_data para processá-lo separadamente
        password = validated_data.pop('password', None)
        user = Usuario.objects.create(**validated_data)
        if password is not None:
            user.set_password(password) # Define a senha de forma segura
        user.save()
        return user

    def update(self, instance, validated_data):
        # Atualiza os campos do usuário
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password is not None:
            instance.set_password(password) # Atualiza a senha de forma segura

        instance.save()
        return instance


# Serializer para o modelo Perfil
class PerfilSerializer(serializers.ModelSerializer):
    class Meta:
        model = Perfil
        fields = ['id', 'nome'] # Ajuste os campos conforme necessário


# Crie uma classe manager para o serializer many=True
class PermissaoPerfilListSerializer(serializers.ListSerializer):
    # Este método create será chamado quando many=True for usado
    # validated_data é uma lista de dicionários, onde cada item foi validado pelo serializer filho (PermissaoPerfilSerializer)
    def create(self, validated_data):
        if not isinstance(validated_data, list):
             raise serializers.ValidationError("Os dados para criação devem ser uma lista.")

        permissoes = []
        for item_data in validated_data:
            # Cada item_data já é um dicionário validado pelo PermissaoPerfilSerializer
            # que inclui o 'perfil_id'

            # Buscamos a instância do Perfil usando o perfil_id validado
            perfil_id_valor = item_data.get('perfil_id') # Acessa o perfil_id do dicionário validado
            if not perfil_id_valor:
                # Esta validação já deve ter ocorrido no campo perfil_id, mas a mantemos
                raise serializers.ValidationError("O ID do perfil é obrigatório para cada permissão.")

            try:
                perfil_instance = Perfil.objects.get(id=perfil_id_valor)
            except Perfil.DoesNotExist:
                 raise serializers.ValidationError(f"Perfil com ID {perfil_id_valor} não encontrado.")

            # Cria a instância de PermissaoPerfil
            permissoes.append(
                PermissaoPerfil(
                    perfil=perfil_instance, # Atribui a instância do Perfil
                    recurso=item_data.get('recurso'), # Acessa outros campos validados
                    pode_ver=item_data.get('pode_ver', False),
                    pode_criar=item_data.get('pode_criar', False),
                    pode_editar=item_data.get('pode_editar', False),
                    pode_excluir=item_data.get('pode_excluir', False)
                )
            )

        # Salvar os objetos no banco de dados
        # Opção 1: Bulk create para performance
        # PermissaoPerfil.objects.bulk_create(permissoes)

        # Opção 2: Salvar um por um (usaremos esta por enquanto para evitar problemas com bulk_create)
        for permissao in permissoes:
            permissao.save()


        return permissoes # Retorna a lista de objetos criados


# Serializer para o modelo PermissaoPerfil
class PermissaoPerfilSerializer(serializers.ModelSerializer):
    # Definimos um campo para receber o ID do perfil na escrita (desserialização)
    perfil_id = serializers.IntegerField(write_only=True)

    # O campo 'perfil' padrão do modelo será usado para a serialização (leitura)
    # Tornamos este campo NÃO OBRIGATÓRIO para a entrada (desserialização)
    # Ele será populado no método create do serializer filho
    perfil = serializers.PrimaryKeyRelatedField(queryset=Perfil.objects.all(), required=False) # Mantenha required=False aqui


    class Meta:
        model = PermissaoPerfil
        # Inclua 'perfil_id' para escrita e 'perfil' para leitura
        # Certifique-se de que 'perfil' está nos fields para que o DRF tente mapeá-lo para o modelo
        fields = ['id', 'perfil_id', 'perfil', 'recurso', 'pode_ver', 'pode_criar', 'pode_editar', 'pode_excluir']
        # Não defina 'perfil' como read_only aqui

        # Remova a linha list_serializer_class = PermissaoPerfilListSerializer
        # Já que estamos criando manualmente na view, não precisamos que o serializer filho
        # use o ListSerializer para a criação em massa.
        # list_serializer_class = PermissaoPerfilListSerializer # REMOVER ESTA LINHA


    # O método create AQUI (no serializer filho) é necessário para validar e criar um único objeto
    # Este método será chamado quando .save() for chamado em uma ÚNICA instância do serializer
    # No nosso caso, a view cria as instâncias do modelo diretamente.
    # Podemos REMOVER este método create do serializer filho, pois a view não o chamará para criação em massa.
    # def create(self, validated_data):
    #     pass