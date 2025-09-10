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
    CicloPagamento  # Importa o novo modelo
)
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

class VendaSerializer(serializers.ModelSerializer):
    cliente = ClienteSerializer(read_only=True)
    plano = PlanoSerializer(read_only=True)
    forma_pagamento = FormaPagamentoSerializer(read_only=True)
    status_tratamento = StatusCRMSerializer(read_only=True)
    status_esteira = StatusCRMSerializer(read_only=True)
    status_comissionamento = StatusCRMSerializer(read_only=True)
    vendedor = UsuarioSerializer(read_only=True)
    status_final = serializers.SerializerMethodField()

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'cliente', 'plano', 'forma_pagamento',
            'status_tratamento', 'status_esteira', 'status_comissionamento',
            'status_final', 'data_criacao', 
            'forma_entrada', 'cpf_representante_legal', 'telefone1', 'telefone2', 
            'cep', 'logradouro', 'numero_residencia', 'complemento', 'bairro', 
            'cidade', 'estado', 'data_pedido', 'ordem_servico', 'data_agendamento',
            'periodo_agendamento'
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
    plano_id = serializers.IntegerField(write_only=True)
    forma_pagamento_id = serializers.IntegerField(write_only=True)
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
            'plano_id', 'forma_pagamento_id',
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
    class Meta:
        model = Venda
        fields = [
            'status_tratamento', 
            'status_esteira',
            'status_comissionamento',
            'ordem_servico',
            'data_agendamento',
            'periodo_agendamento',
            'data_pedido'
        ]
        extra_kwargs = {
            'status_tratamento': {'required': False},
            'status_esteira': {'required': False},
            'status_comissionamento': {'required': False},
            'ordem_servico': {'required': False},
            'data_agendamento': {'required': False},
            'periodo_agendamento': {'required': False},
            'data_pedido': {'read_only': True}
        }
        
class ImportacaoOsabSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportacaoOsab
        fields = '__all__'
        
class ImportacaoChurnSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportacaoChurn
        fields = '__all__'

# =======================================================================================
# NOVO SERIALIZER PARA O CICLO DE PAGAMENTO
# =======================================================================================
class CicloPagamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = CicloPagamento
        fields = '__all__'