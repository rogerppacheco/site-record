from django.db import models
from usuarios.models import Usuario
from django.conf import settings

class Operadora(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    cnpj = models.CharField(max_length=18, unique=True, null=True, blank=True)
    ativo = models.BooleanField(default=True)

    def __str__(self): return self.nome
    class Meta:
        db_table = 'crm_operadora'
        verbose_name = "Operadora"
        verbose_name_plural = "Operadoras"

class Plano(models.Model):
    nome = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    operadora = models.ForeignKey(Operadora, on_delete=models.CASCADE, related_name='planos')
    beneficios = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    comissao_base = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self): return f"{self.nome} - {self.operadora.nome}"
    class Meta:
        db_table = 'crm_plano'
        verbose_name = "Plano"
        verbose_name_plural = "Planos"

class FormaPagamento(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    ativo = models.BooleanField(default=True)
    aplica_desconto = models.BooleanField(default=False, help_text="Aplica desconto de boleto?")
    def __str__(self): return self.nome
    class Meta:
        db_table = 'crm_forma_pagamento'
        verbose_name = "Forma de Pagamento"
        verbose_name_plural = "Formas de Pagamento"

class StatusCRM(models.Model):
    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50, choices=[('Tratamento', 'Tratamento'), ('Esteira', 'Esteira'), ('Comissionamento', 'Comissionamento')])
    estado = models.CharField(max_length=50, blank=True, null=True)
    cor = models.CharField(max_length=7, default="#FFFFFF")

    def __str__(self): return f"{self.nome} ({self.tipo})"
    class Meta:
        db_table = 'crm_status'
        verbose_name = "Status de CRM"
        verbose_name_plural = "Status de CRM"
        unique_together = ('nome', 'tipo')

class MotivoPendencia(models.Model):
    nome = models.CharField(max_length=255)
    tipo_pendencia = models.CharField(max_length=100)
    def __str__(self): return self.nome
    class Meta:
        db_table = 'crm_motivo_pendencia'
        verbose_name = "Motivo de Pendência"
        verbose_name_plural = "Motivos de Pendência"

class RegraComissao(models.Model):
    TIPO_VENDA_CHOICES = [('PAP', 'PAP'), ('TELAG', 'TELAG')]
    TIPO_CLIENTE_CHOICES = [('CPF', 'CPF'), ('CNPJ', 'CNPJ')]
    consultor = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='regras_comissao')
    plano = models.ForeignKey(Plano, on_delete=models.CASCADE, related_name='regras_comissao')
    tipo_venda = models.CharField(max_length=5, choices=TIPO_VENDA_CHOICES)
    tipo_cliente = models.CharField(max_length=4, choices=TIPO_CLIENTE_CHOICES)
    valor_base = models.DecimalField(max_digits=10, decimal_places=2)
    valor_acelerado = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self): return f"Regra {self.consultor} - {self.plano}"
    class Meta:
        db_table = 'crm_regra_comissao'
        verbose_name = "Regra de Comissão"
        verbose_name_plural = "Regras de Comissão"
        unique_together = ('consultor', 'plano', 'tipo_venda', 'tipo_cliente')

class Cliente(models.Model):
    nome_razao_social = models.CharField(max_length=255)
    cpf_cnpj = models.CharField(max_length=18, unique=True)
    email = models.EmailField(max_length=255, blank=True, null=True)
    def __str__(self): return self.nome_razao_social
    class Meta:
        db_table = 'crm_cliente'
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

class Venda(models.Model):
    ativo = models.BooleanField(default=True, verbose_name="Venda Ativa")
    vendedor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, related_name='vendas')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='vendas')
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT)
    forma_pagamento = models.ForeignKey(FormaPagamento, on_delete=models.PROTECT)

    status_tratamento = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_tratamento', limit_choices_to={'tipo': 'Tratamento'})
    status_esteira = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_esteira', limit_choices_to={'tipo': 'Esteira'})
    
    status_comissionamento = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_comissionamento', limit_choices_to={'tipo': 'Comissionamento'})

    data_criacao = models.DateTimeField(auto_now_add=True)
    forma_entrada = models.CharField(max_length=10, choices=[('APP', 'APP'), ('SEM_APP', 'SEM_APP')], default='APP')
    
    nome_mae = models.CharField(max_length=255, blank=True, null=True)
    data_nascimento = models.DateField(blank=True, null=True)
    cpf_representante_legal = models.CharField(max_length=14, blank=True, null=True)
    nome_representante_legal = models.CharField(max_length=255, blank=True, null=True)
    
    telefone1 = models.CharField(max_length=20, blank=True, null=True)
    telefone2 = models.CharField(max_length=20, blank=True, null=True)
    cep = models.CharField(max_length=9, blank=True, null=True)
    logradouro = models.CharField(max_length=255, blank=True, null=True)
    numero_residencia = models.CharField(max_length=20, blank=True, null=True)
    complemento = models.CharField(max_length=100, blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    cidade = models.CharField(max_length=100, blank=True, null=True)
    estado = models.CharField(max_length=2, blank=True, null=True)
    ponto_referencia = models.CharField(max_length=255, blank=True, null=True)
    observacoes = models.TextField(blank=True, null=True)

    ordem_servico = models.CharField(max_length=50, null=True, blank=True)
    data_pedido = models.DateTimeField(null=True, blank=True)
    data_agendamento = models.DateField(null=True, blank=True)
    periodo_agendamento = models.CharField(max_length=10, choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')], null=True, blank=True)
    data_instalacao = models.DateField(null=True, blank=True)
    antecipou_instalacao = models.BooleanField(default=False)
    motivo_pendencia = models.ForeignKey(MotivoPendencia, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_pendentes')

    inclusao = models.BooleanField(default=False, verbose_name="Inclusão/Viabilidade")
    data_pagamento_comissao = models.DateField(null=True, blank=True, verbose_name="Data Pagamento Comissão")
    
    data_pagamento = models.DateField(null=True, blank=True) 
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # --- NOVO CAMPO PARA CONTROLE DE CONCORRÊNCIA NA AUDITORIA ---
    auditor_atual = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='vendas_em_auditoria',
        verbose_name="Em Auditoria Por"
    )

    def __str__(self): return f"Venda #{self.id}"
    class Meta:
        db_table = 'crm_venda'
        verbose_name = "Venda"
        verbose_name_plural = "Vendas"
        permissions = [
            ("pode_reverter_status", "Pode reverter o status"),
            ("can_view_auditoria", "Pode visualizar auditoria"),
            ("can_view_esteira", "Pode visualizar esteira"),
            ("can_view_comissao_dashboard", "Pode visualizar card de comissão"), 
        ]

class PagamentoComissao(models.Model):
    referencia_ano = models.IntegerField()
    referencia_mes = models.IntegerField()
    data_fechamento = models.DateTimeField(auto_now_add=True)
    total_pago_consultores = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    total_recebido_ciclo = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    observacoes = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'crm_pagamento_comissao'
        unique_together = ('referencia_ano', 'referencia_mes')
        ordering = ['-referencia_ano', '-referencia_mes']

class ImportacaoOsab(models.Model):
    # --- Campos Antigos ---
    produto = models.CharField(max_length=255, null=True, blank=True)
    filial = models.CharField(max_length=255, null=True, blank=True)
    uf = models.CharField(max_length=2, null=True, blank=True)
    dt_ref = models.DateField(null=True, blank=True)
    documento = models.CharField(max_length=255, null=True, blank=True) 
    segmento = models.CharField(max_length=255, null=True, blank=True)
    localidade = models.CharField(max_length=255, null=True, blank=True)
    estacao = models.CharField(max_length=255, null=True, blank=True)
    id_bundle = models.CharField(max_length=255, null=True, blank=True)
    telefone = models.CharField(max_length=255, null=True, blank=True)
    cliente = models.CharField(max_length=255, null=True, blank=True)
    velocidade = models.CharField(max_length=255, null=True, blank=True)
    matricula_vendedor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Matrícula do Vendedor")
    classe_produto = models.CharField(max_length=255, null=True, blank=True)
    nome_canal = models.CharField(max_length=255, null=True, blank=True) 
    pdv_sap = models.CharField(max_length=255, null=True, blank=True)
    descricao = models.CharField(max_length=255, null=True, blank=True)
    data_abertura = models.DateField(null=True, blank=True)
    data_fechamento = models.DateField(null=True, blank=True)
    situacao = models.CharField(max_length=255, null=True, blank=True)
    cluster = models.CharField(max_length=255, null=True, blank=True)
    safra = models.CharField(max_length=255, null=True, blank=True)
    data_agendamento = models.DateField(null=True, blank=True)
    dacc_sol = models.CharField(max_length=255, null=True, blank=True)
    dacc_efe = models.CharField(max_length=255, null=True, blank=True)
    dia_vencimento = models.CharField(max_length=255, null=True, blank=True)
    duplicidade_vl_vl_mesmo_endereco_cpf_diferente = models.CharField(max_length=255, null=True, blank=True)
    duplicidade_vl_vl_mesmo_endereco_cpf_igual = models.CharField(max_length=255, null=True, blank=True)
    duplicidade_vl_planta_mesmo_endereco_cpf_igual = models.CharField(max_length=255, null=True, blank=True)
    duplicidade_vl_planta_mesmo_endereco_cpf_diferente = models.CharField(max_length=255, null=True, blank=True)
    contato1 = models.CharField(max_length=255, null=True, blank=True)
    contato2 = models.CharField(max_length=255, null=True, blank=True)
    contato3 = models.CharField(max_length=255, null=True, blank=True)
    flg_mig_cobre_fixo = models.CharField(max_length=255, null=True, blank=True)
    flg_mig_cobre_velox = models.CharField(max_length=255, null=True, blank=True)
    flg_mig_tv = models.CharField(max_length=255, null=True, blank=True)
    desc_pendencia = models.CharField(max_length=255, null=True, blank=True)
    tipo_pendencia = models.CharField(max_length=255, null=True, blank=True)
    cod_pendencia = models.CharField(max_length=255, null=True, blank=True)
    oferta = models.CharField(max_length=255, null=True, blank=True)
    comunidade = models.CharField(max_length=255, null=True, blank=True)
    gv = models.CharField(max_length=255, null=True, blank=True)
    gc = models.CharField(max_length=255, null=True, blank=True) 
    sap_principal_fim = models.CharField(max_length=255, null=True, blank=True)
    gestao = models.CharField(max_length=255, null=True, blank=True)
    st_regional = models.CharField(max_length=255, null=True, blank=True)
    meio_pagamento = models.CharField(max_length=255, null=True, blank=True)
    flag_vll = models.CharField(max_length=255, null=True, blank=True)
    status_checkout = models.CharField(max_length=255, null=True, blank=True)
    numero_ba = models.CharField(max_length=255, null=True, blank=True)
    venda_no_app = models.CharField(max_length=255, null=True, blank=True)

    # --- NOVOS CAMPOS ---
    celula = models.CharField(max_length=255, null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)
    fg_venda_valida = models.CharField(max_length=255, null=True, blank=True)
    desc_motivo_ordem = models.CharField(max_length=255, null=True, blank=True)
    desc_sub_motivo_ordem = models.CharField(max_length=255, null=True, blank=True)
    campanha = models.CharField(max_length=255, null=True, blank=True)
    flg_mei = models.CharField(max_length=255, null=True, blank=True)
    nm_diretoria = models.CharField(max_length=255, null=True, blank=True)
    nm_regional = models.CharField(max_length=255, null=True, blank=True)
    cd_rede = models.CharField(max_length=255, null=True, blank=True)
    gp_canal = models.CharField(max_length=255, null=True, blank=True)
    gerencia = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Importação OSAB - DOC {self.documento}"
    class Meta:
        db_table = 'crm_importacao_osab'
        verbose_name = "Importação OSAB"
        verbose_name_plural = "Importações OSAB"

class ImportacaoChurn(models.Model):
    uf = models.CharField(max_length=2, null=True, blank=True)
    produto = models.CharField(max_length=255, null=True, blank=True)
    matricula_vendedor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Matrícula do Vendedor")
    gv = models.CharField(max_length=255, null=True, blank=True)
    sap_principal_fim = models.CharField(max_length=255, null=True, blank=True)
    gestao = models.CharField(max_length=255, null=True, blank=True)
    st_regional = models.CharField(max_length=255, null=True, blank=True)
    gc = models.CharField(max_length=255, null=True, blank=True)
    numero_pedido = models.CharField(max_length=50, null=True, blank=True, unique=True, verbose_name="Número do Pedido")
    dt_gross = models.DateField(null=True, blank=True, verbose_name="Data Gross")
    anomes_gross = models.CharField(max_length=6, null=True, blank=True, verbose_name="Ano/Mês Gross")
    dt_retirada = models.DateField(null=True, blank=True, verbose_name="Data Retirada")
    anomes_retirada = models.CharField(max_length=6, null=True, blank=True, verbose_name="Ano/Mês Retirada")
    grupo_unidade = models.CharField(max_length=255, null=True, blank=True)
    codigo_sap = models.CharField(max_length=50, null=True, blank=True)
    municipio = models.CharField(max_length=255, null=True, blank=True)
    tipo_retirada = models.CharField(max_length=255, null=True, blank=True)
    motivo_retirada = models.CharField(max_length=255, null=True, blank=True)
    submotivo_retirada = models.CharField(max_length=255, null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)
    desc_apelido = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Importação Churn - Pedido {self.numero_pedido}"
    class Meta:
        db_table = 'crm_importacao_churn'
        verbose_name = "Importação Churn"
        verbose_name_plural = "Importações Churn"

class CicloPagamento(models.Model):
    ano = models.IntegerField(null=True, blank=True)
    mes = models.CharField(max_length=20, null=True, blank=True)
    quinzena = models.CharField(max_length=10, null=True, blank=True)
    ciclo = models.CharField(max_length=50, null=True, blank=True)
    ciclo_complementar = models.CharField(max_length=50, null=True, blank=True)
    evento = models.CharField(max_length=100, null=True, blank=True)
    sub_evento = models.CharField(max_length=100, null=True, blank=True)
    canal_detalhado = models.CharField(max_length=100, null=True, blank=True)
    canal_agrupado = models.CharField(max_length=100, null=True, blank=True)
    sub_canal = models.CharField(max_length=50, null=True, blank=True)
    cod_sap = models.CharField(max_length=50, null=True, blank=True)
    cod_sap_agr = models.CharField(max_length=50, null=True, blank=True)
    parceiro_agr = models.CharField(max_length=255, null=True, blank=True)
    uf_parceiro_agr = models.CharField(max_length=2, null=True, blank=True)
    familia = models.CharField(max_length=100, null=True, blank=True)
    produto = models.CharField(max_length=100, null=True, blank=True)
    oferta = models.CharField(max_length=255, null=True, blank=True)
    plano_detalhado = models.CharField(max_length=255, null=True, blank=True)
    celula = models.CharField(max_length=100, null=True, blank=True)
    metodo_pagamento = models.CharField(max_length=50, null=True, blank=True)
    contrato = models.CharField(max_length=50, unique=True, primary_key=True)
    num_os_pedido_siebel = models.CharField(max_length=50, null=True, blank=True)
    id_bundle = models.CharField(max_length=50, null=True, blank=True)
    data_atv = models.DateField(null=True, blank=True)
    data_retirada = models.DateField(null=True, blank=True)
    qtd = models.IntegerField(null=True, blank=True)
    comissao_bruta = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fator = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    iq = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_comissao_final = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    data_importacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'crm_ciclo_pagamento'
        verbose_name = "Ciclo de Pagamento"
        verbose_name_plural = "Ciclos de Pagamento"

    def __str__(self):
        return f"{self.contrato} - {self.ciclo}"

class HistoricoAlteracaoVenda(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.SET_NULL, null=True, related_name='historico_alteracoes')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='alteracoes_vendas')
    data_alteracao = models.DateTimeField(auto_now_add=True)
    alteracoes = models.JSONField(default=dict, help_text="Registra alterações ou a exclusão da venda")

    class Meta:
        db_table = 'crm_historico_alteracao_venda'
        verbose_name = "Histórico de Alteração de Venda"
        verbose_name_plural = "Históricos de Alteração de Venda"
        ordering = ['-data_alteracao']

    def __str__(self):
        usuario_str = self.usuario.username if self.usuario else 'N/A'
        return f"Alteração na Venda #{self.venda.id} por {usuario_str} em {self.data_alteracao.strftime('%d/%m/%Y %H:%M')}"

class Campanha(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    ativo = models.BooleanField(default=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Campanha"
        verbose_name_plural = "Campanhas"

class ComissaoOperadora(models.Model):
    plano = models.OneToOneField(Plano, on_delete=models.CASCADE, related_name='comissao_operadora', verbose_name="Plano")
    valor_base = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Base")
    bonus_transicao = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Bônus Transição")
    
    data_inicio_bonus = models.DateField(null=True, blank=True, verbose_name="Início Bônus")
    data_fim_bonus = models.DateField(null=True, blank=True, verbose_name="Fim Bônus")

    def __str__(self):
        return f"Recebimento {self.plano.nome}"

# --- NOVO MODELO: RECORD INFORMA (COMUNICADO) ---
class Comunicado(models.Model):
    PERFIL_CHOICES = [
        ('TODOS', 'Todos'),
        ('VENDEDOR', 'Vendedores'),
        ('SUPERVISOR', 'Supervisores'),
        ('BACKOFFICE', 'Backoffice'),
        ('DIRETORIA', 'Diretoria'),
    ]
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('ENVIADO', 'Enviado'),
        ('CANCELADO', 'Cancelado'),
        ('ERRO', 'Erro'),
    ]

    titulo = models.CharField(max_length=200, verbose_name="Título Interno")
    mensagem = models.TextField(verbose_name="Mensagem WhatsApp")
    
    data_programada = models.DateField()
    hora_programada = models.TimeField()
    
    perfil_destino = models.CharField(max_length=20, choices=PERFIL_CHOICES, default='TODOS')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE')
    
    criado_em = models.DateTimeField(auto_now_add=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.titulo} - {self.get_status_display()}"
    
    class Meta:
        verbose_name = "Comunicado (Record Informa)"
        verbose_name_plural = "Comunicados"
        ordering = ['-data_programada', '-hora_programada']