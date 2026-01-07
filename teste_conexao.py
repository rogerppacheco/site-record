import os
import requests

# Pega as variáveis que o Railway vai injetar
instance_id = os.environ.get("ZAPI_INSTANCE_ID")
token = os.environ.get("ZAPI_TOKEN")
client_token = os.environ.get("ZAPI_CLIENT_TOKEN")

print("-" * 30)
print(f"Testando Instancia: {instance_id}")
print(f"Usando Token: {token}")
print("-" * 30)

if not instance_id or not token:
    print("ERRO CRITICO: As variaveis de ambiente nao foram carregadas!")
    exit()

url = f"https://api.z-api.io/instances/{instance_id}/token/{token}/status"
headers = {"client-token": client_token}

print(f"Consultando URL: {url}")

try:
    response = requests.get(url, headers=headers, timeout=15)
    print(f"Status code: {response.status_code}")
    print(f"Resposta Z-API: {response.text}")
except Exception as e:
    print(f"Erro ao conectar: {e}")