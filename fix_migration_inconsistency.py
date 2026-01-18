#!/usr/bin/env python
"""
Script para corrigir inconsistência de migrações:
Migration admin.0001_initial is applied before its dependency usuarios.0001_initial

Este script marca usuarios.0001_initial como aplicada (fake) se as tabelas já existem.
"""
import os
import sys
import django

# Configurar Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.db import connection
from django.core.management import call_command
from django.core.management.base import CommandError

def check_table_exists(table_name):
    """Verifica se uma tabela existe no banco"""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            );
        """, [table_name])
        return cursor.fetchone()[0]

def fix_migration_inconsistency():
    """Corrige a inconsistência de migrações"""
    print("=" * 80)
    print("🔧 CORRIGINDO INCONSISTÊNCIA DE MIGRAÇÕES")
    print("=" * 80)
    
    # Verificar se as tabelas do app usuarios já existem
    tabelas_usuarios = ['usuarios_perfil', 'usuarios_usuario']
    todas_existem = all(check_table_exists(tabela) for tabela in tabelas_usuarios)
    
    if not todas_existem:
        print("\n❌ Erro: As tabelas do app 'usuarios' não existem no banco!")
        print("   Isso não é apenas uma inconsistência de histórico.")
        print("   Você precisa aplicar as migrações normalmente.")
        return False
    
    print("\n✅ Tabelas do app 'usuarios' já existem no banco.")
    print("\n📋 Verificando estado das migrações...")
    
    # Verificar se a migração está marcada como aplicada
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM django_migrations 
            WHERE app = 'usuarios' AND name = '0001_initial';
        """)
        ja_aplicada = cursor.fetchone()[0] > 0
    
    if ja_aplicada:
        print("✅ Migração usuarios.0001_initial já está marcada como aplicada.")
        print("   O problema pode ser outra coisa. Verificando admin...")
        
        # Verificar admin
        cursor.execute("""
            SELECT COUNT(*) FROM django_migrations 
            WHERE app = 'admin' AND name = '0001_initial';
        """)
        admin_aplicada = cursor.fetchone()[0] > 0
        
        if admin_aplicada:
            print("⚠️  Ambas as migrações estão marcadas como aplicadas.")
            print("   Pode ser um problema de dependência circular ou ordem incorreta.")
            print("\n💡 Tentando executar: python manage.py migrate --fake usuarios 0001")
            return False
    else:
        print("📝 Migração usuarios.0001_initial NÃO está marcada como aplicada.")
        print("   Como as tabelas já existem, vamos marcar como fake aplicada...")
        
        try:
            # Marcar como fake aplicada
            call_command('migrate', 'usuarios', '0001', '--fake', verbosity=1)
            print("\n✅ Migração usuarios.0001_initial marcada como aplicada (fake)!")
            return True
        except CommandError as e:
            print(f"\n❌ Erro ao marcar migração como fake: {e}")
            print("\n💡 Tente executar manualmente:")
            print("   python manage.py migrate usuarios 0001 --fake")
            return False

if __name__ == '__main__':
    try:
        sucesso = fix_migration_inconsistency()
        if sucesso:
            print("\n" + "=" * 80)
            print("✅ CORREÇÃO CONCLUÍDA!")
            print("=" * 80)
            print("\nAgora você pode executar:")
            print("  python manage.py makemigrations")
            print("  python manage.py migrate")
        else:
            print("\n" + "=" * 80)
            print("⚠️  CORREÇÃO NÃO COMPLETA")
            print("=" * 80)
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
