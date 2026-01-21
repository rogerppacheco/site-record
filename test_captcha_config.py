#!/usr/bin/env python
"""
Script para verificar a configuração do CAPTCHA
"""
import os
import sys
import django

# Configurar Django
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.conf import settings

print("=" * 60)
print("VERIFICAÇÃO DA CONFIGURAÇÃO DO CAPTCHA")
print("=" * 60)
print()

# Verificar chave da API
api_key = getattr(settings, 'CAPTCHA_API_KEY', None)
provider = getattr(settings, 'CAPTCHA_PROVIDER', None)

print(f"✅ CAPTCHA_PROVIDER: {provider}")
print()

if api_key:
    print(f"✅ CAPTCHA_API_KEY: {api_key[:30]}...{api_key[-10:]}")
    print(f"   Tamanho: {len(api_key)} caracteres")
    
    # Verificar formato da chave CapSolver
    if api_key.startswith('CAP-'):
        print("   ✅ Formato válido para CapSolver (começa com 'CAP-')")
    else:
        print("   ⚠️  Formato não parece ser CapSolver (deveria começar com 'CAP-')")
    
    # Verificar se não é apenas o default
    default_key = 'CAP-4A266E1BA9DC47B87D28FBDE12A129014DB5B7EABC69D961115B3E184D497F85'
    if api_key == default_key:
        print("   ⚠️  ATENÇÃO: Usando valor padrão (default) do código!")
        print("   ⚠️  Isso pode não funcionar em produção!")
    else:
        print("   ✅ Não é o valor padrão do código")
    
    print()
    print("Status: CONFIGURADA ✅")
else:
    print("❌ CAPTCHA_API_KEY: NÃO CONFIGURADA")
    print("Status: NÃO CONFIGURADA ❌")

print()
print("=" * 60)
print("NOTA: A chave precisa ser obtida em:")
print("   https://capsolver.com/")
print("   ou")
print("   https://2captcha.com/")
print("=" * 60)
