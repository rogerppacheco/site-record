import base64
import hashlib
import json
import os
from typing import Dict, Optional

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings

from .recaptcha_solver import RecaptchaSolver

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
PARAMS_URL = "https://negociacao.niointernet.com.br/negociar/params"
SITE_URL = "https://negociacao.niointernet.com.br/negociar"
KEY_STRING = "TZkScM94x4Hvggpt"
DEFAULT_STORAGE_STATE = getattr(settings, "NIO_STORAGE_STATE", os.path.join(settings.BASE_DIR, ".playwright_state.json"))


def decrypt_params(enc_b64: str) -> dict:
    data = base64.b64decode(enc_b64)
    if len(data) <= 16:
        raise ValueError("Encrypted payload too short")
    iv = data[:16]
    ct = data[16:]
    key = hashlib.sha256(KEY_STRING.encode()).digest()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    plain = cipher.decryptor().update(ct) + cipher.decryptor().finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(plain) + unpadder.finalize()
    return json.loads(plain)


def fetch_params_requests(session: requests.Session) -> Optional[dict]:
    headers = {
        "User-Agent": UA,
        "Accept": "text/plain",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    resp = session.get(PARAMS_URL, headers=headers, allow_redirects=True, timeout=20)
    if resp.status_code != 200:
        return None
    try:
        return decrypt_params(resp.text.strip())
    except Exception:
        return None


def _try_solve_recaptcha_nio(page, solver: RecaptchaSolver) -> None:
    """Tenta resolver reCAPTCHA v2 via solver e injeta o token."""
    try:
        site_key = page.evaluate("() => document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey') || null")
    except Exception:
        site_key = None
    if not site_key:
        return
    token = solver.solve_recaptcha_v2(site_key, SITE_URL)
    if not token:
        return
    try:
        page.evaluate(
            """
            (t) => {
                const selectors = [
                    'textarea[name="g-recaptcha-response"]',
                    '#g-recaptcha-response',
                    'input[name="g-recaptcha-response"]'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.value = t;
                        el.innerHTML = t;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
                if (window.grecaptcha && window.grecaptcha.getResponse) {
                    try { window.grecaptcha.getResponse = () => t; } catch (e) {}
                }
            }
            """,
            token,
        )
    except Exception:
        pass


def fetch_params_playwright(headless: bool = True, storage_state: Optional[str] = None) -> Optional[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    enc = None
    state_path = storage_state if storage_state else DEFAULT_STORAGE_STATE
    load_state = state_path if state_path and os.path.exists(state_path) else None
    
    # Inicializa solver se API key estiver disponível
    captcha_api_key = getattr(settings, "CAPTCHA_API_KEY", None) or os.getenv("CAPTCHA_API_KEY")
    solver = RecaptchaSolver(api_key=captcha_api_key) if captcha_api_key else None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=True,
                storage_state=load_state,
            )
            page = context.new_page()
            page.goto(SITE_URL, wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1200)
            
            # Tenta resolver reCAPTCHA se solver estiver disponível
            if solver:
                _try_solve_recaptcha_nio(page, solver)
                page.wait_for_timeout(500)

            # Primeiro: tenta ler token/apiServerUrl já persistidos no localStorage.
            try:
                ls = page.evaluate(
                    "() => ({ token: localStorage.getItem('token'), apiServerUrl: localStorage.getItem('apiServerUrl') })"
                )
                if ls and ls.get("token") and ls.get("apiServerUrl"):
                    enc = json.dumps(ls)
            except Exception:
                pass

            # Segundo: tenta via request API com headers de XHR.
            if not enc:
                try:
                    resp = context.request.get(
                        PARAMS_URL,
                        headers={
                            "Accept": "text/plain, */*;q=0.01",
                            "X-Requested-With": "XMLHttpRequest",
                            "User-Agent": UA,
                            "Referer": SITE_URL,
                            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                        },
                        timeout=15000,
                    )
                    if resp.status == 200:
                        enc = resp.text()
                except Exception:
                    pass

            # Terceiro: fetch dentro da página com cookies carregados.
            if not enc:
                try:
                    enc = page.evaluate(
                        "() => fetch('/negociar/params', {credentials:'include', headers:{'Accept':'text/plain, */*;q=0.01','X-Requested-With':'XMLHttpRequest','Accept-Language':'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'}}).then(r => r.text())"
                    )
                except Exception:
                    pass

            # Persiste storage state para reaproveitar cookies.
            if state_path:
                try:
                    os.makedirs(os.path.dirname(state_path), exist_ok=True) if os.path.dirname(state_path) else None
                    context.storage_state(path=state_path)
                except Exception:
                    pass

            browser.close()
    except Exception:
        return None

    if enc is None:
        return None

    # Se enc for JSON simples com token/apiServerUrl, retorna direto.
    try:
        parsed = json.loads(enc)
        if isinstance(parsed, dict) and parsed.get("token") and parsed.get("apiServerUrl"):
            return parsed
    except Exception:
        pass

    try:
        return decrypt_params(enc.strip())
    except Exception:
        return None


def get_session_id(api_base: str, token: str, session: requests.Session) -> Optional[str]:
    url = api_base.rstrip("/") + "/authentication/sessionId"
    headers = {"Accept": "application/json", "Authorization": token}
    resp = session.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data.get("token")


def get_debts(api_base: str, token: str, session_id: str, cpf: str, offset: int, limit: int, session: requests.Session):
    url = api_base.rstrip("/") + f"/debts/customers/{cpf}?offset={offset}&limit={limit}&origin=nio"
    headers = {
        "Accept": "application/json",
        "Authorization": token,
        "Session-Id": session_id,
    }
    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_invoice_pdf_url(api_base: str, token: str, session_id: str, debt_id: str, invoice_id: str, cpf: str, reference_month: str, session: requests.Session) -> Optional[str]:
    """
    Tenta obter a URL do PDF da fatura através da API Nio ou construindo URL S3.
    
    Args:
        api_base: Base URL da API
        token: Token de autorização
        session_id: ID da sessão
        debt_id: ID da dívida
        invoice_id: ID da invoice
        cpf: CPF do cliente (sem formatação)
        reference_month: Mês de referência (YYYYMM)
        session: Sessão HTTP
    
    Returns:
        URL do PDF ou None
    """
    # Padrão da URL S3 que observamos:
    # https://cobranca-nio-6490.s3.sa-east-1.amazonaws.com/modal_{cpf}_{YYYYMM}_{random}.pdf?[assinatura]
    
    try:
        # Tenta vários endpoints possíveis
        endpoints = [
            f"/debts/{debt_id}/invoices/{invoice_id}/download",
            f"/debts/{debt_id}/invoices/{invoice_id}/pdf",
            f"/invoices/{invoice_id}/download",
            f"/invoices/{invoice_id}/pdf",
        ]
        
        headers = {
            "Accept": "application/pdf,application/json,*/*",
            "Authorization": token,
            "Session-Id": session_id,
        }
        
        for endpoint in endpoints:
            url = api_base.rstrip("/") + endpoint
            try:
                print(f"🔍 [PDF API] Tentando: {url}")
                resp = session.get(url, headers=headers, timeout=10, allow_redirects=True)
                print(f"📊 [PDF API] Status: {resp.status_code}, Content-Type: {resp.headers.get('content-type', 'N/A')}")
                
                # Se retornou JSON com URL do PDF
                if resp.status_code == 200 and 'application/json' in resp.headers.get('content-type', ''):
                    data = resp.json()
                    print(f"📄 [PDF API] JSON response: {data}")
                    if data.get('url') or data.get('pdf_url') or data.get('download_url'):
                        pdf_url = data.get('url') or data.get('pdf_url') or data.get('download_url')
                        print(f"✅ [PDF API] URL obtida via JSON: {pdf_url[:80]}...")
                        return pdf_url
                
                # Se retornou redirect para S3
                elif resp.status_code in [200, 302, 301]:
                    print(f"🔗 [PDF API] Final URL: {resp.url}")
                    if 's3' in resp.url and '.pdf' in resp.url:
                        print(f"✅ [PDF API] URL obtida via redirect: {resp.url[:80]}...")
                        return resp.url
                
                # Log do conteúdo se for texto curto
                if len(resp.text) < 500:
                    print(f"📝 [PDF API] Response: {resp.text[:200]}")
                        
            except Exception as e:
                print(f"❌ [PDF API] Erro no endpoint {endpoint}: {e}")
                continue  # Tenta próximo endpoint
        
        print(f"⚠️ [PDF API] Nenhum endpoint retornou PDF válido")
        return None
        
    except Exception as e:
        print(f"⚠️ [PDF API] Erro ao buscar URL do PDF: {e}")
        return None


def _map_invoice(invoice: Dict, debt: Dict) -> Dict:
    return {
        "debt_id": debt.get("debtId"),
        "invoice_id": invoice.get("id"),  # ID da invoice para buscar PDF
        "deal_code": debt.get("dealCode"),
        "product": debt.get("productName"),
        "origin": debt.get("origin"),
        "amount": invoice.get("amount"),
        "reference_month": invoice.get("referenceMonth"),
        "due_date_raw": invoice.get("dueDate"),
        "expiration": invoice.get("expirationDate"),
        "status": invoice.get("status") or debt.get("status"),
        "barcode": invoice.get("barCode"),
        "pix": invoice.get("originalPixCode") or invoice.get("pixCode"),
        "cpf_cnpj": invoice.get("cpfCnpj"),
    }


def consultar_dividas_nio(cpf: str, offset: int = 0, limit: int = 10, storage_state: Optional[str] = None, headless: bool = True) -> Dict:
    session = requests.Session()

    params = fetch_params_requests(session)
    if not params:
        params = fetch_params_playwright(headless=headless, storage_state=storage_state)

    if not params:
        raise RuntimeError("Falha ao obter token/apiServerUrl (possível bloqueio/captcha). Rode headful para renovar cookies.")

    token = params.get("token")
    api_url = params.get("apiServerUrl")
    if not token or not api_url:
        raise RuntimeError("/params sem token ou apiServerUrl")

    session_id = get_session_id(api_url, token, session)
    if not session_id:
        raise RuntimeError("Falha ao obter sessionId")

    data = get_debts(api_url, token, session_id, cpf, offset, limit, session)
    invoices = []
    for debt in data.get("debts", []):
        for inv in debt.get("invoices", []) or []:
            invoices.append(_map_invoice(inv, debt))

    return {
        "token": token,
        "api_base": api_url,
        "session_id": session_id,
        "invoices": invoices,
        "raw": data,
    }
