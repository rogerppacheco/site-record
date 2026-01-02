#!/usr/bin/env python
"""
Script para sincronizar usuários do banco em produção para o banco local.
Faz dump apenas da tabela de usuários para evitar problemas de encoding com dados grandes.
"""
import os
import json
import subprocess
import sys
from pathlib import Path

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

import django
django.setup()

from django.core.management import call_command
from io import StringIO

print("=" * 80)
print("SINCRONIZAÇÃO DE USUÁRIOS - PRODUÇÃO → LOCAL")
print("=" * 80)

# PASSO 1: Fazer dump dos usuários da produção via Heroku
print("\n[1/3] Fazendo dump dos usuários da produção via Heroku...")
try:
    # Usar heroku run com pipe direto
    result = subprocess.run(
        ['heroku', 'run', 'python manage.py dumpdata usuarios --format=json', 
         '--app', 'record-pap-app'],
        capture_output=True,
        text=True,
        timeout=60
    )
    
    if result.returncode != 0:
        print(f"❌ Erro ao fazer dump: {result.stderr}")
        sys.exit(1)
    
    # O output contém linhas do Heroku + JSON
    output_lines = result.stdout.split('\n')
    
    # Procurar pela linha que começa com '['
    json_start_idx = None
    for i, line in enumerate(output_lines):
        if line.strip().startswith('['):
            json_start_idx = i
            break
    
    if json_start_idx is None:
        print("❌ Não foi possível encontrar JSON no output")
        print(f"Output completo:\n{result.stdout}")
        sys.exit(1)
    
    # Extrair JSON
    json_str = '\n'.join(output_lines[json_start_idx:])
    usuarios_data = json.loads(json_str)
    
    print(f"✅ Dump realizado com sucesso!")
    print(f"   Total de usuários encontrados: {len(usuarios_data)}")
    
    if usuarios_data:
        for user in usuarios_data:
            print(f"   - {user['fields']['email']}")
    else:
        print("   ⚠️  Nenhum usuário encontrado em produção!")
    
except json.JSONDecodeError as e:
    print(f"❌ Erro ao fazer parse do JSON: {e}")
    print(f"Output:\n{result.stdout}")
    sys.exit(1)
except subprocess.TimeoutExpired:
    print("❌ Timeout ao conectar com Heroku")
    sys.exit(1)
except Exception as e:
    print(f"❌ Erro: {e}")
    sys.exit(1)

# PASSO 2: Salvar em arquivo local
print("\n[2/3] Salvando dados localmente...")
backup_file = Path('usuarios_producao.json')
try:
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(usuarios_data, f, indent=2, ensure_ascii=False)
    print(f"✅ Arquivo criado: {backup_file.absolute()}")
except Exception as e:
    print(f"❌ Erro ao salvar arquivo: {e}")
    sys.exit(1)

# PASSO 3: Restaurar no banco local
print("\n[3/3] Restaurando dados no banco local...")
try:
    # Deletar usuários existentes primeiro
    from usuarios.models import Usuario
    Usuario.objects.all().delete()
    print("   - Usuários antigos deletados")
    
    # Carregar novos dados
    out = StringIO()
    call_command('loaddata', str(backup_file), stdout=out, verbosity=2)
    print(out.getvalue())
    
    # Verificar resultado
    total = Usuario.objects.count()
    print(f"✅ Restauração concluída!")
    print(f"   Total de usuários no banco local: {total}")
    
    usuarios_locais = Usuario.objects.all()
    for user in usuarios_locais:
        print(f"   - {user.email} (Ativo: {user.is_active})")
    
except Exception as e:
    print(f"❌ Erro ao restaurar: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("✅ SINCRONIZAÇÃO CONCLUÍDA COM SUCESSO!")
print("=" * 80)
