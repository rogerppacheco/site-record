
from rest_framework import serializers
from django.db import transaction
import re
from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia,
    RegraComissao, Cliente, Venda, ImportacaoOsab, ImportacaoChurn,
    CicloPagamento, HistoricoAlteracaoVenda, Campanha,
    ComissaoOperadora, Comunicado, LancamentoFinanceiro,
    RegraCampanha, FaturaM10, GrupoDisparo
)
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

# --- CAMPANHA SERIALIZER ---
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
                  'regras_meta')

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
    
    def validate_nome(self, value):
        # Verifica se já existe um motivo com o mesmo nome (case-insensitive)
        # Exclui a instância atual se estiver editando
        queryset = MotivoPendencia.objects.filter(nome__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        
        if queryset.exists():
            raise serializers.ValidationError("Já existe um motivo de pendência cadastrado com este nome.")
        return value

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
    """
    Serializer otimizado para LISTAGEM (evita N+1 queries)
    Carrega APENAS campos achatados, sem serializers aninhados complexos
    """
    # Campos Achatados (Legacy Support para outras telas)
    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social', read_only=True)
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', read_only=True)
    cliente_email = serializers.CharField(source='cliente.email', read_only=True)
    vendedor_nome = serializers.ReadOnlyField(source='vendedor.username')
    
    # Status como SimpleFields (sem serializers aninhados)
    status_tratamento_nome = serializers.CharField(source='status_tratamento.nome', read_only=True)
    status_esteira_nome = serializers.CharField(source='status_esteira.nome', read_only=True)
    status_comissionamento_nome = serializers.CharField(source='status_comissionamento.nome', read_only=True)
    
    plano_nome = serializers.CharField(source='plano.nome', read_only=True)
    forma_pagamento_nome = serializers.CharField(source='forma_pagamento.nome', read_only=True)
    motivo_pendencia_nome = serializers.CharField(source='motivo_pendencia.nome', read_only=True, allow_null=True)
    
    # Auditoria
    nome_editor = serializers.SerializerMethodField()
    auditor_atual_nome = serializers.SerializerMethodField()
    auditor_atual_id = serializers.SerializerMethodField()
    
    # Campos de Escrita
    cliente_id = serializers.PrimaryKeyRelatedField(queryset=Cliente.objects.all(), source='cliente', write_only=False)

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'vendedor_nome', 'cliente_id',
            'cliente_nome_razao_social', 'cliente_cpf_cnpj', 'cliente_email',
            'plano_nome', 'forma_pagamento_nome',
            'status_tratamento', 'status_tratamento_nome',
            'status_esteira', 'status_esteira_nome',
            'status_comissionamento', 'status_comissionamento_nome',
            'motivo_pendencia', 'motivo_pendencia_nome',
            'data_criacao', 'forma_entrada', 'cpf_representante_legal', 'nome_representante_legal',
            'nome_mae', 'data_nascimento', 'telefone1', 'telefone2', 'cep', 'logradouro', 'numero_residencia',
            'complemento', 'bairro', 'cidade', 'estado', 'data_abertura', 'ordem_servico', 'data_agendamento',
            'periodo_agendamento', 'data_instalacao', 'antecipou_instalacao',
            'ponto_referencia', 'observacoes', 'data_pagamento', 'valor_pago',
            'auditor_atual', 'auditor_atual_nome', 'auditor_atual_id',
            'nome_editor', 'data_ultima_alteracao'
        ]

    def get_auditor_atual_nome(self, obj):
        return obj.auditor_atual.get_full_name() or obj.auditor_atual.username if obj.auditor_atual else None
    
    def get_auditor_atual_id(self, obj):
        return obj.auditor_atual.id if obj.auditor_atual else None
    
    def get_nome_editor(self, obj):
        return obj.editado_por.username if obj.editado_por else None

class VendaDetailSerializer(serializers.ModelSerializer):
    """
    Serializer COMPLETO para visualizar detalhes (retrieve/PUT)
    Carrega serializers aninhados completos
    """
    # Objetos completos (apenas em detail view, não em list)
    cliente = ClienteSerializer(read_only=True)
    vendedor_detalhes = UsuarioSerializer(source='vendedor', read_only=True)
    plano = PlanoSerializer(read_only=True)
    forma_pagamento = FormaPagamentoSerializer(read_only=True)
    status_tratamento = StatusCRMSerializer(read_only=True)
    status_esteira = StatusCRMSerializer(read_only=True)
    status_comissionamento = StatusCRMSerializer(read_only=True)
    motivo_pendencia = MotivoPendenciaSerializer(read_only=True)
    
    # Campos Achatados para compatibilidade
    cliente_cpf_cnpj = serializers.CharField(source='cliente.cpf_cnpj', read_only=True)
    cliente_nome_razao_social = serializers.CharField(source='cliente.nome_razao_social')
    cliente_email = serializers.CharField(source='cliente.email', read_only=True)
    
    # Histórico (apenas em detail, NÃO em list)
    historico_alteracoes = HistoricoAlteracaoVendaSerializer(many=True, read_only=True)

    class Meta:
        model = Venda
        fields = [
            'id', 'vendedor', 'vendedor_detalhes', 'cliente', 
            'cliente_cpf_cnpj', 'cliente_nome_razao_social', 'cliente_email',
            'plano', 'forma_pagamento', 'status_tratamento', 'status_esteira', 
            'status_comissionamento', 'motivo_pendencia',
            'nome_mae', 'data_nascimento', 'telefone1', 'telefone2',
            'cep', 'logradouro', 'numero_residencia', 'complemento', 'bairro', 'cidade', 'estado',
            'ponto_referencia', 'observacoes', 'ordem_servico', 'data_abertura',
            'data_agendamento', 'periodo_agendamento', 'data_instalacao', 'antecipou_instalacao',
            'data_pagamento', 'valor_pago', 'cpf_representante_legal', 'nome_representante_legal', 
            'forma_entrada', 'historico_alteracoes', 'data_criacao', 'data_ultima_alteracao'
        ]

class VendaCreateSerializer(serializers.ModelSerializer):
    # Campos de Plano e Pagamento opcionais para criação flexível
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all(), required=False, allow_null=True)
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all(), required=False, allow_null=True)
    
    cliente_cpf_cnpj = serializers.CharField(write_only=True, max_length=18)
    cliente_nome_razao_social = serializers.CharField(write_only=True, max_length=255)
    cliente_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    
    telefone1 = serializers.CharField(max_length=20, required=True)
    telefone2 = serializers.CharField(max_length=20, required=True)
    
    # Campos de endereço opcionais no Serializer
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
    # Campos "Manuais" para evitar conflito de nesting e validação
    cliente_nome_razao_social = serializers.CharField(required=False, allow_null=True, allow_blank=True, write_only=True)
    cliente_cpf_cnpj = serializers.CharField(required=False, allow_null=True, allow_blank=True, write_only=True)
    cliente_email = serializers.EmailField(required=False, allow_null=True, allow_blank=True, write_only=True)

    vendedor = serializers.PrimaryKeyRelatedField(queryset=Usuario.objects.all(), required=False)
    
    # --- CORREÇÃO: allow_null=True em todos os campos que podem ser nulos no rascunho ---
    plano = serializers.PrimaryKeyRelatedField(queryset=Plano.objects.all(), required=False, allow_null=True)
    forma_pagamento = serializers.PrimaryKeyRelatedField(queryset=FormaPagamento.objects.all(), required=False, allow_null=True)
    status_tratamento = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Tratamento'), required=False, allow_null=True)
    status_esteira = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Esteira'), required=False, allow_null=True)
    status_comissionamento = serializers.PrimaryKeyRelatedField(queryset=StatusCRM.objects.filter(tipo='Comissionamento'), required=False, allow_null=True)
    motivo_pendencia = serializers.PrimaryKeyRelatedField(queryset=MotivoPendencia.objects.all().order_by('nome'), required=False, allow_null=True)
    # ------------------------------------------------------------------------------------

    class Meta:
        model = Venda
        fields = '__all__'
        read_only_fields = ('data_criacao', 'forma_entrada', 'cliente')

    def validate(self, data):
        # Converte para maiúsculo, exceto email e obs
        for key, value in data.items():
            if value is None: continue
            if isinstance(value, str) and key not in ['cliente_email', 'observacoes']:
                data[key] = value.upper()
        return data

    def _get_field_repr(self, instance_value):
        if hasattr(instance_value, 'nome'): return instance_value.nome
        return str(instance_value)

    def update(self, instance, validated_data):
        request = self.context.get('request')
        user = request.user if request else None

        # 1. Atualização Manual dos Dados do Cliente
        cliente_instance = instance.cliente
        mudou_cliente = False
        
        # Pega os valores "write_only" validados
        novo_nome = validated_data.pop('cliente_nome_razao_social', None)
        novo_cpf = validated_data.pop('cliente_cpf_cnpj', None)
        novo_email = validated_data.pop('cliente_email', None)

        if novo_nome and novo_nome.strip() and novo_nome != cliente_instance.nome_razao_social:
            cliente_instance.nome_razao_social = novo_nome.upper()
            mudou_cliente = True
        
        if novo_cpf and novo_cpf.strip() and novo_cpf != cliente_instance.cpf_cnpj:
            cliente_instance.cpf_cnpj = novo_cpf
            mudou_cliente = True
            
        if novo_email is not None and novo_email != cliente_instance.email:
            cliente_instance.email = novo_email
            mudou_cliente = True

        if mudou_cliente:
            cliente_instance.save()

        # 2. Histórico de Alterações
        alteracoes = {}
        campos_status = ['status_tratamento', 'status_esteira', 'status_comissionamento']
        for campo in campos_status:
            novo = validated_data.get(campo)
            if novo:
                antigo = getattr(instance, campo)
                if novo != antigo:
                    alteracoes[campo] = {'de': self._get_field_repr(antigo) if antigo else "Nenhum", 'para': self._get_field_repr(novo)}

        # 3. Automatização de Esteira
        novo_tratamento = validated_data.get('status_tratamento', instance.status_tratamento)
        if novo_tratamento and novo_tratamento.nome.lower() == 'cadastrada' and not instance.status_esteira:
            try:
                st_ini = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
                validated_data['status_esteira'] = st_ini
            except: pass

        # 4. Automatização: Quando reemissão é marcada, definir status_esteira como AGENDADO
        nova_reemissao = validated_data.get('reemissao')
        if nova_reemissao is not None:  # Campo foi enviado na requisição
            if nova_reemissao and not instance.reemissao:  # Reemissão foi marcada como True (mudou de False para True)
                try:
                    st_agendado = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
                    validated_data['status_esteira'] = st_agendado
                    if 'status_esteira' not in alteracoes:
                        alteracoes['status_esteira'] = {
                            'de': self._get_field_repr(instance.status_esteira) if instance.status_esteira else "Nenhum",
                            'para': 'AGENDADO'
                        }
                except StatusCRM.DoesNotExist:
                    pass

        novo_esteira = validated_data.get('status_esteira', instance.status_esteira)
        if novo_esteira and novo_esteira.nome.lower() == 'instalada' and not instance.status_comissionamento:
            try:
                st_com = StatusCRM.objects.get(nome__iexact="PENDENTE", tipo__iexact="Comissionamento")
                validated_data['status_comissionamento'] = st_com
            except: pass

        updated_instance = super().update(instance, validated_data)

        # 4. Atualiza auditor/editor
        if user:
            updated_instance.editado_por = user
            updated_instance.save(update_fields=['editado_por'])

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
    class Meta: model = LancamentoFinanceiro; fields = '__all__'

class FaturaM10Serializer(serializers.ModelSerializer):
    """Serializer para as faturas do Bônus M-10"""
    arquivo_pdf_url = serializers.SerializerMethodField()
    
    class Meta:
        model = FaturaM10
        fields = [
            'id', 'contrato', 'numero_fatura', 'numero_fatura_operadora',
            'valor', 'data_vencimento', 'data_pagamento', 'dias_atraso',
            'status', 'codigo_pix', 'codigo_barras', 'pdf_url', 'arquivo_pdf',
            'arquivo_pdf_url', 'observacao', 'criado_em', 'atualizado_em'
        ]
        read_only_fields = ['criado_em', 'atualizado_em']
    
    def get_arquivo_pdf_url(self, obj):
        """Retorna a URL completa do PDF se existir"""
        if obj.pdf_url:
            return obj.pdf_url
        if obj.arquivo_pdf:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.arquivo_pdf.url)
            return obj.arquivo_pdf.url
        return None