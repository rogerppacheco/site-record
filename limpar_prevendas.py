#!/usr/bin/env python
"""Script para limpar dados antigos da tabela PreVenda"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import PreVenda

print("🗑️ Limpando dados antigos de PreVenda...")
count = PreVenda.objects.count()
print(f"   Registros encontrados: {count}")

if count > 0:
    PreVenda.objects.all().delete()
    print(f"✅ {count} registros removidos com sucesso!")
else:
    print("✅ Tabela já está vazia!")

print("\n📝 Agora você pode executar: python manage.py migrate crm_app")
