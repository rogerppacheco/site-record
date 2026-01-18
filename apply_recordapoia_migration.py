#!/usr/bin/env python
"""
Script para aplicar a migração RecordApoia de verdade
Remove a marcação fake e aplica a migração real
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.db import connection
from django.core.management import call_command

def apply_recordapoia_migration():
    """Remove marcação fake e aplica migração de verdade"""
    print("=" * 80)
    print("🔧 APLICANDO MIGRAÇÃO RecordApoia (0071)")
    print("=" * 80)
    
    with connection.cursor() as cursor:
        # Verificar se a migração está marcada como aplicada
        cursor.execute("""
            SELECT COUNT(*) FROM django_migrations 
            WHERE app = 'crm_app' AND name = '0071_recordapoia';
        """)
        ja_marcada = cursor.fetchone()[0] > 0
        
        if ja_marcada:
            print("\n📝 Migração 0071_recordapoia está marcada como aplicada (fake).")
            print("   Removendo marcação fake...")
            
            # Remover a entrada fake
            cursor.execute("""
                DELETE FROM django_migrations 
                WHERE app = 'crm_app' AND name = '0071_recordapoia';
            """)
            print("✅ Marcação fake removida.")
        
        # Verificar se a tabela já existe
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'crm_app_recordapoia'
            );
        """)
        tabela_existe = cursor.fetchone()[0]
        
        if tabela_existe:
            print("\n⚠️  Tabela crm_app_recordapoia JÁ EXISTE no banco!")
            print("   Se a tabela já existe, vamos apenas marcar como aplicada (fake).")
            try:
                call_command('migrate', 'crm_app', '0071', '--fake', verbosity=1)
                print("✅ Migração marcada como aplicada (fake).")
            except Exception as e:
                print(f"❌ Erro: {e}")
                return False
        else:
            print("\n📝 Tabela não existe. Aplicando migração de verdade...")
            try:
                call_command('migrate', 'crm_app', '0071', verbosity=1)
                print("✅ Migração aplicada com sucesso!")
            except Exception as e:
                print(f"❌ Erro ao aplicar migração: {e}")
                import traceback
                traceback.print_exc()
                return False
        
        return True

if __name__ == '__main__':
    try:
        sucesso = apply_recordapoia_migration()
        if sucesso:
            print("\n" + "=" * 80)
            print("✅ PROCESSO CONCLUÍDO!")
            print("=" * 80)
        else:
            print("\n❌ Erro ao aplicar migração.")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
