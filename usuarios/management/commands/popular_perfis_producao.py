"""
Comando para popular perfis em produção
Cria os perfis básicos: Diretoria, BackOffice, Supervisor, Vendedor
"""
from django.core.management.base import BaseCommand
from usuarios.models import Perfil


class Command(BaseCommand):
    help = 'Cria os perfis básicos em produção (Diretoria, BackOffice, Supervisor, Vendedor)'

    def handle(self, *args, **options):
        perfis_data = [
            {'nome': 'Diretoria', 'cod_perfil': 'diretoria', 'descricao': 'Diretoria'},
            {'nome': 'BackOffice', 'cod_perfil': 'backoffice', 'descricao': 'BackOffice'},
            {'nome': 'Supervisor', 'cod_perfil': 'supervisor', 'descricao': 'Supervisor'},
            {'nome': 'Vendedor', 'cod_perfil': 'vendedor', 'descricao': 'Vendedor'},
        ]
        
        criados = 0
        for perfil_data in perfis_data:
            perfil, created = Perfil.objects.get_or_create(
                cod_perfil=perfil_data['cod_perfil'],
                defaults={
                    'nome': perfil_data['nome'],
                    'descricao': perfil_data.get('descricao', '')
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Perfil criado: {perfil.nome}'))
                criados += 1
            else:
                self.stdout.write(f'Perfil já existe: {perfil.nome}')
        
        self.stdout.write(self.style.SUCCESS(f'\nTotal: {criados} perfis criados, {Perfil.objects.count()} perfis no total'))
