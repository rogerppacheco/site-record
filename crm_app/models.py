# crm_app/models.py

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
    
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT, null=True, blank=True)
    forma_pagamento = models.ForeignKey(FormaPagamento, on_delete=models.PROTECT, null=True, blank=True)

    status_tratamento = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_tratamento', limit_choices_to={'tipo': 'Tratamento'})
    status_esteira = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_esteira', limit_choices_to={'tipo': 'Esteira'})
    
    status_comissionamento = models.ForeignKey(StatusCRM, on_delete=models.SET_NULL, null=True, blank=True, related_name='vendas_comissionamento', limit_choices_to={'tipo': 'Comissionamento'})

    data_criacao = models.DateTimeField(auto_now_add=True)
    
    # --- NOVOS CAMPOS PARA RASTREIO DE EDIÇÃO ---
    editado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendas_editadas',
        verbose_name="Última alteração por"
    )
    data_ultima_alteracao = models.DateTimeField(auto_now=True, verbose_name="Data da Última Alteração")
    # --------------------------------------------

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
    data_abertura = models.DateTimeField(null=True, blank=True, verbose_name="Data de Abertura da O.S")
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

    auditor_atual = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='vendas_em_auditoria',
        verbose_name="Em Auditoria Por"
    )

    # --- CAMPOS PARA CONTROLE DE DESCONTOS ---
    flag_adiant_cnpj = models.BooleanField(default=False, verbose_name="Adiant. CNPJ Processado")
    flag_desc_boleto = models.BooleanField(default=False, verbose_name="Desc. Boleto Processado")
    flag_desc_viabilidade = models.BooleanField(default=False, verbose_name="Desc. Viab. Processado")
    flag_desc_antecipacao = models.BooleanField(default=False, verbose_name="Desc. Antecip. Processado")
    # ------------------------------------------

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
    TIPO_META_CHOICES = [
        ('BRUTA', 'Vendas Brutas (OS Aberta)'),
        ('LIQUIDA', 'Vendas Líquidas (Instaladas)'),
    ]
    
    CANAL_CHOICES = [
        ('TODOS', 'Todos os Canais'),
        ('PAP', 'PAP'),
        ('DIGITAL', 'Digital'),
        ('RECEPTIVO', 'Receptivo'),
        ('PARCEIRO', 'Parceiro'),
    ]

    nome = models.CharField(max_length=100, unique=True)
    
    data_inicio = models.DateField(null=True, blank=True, verbose_name="Início")
    data_fim = models.DateField(null=True, blank=True, verbose_name="Fim")
    
    meta_vendas = models.IntegerField(default=0, help_text="Quantidade alvo de vendas")
    valor_premio = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Prêmio em Dinheiro (R$)", help_text="Valor a ser pago se atingir a meta")
    
    tipo_meta = models.CharField(max_length=20, choices=TIPO_META_CHOICES, default='LIQUIDA', verbose_name="Tipo de Meta")
    canal_alvo = models.CharField(max_length=20, choices=CANAL_CHOICES, default='TODOS', verbose_name="Canal Alvo")
    
    # Novos Relacionamentos ManyToMany
    planos_elegiveis = models.ManyToManyField('Plano', blank=True, verbose_name="Planos Válidos", help_text="Se deixar vazio, vale para todos.")
    formas_pagamento_elegiveis = models.ManyToManyField('FormaPagamento', blank=True, verbose_name="Pagamentos Válidos", help_text="Se deixar vazio, vale para todas.")
    
    descricao_premio = models.TextField(blank=True, null=True, verbose_name="Prêmio", help_text="Descrição da premiação")
    regras = models.TextField(blank=True, null=True, verbose_name="Regras") 
    
    ativo = models.BooleanField(default=True)
    data_criacao = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self):
        inicio = self.data_inicio.strftime('%d/%m') if self.data_inicio else '?'
        fim = self.data_fim.strftime('%d/%m') if self.data_fim else '?'
        return f"{self.nome} ({inicio} - {fim})"

    class Meta:
        verbose_name = "Campanha"
        verbose_name_plural = "Campanhas"

class RegraCampanha(models.Model):
    campanha = models.ForeignKey(Campanha, on_delete=models.CASCADE, related_name='regras_meta')
    meta = models.IntegerField(verbose_name="Meta (Qtd Vendas)")
    valor_premio = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Prêmio (R$)")

    def __str__(self):
        return f"> {self.meta} vendas = R$ {self.valor_premio}"

    class Meta:
        verbose_name = "Faixa de Premiação"
        verbose_name_plural = "Faixas de Premiação"
        ordering = ['-meta']

class ComissaoOperadora(models.Model):
    plano = models.OneToOneField(Plano, on_delete=models.CASCADE, related_name='comissao_operadora', verbose_name="Plano")
    valor_base = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Base")
    bonus_transicao = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Bônus Transição")
    
    data_inicio_bonus = models.DateField(null=True, blank=True, verbose_name="Início Bônus")
    data_fim_bonus = models.DateField(null=True, blank=True, verbose_name="Fim Bônus")

    def __str__(self):
        return f"Recebimento {self.plano.nome}"

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

class AreaVenda(models.Model):
    nome_kml = models.CharField(max_length=255, help_text="Nome que estava no Placemark")
    celula = models.CharField(max_length=255, null=True, blank=True)
    uf = models.CharField(max_length=2, null=True, blank=True)
    municipio = models.CharField(max_length=100, null=True, blank=True)
    bairro = models.CharField(max_length=100, null=True, blank=True)
    prioridade = models.IntegerField(default=0, null=True, blank=True)
    estacao = models.CharField(max_length=50, null=True, blank=True)
    aging = models.IntegerField(default=0, null=True, blank=True)
    cluster = models.CharField(max_length=50, null=True, blank=True)
    status_venda = models.CharField(max_length=100, null=True, blank=True)
    hc = models.IntegerField(default=0, verbose_name="HC")
    hp = models.IntegerField(default=0, verbose_name="HP")
    hp_viavel = models.IntegerField(default=0, verbose_name="HP Viável")
    hp_viavel_total = models.IntegerField(default=0, verbose_name="HP Viável Total")
    ocupacao = models.CharField(max_length=20, null=True, blank=True, help_text="Percentual texto")
    hc_esperado = models.FloatField(default=0.0)
    atingimento_meta = models.CharField(max_length=20, null=True, blank=True)
    coordenadas = models.TextField(null=True, blank=True)
    data_importacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.municipio} - {self.celula} ({self.nome_kml})"

    class Meta:
        verbose_name = "Área de Venda (KML)"
        verbose_name_plural = "Áreas de Venda (KML)"

class SessaoWhatsapp(models.Model):
    # O PROBLEMA ESTÁ AQUI: max_length=20 é muito curto
    telefone = models.CharField(max_length=100, unique=True) 
    etapa = models.CharField(max_length=50) 
    dados_temp = models.JSONField(default=dict) 
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.telefone} - {self.etapa}"

class DFV(models.Model):
    uf = models.CharField(max_length=2, null=True, blank=True)
    municipio = models.CharField(max_length=100, null=True, blank=True)
    logradouro = models.CharField(max_length=255, null=True, blank=True)
    num_fachada = models.CharField(max_length=50, null=True, blank=True, help_text="Número da fachada")
    complemento = models.CharField(max_length=255, null=True, blank=True)
    cep = models.CharField(max_length=10, null=True, blank=True)
    bairro = models.CharField(max_length=100, null=True, blank=True)
    tipo_viabilidade = models.CharField(max_length=100, null=True, blank=True)
    tipo_rede = models.CharField(max_length=50, null=True, blank=True) 
    celula = models.CharField(max_length=50, null=True, blank=True)
    data_importacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.logradouro}, {self.num_fachada} - {self.municipio}"
        
    class Meta:
        verbose_name = "Base DFV"
        verbose_name_plural = "Base DFV"
        indexes = [
            models.Index(fields=['cep']),
            models.Index(fields=['cep', 'num_fachada']),
        ]

class GrupoDisparo(models.Model):
    nome = models.CharField(max_length=100, help_text="Ex: Grupo Gestão Comercial")
    chat_id = models.CharField(max_length=100, help_text="ID do grupo (Ex: 12036304...g.us)")
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome

class LancamentoFinanceiro(models.Model):
    TIPOS_CHOICES = [
        ('ADIANTAMENTO_CNPJ', 'Adiantamento CNPJ'),
        ('ADIANTAMENTO_COMISSAO', 'Adiantamento de Comissão'),
        ('DESCONTO', 'Desconto Avulso'),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lancamentos_financeiros')
    tipo = models.CharField(max_length=30, choices=TIPOS_CHOICES)
    
    data = models.DateField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    
    quantidade_vendas = models.IntegerField(default=0, blank=True, null=True)
    descricao = models.CharField(max_length=255, verbose_name="Descrição / Observação")
    
    # --- NOVO CAMPO: Para guardar IDs das vendas e permitir reversão ---
    metadados = models.JSONField(default=dict, blank=True, null=True, verbose_name="Dados de Controle") 
    
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='lancamentos_criados')
    data_criacao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.usuario} - R$ {self.valor}"

    class Meta:
        verbose_name = "Lançamento Financeiro"
        verbose_name_plural = "Lançamentos Financeiros"
        ordering = ['-data']
        
class AgendamentoDisparo(models.Model):
    TIPOS = [
        ('HORARIO', 'Diário (Hora em Hora 9h-19h)'),
        ('SEMANAL', 'Semanal (Ter/Qui/Sáb 17h)'),
    ]
    CANAL_OPCOES = [
        ('TODOS', 'Todos'),
        ('PAP', 'PAP'),
        ('DIGITAL', 'Digital'),
        ('RECEPTIVO', 'Receptivo'),
        ('PARCEIRO', 'Parceiro'),
    ]

    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    canal_alvo = models.CharField(max_length=20, choices=CANAL_OPCOES, default='TODOS')
    destinatarios = models.TextField(help_text="IDs de grupos ou números separados por vírgula")
    ativo = models.BooleanField(default=True)
    ultimo_disparo = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.nome} - {self.get_canal_alvo_display()}"
    
# No arquivo site-record/crm_app/models.py

class CdoiSolicitacao(models.Model):
    STATUS_CHOICES = [
        ('SEM_TRATAMENTO', 'Sem tratamento'),
        ('EM_CADASTRO', 'Em cadastro'),
        ('EM_PROJETO', 'Em Projeto'),
        ('EM_EXECUCAO', 'Em Execução'),
        ('CONCLUIDA', 'Concluída'),
    ]

    # ... (mantenha os campos existentes: nome_condominio, nome_sindico, etc.)
    nome_condominio = models.CharField(max_length=255)
    nome_sindico = models.CharField(max_length=255)
    contato_sindico = models.CharField(max_length=20)
    cep = models.CharField(max_length=9)
    logradouro = models.CharField(max_length=255)
    numero = models.CharField(max_length=20)
    bairro = models.CharField(max_length=100)
    cidade = models.CharField(max_length=100)
    uf = models.CharField(max_length=2)
    latitude = models.CharField(max_length=50, blank=True, null=True)
    longitude = models.CharField(max_length=50, blank=True, null=True)
    infraestrutura_tipo = models.CharField(max_length=50)
    possui_shaft_dg = models.BooleanField(default=False)
    total_hps = models.IntegerField(default=0)
    pre_venda_minima = models.IntegerField(default=0)
    
    link_carta_sindico = models.URLField(max_length=500, blank=True, null=True)
    link_fotos_fachada = models.URLField(max_length=500, blank=True, null=True)

    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data_criacao = models.DateTimeField(auto_now_add=True)
    
    # NOVOS CAMPOS / ATUALIZADOS
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='SEM_TRATAMENTO')
    observacao = models.TextField(blank=True, null=True, verbose_name="Observação do Backoffice")

    def __str__(self):
        return f"{self.nome_condominio} ({self.status})"

class CdoiBloco(models.Model):
    solicitacao = models.ForeignKey(CdoiSolicitacao, on_delete=models.CASCADE, related_name='blocos')
    nome_bloco = models.CharField(max_length=100)
    andares = models.IntegerField()
    unidades_por_andar = models.IntegerField()
    total_hps_bloco = models.IntegerField()


# =============================================================================
# BÔNUS M-10 & FPD
# =============================================================================

class SafraM10(models.Model):
    """Agrupa contratos por safra (mês de instalação)"""
    mes_referencia = models.DateField(help_text="Mês/Ano da safra (ex: 2025-07-01)")
    total_instalados = models.IntegerField(default=0, help_text="Total de contratos instalados na safra")
    total_ativos = models.IntegerField(default=0, help_text="Total ainda ativo")
    total_elegivel_bonus = models.IntegerField(default=0, help_text="Elegíveis para bônus M-10")
    valor_bonus_total = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Total a pagar (elegíveis × R$ 150)")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Safra M-10"
        verbose_name_plural = "Safras M-10"
        ordering = ['-mes_referencia']

    def __str__(self):
        return f"Safra {self.mes_referencia.strftime('%m/%Y')} - {self.total_instalados} contratos"


class ContratoM10(models.Model):
    """Cada contrato individual da safra"""
    STATUS_CHOICES = [
        ('ATIVO', 'Ativo'),
        ('CANCELADO', 'Cancelado'),
        ('DOWNGRADE', 'Downgrade'),
    ]

    safra = models.ForeignKey(SafraM10, on_delete=models.CASCADE, related_name='contratos')
    venda = models.ForeignKey('Venda', on_delete=models.SET_NULL, null=True, blank=True, related_name='bonus_m10')
    numero_contrato = models.CharField(max_length=100, unique=True)
    ordem_servico = models.CharField(max_length=100, null=True, blank=True, unique=True, help_text="O.S para crossover com FPD/Churn")
    cliente_nome = models.CharField(max_length=255)
    cpf_cliente = models.CharField(max_length=18, null=True, blank=True, help_text="CPF do cliente")
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    data_instalacao = models.DateField()
    plano_original = models.CharField(max_length=100)
    plano_atual = models.CharField(max_length=100)
    valor_plano = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status_contrato = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ATIVO')
    teve_downgrade = models.BooleanField(default=False, help_text="Marca manual se houve downgrade")
    data_cancelamento = models.DateField(null=True, blank=True)
    motivo_cancelamento = models.CharField(max_length=255, blank=True, null=True)
    elegivel_bonus = models.BooleanField(default=False, help_text="10 faturas pagas + sem downgrade + ativo")
    observacao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato M-10"
        verbose_name_plural = "Contratos M-10"
        ordering = ['-data_instalacao']

    def __str__(self):
        return f"{self.numero_contrato} - {self.cliente_nome}"

    def calcular_elegibilidade(self):
        """Verifica se o contrato é elegível para bônus M-10"""
        # Verifica se tem 10 faturas pagas
        faturas_pagas = self.faturas.filter(status='PAGO').count()
        
        self.elegivel_bonus = (
            faturas_pagas == 10 and
            not self.teve_downgrade and
            self.status_contrato == 'ATIVO'
        )
        self.save()
        return self.elegivel_bonus


class FaturaM10(models.Model):
    """10 faturas de cada contrato"""
    STATUS_CHOICES = [
        ('PAGO', 'Pago'),
        ('NAO_PAGO', 'Não Pago'),
        ('AGUARDANDO', 'Aguardando Arrecadação'),
        ('ATRASADO', 'Atrasado'),
        ('OUTROS', 'Outros'),
    ]

    contrato = models.ForeignKey(ContratoM10, on_delete=models.CASCADE, related_name='faturas')
    numero_fatura = models.IntegerField(help_text="1 a 10")
    numero_fatura_operadora = models.CharField(max_length=100, blank=True, null=True, help_text="NR_FATURA da planilha")
    valor = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    data_vencimento = models.DateField()
    data_pagamento = models.DateField(null=True, blank=True)
    dias_atraso = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NAO_PAGO')
    observacao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fatura M-10"
        verbose_name_plural = "Faturas M-10"
        ordering = ['contrato', 'numero_fatura']
        unique_together = ['contrato', 'numero_fatura']

    def __str__(self):
        return f"Fatura {self.numero_fatura} - {self.contrato.numero_contrato} - {self.status}"

class ImportacaoAgendamento(models.Model):
    """Modelo para armazenar importaÃ§Ãµes de Agendamentos Futuros e Tarefas Fechadas"""
    sg_uf = models.CharField(max_length=2, null=True, blank=True, verbose_name="UF")
    nm_municipio = models.CharField(max_length=255, null=True, blank=True, verbose_name="MunicÃ­pio")
    indicador = models.CharField(max_length=255, null=True, blank=True, verbose_name="Indicador")
    cd_nrba = models.CharField(max_length=255, null=True, blank=True, verbose_name="CÃ³digo NRBA")
    st_ba = models.CharField(max_length=255, null=True, blank=True, verbose_name="Status BA")
    cd_encerramento = models.CharField(max_length=255, null=True, blank=True, verbose_name="CÃ³digo Encerramento")
    desc_observacao = models.TextField(null=True, blank=True, verbose_name="ObservaÃ§Ã£o")
    desc_macro_atividade = models.CharField(max_length=255, null=True, blank=True, verbose_name="Macro Atividade")
    ds_atividade = models.CharField(max_length=255, null=True, blank=True, verbose_name="Atividade")
    dt_abertura_ba = models.DateField(null=True, blank=True, verbose_name="Data Abertura BA")
    dt_inicio_agendamento = models.DateTimeField(null=True, blank=True, verbose_name="InÃ­cio Agendamento")
    dt_fim_agendamento = models.DateTimeField(null=True, blank=True, verbose_name="Fim Agendamento")
    dt_inicio_execucao_real = models.DateTimeField(null=True, blank=True, verbose_name="InÃ­cio ExecuÃ§Ã£o Real")
    dt_fim_execucao_real = models.DateTimeField(null=True, blank=True, verbose_name="Fim ExecuÃ§Ã£o Real")
    nr_ordem = models.CharField(max_length=255, null=True, blank=True, verbose_name="NÃºmero Ordem")
    nr_ordem_venda = models.CharField(max_length=255, null=True, blank=True, verbose_name="Ordem Venda")
    dt_execucao_particao = models.DateField(null=True, blank=True, verbose_name="Data ExecuÃ§Ã£o PartiÃ§Ã£o")
    anomes = models.CharField(max_length=6, null=True, blank=True, verbose_name="Ano/MÃªs")
    cd_sap_original = models.CharField(max_length=255, null=True, blank=True, verbose_name="SAP Original")
    cd_rede = models.CharField(max_length=255, null=True, blank=True, verbose_name="CÃ³digo Rede")
    nm_pdv_rel = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome PDV")
    rede = models.CharField(max_length=255, null=True, blank=True, verbose_name="Rede")
    gp_canal = models.CharField(max_length=255, null=True, blank=True, verbose_name="Grupo Canal")
    sg_gerencia = models.CharField(max_length=255, null=True, blank=True, verbose_name="Sigla GerÃªncia")
    nm_gc = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome GC")
    dt_agendamento = models.DateField(null=True, blank=True, verbose_name="Data Agendamento")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "ImportaÃ§Ã£o Agendamento"
        verbose_name_plural = "ImportaÃ§Ãµes Agendamentos"
        ordering = ["-dt_agendamento", "-criado_em"]
        indexes = [
            models.Index(fields=["cd_nrba"]),
            models.Index(fields=["nr_ordem"]),
            models.Index(fields=["dt_agendamento"]),
            models.Index(fields=["anomes"]),
        ]

    def __str__(self):
        return f"BA {self.cd_nrba} - {self.dt_agendamento or 'Sem data'}"
