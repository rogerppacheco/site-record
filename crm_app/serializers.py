from rest_framework import serializers
from .models import (
    Operadora,
    Plano,
    FormaPagamento,
    StatusCRM,
    MotivoPendencia,
    RegraComissao,
    Cliente,
    Venda,
    ImportacaoOsab,
    ImportacaoChurn,
    CicloPagamento,
    HistoricoAlteracaoVenda # Importa o novo modelo de histórico
)
from usuarios.models import Usuario # Adicionado para o VendaUpdateSerializer
from usuarios.serializers import UsuarioSerializer

class OperadoraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Operadora
        fields = '__all__'

class PlanoSerializer(serializers.ModelSerializer):
    operadora_nome = serializers.CharField(source='operadora.nome', read_only=True)
    class Meta:
        model = Plano
        fields = '__all__'

class FormaPagamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormaPagamento
        fields = ['id', 'nome', 'ativo', 'aplica_desconto']

class StatusCRMSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusCRM
        fields = '__all__'

class MotivoPendenciaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MotivoPendencia
        fields = '__all__'

class RegraComissaoSerializer(serializers.ModelSerializer):
    consultor_nome = serializers.CharField(source='consultor.get_full_name', read_only=True)
    plano_nome = serializers.CharField(source='plano.nome', read_only=True)

    class Meta:
        model = RegraComissao
        fields = '__all__'

class ClienteSerializer(serializers.ModelSerializer):
    vendas_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Cliente
        fields = ['id', 'cpf_cnpj', 'nome_razao_social', 'email', 'vendas_count']

# =======================================================================================
# NOVOS SERIALIZERS E AJUSTES PARA VENDA
# =======================================================================================

class HistoricoAlteracaoVendaSerializer(serializers.ModelSerializer):
    """
    Serializer para exibir o histórico de alterações de uma venda.
    """
    usuario = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = HistoricoAlteracaoVenda
        fields = ('usuario', 'data_alteracao', 'alteracoes')


class VendaSerializer(serializers.ModelSerializer):
    """
    Serializer de LEITURA para Vendas. Mantém sua estrutura original
    e adiciona o histórico de alterações.
    """
    cliente = ClienteSerializer(read_only=True)
    plano = PlanoSerializer(read_only=True)
    forma_pagamento = FormaPagamentoSerializer(read_only=True)
    status_tratamento = StatusCRMSerializer(read_only=True)
    status_esteira = StatusCRMSerializer(read_only=True)
    status_comissionamento = StatusCRMSerializer(read_only=True)
    vendedor = UsuarioSerializer(read_only=True)
    status_final = serializers.SerializerMethodField()
    historico_alteracoes = HistoricoAlteracaoVendaSerializer(many=True, read_only=True) # Adicionado

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'cliente', 'plano', 'forma_pagamento',
            'status_tratamento', 'status_esteira', 'status_comissionamento',
            'status_final', 'data_criacao', 
            'forma_entrada', 'cpf_representante_legal', 'telefone1', 'telefone2', 
            'cep', 'logradouro', 'numero_residencia', 'complemento', 'bairro', 
            'cidade', 'estado', 'data_pedido', 'ordem_servico', 'data_agendamento',
            'periodo_agendamento',
            'historico_alteracoes' # Adicionado
        ]
    
    def get_status_final(self, obj):
        if obj.status_comissionamento:
            return obj.status_comissionamento.nome
        if obj.status_esteira:
            return obj.status_esteira.nome
        if obj.status_tratamento:
            return obj.status_tratamento.nome
        return "N/A"

class VendaCreateSerializer(serializers.ModelSerializer):
    """
    Seu Serializer de CRIAÇÃO de Vendas. (Inalterado)
    """
    # Renomeado de plano_id para plano para corresponder ao modelo
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all())
    # Renomeado de forma_pagamento_id para forma_pagamento
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all())
    cliente_cpf_cnpj = serializers.CharField(write_only=True, max_length=18)
    cliente_nome_razao_social = serializers.CharField(write_only=True, max_length=255)
    cliente_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    telefone1 = serializers.CharField(max_length=20, required=False, allow_blank=True)
    telefone2 = serializers.CharField(max_length=20, required=False, allow_blank=True)
    cpf_representante_legal = serializers.CharField(max_length=14, required=False, allow_blank=True)

    class Meta:
        model = Venda
        fields = [
            'cliente_cpf_cnpj', 'cliente_nome_razao_social', 'cliente_email',
            'plano', 'forma_pagamento',
            'cep', 'logradouro', 'numero_residencia', 'complemento', 'bairro',
            'cidade', 'estado',
            'forma_entrada', 'telefone1', 'telefone2', 'cpf_representante_legal'
        ]

    def validate(self, data):
        for key, value in data.items():
            if isinstance(value, str) and key != 'cliente_email':
                data[key] = value.upper()
        return data

class VendaUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer de ATUALIZAÇÃO de Vendas. Permite a edição de todos os campos.
    """
    vendedor = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all(), required=False)
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all(), required=False)
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all(), required=False)
    status_tratamento = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Tratamento'), required=False, allow_null=True)
    status_esteira = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Esteira'), required=False, allow_null=True)
    status_comissionamento = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Comissionamento'), required=False, allow_null=True)

    class Meta:
        model = Venda
        # Inclui todos os campos do modelo para permitir a edição
        fields = '__all__'
        # Campos que não devem ser editados diretamente por esta via
        read_only_fields = ('data_criacao', 'cliente')

# =======================================================================================
# SERIALIZERS DE IMPORTAÇÃO (Inalterados)
# =======================================================================================
class ImportacaoOsabSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportacaoOsab
        fields = '__all__'
        
class ImportacaoChurnSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportacaoChurn
        fields = '__all__'

class CicloPagamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CicloPagamento
        fields = '__all__'