"""
Guia PRÁTICO para sincronizar banco de Produção (MySQL/JawsDB) para Local (SQLite)

MELHOR OPÇÃO: Usar dumpdata/loaddata do Django (não precisa de MySQL instalado)
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent

def opcao_1_via_django():
    """
    OPÇÃO 1: Usar Django dumpdata/loaddata (RECOMENDADO)
    Funciona sem MySQL instalado, pois faz dump via Django ORM
    """
    print("\n" + "="*80)
    print("📦 OPÇÃO 1: Exportar dados via Django (RECOMENDADO)")
    print("="*80)
    print("""
PASSO 1: Na produção (Heroku), fazer dump:
  heroku run python manage.py dumpdata > backup.json --app record-pap-app-80fd14bb6cb5

PASSO 2: Baixar o arquivo:
  heroku run python manage.py dumpdata --app record-pap-app-80fd14bb6cb5 > backup.json

PASSO 3: Restaurar localmente:
  # Apagar dados locais atuais
  python manage.py flush --no-input
  
  # Restaurar do backup
  python manage.py loaddata backup.json

✅ Vantagem: Não precisa MySQL instalado!
⚠️  Nota: Alguns dados podem não ser totalmente portáveis entre SQLite e MySQL
""")

def opcao_2_via_heroku_cli():
    """
    OPÇÃO 2: Usar Heroku CLI para fazer backup MySQL
    """
    print("\n" + "="*80)
    print("🗄️  OPÇÃO 2: Backup via Heroku CLI (MySQL → MySQL)")
    print("="*80)
    print("""
PASSO 1: Instalar Heroku CLI:
  https://devcenter.heroku.com/articles/heroku-cli

PASSO 2: Login no Heroku:
  heroku login

PASSO 3: Fazer backup:
  heroku pg:backups:capture --app record-pap-app-80fd14bb6cb5 --wait
  heroku pg:backups:download --app record-pap-app-80fd14bb6cb5 -o backup.sql

PASSO 4: Restaurar localmente (precisa MySQL):
  mysql -u root -p < backup.sql

⚠️  Problema: Se tiver MySQL, precisa restaurar no MySQL, depois converter para SQLite
""")

def opcao_3_via_jawsdb():
    """
    OPÇÃO 3: Download direto do JawsDB
    """
    print("\n" + "="*80)
    print("☁️  OPÇÃO 3: Download direto do JawsDB")
    print("="*80)
    print("""
PASSO 1: Acessar painel JawsDB:
  https://www.jawsdb.com/dashboard

PASSO 2: Encontrar sua instância:
  - Procure por 'record' ou 'pap' na lista
  - Clique nela

PASSO 3: Fazer backup:
  - Aba "Backups"
  - Botão "Create Backup"
  - Aguarde alguns minutos

PASSO 4: Download:
  - Aba "Backups"
  - Clique "Download" no backup criado
  - Salve como: c:\\site-record\\backup_producao.sql

PASSO 5: Converter SQL para JSON (usar com Django):
  python manage.py flush --no-input
  
  # Se tiver MySQL:
  mysql -u root -p < backup_producao.sql
  python manage.py dumpdata > backup.json
  python manage.py flush --no-input
  python manage.py loaddata backup.json
""")

def main():
    print("\n" + "="*80)
    print("🔄 GUIA: SINCRONIZAR BANCO PRODUÇÃO → LOCAL")
    print("="*80)
    print("""
Você tem 3 opções:

1️⃣  OPÇÃO 1: Django dumpdata/loaddata (MAIS RÁPIDO E SIMPLES)
    ✅ Não precisa MySQL instalado
    ✅ Funciona entre qualquer banco
    
2️⃣  OPÇÃO 2: Heroku CLI (precisa MySQL)
    ✅ Backup completo
    ⚠️  Requer MySQL instalado
    
3️⃣  OPÇÃO 3: JawsDB Dashboard (manual, mais seguro)
    ✅ Controle manual
    ✅ Seguro
    ⚠️  Mais passos
""")
    
    while True:
        escolha = input("\nQual opção você prefere? (1, 2, 3 ou 'sair'): ").strip().lower()
        
        if escolha == '1':
            opcao_1_via_django()
        elif escolha == '2':
            opcao_2_via_heroku_cli()
        elif escolha == '3':
            opcao_3_via_jawsdb()
        elif escolha == 'sair':
            print("\nSaindo...")
            sys.exit(0)
        else:
            print("❌ Opção inválida. Digite 1, 2, 3 ou 'sair'")

if __name__ == '__main__':
    main()
    input("\nPressione ENTER para sair...")
