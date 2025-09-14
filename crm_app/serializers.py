# crm_app/serializers.py

from rest_framework import serializers
import re
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
    HistoricoAlteracaoVenda
)
from usuarios.models import Usuario
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

class HistoricoAlteracaoVendaSerializer(serializers.ModelSerializer):
    usuario = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = HistoricoAlteracaoVenda
        fields = ('usuario', 'data_alteracao', 'alteracoes')


class VendaSerializer(serializers.ModelSerializer):
    cliente = ClienteSerializer(read_only=True)
    plano = PlanoSerializer(read_only=True)
    forma_pagamento = FormaPagamentoSerializer(read_only=True)
    status_tratamento = StatusCRMSerializer(read_only=True)
    status_esteira = StatusCRMSerializer(read_only=True)
    status_comissionamento = StatusCRMSerializer(read_only=True)
    vendedor = UsuarioSerializer(read_only=True)
    motivo_pendencia = MotivoPendenciaSerializer(read_only=True)
    status_final = serializers.SerializerMethodField()
    historico_alteracoes = HistoricoAlteracaoVendaSerializer(many=True, read_only=True)
    alterado_por = serializers.SerializerMethodField()

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'cliente', 'plano', 'forma_pagamento',
            'status_tratamento', 'status_esteira', 'status_comissionamento',
            'status_final', 'data_criacao',
            'forma_entrada', 'cpf_representante_legal', 'telefone1', 'telefone2',
            'cep', 'logradouro', 'numero_residencia', 'complemento', 'bairro',
            'cidade', 'estado', 'data_pedido', 'ordem_servico', 'data_agendamento',
            'periodo_agendamento', 'data_instalacao', 'antecipou_instalacao', 'motivo_pendencia',
            'ponto_referencia', 'observacoes',
            'historico_alteracoes',
            'data_pagamento', 'valor_pago', 'alterado_por'
        ]

    def get_status_final(self, obj):
        if obj.status_comissionamento: return obj.status_comissionamento.nome
        if obj.status_esteira: return obj.status_esteira.nome
        if obj.status_tratamento: return obj.status_tratamento.nome
        return "N/A"

    def get_alterado_por(self, obj):
        ultimo_historico = obj.historico_alteracoes.order_by('-data_alteracao').first()
        if ultimo_historico and ultimo_historico.usuario:
            return ultimo_historico.usuario.username
        # Fallback para o vendedor original se não houver histórico
        return obj.vendedor.username if obj.vendedor else "Sistema"

class VendaDetailSerializer(serializers.ModelSerializer):
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', read_only=True)
    # AGORA O NOME DO CLIENTE É EDITÁVEL, ENTÃO USAMOS O CAMPO PADRÃO
    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social')

    class Meta:
        model = Venda
        fields = [
            'id',
            'vendedor',
            'plano',
            'forma_pagamento',
            'status_tratamento',
            'status_esteira',
            'status_comissionamento',
            'motivo_pendencia',
            'cliente_cpf_cnpj',
            'cliente_nome_razao_social', # Campo adicionado
            'telefone1',
            'telefone2',
            'cep',
            'logradouro',
            'numero_residencia',
            'complemento',
            'bairro',
            'cidade',
            'estado',
            'ponto_referencia',
            'observacoes',
            'ordem_servico',
            'data_pedido',
            'data_agendamento',
            'periodo_agendamento',
            'data_instalacao',
            'antecipou_instalacao',
            'data_pagamento',
            'valor_pago'
        ]

class VendaCreateSerializer(serializers.ModelSerializer):
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all())
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all())
    cliente_cpf_cnpj = serializers.CharField(write_only=True, max_length=18)
    cliente_nome_razao_social = serializers.CharField(write_only=True, max_length=255)
    cliente_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    telefone1 = serializers.CharField(max_length=20, required=False, allow_blank=True)
    telefone2 = serializers.CharField(max_length=20, required=False, allow_blank=True)
    cpf_representante_legal = serializers.CharField(max_length=14, required=False, allow_blank=True)
    ponto_referencia = serializers.CharField(max_length=255, required=True)
    observacoes = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Venda
        fields = [
            'cliente_cpf_cnpj', 'cliente_nome_razao_social', 'cliente_email',
            'forma_pagamento', 'plano', 'cep', 'logradouro', 'numero_residencia',
            'complemento', 'bairro', 'cidade', 'estado', 'forma_entrada',
            'telefone1', 'telefone2', 'cpf_representante_legal',
            'ponto_referencia', 'observacoes'
        ]

    def validate(self, data):
        for key, value in data.items():
            if isinstance(value, str) and key not in ['cliente_email', 'observacoes']:
                data[key] = value.upper()
        return data

class VendaUpdateSerializer(serializers.ModelSerializer):
    # Campo para receber o novo nome do cliente
    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social', required=False)

    vendedor = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all(), required=False)
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all(), required=False)
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all(), required=False)
    status_tratamento = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Tratamento'), required=False, allow_null=True)
    status_esteira = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Esteira'), required=False, allow_null=True)
    status_comissionamento = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Comissionamento'), required=False, allow_null=True)
    motivo_pendencia = serializers.PrimaryKeyRelatedField(queryset=MotivoPendencia.objects.all(), required=False, allow_null=True)

    class Meta:
        model = Venda
        fields = '__all__'
        read_only_fields = ('data_criacao', 'cliente')

    def _get_field_repr(self, instance_value):
        if hasattr(instance_value, 'nome'):
            return instance_value.nome
        return str(instance_value)

    def update(self, instance, validated_data):
        # Pega o usuário da requisição (passado pela view)
        request = self.context.get('request')
        user = request.user if request else None

        # Dicionário para registrar alterações
        alteracoes = {}
        
        # Campos de status para monitorar
        campos_status = ['status_tratamento', 'status_esteira', 'status_comissionamento']
        for campo in campos_status:
            novo_valor = validated_data.get(campo)
            valor_antigo = getattr(instance, campo)
            if novo_valor != valor_antigo:
                alteracoes[campo] = {
                    'de': self._get_field_repr(valor_antigo) if valor_antigo else "Nenhum",
                    'para': self._get_field_repr(novo_valor) if novo_valor else "Nenhum"
                }

        # Lógica para editar o nome do cliente
        if 'cliente' in validated_data and 'nome_razao_social' in validated_data['cliente']:
            novo_nome_cliente = validated_data['cliente']['nome_razao_social']
            cliente_instance = instance.cliente
            if cliente_instance.nome_razao_social != novo_nome_cliente:
                alteracoes['nome_cliente'] = {
                    'de': cliente_instance.nome_razao_social,
                    'para': novo_nome_cliente
                }
                cliente_instance.nome_razao_social = novo_nome_cliente
                cliente_instance.save()
            # Remove o dado aninhado para não interferir no update principal
            validated_data.pop('cliente')

        # Lógica de automação de status (existente)
        novo_status_tratamento = validated_data.get('status_tratamento', instance.status_tratamento)
        if novo_status_tratamento and novo_status_tratamento.nome.lower() == 'cadastrada' and not instance.status_esteira:
            try:
                status_inicial_esteira = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
                validated_data['status_esteira'] = status_inicial_esteira
            except StatusCRM.DoesNotExist:
                print("ATENÇÃO: O status inicial 'AGENDADO' para a Esteira não foi encontrado.")

        novo_status_esteira = validated_data.get('status_esteira', instance.status_esteira)
        if novo_status_esteira and novo_status_esteira.nome.lower() == 'instalada' and not instance.status_comissionamento:
            try:
                status_inicial_comissao = StatusCRM.objects.get(nome__iexact="PENDENTE", tipo__iexact="Comissionamento")
                validated_data['status_comissionamento'] = status_inicial_comissao
            except StatusCRM.DoesNotExist:
                print("ATENÇÃO: O status inicial 'PENDENTE' para o Comissionamento não foi encontrado.")

        # Executa a atualização da venda
        updated_instance = super().update(instance, validated_data)

        # Se houveram alterações de status, cria um registro no histórico
        if alteracoes and user:
            HistoricoAlteracaoVenda.objects.create(
                venda=updated_instance,
                usuario=user,
                alteracoes=alteracoes
            )

        return updated_instance

    def validate_telefone(self, value, field_name):
        if not value: return value
        pattern = re.compile(r'^\(?([1-9]{2})\)? ?(9[1-9][0-9]{3}|[2-5][0-9]{3})\-?[0-9]{4}$')
        if not pattern.match(str(value)):
            raise serializers.ValidationError(f"O formato do campo '{field_name}' é inválido.")
        return value

    def validate_telefone1(self, value):
        return self.validate_telefone(value, "Telefone 1")

    def validate_telefone2(self, value):
        return self.validate_telefone(value, "Telefone 2")


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