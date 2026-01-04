#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
import django
django.setup()

from usuarios.models import Usuario

print("=== Criando usuário Roger ===")

# Verificar se já existe
try:
    user = Usuario.objects.get(username='Roger')
    print(f'User Roger já existe: {user.username}')
except Usuario.DoesNotExist:
    # Criar novo usuário Roger
    user = Usuario.objects.create_user(
        username='Roger',
        password='123456',  # Senha padrão - você pode alterar
        first_name='Roger',
        is_active=True,
        is_staff=True,
        is_superuser=True
    )
    print(f'✓ User Roger criado com sucesso!')
    print(f'  Username: {user.username}')
    print(f'  Senha: 123456')
    print(f'  Is active: {user.is_active}')
    print(f'  Is staff: {user.is_staff}')

# Testar login
from rest_framework.test import APIClient

client = APIClient()
response = client.post('/api/auth/login/', {'username': 'Roger', 'password': '123456'}, format='json')

print(f'\n=== Teste de Login ===')
print(f'Status: {response.status_code}')
if response.status_code == 200:
    print(f'✓ Login bem sucedido!')
    print(f'Token: {response.data.get("token", "N/A")[:50]}...')
else:
    print(f'✗ Erro: {response.data}')
