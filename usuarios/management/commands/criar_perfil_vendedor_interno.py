"""
Cria o perfil Vendedor Interno com acesso ao módulo Funil de vendas.

O perfil Vendedor não recebe essa permissão.

Uso: python manage.py criar_perfil_vendedor_interno
"""
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from crm_app.models import Venda
from crm_app.perfis_acesso import PERFIL_VENDEDOR, PERFIL_VENDEDOR_INTERNO
from usuarios.models import Perfil


class Command(BaseCommand):
    help = 'Cria o perfil Vendedor Interno com a permissão do Funil de vendas'

    def handle(self, *args, **options) -> None:
        perfil, perfil_criado = Perfil.objects.get_or_create(
            cod_perfil='vendedor_interno',
            defaults={
                'nome': PERFIL_VENDEDOR_INTERNO,
                'descricao': (
                    'Mesmas ferramentas do vendedor, mais o módulo Funil de vendas. '
                    'O perfil Vendedor não vê esse módulo.'
                ),
            },
        )
        if perfil_criado:
            self.stdout.write(self.style.SUCCESS(f'Perfil criado: {perfil.nome}'))
        else:
            self.stdout.write(f'Perfil já existe: {perfil.nome}')

        grupo, grupo_criado = Group.objects.get_or_create(name=PERFIL_VENDEDOR_INTERNO)
        if grupo_criado:
            self.stdout.write(self.style.SUCCESS(f'Grupo criado: {grupo.name}'))
        else:
            self.stdout.write(f'Grupo já existe: {grupo.name}')

        if grupo_criado or not grupo.permissions.exists():
            origem = Group.objects.filter(name__iexact=PERFIL_VENDEDOR).first()
            if origem:
                grupo.permissions.add(*list(origem.permissions.all()))
                self.stdout.write(
                    f'Permissões do perfil {PERFIL_VENDEDOR} copiadas para {PERFIL_VENDEDOR_INTERNO}.'
                )

        ct = ContentType.objects.get_for_model(Venda)
        perm = Permission.objects.filter(
            content_type=ct,
            codename='can_view_funil_vendas',
        ).first()
        if not perm:
            self.stdout.write(
                self.style.ERROR(
                    'Permissão can_view_funil_vendas não encontrada. Rode migrate antes deste comando.'
                )
            )
            return

        grupo.permissions.add(perm)
        self.stdout.write(
            self.style.SUCCESS(
                'Permissão "Pode visualizar módulo Funil de vendas" marcada em Vendedor Interno.'
            )
        )
        self.stdout.write(
            'O perfil Vendedor permanece sem essa permissão. '
            'Quem for trocado de perfil precisa entrar de novo para o card aparecer.'
        )
