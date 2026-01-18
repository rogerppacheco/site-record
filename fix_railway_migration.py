#!/usr/bin/env python
"""
Script para corrigir inconsistência de migrações no Railway:
Insere usuarios.0001_initial na tabela django_migrations com timestamp correto
"""
import os
import sys
import django
from datetime import datetime

# Configurar Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.db import connection
from django.utils import timezone

def fix_railway_migration():
    """Insere usuarios.0001_initial na tabela django_migrations se não existir"""
    print("=" * 80)
    print("🔧 CORRIGINDO MIGRAÇÃO NO RAILWAY")
    print("=" * 80)
    
    with connection.cursor() as cursor:
        # Verificar se usuarios.0001_initial já está registrada
        cursor.execute("""
            SELECT COUNT(*) FROM django_migrations 
            WHERE app = 'usuarios' AND name = '0001_initial';
        """)
        ja_existe = cursor.fetchone()[0] > 0
        
        if ja_existe:
            print("\n✅ Migração usuarios.0001_initial já está registrada.")
            print("   O problema pode ser de ordem/timestamp.")
            
            # Verificar timestamp de admin.0001_initial
            cursor.execute("""
                SELECT applied FROM django_migrations 
                WHERE app = 'admin' AND name = '0001_initial'
                LIMIT 1;
            """)
            result = cursor.fetchone()
            if result:
                admin_timestamp = result[0]
                print(f"   admin.0001_initial aplicada em: {admin_timestamp}")
            
            # Verificar timestamp de usuarios.0001_initial
            cursor.execute("""
                SELECT applied FROM django_migrations 
                WHERE app = 'usuarios' AND name = '0001_initial'
                LIMIT 1;
            """)
            result = cursor.fetchone()
            if result:
                usuarios_timestamp = result[0]
                print(f"   usuarios.0001_initial aplicada em: {usuarios_timestamp}")
                
                # Se usuarios tem timestamp posterior a admin, atualizar para anterior
                if usuarios_timestamp > admin_timestamp:
                    print("\n📝 Atualizando timestamp de usuarios.0001_initial para antes de admin...")
                    # Criar timestamp 1 segundo antes do admin
                    novo_timestamp = admin_timestamp.replace(microsecond=admin_timestamp.microsecond - 1000000 if admin_timestamp.microsecond > 0 else 0)
                    if novo_timestamp >= admin_timestamp:
                        from datetime import timedelta
                        novo_timestamp = admin_timestamp - timedelta(seconds=1)
                    
                    cursor.execute("""
                        UPDATE django_migrations 
                        SET applied = %s 
                        WHERE app = 'usuarios' AND name = '0001_initial';
                    """, [novo_timestamp])
                    print(f"✅ Timestamp atualizado para: {novo_timestamp}")
                    return True
            return False
        else:
            print("\n📝 Migração usuarios.0001_initial NÃO está registrada.")
            print("   Inserindo registro na tabela django_migrations...")
            
            # Obter timestamp de admin.0001_initial para usar como referência
            cursor.execute("""
                SELECT applied FROM django_migrations 
                WHERE app = 'admin' AND name = '0001_initial'
                LIMIT 1;
            """)
            result = cursor.fetchone()
            if result:
                admin_timestamp = result[0]
                # Criar timestamp 1 segundo ANTES do admin
                from datetime import timedelta
                usuarios_timestamp = admin_timestamp - timedelta(seconds=1)
            else:
                # Se não encontrar admin, usar timestamp atual
                usuarios_timestamp = timezone.now()
                print("   ⚠️  admin.0001_initial não encontrada, usando timestamp atual")
            
            # Inserir registro
            cursor.execute("""
                INSERT INTO django_migrations (app, name, applied)
                VALUES ('usuarios', '0001_initial', %s)
                ON CONFLICT DO NOTHING;
            """, [usuarios_timestamp])
            
            print(f"✅ Registro inserido com timestamp: {usuarios_timestamp}")
            return True

if __name__ == '__main__':
    try:
        sucesso = fix_railway_migration()
        if sucesso:
            print("\n" + "=" * 80)
            print("✅ CORREÇÃO CONCLUÍDA!")
            print("=" * 80)
            print("\nAgora você pode executar:")
            print("  railway run python manage.py makemigrations")
            print("  railway run python manage.py migrate")
        else:
            print("\n⚠️  Nenhuma correção necessária ou problema diferente.")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
