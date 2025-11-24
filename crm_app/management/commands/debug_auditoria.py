from django.core.management.base import BaseCommand
from crm_app.models import Venda, StatusCRM

class Command(BaseCommand):
    help = 'Investiga a ultima venda para entender porque nao vai para auditoria'

    def handle(self, *args, **options):
        v = Venda.objects.last()
        if not v:
            self.stdout.write("Nenhuma venda encontrada no banco.")
            return

        self.stdout.write(f"--- VENDA #{v.id} - Cliente: {v.cliente} ---")
        self.stdout.write(f"Criada em: {v.data_criacao}")
        self.stdout.write(f"Vendedor: {v.vendedor}")
        self.stdout.write(f"Status Tratamento Atual: {v.status_tratamento}")
        self.stdout.write(f"Status Esteira Atual: {v.status_esteira}")
        self.stdout.write("----------------------------------")

        # Verifica se o status existe no banco com o nome exato
        status_correto = StatusCRM.objects.filter(nome__iexact="SEM TRATAMENTO", tipo__iexact="Tratamento").first()
        if status_correto:
            self.stdout.write(f"CHECK: O status 'SEM TRATAMENTO' existe no banco? SIM (ID: {status_correto.id})")
        else:
            self.stdout.write("CHECK: O status 'SEM TRATAMENTO' existe no banco? NÃO (Isso é o problema!)")

        # Diagnóstico Final
        if not v.status_tratamento:
            self.stdout.write("\n[DIAGNÓSTICO]: O campo 'status_tratamento' está VAZIO (None).")
            self.stdout.write("MOTIVO: O sistema tentou salvar, mas não encontrou o status padrão no banco.")
            self.stdout.write("SOLUÇÃO: Cadastre um status com Nome 'SEM TRATAMENTO' e Tipo 'Tratamento' na Governança.")
        elif v.status_esteira:
            self.stdout.write("\n[DIAGNÓSTICO]: A venda já tem 'status_esteira'.")
            self.stdout.write("MOTIVO: Vendas com status de esteira (Instalada, Cancelada, etc) saem automaticamente da Auditoria.")
        else:
            self.stdout.write("\n[DIAGNÓSTICO]: Os dados parecem corretos para Auditoria.")
            self.stdout.write("Se não aparece na tela, o problema pode ser o filtro de PERFIL no 'views.py' (ex: Vendedor não vê auditoria).")