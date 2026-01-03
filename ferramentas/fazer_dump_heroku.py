"""
Script para fazer dump do Heroku e salvar com encoding correto
"""
import subprocess
import json

print("📥 Baixando dados da produção (Heroku)...")

# Rodar comando no Heroku
result = subprocess.run(
    'heroku run python manage.py dumpdata --app record-pap-app',
    shell=True,
    capture_output=True,
    text=True
)

if result.returncode != 0:
    print(f"❌ Erro: {result.stderr}")
    exit(1)

# Extrair apenas o JSON (remove output do Heroku)
output_lines = result.stdout.split('\n')
json_start = None

for i, line in enumerate(output_lines):
    if line.strip().startswith('['):
        json_start = i
        break

if json_start is None:
    print("❌ Não conseguiu extrair JSON do output")
    exit(1)

json_str = '\n'.join(output_lines[json_start:])

# Validar JSON
try:
    data = json.loads(json_str)
    print(f"✅ JSON válido com {len(data)} registros")
except json.JSONDecodeError as e:
    print(f"❌ Erro ao parsear JSON: {e}")
    exit(1)

# Salvar com encoding UTF-8
with open('backup.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"✅ Backup salvo em: backup.json")
print(f"   Registros: {len(data)}")

# Próximo passo
print("\n" + "="*80)
print("PRÓXIMO PASSO: Restaurar dados")
print("="*80)
print("\nExecute: python manage.py loaddata backup.json --verbosity 2")
