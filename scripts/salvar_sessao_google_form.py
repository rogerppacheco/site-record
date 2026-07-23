"""
Grava sessão Google Forms (storage state) para a automação Inclusão.

Usa o Chrome real (channel=chrome) + perfil persistente — o Google bloqueia
menos do que o Chromium do Playwright.

Uso (rode no SEU PowerShell, para ver a janela):
  .venv\\Scripts\\python.exe scripts\\salvar_sessao_google_form.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["PAP_HEADLESS"] = "false"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decouple import config as env_config

for key in ("GOOGLE_FORM_EMAIL", "GOOGLE_FORM_PASSWORD", "GOOGLE_FORM_STORAGE_STATE"):
    val = env_config(key, default="")
    if val and key not in os.environ:
        os.environ[key] = str(val)

import django

django.setup()

from playwright.sync_api import sync_playwright

from crm_app.services_inclusao_viabilidade import (
    FORM_URL,
    _caminho_storage_state,
    _esta_no_formulario,
    _salvar_storage_state,
)

TIMEOUT_LOGIN_SEGUNDOS = 10 * 60  # 10 min
POLL_SEGUNDOS = 2
PERFIL_DIR = ROOT / ".playwright_google_profile"


def main() -> None:
    state_path = _caminho_storage_state()
    PERFIL_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("GRAVAR SESSÃO GOOGLE FORMS (Inclusão)")
    print(f"Storage state: {state_path}")
    print(f"Perfil Chrome: {PERFIL_DIR}")
    print("=" * 60)
    print()
    print(">>> Procure a janela do CHROME que vai abrir agora.")
    print(">>> Faça login na conta do formulário (2FA / passkey / Agora não).")
    print(">>> Quando o formulário abrir, este script salva sozinho.")
    print(f">>> Timeout: {TIMEOUT_LOGIN_SEGUNDOS // 60} minutos.")
    print()

    with sync_playwright() as p:
        # Preferir Chrome instalado no Windows (menos bloqueio do Google)
        launch_kwargs = {
            "user_data_dir": str(PERFIL_DIR),
            "headless": False,
            "viewport": {"width": 1280, "height": 900},
            "args": ["--disable-blink-features=AutomationControlled"],
            "ignore_default_args": ["--enable-automation"],
        }
        try:
            context = p.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
            print("Usando: Google Chrome (channel=chrome)")
        except Exception as e:
            print(f"Chrome não disponível ({e}); usando Chromium Playwright.")
            context = p.chromium.launch_persistent_context(**launch_kwargs)

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(FORM_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

        print(f"URL inicial: {page.url}")
        print("Aguardando formulário...")
        print()

        deadline = time.time() + TIMEOUT_LOGIN_SEGUNDOS
        form_ok = False
        while time.time() < deadline:
            try:
                # Pode haver várias abas após login
                for pg in context.pages:
                    if _esta_no_formulario(pg):
                        page = pg
                        form_ok = True
                        break
                if form_ok:
                    break
            except Exception:
                pass
            restante = int(deadline - time.time())
            try:
                url_curta = (page.url or "")[:100]
            except Exception:
                url_curta = "?"
            print(f"  [{restante:3d}s] {url_curta}", flush=True)
            time.sleep(POLL_SEGUNDOS)

        if not form_ok:
            print()
            print("TIMEOUT — formulário não abriu.")
            try:
                print(f"URL final: {page.url}")
            except Exception:
                pass
            context.close()
            print("Nada foi salvo. Rode de novo e complete o login na janela do Chrome.")
            sys.exit(1)

        print()
        print(f"Formulário detectado! URL: {page.url[:100]}")
        page.wait_for_timeout(1500)
        salvo = _salvar_storage_state(context)
        context.close()

        if salvo and os.path.isfile(salvo):
            print()
            print(f"OK — sessão salva ({os.path.getsize(salvo)} bytes):")
            print(f"  {salvo}")
            print()
            print("Agora teste:")
            print("  .\\.venv\\Scripts\\python.exe scripts\\teste_inclusao_form_visivel.py")
        else:
            print("Falha ao salvar storage state.")
            sys.exit(1)


if __name__ == "__main__":
    main()
