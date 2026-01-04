# crm_app/models.py

from django.db import models
from usuarios.models import Usuario
from django.conf import settings
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

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

    venda = models.ForeignKey('Venda', on_delete=models.SET_NULL, null=True, blank=True, related_name='bonus_m10')
    numero_contrato = models.CharField(max_length=100, unique=True)
    numero_contrato_definitivo = models.CharField(max_length=100, null=True, blank=True, help_text="Preenchido automaticamente do FPD")
    ordem_servico = models.CharField(max_length=100, null=True, blank=True, unique=True, help_text="O.S para crossover com FPD/Churn")
    
    # Dados preenchidos automaticamente do FPD
    data_vencimento_fpd = models.DateField(null=True, blank=True, help_text="Data de vencimento da última fatura FPD")
    data_pagamento_fpd = models.DateField(null=True, blank=True, help_text="Data de pagamento da última fatura FPD")
    status_fatura_fpd = models.CharField(max_length=50, null=True, blank=True, help_text="Status da última fatura FPD (PAGO, ABERTO, etc)")
    valor_fatura_fpd = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Valor da última fatura FPD")
    nr_dias_atraso_fpd = models.IntegerField(null=True, blank=True, help_text="Dias em atraso da última fatura FPD")
    
    cliente_nome = models.CharField(max_length=255)
    cpf_cliente = models.CharField(max_length=18, null=True, blank=True, help_text="CPF do cliente")
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    data_instalacao = models.DateField()
    safra = models.CharField(max_length=7, null=True, blank=True, help_text="Mês/Ano da instalação (YYYY-MM)")
    plano_original = models.CharField(max_length=100)
    plano_atual = models.CharField(max_length=100)
    valor_plano = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status_contrato = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ATIVO')
    teve_downgrade = models.BooleanField(default=False, help_text="Marca manual se houve downgrade")
    data_cancelamento = models.DateField(null=True, blank=True)
    motivo_cancelamento = models.CharField(max_length=255, blank=True, null=True)
    elegivel_bonus = models.BooleanField(default=False, help_text="10 faturas pagas + sem downgrade + ativo")
    data_ultima_sincronizacao_fpd = models.DateTimeField(null=True, blank=True, help_text="Última sincronização com FPD")
    observacao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato M-10"
        verbose_name_plural = "Contratos M-10"
        ordering = ['-data_instalacao']

    def __str__(self):
        return f"{self.numero_contrato} - {self.cliente_nome}"

    def save(self, *args, **kwargs):
        """Calcula safra automaticamente"""
        if self.data_instalacao:
            self.safra = self.data_instalacao.strftime('%Y-%m')
        
        super().save(*args, **kwargs)
    
    def calcular_vencimento_fatura_1(self):
        """Calcula o vencimento da primeira fatura segundo a regra:
        - Dias 1-28: data_instalacao + 25 dias
        - Dias 29-31: dia 26 do mês seguinte
        """
        dia_instalacao = self.data_instalacao.day
        
        if dia_instalacao <= 28:
            return self.data_instalacao + timedelta(days=25)
        else:
            # Dias 29, 30, 31: vencimento no dia 26 do mês seguinte
            mes_seguinte = self.data_instalacao + relativedelta(months=1)
            return mes_seguinte.replace(day=26)
    
    def calcular_data_disponibilidade(self, numero_fatura):
        """Calcula quando a fatura estará disponível no Nio (3-5 dias após instalação)
        Para simplificar, usamos 3 dias como mínimo
        """
        if numero_fatura == 1:
            return self.data_instalacao + timedelta(days=3)
        else:
            # Faturas subsequentes ficam disponíveis 3 dias antes do vencimento
            vencimento = self.calcular_vencimento_fatura_n(numero_fatura)
            return vencimento - timedelta(days=3)
    
    def calcular_vencimento_fatura_n(self, numero_fatura):
        """Calcula o vencimento da fatura N (1 a 10)
        Fatura 1: conforme regra especial
        Faturas 2-10: mesmo dia da fatura 1, mas nos meses subsequentes
        """
        if numero_fatura == 1:
            return self.calcular_vencimento_fatura_1()
        else:
            vencimento_fatura_1 = self.calcular_vencimento_fatura_1()
            return vencimento_fatura_1 + relativedelta(months=numero_fatura - 1)
    
    def criar_ou_atualizar_faturas(self):
        """Cria ou atualiza as 10 faturas com as datas de vencimento calculadas"""
        for i in range(1, 11):
            data_vencimento = self.calcular_vencimento_fatura_n(i)
            data_disponibilidade = self.calcular_data_disponibilidade(i)
            
            fatura, created = FaturaM10.objects.get_or_create(
                contrato=self,
                numero_fatura=i,
                defaults={
                    'data_vencimento': data_vencimento,
                    'data_disponibilidade': data_disponibilidade,
                    'valor': self.valor_plano,
                }
            )
            
            # Se já existe, atualiza apenas as datas
            if not created:
                fatura.data_vencimento = data_vencimento
                fatura.data_disponibilidade = data_disponibilidade
                fatura.save(update_fields=['data_vencimento', 'data_disponibilidade', 'atualizado_em'])

    def calcular_elegibilidade(self):
        """Verifica se o contrato é elegível para bônus M-10.

        Nova regra: basta que todas as faturas cadastradas estejam pagas
        (qualquer quantidade) e o contrato esteja ativo. Mantemos o bloqueio
        para contratos com downgrade.
        """
        total_faturas = self.faturas.count()
        faturas_pagas = self.faturas.filter(status='PAGO').count()

        # Se não existem faturas cadastradas, mas o status FPD está pago,
        # consideramos como 1/1 para fins de elegibilidade.
        if total_faturas == 0 and self.status_fatura_fpd and str(self.status_fatura_fpd).lower().startswith('paga'):
            total_faturas = 1
            faturas_pagas = 1

        self.elegivel_bonus = (
            total_faturas > 0 and
            faturas_pagas == total_faturas and
            not self.teve_downgrade and
            self.status_contrato == 'ATIVO'
        )
        self.save(update_fields=['elegivel_bonus', 'atualizado_em'])
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
    
    ORIGEM_BUSCA_CHOICES = [
        ('MANUAL', 'Busca Manual'),
        ('AUTOMATICA', 'Busca Automática (Agendada)'),
        ('SAFRA', 'Busca por Safra'),
        ('INDIVIDUAL', 'Busca Individual'),
    ]
    
    STATUS_BUSCA_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]

    contrato = models.ForeignKey(ContratoM10, on_delete=models.CASCADE, related_name='faturas')
    numero_fatura = models.IntegerField(help_text="1 a 10")
    numero_fatura_operadora = models.CharField(max_length=100, blank=True, null=True, help_text="NR_FATURA da planilha")
    valor = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    data_vencimento = models.DateField()
    data_disponibilidade = models.DateField(null=True, blank=True, help_text="Data em que a fatura estará disponível no Nio")
    data_pagamento = models.DateField(null=True, blank=True)
    dias_atraso = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NAO_PAGO')
    # Campos mapeados diretamente do arquivo FPD
    id_contrato_fpd = models.CharField(max_length=100, blank=True, null=True, help_text="ID_CONTRATO do arquivo FPD")
    dt_pagamento_fpd = models.DateField(blank=True, null=True, help_text="DT_PAGAMENTO do arquivo FPD")
    ds_status_fatura_fpd = models.CharField(max_length=50, blank=True, null=True, help_text="DS_STATUS_FATURA do arquivo FPD")
    data_importacao_fpd = models.DateTimeField(blank=True, null=True, help_text="Data da última importação FPD")
    codigo_pix = models.TextField(blank=True, null=True, help_text="Código PIX Copia e Cola")
    codigo_barras = models.CharField(max_length=100, blank=True, null=True, help_text="Código de barras da fatura")
    pdf_url = models.URLField(max_length=500, blank=True, null=True, help_text="Link público do PDF da fatura")
    arquivo_pdf = models.FileField(upload_to='faturas_m10/%Y/%m/', blank=True, null=True, help_text="PDF da fatura")
    observacao = models.TextField(blank=True, null=True)
    
    # Campos de rastreamento de busca
    origem_busca = models.CharField(max_length=20, choices=ORIGEM_BUSCA_CHOICES, blank=True, null=True, help_text="Origem da última busca")
    status_busca = models.CharField(max_length=20, choices=STATUS_BUSCA_CHOICES, default='PENDENTE', help_text="Status da última busca")
    ultima_busca_em = models.DateTimeField(blank=True, null=True, help_text="Data/hora da última tentativa de busca")
    tempo_busca_segundos = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True, help_text="Tempo de execução da busca em segundos")
    tentativas_busca = models.IntegerField(default=0, help_text="Número de tentativas de busca")
    erro_busca = models.TextField(blank=True, null=True, help_text="Mensagem de erro da última busca")
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fatura M-10"
        verbose_name_plural = "Faturas M-10"
        ordering = ['contrato', 'numero_fatura']
        unique_together = ['contrato', 'numero_fatura']

    def __str__(self):
        return f"Fatura {self.numero_fatura} - {self.contrato.numero_contrato} - {self.status}"


class HistoricoBuscaFatura(models.Model):
    """Histórico detalhado de execuções de busca de faturas"""
    TIPO_BUSCA_CHOICES = [
        ('AUTOMATICA', 'Busca Automática (Agendada)'),
        ('SAFRA', 'Busca por Safra'),
        ('INDIVIDUAL', 'Busca Individual'),
        ('RETRY', 'Retry de Erro'),
    ]
    
    STATUS_CHOICES = [
        ('EM_ANDAMENTO', 'Em Andamento'),
        ('CONCLUIDA', 'Concluída'),
        ('ERRO', 'Erro'),
        ('CANCELADA', 'Cancelada'),
    ]
    
    tipo_busca = models.CharField(max_length=20, choices=TIPO_BUSCA_CHOICES, help_text="Tipo de execução")
    safra = models.CharField(max_length=7, blank=True, null=True, help_text="Safra processada (formato YYYY-MM)")
    usuario = models.ForeignKey('usuarios.Usuario', on_delete=models.SET_NULL, null=True, blank=True, help_text="Usuário que iniciou")
    
    # Métricas de execução
    inicio_em = models.DateTimeField(auto_now_add=True)
    termino_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    # Estatísticas
    total_contratos = models.IntegerField(default=0)
    total_faturas = models.IntegerField(default=0)
    faturas_sucesso = models.IntegerField(default=0)
    faturas_erro = models.IntegerField(default=0)
    faturas_nao_disponiveis = models.IntegerField(default=0)
    faturas_retry = models.IntegerField(default=0)
    
    # Performance
    tempo_medio_fatura = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True, help_text="Tempo médio por fatura (segundos)")
    tempo_min_fatura = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    tempo_max_fatura = models.DecimalField(max_digits=8, decimal_places=3, blank=True, null=True)
    
    # Status e logs
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='EM_ANDAMENTO')
    mensagem = models.TextField(blank=True, null=True, help_text="Mensagem final ou erro")
    logs = models.JSONField(blank=True, null=True, help_text="Logs detalhados da execução")
    
    class Meta:
        verbose_name = "Histórico de Busca de Fatura"
        verbose_name_plural = "Histórico de Buscas de Faturas"
        ordering = ['-inicio_em']
    
    def __str__(self):
        return f"{self.get_tipo_busca_display()} - {self.inicio_em.strftime('%d/%m/%Y %H:%M')}"


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

class ImportacaoRecompra(models.Model):
    """Modelo para importação de dados de Recompra"""
    
    # Identificadores
    ds_anomes = models.CharField(max_length=50, null=True, blank=True, verbose_name="Ano/Mês")
    nr_ordem = models.CharField(max_length=255, null=True, blank=True, db_index=True, verbose_name="Número Ordem")
    
    # Datas
    dt_venda_particao = models.DateField(null=True, blank=True, verbose_name="Data Venda Partição")
    dt_encerramento = models.DateField(null=True, blank=True, verbose_name="Data Encerramento")
    dt_inicio_ativo = models.DateField(null=True, blank=True, verbose_name="Data Início Ativo")
    
    # Status e Segmento
    st_ordem = models.CharField(max_length=255, null=True, blank=True, verbose_name="Status Ordem")
    nm_seg = models.CharField(max_length=255, null=True, blank=True, verbose_name="Nome Segmento")
    resultado = models.CharField(max_length=255, null=True, blank=True, verbose_name="Resultado")
    
    # Localização
    sg_uf = models.CharField(max_length=2, null=True, blank=True, verbose_name="UF")
    nm_municipio = models.CharField(max_length=255, null=True, blank=True, verbose_name="Município")
    nm_bairro = models.CharField(max_length=255, null=True, blank=True, verbose_name="Bairro")
    nr_cep = models.CharField(max_length=20, null=True, blank=True, verbose_name="CEP")
    nr_cep_base = models.CharField(max_length=20, null=True, blank=True, verbose_name="CEP Base")
    
    # Complementos de Endereço
    nr_complemento1_base = models.CharField(max_length=255, null=True, blank=True, verbose_name="Complemento 1")
    nr_complemento2_base = models.CharField(max_length=255, null=True, blank=True, verbose_name="Complemento 2")
    nr_complemento3_base = models.CharField(max_length=255, null=True, blank=True, verbose_name="Complemento 3")
    
    # SAP e Transações
    cd_sap_pdv = models.CharField(max_length=255, null=True, blank=True, verbose_name="SAP PDV")
    cd_tr_vdd = models.CharField(max_length=255, null=True, blank=True, verbose_name="Transação Vendedor")
    
    # Organização
    nm_diretoria = models.CharField(max_length=255, null=True, blank=True, verbose_name="Diretoria")
    nm_regional = models.CharField(max_length=255, null=True, blank=True, verbose_name="Regional")
    cd_rede = models.CharField(max_length=255, null=True, blank=True, verbose_name="Código Rede")
    gp_canal = models.CharField(max_length=255, null=True, blank=True, verbose_name="Grupo Canal")
    nm_pdv_rel = models.CharField(max_length=255, null=True, blank=True, verbose_name="PDV Relacionado")
    nm_gc = models.CharField(max_length=255, null=True, blank=True, verbose_name="Gerente de Conta")
    
    # Extras
    GERENCIA = models.CharField(max_length=255, null=True, blank=True, verbose_name="Gerência")
    REDE = models.CharField(max_length=255, null=True, blank=True, verbose_name="Rede")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")
    
    class Meta:
        verbose_name = "Importação Recompra"
        verbose_name_plural = "Importações Recompra"
        ordering = ["-dt_venda_particao", "-created_at"]
        indexes = [
            models.Index(fields=["nr_ordem"]),
            models.Index(fields=["ds_anomes"]),
            models.Index(fields=["dt_venda_particao"]),
            models.Index(fields=["sg_uf"]),
        ]
    
    def __str__(self):
        return f"Recompra {self.nr_ordem} - {self.nm_municipio or 'Sem município'}"


class ImportacaoFPD(models.Model):
    """Modelo para importação de dados FPD (Faturas Pagas/Detalhadas)"""
    
    # Chaves de matching
    nr_ordem = models.CharField(max_length=100, db_index=True, help_text="Número de Ordem (O.S)")
    numero_os = models.CharField(max_length=100, null=True, blank=True, db_index=True, help_text="Alternativa NR_OS")
    id_contrato = models.CharField(max_length=100, help_text="ID_CONTRATO do arquivo FPD")
    
    # Dados da fatura
    nr_fatura = models.CharField(max_length=100, help_text="NR_FATURA do arquivo FPD")
    dt_venc_orig = models.DateField(help_text="Data de vencimento original")
    dt_pagamento = models.DateField(null=True, blank=True, help_text="Data de pagamento")
    nr_dias_atraso = models.IntegerField(default=0, help_text="Número de dias em atraso")
    ds_status_fatura = models.CharField(max_length=50, help_text="Status da fatura (PAGO, ABERTO, VENCIDO, etc)")
    vl_fatura = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Valor da fatura")
    
    # Vínculo com ContratoM10
    contrato_m10 = models.ForeignKey(
        ContratoM10, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='importacoes_fpd'
    )
    
    # Timestamps
    importada_em = models.DateTimeField(auto_now_add=True, help_text="Data da importação")
    atualizada_em = models.DateTimeField(auto_now=True, help_text="Data da última atualização")
    
    class Meta:
        verbose_name = "Importação FPD"
        verbose_name_plural = "Importações FPD"
        ordering = ["-importada_em"]
        indexes = [
            models.Index(fields=["nr_ordem"]),
            models.Index(fields=["id_contrato"]),
            models.Index(fields=["ds_status_fatura"]),
        ]
    
    def __str__(self):
        return f"FPD {self.nr_ordem} - Fatura {self.nr_fatura}"


class LogImportacaoFPD(models.Model):
    """Log de importações FPD"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    total_linhas = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    sucesso = models.IntegerField(default=0)
    erros = models.IntegerField(default=0)
    total_contratos_nao_encontrados = models.IntegerField(default=0)
    total_valor_importado = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    exemplos_nao_encontrados = models.TextField(blank=True, null=True)
    data_importacao = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Log Importação FPD"
        verbose_name_plural = "Logs Importação FPD"
        ordering = ["-data_importacao"]
    
    def __str__(self):
        return f"Log FPD {self.nome_arquivo} - {self.status}"
    
    def calcular_duracao(self):
        """Calcula duração em segundos entre início e fim"""
        if self.iniciado_em and self.finalizado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())

    # Compatível com chamadas existentes nos views: calcula a duração usando data_importacao
    # e um possível atributo finalizado_em (quando presente). Ignora silenciosamente se
    # os campos extras não existirem na base.
    def calcular_duracao(self):
        inicio = getattr(self, 'data_importacao', None) or getattr(self, 'iniciado_em', None)
        fim = getattr(self, 'finalizado_em', None)
        if not fim:
            try:
                from django.utils import timezone
                fim = timezone.now()
            except Exception:
                return None
        if not inicio or not fim:
            return None
        duracao = int((fim - inicio).total_seconds()) if hasattr(fim, '__sub__') else None
        if duracao is not None and hasattr(self, 'duracao_segundos'):
            self.duracao_segundos = duracao
        return duracao


class LogImportacaoOSAB(models.Model):
    """Log de importações OSAB"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas OSAB
    total_registros = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    criados = models.IntegerField(default=0)
    atualizados = models.IntegerField(default=0)
    vendas_encontradas = models.IntegerField(default=0)
    ja_corretos = models.IntegerField(default=0)
    erros_count = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    # Flags de controle
    enviar_whatsapp = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Log Importação OSAB"
        verbose_name_plural = "Logs Importação OSAB"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"


class LogImportacaoLegado(models.Model):
    """Log de importações de Vendas Legado (Históricas)"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas Legado
    total_linhas = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    vendas_criadas = models.IntegerField(default=0)
    vendas_atualizadas = models.IntegerField(default=0)
    clientes_criados = models.IntegerField(default=0)
    erros_count = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    class Meta:
        verbose_name = "Log Importação Legado"
        verbose_name_plural = "Logs Importação Legado"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"


class LogImportacaoAgendamento(models.Model):
    """Log de importações de Agendamentos"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas Agendamento
    total_linhas = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    agendamentos_criados = models.IntegerField(default=0)
    agendamentos_atualizados = models.IntegerField(default=0)
    nao_encontrados = models.IntegerField(default=0)
    erros_count = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    class Meta:
        verbose_name = "Log Importação Agendamento"
        verbose_name_plural = "Logs Importação Agendamento"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"


class ImportacaoChurn(models.Model):
    """Modelo para importação de dados de CHURN da operadora"""
    
    # Localização
    uf = models.CharField(max_length=2, null=True, blank=True)
    produto = models.CharField(max_length=255, null=True, blank=True)
    
    # Vendedor
    matricula_vendedor = models.CharField(max_length=50, null=True, blank=True, verbose_name="Matrícula do Vendedor")
    
    # Gestão
    gv = models.CharField(max_length=255, null=True, blank=True)
    sap_principal_fim = models.CharField(max_length=255, null=True, blank=True)
    gestao = models.CharField(max_length=255, null=True, blank=True)
    st_regional = models.CharField(max_length=255, null=True, blank=True)
    gc = models.CharField(max_length=255, null=True, blank=True)
    
    # Identificação
    numero_pedido = models.CharField(max_length=50, null=True, blank=True, unique=True, verbose_name="Número do Pedido")
    nr_ordem = models.CharField(max_length=100, null=True, blank=True, db_index=True, verbose_name="Número de Ordem")
    
    # Datas
    dt_gross = models.DateField(null=True, blank=True, verbose_name="Data Gross")
    anomes_gross = models.CharField(max_length=6, null=True, blank=True, verbose_name="Ano/Mês Gross")
    dt_retirada = models.DateField(null=True, blank=True, verbose_name="Data Retirada")
    anomes_retirada = models.CharField(max_length=6, null=True, blank=True, verbose_name="Ano/Mês Retirada")
    
    # Outros
    grupo_unidade = models.CharField(max_length=255, null=True, blank=True)
    codigo_sap = models.CharField(max_length=50, null=True, blank=True)
    municipio = models.CharField(max_length=255, null=True, blank=True)
    tipo_retirada = models.CharField(max_length=255, null=True, blank=True)
    motivo_retirada = models.CharField(max_length=255, null=True, blank=True)
    submotivo_retirada = models.CharField(max_length=255, null=True, blank=True)
    classificacao = models.CharField(max_length=255, null=True, blank=True)
    desc_apelido = models.CharField(max_length=255, null=True, blank=True)
    
    class Meta:
        verbose_name = "Importação Churn"
        verbose_name_plural = "Importações Churn"
        db_table = "crm_importacao_churn"
    
    def __str__(self):
        return f"Churn {self.numero_pedido} - {self.dt_retirada or 'Sem data'}"


class LogImportacaoChurn(models.Model):
    """Log de importações CHURN"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Sucesso Parcial'),
    ]
    
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='logs_importacao_churn'
    )
    nome_arquivo = models.CharField(max_length=255, help_text="Nome do arquivo importado")
    tamanho_arquivo = models.IntegerField(help_text="Tamanho do arquivo em bytes")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PROCESSANDO')
    
    # Timestamps
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    duracao_segundos = models.IntegerField(null=True, blank=True, help_text="Duração em segundos")
    
    # Estatísticas
    total_linhas = models.IntegerField(default=0, help_text="Total de linhas no arquivo")
    total_processadas = models.IntegerField(default=0, help_text="Linhas processadas com sucesso")
    total_erros = models.IntegerField(default=0, help_text="Linhas com erro")
    total_contratos_cancelados = models.IntegerField(default=0, help_text="Contratos M10 cancelados")
    total_contratos_reativados = models.IntegerField(default=0, help_text="Contratos M10 reativados")
    total_nao_encontrados = models.IntegerField(default=0, help_text="O.S não encontradas no M10")
    
    # Detalhes
    mensagem_erro = models.TextField(null=True, blank=True, help_text="Mensagem de erro se houver")
    detalhes_json = models.JSONField(default=dict, blank=True, help_text="Detalhes adicionais em JSON")
    
    class Meta:
        verbose_name = "Log Importação CHURN"
        verbose_name_plural = "Logs Importações CHURN"
        ordering = ["-iniciado_em"]
        indexes = [
            models.Index(fields=["-iniciado_em"]),
            models.Index(fields=["status"]),
        ]
    
    def __str__(self):
        return f"Log CHURN {self.nome_arquivo} - {self.get_status_display()}"


class LogImportacaoDFV(models.Model):
    """Log de importações DFV (Dados do Faturamento de Vendas)"""
    
    STATUS_CHOICES = [
        ('PROCESSANDO', 'Processando'),
        ('SUCESSO', 'Sucesso'),
        ('ERRO', 'Erro'),
        ('PARCIAL', 'Parcial'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    nome_arquivo = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    tamanho_arquivo = models.IntegerField(default=0, null=True, blank=True)
    iniciado_em = models.DateTimeField(auto_now_add=True)
    finalizado_em = models.DateTimeField(blank=True, null=True)
    duracao_segundos = models.IntegerField(blank=True, null=True)
    
    # Métricas específicas DFV
    total_registros = models.IntegerField(default=0)
    total_processadas = models.IntegerField(default=0)
    sucesso = models.IntegerField(default=0)
    erros = models.IntegerField(default=0)
    total_valor_importado = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    contratos_nao_encontrados = models.IntegerField(default=0)
    
    mensagem = models.TextField(blank=True, null=True)
    mensagem_erro = models.TextField(blank=True, null=True)
    detalhes_json = models.JSONField(default=dict, blank=True, null=True)
    
    class Meta:
        verbose_name = "Log Importação DFV"
        verbose_name_plural = "Logs Importação DFV"
        ordering = ['-iniciado_em']
    
    def calcular_duracao(self):
        """Calcula duração em segundos se finalizado"""
        if self.finalizado_em and self.iniciado_em:
            delta = self.finalizado_em - self.iniciado_em
            self.duracao_segundos = int(delta.total_seconds())
            self.save(update_fields=['duracao_segundos'])
    
    def __str__(self):
        return f"{self.nome_arquivo} - {self.status} ({self.iniciado_em.strftime('%d/%m/%Y %H:%M')})"