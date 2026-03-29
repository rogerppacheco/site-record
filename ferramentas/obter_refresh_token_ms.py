"""
Um comando só: abre o login Microsoft, recebe o redirect em localhost:8000
e imprime o MS_REFRESH_TOKEN (e troca o code por tokens no servidor da Microsoft).

Uso:
  cd C:\\site-record
  .\\.venv\\Scripts\\python.exe ferramentas\\obter_refresh_token_ms.py

Requisitos no .env: MS_CLIENT_ID, MS_CLIENT_SECRET
Redirect no Azure (Web): http://localhost:8000/callback
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

CLIENT_ID = os.getenv("MS_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "").strip()
REDIRECT_URI = "http://localhost:8000/callback"
PORT = 8000
HOST = "127.0.0.1"

AUTH_URL = (
    "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    f"?client_id={CLIENT_ID}"
    "&response_type=code"
    f"&redirect_uri=http%3A%2F%2Flocalhost%3A{PORT}%2Fcallback"
    "&response_mode=query"
    "&scope=offline_access%20Files.ReadWrite.All"
)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/callback":
            self.send_error(404)
            return
        qs = parse_qs(parsed.query)
        if "error" in qs:
            err = qs.get("error_description", qs["error"])[0]
            self.server.oauth_err = err
        if "code" in qs:
            self.server.oauth_code = qs["code"][0]
        body = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>OK</title></head>"
            "<body><p>Login concluído. Pode fechar esta aba.</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERRO: defina MS_CLIENT_ID e MS_CLIENT_SECRET no .env")
        sys.exit(1)

    httpd = HTTPServer((HOST, PORT), _Handler)
    httpd.oauth_code = None
    httpd.oauth_err = None

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    print(f"Servidor em http://localhost:{PORT}/callback — abrindo o navegador...\n")
    webbrowser.open(AUTH_URL)

    deadline = time.time() + 300
    while time.time() < deadline:
        if httpd.oauth_code or httpd.oauth_err:
            break
        time.sleep(0.15)

    httpd.shutdown()

    if httpd.oauth_err:
        print("Erro no login:", httpd.oauth_err)
        sys.exit(1)
    if not httpd.oauth_code:
        print("Tempo esgotado: nenhum código recebido. Tente de novo.")
        sys.exit(1)

    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": httpd.oauth_code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": "offline_access Files.ReadWrite.All",
    }
    print("Trocando o código por tokens...\n")
    r = requests.post(token_url, data=data, timeout=60)
    if r.status_code != 200:
        print("ERRO na troca:", r.text)
        sys.exit(1)

    tokens = r.json()
    refresh = tokens.get("refresh_token")
    if not refresh:
        print("Resposta sem refresh_token:", tokens)
        sys.exit(1)

    print("=" * 60)
    print("MS_REFRESH_TOKEN (copie para o .env e para produção):")
    print("=" * 60)
    print(refresh)
    print("=" * 60)


if __name__ == "__main__":
    main()
