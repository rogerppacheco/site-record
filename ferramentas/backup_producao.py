"""
Script para fazer backup do banco de produção (Heroku/MySQL) e restaurar localmente

REQUISITOS:
1. Heroku CLI instalado: https://devcenter.heroku.com/articles/heroku-cli
2. MySQL instalado localmente
3. Credenciais do Heroku configuradas: heroku login

PASSO A PASSO:
1. Execute este script: python backup_producao.py
2. Script vai fazer download do banco em produção
3. Restaurar no SQLite local
4. Testar e validar os dados
"""

import os
import sys
import subprocess
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def executar_comando(cmd, descricao=""):
    """Executa comando no terminal"""
    print(f"\n{'='*80}")
    print(f"🔄 {descricao}")
    print(f"{'='*80}")
    print(f"Comando: {cmd}\n")
    
    resultado = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if resultado.stdout:
        print(resultado.stdout)
    if resultado.stderr:
        print("⚠️  STDERR:", resultado.stderr)
    
    return resultado.returncode == 0

def fazer_backup_producao():
    """Faz backup do MySQL em produção via Heroku"""
    
    print("\n" + "="*80)
    print("📦 BACKUP DO BANCO DE PRODUÇÃO")
    print("="*80)
    
    # 1. Verificar se Heroku CLI está instalado
    print("\n✅ Verificando Heroku CLI...")
    if not executar_comando("heroku --version", "Verificando Heroku CLI"):
        print("❌ Heroku CLI não está instalado!")
        print("Instale em: https://devcenter.heroku.com/articles/heroku-cli")
        return False
    
    # 2. Fazer login no Heroku (se necessário)
    print("\n✅ Verificando autenticação Heroku...")
    if not executar_comando("heroku auth:whoami", "Verificando login Heroku"):
        print("⚠️  Não autenticado. Execute: heroku login")
        return False
    
    # 3. Criar backup no JawsDB
    print("\n✅ Criando backup no banco de produção...")
    app_name = "record-pap-app-80fd14bb6cb5"
    
    if not executar_comando(
        f"heroku pg:backups:capture --app {app_name} --wait 2>&1 || heroku addons:open jawsdb --app {app_name}",
        "Solicitando backup no JawsDB"
    ):
        print("⚠️  Não conseguiu criar backup automático")
        print("Acesse a interface JawsDB manualmente e faça download do dump")
        return False
    
    # 4. Fazer download via Heroku
    print("\n✅ Fazendo download do backup...")
    backup_file = BASE_DIR / f"backup_producao_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    
    if not executar_comando(
        f"heroku pg:backups:download --app {app_name} -o {backup_file}",
        "Baixando arquivo do backup"
    ):
        print(f"⚠️  Não conseguiu baixar via heroku, tente manualmente em:")
        print(f"   https://www.jawsdb.com/dashboard -> Backup -> Download")
        return False
    
    print(f"\n✅ Backup salvo em: {backup_file}")
    return str(backup_file)

def restaurar_sqlite_manualmente():
    """Instrui o usuário a restaurar manualmente via MySQL"""
    
    print("\n" + "="*80)
    print("📥 RESTAURAÇÃO MANUAL (OPÇÃO ALTERNATIVA)")
    print("="*80)
    print("""
Se o script acima não funcionar, siga estes passos:

1. ACESSAR JAWSDB NA INTERFACE:
   - Acesse: https://www.jawsdb.com/dashboard
   - Encontre sua instância de banco
   - Clique em "Actions" → "Create Backup"
   - Aguarde a criação
   - Clique em "Download" para baixar o arquivo SQL

2. SALVAR O ARQUIVO:
   - Salve em: c:\\site-record\\backup_producao.sql

3. RESTAURAR LOCALMENTE (Windows PowerShell):
   # Se tiver MySQL instalado:
   mysql -u root -p < backup_producao.sql

4. CONVERTER PARA SQLITE (opcional):
   python manage.py dumpdata > dados_producao.json
   python manage.py flush
   python manage.py loaddata dados_producao.json
""")

def validar_dados_locais():
    """Valida os dados restaurados localmente"""
    
    print("\n" + "="*80)
    print("✅ VALIDANDO DADOS LOCAIS")
    print("="*80)
    
    db_path = BASE_DIR / 'db.sqlite3'
    
    if not db_path.exists():
        print(f"❌ Banco local não encontrado: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Contar registros principais
        tabelas = [
            'usuarios_usuario',
            'crm_app_contratoM10',
            'crm_app_faturasm10',
            'crm_app_importacaochurn',
            'crm_app_logimportacaochurn'
        ]
        
        print("\n📊 Contagem de registros:\n")
        total = 0
        for tabela in tabelas:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {tabela}")
                count = cursor.fetchone()[0]
                total += count
                print(f"  {tabela}: {count:,} registros")
            except sqlite3.OperationalError:
                print(f"  {tabela}: ⚠️  Tabela não encontrada")
        
        print(f"\n  TOTAL: {total:,} registros")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Erro ao validar: {e}")
        return False

def main():
    print("\n" + "="*80)
    print("🚀 SINCRONIZADOR BANCO PRODUÇÃO → LOCAL")
    print("="*80)
    
    # Opções
    print("""
OPÇÕES:
1. Fazer backup via Heroku CLI (automático)
2. Instruções para restauração manual (JawsDB)
3. Validar dados locais
4. Sair
""")
    
    escolha = input("\nEscolha uma opção (1-4): ").strip()
    
    if escolha == "1":
        backup_file = fazer_backup_producao()
        if backup_file:
            print(f"\n✅ Backup criado com sucesso: {backup_file}")
            print("Próximo passo: Restaurar manualmente via MySQL ou converter para SQLite")
    
    elif escolha == "2":
        restaurar_sqlite_manualmente()
    
    elif escolha == "3":
        validar_dados_locais()
    
    elif escolha == "4":
        print("Saindo...")
        sys.exit(0)
    
    else:
        print("❌ Opção inválida")

if __name__ == '__main__':
    main()
    input("\nPressione ENTER para sair...")
