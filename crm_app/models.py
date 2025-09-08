from django.db import models
from usuarios.models import Usuario

class Operadora(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    cnpj = models.CharField(max_length=18, unique=True, null=True, blank=True)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome
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

    def __str__(self):
        return f"{self.nome} - {self.operadora.nome}"
    class Meta:
        db_table = 'crm_plano'
        verbose_name = "Plano"
        verbose_name_plural = "Planos"

class FormaPagamento(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    ativo = models.BooleanField(default=True)
    aplica_desconto = models.BooleanField(
        default=False,
        help_text="Marque esta opção se esta forma de pagamento aplica o desconto de R$10,00 nos planos."
    )
    def __str__(self):
        return self.nome
    class Meta:
        db_table = 'crm_forma_pagamento'
        verbose_name = "Forma de Pagamento"
        verbose_name_plural = "Formas de Pagamento"

class StatusCRM(models.Model):
    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50, choices=[('Tratamento', 'Tratamento'), ('Esteira', 'Esteira'), ('Comissionamento', 'Comissionamento')])
    estado = models.CharField(max_length=50, blank=True, null=True, help_text="Ex: Pendente, Em Andamento, Finalizado, Cancelado")
    cor = models.CharField(max_length=7, default="#FFFFFF")

    def __str__(self):
        return f"{self.nome} ({self.tipo})"
    class Meta:
        db_table = 'crm_status'
        verbose_name = "Status de CRM"
        verbose_name_plural = "Status de CRM"
        unique_together = ('nome', 'tipo')

class MotivoPendencia(models.Model):
    nome = models.CharField(max_length=255)
    tipo_pendencia = models.CharField(max_length=100, help_text="Ex: Documentação, Financeiro, Técnico")

    def __str__(self):
        return self.nome
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

    def __str__(self):
        return f"Regra para {self.consultor.get_full_name()} - Plano {self.plano.nome}"
    class Meta:
        db_table = 'crm_regra_comissao'
        verbose_name = "Regra de Comissão"
        verbose_name_plural = "Regras de Comissão"
        unique_together = ('consultor', 'plano', 'tipo_venda', 'tipo_cliente')

class Cliente(models.Model):
    nome_razao_social = models.CharField(max_length=255)
    cpf_cnpj = models.CharField(max_length=18, unique=True)
    email = models.EmailField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.nome_razao_social
    class Meta:
        db_table = 'crm_cliente'
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

class Venda(models.Model):
    vendedor = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='vendas')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='vendas')
    plano = models.ForeignKey(Plano, on_delete=models.PROTECT)
    forma_pagamento = models.ForeignKey(FormaPagamento, on_delete=models.PROTECT)
    
    status_tratamento = models.ForeignKey(
        StatusCRM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendas_tratamento',
        limit_choices_to={'tipo': 'Tratamento'}
    )
    status_esteira = models.ForeignKey(
        StatusCRM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vendas_esteira',
        limit_choices_to={'tipo': 'Esteira'}
    )
    
    data_criacao = models.DateTimeField(auto_now_add=True)
    
    forma_entrada = models.CharField(max_length=10, choices=[('APP', 'APP'), ('SEM_APP', 'SEM_APP')], default='APP')
    cpf_representante_legal = models.CharField(max_length=14, blank=True, null=True)
    telefone1 = models.CharField(max_length=20, blank=True, null=True)
    telefone2 = models.CharField(max_length=20, blank=True, null=True)
    cep = models.CharField(max_length=9, blank=True, null=True)
    logradouro = models.CharField(max_length=255, blank=True, null=True)
    numero_residencia = models.CharField(max_length=20, blank=True, null=True)
    complemento = models.CharField(max_length=100, blank=True, null=True)
    bairro = models.CharField(max_length=100, blank=True, null=True)
    cidade = models.CharField(max_length=100, blank=True, null=True)
    estado = models.CharField(max_length=2, blank=True, null=True)

    # --- NOVOS CAMPOS ADICIONADOS ---
    ordem_servico = models.CharField(max_length=50, null=True, blank=True, verbose_name="Ordem de Serviço (O.S)")
    data_pedido = models.DateTimeField(null=True, blank=True, verbose_name="Data do Pedido")
    data_agendamento = models.DateField(null=True, blank=True, verbose_name="Data de Agendamento")
    periodo_agendamento = models.CharField(
        max_length=10, 
        choices=[('MANHA', 'Manhã'), ('TARDE', 'Tarde')], 
        null=True, 
        blank=True, 
        verbose_name="Período"
    )

    def __str__(self):
        return f"Venda #{self.id} - {self.cliente.nome_razao_social}"
    class Meta:
        db_table = 'crm_venda'
        verbose_name = "Venda"
        verbose_name_plural = "Vendas"