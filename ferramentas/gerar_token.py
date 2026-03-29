"""
Troca o `code` da URL de callback do OAuth por tokens (incluindo refresh_token).

1. Coloque no .env (na raiz do projeto):
   MS_CLIENT_ID, MS_CLIENT_SECRET (já devem existir)
2. Após o login na Microsoft, copie o parâmetro `code` da URL e adicione UMA vez:
   MS_OAUTH_CODE=cole_aqui_o_code_completo
3. Rode: python ferramentas/gerar_token.py
4. Copie o refresh_token para MS_REFRESH_TOKEN no .env e REMOVA MS_OAUTH_CODE do .env.

O code expira em poucos minutos — use logo após copiar da barra de endereços.
"""
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def sanitize_oauth_code(raw: str) -> str:
    """Aceita só o code, ou URL/path com code=...; remove &session_state, #, etc."""
    raw = (raw or "").strip()
    if not raw:
        return raw
    lower = raw.lower()
    if "code=" in raw:
        if raw.startswith("http"):
            q = urlparse(raw).query
        elif raw.startswith("?"):
            q = raw[1:]
        elif "?" in raw:
            q = raw.split("?", 1)[1]
        else:
            q = raw
        if "#" in q:
            q = q.split("#")[0]
        pairs = parse_qs(q, keep_blank_values=True)
        if "code" in pairs and pairs["code"]:
            return pairs["code"][0]
    if "&" in raw:
        raw = raw.split("&", 1)[0]
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    return raw.strip()


client_id = os.getenv("MS_CLIENT_ID", "").strip()
client_secret = os.getenv("MS_CLIENT_SECRET", "").strip()
code = os.getenv("MS_OAUTH_CODE", "").strip()

# Permite passar o code só na linha de comando: python gerar_token.py "1.Ab0A_..."
if len(sys.argv) > 1:
    code = sys.argv[1].strip()

code = sanitize_oauth_code(code)

if not client_id:
    print("ERRO: defina MS_CLIENT_ID no .env")
    sys.exit(1)
if not client_secret:
    print("ERRO: defina MS_CLIENT_SECRET no .env")
    sys.exit(1)
if not code:
    print(
        "ERRO: defina MS_OAUTH_CODE no .env com o valor do parâmetro `code` da URL,\n"
        "      ou rode: python ferramentas/gerar_token.py \"<cole_o_code_aqui>\""
    )
    sys.exit(1)

url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

data = {
    "client_id": client_id,
    "scope": "offline_access Files.ReadWrite.All",
    "code": code,
    "redirect_uri": "http://localhost:8000/callback",
    "grant_type": "authorization_code",
    "client_secret": client_secret,
}

print("Contactando a Microsoft para gerar o refresh token...")
try:
    r = requests.post(url, data=data, timeout=60)
    r.raise_for_status()
    tokens = r.json()

    refresh_token = tokens.get("refresh_token")

    print("\n" + "=" * 60)
    print("SUCESSO! AQUI ESTÁ SEU REFRESH TOKEN:")
    print("=" * 60)
    print(refresh_token)
    print("=" * 60 + "\n")
    print("Cole no .env em MS_REFRESH_TOKEN e atualize a produção.")
    print("Apague MS_OAUTH_CODE do .env se tiver usado.\n")

except Exception as e:
    print(f"\nERRO: {e}")
    if "r" in locals():
        print("Detalhe do erro:", r.text)
