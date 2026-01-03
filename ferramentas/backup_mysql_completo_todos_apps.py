#!/usr/bin/env python
"""
Backup COMPLETO do MySQL (JawsDB Heroku) - TODOS OS APPS
Inclui: crm_app, usuarios, osab, presenca, relatorios, core, auth, contenttypes
"""
import os
import django
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

# FORÇA usar MySQL de produção
os.environ['JAWSDB_URL'] = 'mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45'
os.environ.pop('DATABASE_URL', None)  # Remove PostgreSQL se existir

django.setup()

from django.core.management import call_command

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_file = f'backup_mysql_completo_{timestamp}.json'

print("="*60)
print("📦 BACKUP COMPLETO - TODOS OS APPS DO MYSQL")
print("="*60)
print(f"\n🎯 Origem: JawsDB MySQL (Produção)")
print(f"📁 Destino: {backup_file}\n")

# Lista de TODOS os apps que têm dados
apps_para_backup = [
    'contenttypes',  # Django base
    'auth',          # Usuários Django, permissões, grupos
    'sessions',      # Sessões
    'admin',         # Log do admin
    'usuarios',      # APP CRÍTICO - seus usuários customizados
    'crm_app',       # Dados principais
    'osab',          # Ordens de serviço
    'presenca',      # Presença/RH
    'relatorios',    # Relatórios
    'core',          # Core do sistema
]

print("📋 Apps incluídos no backup:")
for app in apps_para_backup:
    print(f"   - {app}")

print(f"\n🚀 Iniciando exportação...")

try:
    # dumpdata com natural keys para evitar problemas de FK
    call_command(
        'dumpdata',
        *apps_para_backup,
        natural_foreign=True,
        natural_primary=True,
        indent=2,
        output=backup_file
    )
    
    # Verifica tamanho
    import os
    size_mb = os.path.getsize(backup_file) / (1024 * 1024)
    
    print(f"\n✅ BACKUP COMPLETO CRIADO!")
    print(f"📊 Arquivo: {backup_file}")
    print(f"💾 Tamanho: {size_mb:.2f} MB")
    print(f"\n⚠️  IMPORTANTE: Use ESTE arquivo para migrar para PostgreSQL!")
    
except Exception as e:
    print(f"\n❌ Erro ao criar backup: {e}")
    import traceback
    traceback.print_exc()
