"""
Script simples e direto para sincronizar banco de Produção para Local
"""

import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def main():
    print("\n" + "="*80)
    print("🔄 SINCRONIZAR BANCO: PRODUÇÃO (Heroku) → LOCAL")
    print("="*80)
    
    print("""
RECOMENDAÇÃO: Use a OPÇÃO 1 (Django dumpdata)
Não precisa instalar MySQL, funciona direto!

PASSOS:

1️⃣  FAZER DUMP NA PRODUÇÃO (Heroku):
    
    heroku run "python manage.py dumpdata --indent 2" --app record-pap-app-80fd14bb6cb5 > backup.json
    
    (Isso baixa TODOS os dados em JSON)

2️⃣  APAGAR DADOS LOCAIS:
    
    python manage.py flush --no-input
    
    (Confirme que quer apagar o banco local)

3️⃣  RESTAURAR DADOS LOCAIS:
    
    python manage.py loaddata backup.json
    
    (Carrega os dados do JSON para o SQLite local)

4️⃣  TESTAR:
    
    python manage.py runserver
    
    (Acesse http://127.0.0.1:8000 e verifique se os dados estão lá)

═════════════════════════════════════════════════════════════════════════════════

PRÓXIMOS PASSOS (escolha um):

[A] Executar PASSO 1: Fazer dump no Heroku
[B] Executar PASSO 2: Apagar dados locais  
[C] Executar PASSO 3: Restaurar dados
[D] Sair

═════════════════════════════════════════════════════════════════════════════════
""")
    
    while True:
        escolha = input("Escolha [A/B/C/D]: ").strip().upper()
        
        if escolha == 'A':
            print("\n🔽 Fazendo dump da produção (Heroku)...")
            print("Isso pode levar alguns minutos...\n")
            
            cmd = 'heroku run "python manage.py dumpdata --indent 2" --app record-pap-app-80fd14bb6cb5 > backup.json'
            print(f"Executando: {cmd}\n")
            resultado = subprocess.run(cmd, shell=True)
            
            if resultado.returncode == 0:
                print("\n✅ Dump criado com sucesso em: backup.json")
                print(f"   Tamanho: ", end="")
                subprocess.run("ls -lh backup.json", shell=True)
            else:
                print("\n❌ Erro ao fazer dump. Verifique se:")
                print("   1. Heroku CLI está instalado")
                print("   2. Você fez 'heroku login'")
                print("   3. Nome do app está correto")
        
        elif escolha == 'B':
            print("\n⚠️  ATENÇÃO: Isso vai APAGAR todos os dados locais!")
            confirmacao = input("Continuar? [SIM/NAO]: ").strip().upper()
            
            if confirmacao == 'SIM':
                print("\n🗑️  Apagando dados locais...")
                resultado = subprocess.run("python manage.py flush --no-input", shell=True)
                
                if resultado.returncode == 0:
                    print("\n✅ Dados locais apagados com sucesso")
                else:
                    print("\n❌ Erro ao apagar dados")
            else:
                print("Cancelado.")
        
        elif escolha == 'C':
            backup_file = BASE_DIR / 'backup.json'
            
            if not backup_file.exists():
                print(f"\n❌ Arquivo backup.json não encontrado em: {BASE_DIR}")
                print("Execute o PASSO 1 primeiro!")
                continue
            
            print(f"\n📥 Restaurando dados de: {backup_file}")
            print("Isso pode levar alguns minutos...\n")
            
            resultado = subprocess.run(f"python manage.py loaddata backup.json", shell=True)
            
            if resultado.returncode == 0:
                print("\n✅ Dados restaurados com sucesso!")
                print("Próximo: python manage.py runserver")
            else:
                print("\n❌ Erro ao restaurar dados")
        
        elif escolha == 'D':
            print("\nSaindo...")
            break
        
        else:
            print("❌ Opção inválida. Use [A/B/C/D]")
        
        print("\n" + "="*80)

if __name__ == '__main__':
    main()
