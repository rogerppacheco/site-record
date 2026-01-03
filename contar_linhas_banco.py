"""
Script para contar total de linhas em todas as tabelas do banco
"""
from django.db import connection
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'record_crm.settings')
django.setup()

cursor = connection.cursor()

# Pega todas as tabelas
cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
tables = cursor.fetchall()

print("\n" + "="*60)
print("CONTAGEM DE LINHAS POR TABELA")
print("="*60)

total = 0
tabelas_detalhes = []

for table in tables:
    table_name = table[0]
    try:
        cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
        count = cursor.fetchone()[0]
        tabelas_detalhes.append((table_name, count))
        total += count
    except Exception as e:
        print(f"Erro em {table_name}: {e}")

# Ordena por quantidade decrescente
tabelas_detalhes.sort(key=lambda x: x[1], reverse=True)

# Mostra top 15
print("\nTOP 15 TABELAS COM MAIS LINHAS:")
print("-"*60)
for i, (table_name, count) in enumerate(tabelas_detalhes[:15], 1):
    print(f"{i:2}. {table_name:40} {count:>8,} linhas")

print("-"*60)
print(f"TOTAL GERAL: {total:,} linhas")
print("="*60)

# Análise
print("\n📊 ANÁLISE:")
if total < 5000:
    print(f"✅ Muito confortável! Você está usando apenas {(total/10000)*100:.1f}% do limite de 10k")
    print("   Postgres Hobby Dev (gratuito) é perfeito para você!")
elif total < 8000:
    print(f"✅ Confortável! Você está usando {(total/10000)*100:.1f}% do limite de 10k")
    print("   Postgres Hobby Dev funciona bem, mas planeje upgrade em 6-12 meses")
elif total < 10000:
    print(f"⚠️  Atenção! Você está usando {(total/10000)*100:.1f}% do limite de 10k")
    print("   Considere já migrar para Standard-0 ($50/mês)")
else:
    print(f"🚨 LIMITE EXCEDIDO! Você tem {total:,} linhas (limite 10k)")
    print("   Você PRECISA do Standard-0 ($50/mês)")

print()
