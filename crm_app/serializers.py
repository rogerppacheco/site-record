from rest_framework import serializers
from django.db import transaction
import re
from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia,
    RegraComissao, Cliente, Venda, ImportacaoOsab, ImportacaoChurn,
    CicloPagamento, HistoricoAlteracaoVenda, Campanha,
    ComissaoOperadora, Comunicado, LancamentoFinanceiro,
    # Assumindo que RegraCampanha foi adicionada em .models conforme instruído
    RegraCampanha 
)
from .models import GrupoDisparo 
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer


# --- SERIALIZER PARA REGRAS DE CAMPANHA (FAIXAS) ---
class RegraCampanhaSerializer(serializers.ModelSerializer):
    """Serializer para as faixas de premiação dentro de uma Campanha."""
    class Meta:
        model = RegraCampanha
        fields = ('id', 'meta', 'valor_premio')


# --- SERIALIZERS BÁSICOS ---

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

# --- CAMPANHA SERIALIZER (CORRIGIDO PARA SUPORTE ÀS FAIXAS) ---
class CampanhaSerializer(serializers.ModelSerializer):
    # Campo aninhado: indica que esperamos uma lista (many=True) de objetos RegraCampanha
    regras_meta = RegraCampanhaSerializer(many=True, required=False) 
    
    # Campo M2M (Many to Many)
    planos_elegiveis = serializers.PrimaryKeyRelatedField(many=True, queryset=Plano.objects.all(), required=False)
    formas_pagamento_elegiveis = serializers.PrimaryKeyRelatedField(many=True, queryset=FormaPagamento.objects.all(), required=False)

    class Meta:
        model = Campanha
        fields = ('id', 'nome', 'data_inicio', 'data_fim', 
                  'meta_vendas', 'valor_premio', 'tipo_meta', 
                  'canal_alvo', 'planos_elegiveis', 'formas_pagamento_elegiveis', 
                  'regras', 'ativo', 'data_criacao', 
                  'regras_meta') # <-- Incluído o campo aninhado

    def create(self, validated_data):
        # 1. Pop a lista de faixas do dicionário principal
        regras_data = validated_data.pop('regras_meta', [])
        
        # 2. Pop M2M fields para salvar depois
        planos_data = validated_data.pop('planos_elegiveis', [])
        pagamentos_data = validated_data.pop('formas_pagamento_elegiveis', [])
        
        # 3. Cria o objeto Campanha principal
        with transaction.atomic():
            campanha = Campanha.objects.create(**validated_data)
            
            # 4. Cria os objetos RegraCampanha (Faixas)
            for regra_data in regras_data:
                RegraCampanha.objects.create(campanha=campanha, **regra_data)
                
            # 5. Salva os relacionamentos M2M
            campanha.planos_elegiveis.set(planos_data)
            campanha.formas_pagamento_elegiveis.set(pagamentos_data)
        
        return campanha

    def update(self, instance, validated_data):
        # 1. Pop a lista de faixas para atualização
        regras_data = validated_data.pop('regras_meta', None)
        
        # 2. Pop M2M fields
        planos_data = validated_data.pop('planos_elegiveis', None)
        pagamentos_data = validated_data.pop('formas_pagamento_elegiveis', None)

        with transaction.atomic():
            # 3. Atualiza Campanha principal (campos simples)
            for key, value in validated_data.items():
                setattr(instance, key, value)
            
            instance.save()
            
            # 4. Atualiza os relacionamentos M2M
            if planos_data is not None:
                instance.planos_elegiveis.set(planos_data)
            if pagamentos_data is not None:
                instance.formas_pagamento_elegiveis.set(pagamentos_data)

            # 5. Atualiza/Substitui Faixas de Premiação
            if regras_data is not None:
                # Exclui todas as regras antigas desta campanha
                instance.regras_meta.all().delete()
                
                # Cria as novas regras enviadas pelo frontend
                for regra_data in regras_data:
                    RegraCampanha.objects.create(campanha=instance, **regra_data)

        return instance
# --- FIM CAMPANHA SERIALIZER ---


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
    telefone1 = serializers.SerializerMethodField()
    telefone2 = serializers.SerializerMethodField()
    nome_mae = serializers.SerializerMethodField()
    data_nascimento = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = [
            'id', 'cpf_cnpj', 'nome_razao_social', 'email', 'vendas_count',
            'telefone1', 'telefone2', 'nome_mae', 'data_nascimento'
        ]

    def get_last_sale(self, obj):
        if not hasattr(obj, '_last_sale_cache'):
            obj._last_sale_cache = obj.vendas.filter(ativo=True).order_by('-data_criacao').first()
        return obj._last_sale_cache

    def get_telefone1(self, obj):
        last = self.get_last_sale(obj)
        return last.telefone1 if last and last.telefone1 else ""

    def get_telefone2(self, obj):
        last = self.get_last_sale(obj)
        return last.telefone2 if last and last.telefone2 else ""

    def get_nome_mae(self, obj):
        last = self.get_last_sale(obj)
        return last.nome_mae if last and last.nome_mae else ""

    def get_data_nascimento(self, obj):
        last = self.get_last_sale(obj)
        return last.data_nascimento if last and last.data_nascimento else None

class HistoricoAlteracaoVendaSerializer(serializers.ModelSerializer):
    usuario = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = HistoricoAlteracaoVenda
        fields = ('usuario', 'data_alteracao', 'alteracoes')

# --- SERIALIZERS DE VENDA ---

class VendaSerializer(serializers.ModelSerializer):
    # Campos aninhados (Objetos)
    cliente = ClienteSerializer(read_only=True)
    vendedor_detalhes = UsuarioSerializer(source='vendedor', read_only=True)
    
    # Campos Achatados (Legacy Support para outras telas)
    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social', read_only=True)
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', read_only=True)
    cliente_email = serializers.CharField(source='cliente.email', read_only=True)
    vendedor_nome = serializers.ReadOnlyField(source='vendedor.username')
    
    # Campos de Escrita
    cliente_id = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.all(), source='cliente', write_only=False)
    
    plano = PlanoSerializer(read_only=True)
    forma_pagamento = FormaPagamentoSerializer(read_only=True)
    status_tratamento = StatusCRMSerializer(read_only=True)
    status_esteira = StatusCRMSerializer(read_only=True)
    status_comissionamento = StatusCRMSerializer(read_only=True)
    motivo_pendencia = MotivoPendenciaSerializer(read_only=True)
    
    status_final = serializers.SerializerMethodField()
    historico_alteracoes = HistoricoAlteracaoVendaSerializer(many=True, read_only=True)
    alterado_por = serializers.SerializerMethodField()
    auditor_atual_nome = serializers.SerializerMethodField()
    auditor_atual_id = serializers.SerializerMethodField()

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'vendedor_nome', 'vendedor_detalhes', 
            'cliente', 'cliente_id', 
            'cliente_nome_razao_social', 'cliente_cpf_cnpj', 'cliente_email', # Restaurados
            'plano', 'forma_pagamento', 'status_tratamento', 'status_esteira', 'status_comissionamento',
            'status_final', 'data_criacao', 'forma_entrada', 'cpf_representante_legal', 'nome_representante_legal',
            'nome_mae', 'data_nascimento', 'telefone1', 'telefone2', 'cep', 'logradouro', 'numero_residencia',
            'complemento', 'bairro', 'cidade', 'estado', 'data_pedido', 'ordem_servico', 'data_agendamento',
            'periodo_agendamento', 'data_instalacao', 'antecipou_instalacao', 'motivo_pendencia',
            'ponto_referencia', 'observacoes', 'historico_alteracoes', 'data_pagamento', 'valor_pago', 'alterado_por',
            'auditor_atual', 'auditor_atual_nome', 'auditor_atual_id'
        ]

    def get_auditor_atual_nome(self, obj):
        return obj.auditor_atual.get_full_name() or obj.auditor_atual.username if obj.auditor_atual else None
    def get_auditor_atual_id(self, obj):
        return obj.auditor_atual.id if obj.auditor_atual else None
    def get_status_final(self, obj):
        if obj.status_comissionamento: return obj.status_comissionamento.nome
        if obj.status_esteira: return obj.status_esteira.nome
        if obj.status_tratamento: return obj.status_tratamento.nome
        return "N/A"
    def get_alterado_por(self, obj):
        h = obj.historico_alteracoes.order_by('-data_alteracao').first()
        return h.usuario.username if h and h.usuario else (obj.vendedor.username if obj.vendedor else "Sistema")

class VendaDetailSerializer(serializers.ModelSerializer):
    # Objeto completo para garantir edição
    cliente = ClienteSerializer(read_only=True)
    
    # Campos achatados para compatibilidade
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', read_only=True)
    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social')
    cliente_email = serializers.CharField(source='cliente.email', read_only=True)

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'cliente', 'plano', 'forma_pagamento',
            'status_tratamento', 'status_esteira', 'status_comissionamento', 'motivo_pendencia',
            'cliente_cpf_cnpj', 'cliente_nome_razao_social', 'cliente_email',
            'nome_mae', 'data_nascimento', 'telefone1', 'telefone2',
            'cep', 'logradouro', 'numero_residencia', 'complemento', 'bairro', 'cidade', 'estado',
            'ponto_referencia', 'observacoes', 'ordem_servico', 'data_pedido',
            'data_agendamento', 'periodo_agendamento', 'data_instalacao', 'antecipou_instalacao',
            'data_pagamento', 'valor_pago', 'cpf_representante_legal', 'nome_representante_legal', 'forma_entrada'
        ]

class VendaCreateSerializer(serializers.ModelSerializer):
    # ALTERAÇÃO: Campos de Plano e Pagamento tornados opcionais para criação flexível
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all(), required=False, allow_null=True)
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all(), required=False, allow_null=True)
    
    cliente_cpf_cnpj = serializers.CharField(write_only=True, max_length=18)
    cliente_nome_razao_social = serializers.CharField(write_only=True, max_length=255)
    cliente_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    
    telefone1 = serializers.CharField(max_length=20, required=True)
    telefone2 = serializers.CharField(max_length=20, required=True)
    
    # ALTERAÇÃO: Campos de endereço agora opcionais no Serializer
    cep = serializers.CharField(required=False, allow_blank=True)
    logradouro = serializers.CharField(required=False, allow_blank=True)
    numero_residencia = serializers.CharField(required=False, allow_blank=True)
    bairro = serializers.CharField(required=False, allow_blank=True)
    cidade = serializers.CharField(required=False, allow_blank=True)
    estado = serializers.CharField(required=False, allow_blank=True)
    ponto_referencia = serializers.CharField(max_length=255, required=False, allow_blank=True)
    
    cpf_representante_legal = serializers.CharField(max_length=14, required=False, allow_blank=True)
    nome_representante_legal = serializers.CharField(max_length=255, required=False, allow_blank=True)
    nome_mae = serializers.CharField(max_length=255, required=False, allow_blank=True)
    data_nascimento = serializers.DateField(required=False, allow_null=True)
    observacoes = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Venda
        fields = [
            'cliente_cpf_cnpj', 'cliente_nome_razao_social', 'cliente_email',
            'nome_mae', 'data_nascimento', 'forma_pagamento', 'plano', 'cep',
            'logradouro', 'numero_residencia', 'complemento', 'bairro', 'cidade', 'estado',
            'forma_entrada', 'telefone1', 'telefone2', 'cpf_representante_legal',
            'nome_representante_legal', 'ponto_referencia', 'observacoes'
        ]

    def validate(self, data):
        for key, value in data.items():
            if isinstance(value, str) and key not in ['cliente_email', 'observacoes']:
                data[key] = value.upper()
        return data

class VendaUpdateSerializer(serializers.ModelSerializer):
    cliente = serializers.DictField(required=False, write_only=True)

    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social', required=False)
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', required=False)
    cliente_email = serializers.EmailField(source='cliente.email', required=False)

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
        read_only_fields = ('data_criacao', 'forma_entrada')

    def validate(self, data):
        for key, value in data.items():
            if isinstance(value, str) and key not in ['cliente', 'cliente_email', 'observacoes']:
                data[key] = value.upper()
        
        if 'cliente' in data and isinstance(data['cliente'], dict):
            if 'nome_razao_social' in data['cliente']:
                val = data['cliente']['nome_razao_social']
                data['cliente']['nome_razao_social'] = val.upper() if isinstance(val, str) else str(val).upper()
        
        return data

    def _get_field_repr(self, instance_value):
        if hasattr(instance_value, 'nome'): return instance_value.nome
        return str(instance_value)

    def update(self, instance, validated_data):
        request = self.context.get('request')
        user = request.user if request else None

        cliente_data = validated_data.pop('cliente', {})
        if cliente_data:
            cliente_instance = instance.cliente
            mudou = False
            
            novo_nome = cliente_data.get('nome_razao_social')
            if novo_nome and novo_nome.strip() and novo_nome != cliente_instance.nome_razao_social:
                cliente_instance.nome_razao_social = novo_nome.upper()
                mudou = True
            
            novo_cpf = cliente_data.get('cpf_cnpj')
            if novo_cpf and novo_cpf.strip() and novo_cpf != cliente_instance.cpf_cnpj:
                cliente_instance.cpf_cnpj = novo_cpf
                mudou = True
                
            novo_email = cliente_data.get('email')
            if novo_email is not None and novo_email != cliente_instance.email:
                if novo_email.strip() != "":
                    cliente_instance.email = novo_email
                    mudou = True

            if mudou:
                cliente_instance.save()

        alteracoes = {}
        campos_status = ['status_tratamento', 'status_esteira', 'status_comissionamento']
        for campo in campos_status:
            novo = validated_data.get(campo)
            if novo:
                antigo = getattr(instance, campo)
                if novo != antigo:
                    alteracoes[campo] = {'de': self._get_field_repr(antigo) if antigo else "Nenhum", 'para': self._get_field_repr(novo)}

        novo_tratamento = validated_data.get('status_tratamento', instance.status_tratamento)
        if novo_tratamento and novo_tratamento.nome.lower() == 'cadastrada' and not instance.status_esteira:
            try:
                st_ini = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
                validated_data['status_esteira'] = st_ini
            except: pass

        novo_esteira = validated_data.get('status_esteira', instance.status_esteira)
        if novo_esteira and novo_esteira.nome.lower() == 'instalada' and not instance.status_comissionamento:
            try:
                st_com = StatusCRM.objects.get(nome__iexact="PENDENTE", tipo__iexact="Comissionamento")
                validated_data['status_comissionamento'] = st_com
            except: pass

        updated_instance = super().update(instance, validated_data)

        if alteracoes and user:
            HistoricoAlteracaoVenda.objects.create(venda=updated_instance, usuario=user, alteracoes=alteracoes)

        return updated_instance

    def validate_telefone(self, value, field_name):
        if not value: return value
        pattern = re.compile(r'^\(?([1-9]{2})\)? ?(9[1-9][0-9]{3}|[2-5][0-9]{3})\-?[0-9]{4}$')
        if not pattern.match(str(value)):
            pass
        return value
    def validate_telefone1(self, value): return self.validate_telefone(value, "Telefone 1")
    def validate_telefone2(self, value): return self.validate_telefone(value, "Telefone 2")

class ImportacaoOsabSerializer(serializers.ModelSerializer):
    class Meta: model = ImportacaoOsab; fields = '__all__'
class ImportacaoChurnSerializer(serializers.ModelSerializer):
    class Meta: model = ImportacaoChurn; fields = '__all__'
class CicloPagamentoSerializer(serializers.ModelSerializer):
    class Meta: model = CicloPagamento; fields = '__all__'

class ComissaoOperadoraSerializer(serializers.ModelSerializer):
    plano_nome = serializers.ReadOnlyField(source='plano.nome')
    class Meta:
        model = ComissaoOperadora
        fields = '__all__'

class ComunicadoSerializer(serializers.ModelSerializer):
    criado_por_nome = serializers.ReadOnlyField(source='criado_por.username')
    class Meta:
        model = Comunicado
        fields = '__all__'
        read_only_fields = ['criado_por', 'criado_em']
class GrupoDisparoSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrupoDisparo
        fields = '__all__'
class LancamentoFinanceiroSerializer(serializers.ModelSerializer):
    usuario_nome = serializers.ReadOnlyField(source='usuario.nome_completo')
    criado_por_nome = serializers.ReadOnlyField(source='criado_por.username')

    class Meta:
        model = LancamentoFinanceiro
        fields = '__all__'