# crm_app/historico_pap_service.py
"""Busca o histórico PAP (venda / interesse / pré-venda) com a sessão do usuário.

Ritmo igual à tela: 15 por página, pausa entre páginas. Não abre Detalhar.
Não grava Venda — só protocolos em HistoricoPapPedido.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import threading
import time
from datetime import date, datetime
from typing import Any, Optional, Tuple

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from crm_app.historico_pap import (
    LIMIT_PAGINA,
    MAX_DIAS_BUSCA,
    PAP_HISTORICO_URL,
    STATUS_LISTA_PADRAO,
    TIPO_API_ALIASES,
    extrair_lista_api,
    map_pedido_api,
    montar_url_vendas,
    montar_xlsx_historico,
    normalizar_pedido,
    parse_arquivo_exportacao,
    tipos_solicitados,
)

logger = logging.getLogger(__name__)

# Fallback em memória caso a tabela de cache (django_cache_table) não esteja inicializada
_IN_MEMORY_CACHE: dict[str, tuple[Any, float]] = {}


def _cache_get(key: str) -> Any:
    try:
        val = cache.get(key)
        if val is not None:
            return val
    except Exception:
        pass
    item = _IN_MEMORY_CACHE.get(key)
    if item:
        val, exp_ts = item
        if exp_ts > time.time():
            return val
        _IN_MEMORY_CACHE.pop(key, None)
    return None


def _cache_set(key: str, val: Any, timeout_seconds: int = 3600) -> None:
    exp_ts = time.time() + timeout_seconds
    _IN_MEMORY_CACHE[key] = (val, exp_ts)
    try:
        cache.set(key, val, timeout_seconds)
    except Exception:
        pass


def _cache_delete(key: str) -> None:
    _IN_MEMORY_CACHE.pop(key, None)
    try:
        cache.delete(key)
    except Exception:
        pass


def limpar_jwt(token: str) -> str:
    """Extrai a sequência pura de Base64/Base64URL do JWT, eliminando Bearer, aspas ou espaços."""
    if not token or not isinstance(token, str):
        return ""
    t = token.strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    t = t.strip("\"'`")
    m = re.search(r"eyJ[A-Za-z0-9_\-\+\/=]{5,}\.[A-Za-z0-9_\-\+\/=]{5,}\.[A-Za-z0-9_\-\+\/=]{5,}", t)
    if m:
        return m.group(0)
    if t.startswith("eyJ") and t.count(".") == 2:
        return t
    return ""


def validar_e_decodificar_jwt(token: str) -> tuple[bool, Optional[dict], str]:
    """
    Valida formato de JWT e verifica se está expirado.
    Retorna (valido, payload_dict, motivo_ou_token_limpo).
    """
    if not token or not isinstance(token, str):
        return False, None, "Token vazio ou formato inválido."
    clean = limpar_jwt(token)
    if not clean:
        return False, None, "Token não possui estrutura de JWT válido (esperado eyJ...)."
    parts = clean.split(".")
    payload_b64 = parts[1]
    rem = len(payload_b64) % 4
    if rem > 0:
        payload_b64 += "=" * (4 - rem)
    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        return False, None, f"Payload do JWT ilegível: {exc}"

    exp = payload.get("exp")
    if exp is not None:
        try:
            exp_ts = float(exp)
            agora = time.time()
            if exp_ts <= agora:
                dt_exp = datetime.fromtimestamp(exp_ts).strftime("%d/%m/%Y %H:%M:%S")
                return False, payload, f"Token expirado em {dt_exp}."
            if exp_ts - agora < 30:
                return False, payload, "Token expirando em menos de 30 segundos."
        except (ValueError, TypeError):
            pass
    return True, payload, clean


def obter_token_cache(matricula: str) -> tuple[Optional[str], Optional[dict]]:
    """Obtém token em cache se ainda for válido e não expirado."""
    matricula_clean = (matricula or "").strip()
    keys_to_check = [f"pap_token_{matricula_clean}"] if matricula_clean else []
    keys_to_check.append("pap_token_global")
    for k in keys_to_check:
        tok = _cache_get(k)
        if tok:
            ok, payload, clean = validar_e_decodificar_jwt(tok)
            if ok:
                return clean, payload
            _cache_delete(k)
    return None, None


def salvar_token_cache(matricula: str, token: str, exp_ts: Optional[float] = None) -> None:
    """Salva token no cache com TTL baseado na expiração do JWT (máx 2 horas)."""
    ok, payload, clean = validar_e_decodificar_jwt(token)
    if not ok:
        return
    agora = time.time()
    exp = exp_ts or (payload.get("exp") if payload else None)
    if exp:
        ttl = max(60, int(float(exp) - agora - 60))
        ttl = min(ttl, 7200)
    else:
        ttl = 3600
    matricula_clean = (matricula or "").strip()
    if matricula_clean:
        _cache_set(f"pap_token_{matricula_clean}", clean, ttl)
    _cache_set("pap_token_global", clean, ttl)


def remover_token_cache(matricula: str) -> None:
    matricula_clean = (matricula or "").strip()
    if matricula_clean:
        _cache_delete(f"pap_token_{matricula_clean}")
    _cache_delete("pap_token_global")


def verificar_cooldown_login(matricula: str) -> tuple[bool, int]:
    """Retorna (esta_em_cooldown, segundos_restantes)."""
    matricula_clean = (matricula or "").strip()
    keys = [f"pap_cooldown_{matricula_clean}"] if matricula_clean else []
    keys.append("pap_cooldown_global")
    agora = time.time()
    for k in keys:
        until = _cache_get(k)
        if until:
            try:
                until_f = float(until)
                if until_f > agora:
                    return True, int(until_f - agora)
            except (ValueError, TypeError):
                pass
            _cache_delete(k)
    return False, 0


def registrar_cooldown_login(matricula: str, segundos: int = 900) -> None:
    """Ativa cooldown de login para evitar bloqueio por tentativas automáticas seguidas."""
    matricula_clean = (matricula or "").strip()
    until = time.time() + segundos
    if matricula_clean:
        _cache_set(f"pap_cooldown_{matricula_clean}", until, segundos)
    _cache_set("pap_cooldown_global", until, segundos)
    logger.warning("[HISTORICO PAP] Cooldown de login ativado por %s segundos para matrícula %s", segundos, matricula_clean)


def limpar_cooldown_login(matricula: str) -> None:
    matricula_clean = (matricula or "").strip()
    if matricula_clean:
        _cache_delete(f"pap_cooldown_{matricula_clean}")
    _cache_delete("pap_cooldown_global")


def obter_status_sessao_pap(matricula: str) -> dict:
    """Status resumido para a UI: token ativo, cooldown e expiração."""
    tok, payload = obter_token_cache(matricula)
    em_cooldown, seg_cooldown = verificar_cooldown_login(matricula)
    exp_min = 0
    if payload and payload.get("exp"):
        try:
            exp_min = max(0, int((float(payload["exp"]) - time.time()) // 60))
        except Exception:
            exp_min = 0
    return {
        "tem_token_valido": bool(tok),
        "expira_em_minutos": exp_min,
        "cooldown_ativo": em_cooldown,
        "cooldown_restante_minutos": max(1, seg_cooldown // 60) if em_cooldown else 0,
        "matricula": (matricula or "").strip(),
    }


# Extrai Bearer JWT do cookie/localStorage varrendo todas as chaves e Redux persist.
JS_TOKEN = """
() => {
  const cleanJwt = (s) => {
    if (!s || typeof s !== 'string') return '';
    const m = s.match(/eyJ[A-Za-z0-9_\\-\\+\\/=]{5,}\\.[A-Za-z0-9_\\-\\+\\/=]{5,}\\.[A-Za-z0-9_\\-\\+\\/=]{5,}/);
    return m ? m[0] : '';
  };

  for (const store of [localStorage, sessionStorage]) {
    try {
      for (const key of ['token', 'accessToken', 'access_token', 'authToken', 'jwt', 'auth', 'user']) {
        const val = store.getItem(key);
        const jwt = cleanJwt(val);
        if (jwt) return jwt;
      }
      for (let i = 0; i < store.length; i++) {
        const k = store.key(i);
        const val = store.getItem(k);
        const jwt = cleanJwt(val);
        if (jwt) return jwt;

        if (val && (val.startsWith('{') || val.startsWith('['))) {
          const walk = (o, depth) => {
            if (!o || depth > 5) return '';
            if (typeof o === 'string') {
              const j = cleanJwt(o);
              if (j) return j;
              if (o.startsWith('{') || o.startsWith('[')) {
                try { return walk(JSON.parse(o), depth + 1); } catch (e) {}
              }
              return '';
            }
            if (typeof o === 'object') {
              for (const prop of Object.keys(o)) {
                const res = walk(o[prop], depth + 1);
                if (res) return res;
              }
            }
            return '';
          };
          try {
            const found = walk(JSON.parse(val), 0);
            if (found) return found;
          } catch (e) {}
        }
      }
    } catch (e) {}
  }

  try {
    const cookies = (document.cookie || '').split(';');
    for (const c of cookies) {
      const parts = c.trim().split('=');
      if (parts.length >= 2) {
        const val = decodeURIComponent(parts.slice(1).join('='));
        const jwt = cleanJwt(val);
        if (jwt) return jwt;
      }
    }
  } catch (e) {}

  return '';
}
"""

JS_FETCH = """
async (url) => {
  try {
    const raw = (document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('token=')) || '').slice(6);
    const headers = { Accept: 'application/json' };
    if (raw) {
      const t = decodeURIComponent(raw);
      headers.Authorization = t.startsWith('Bearer') ? t : ('Bearer ' + t);
    }
    const r = await fetch(url, { credentials: 'include', headers });
    const text = await r.text();
    let json = null;
    try { json = JSON.parse(text); } catch (e) {
      return { ok: false, status: r.status, error: 'parse', preview: text.slice(0, 280) };
    }
    return { ok: r.ok, status: r.status, json };
  } catch (e) {
    return { ok: false, status: 0, error: String((e && e.message) || e || 'fetch_failed') };
  }
}
"""


def _extrair_token_cookies(page) -> str:
    """Extrai o cookie 'token' diretamente dos cookies do Playwright (imune ao path /administrativo)."""
    if not page:
        return ""
    try:
        cookies = page.context.cookies()
        for c in cookies:
            if c.get("name") == "token" and "pap.niointernet.com.br" in (c.get("domain") or ""):
                val = (c.get("value") or "").strip()
                clean = limpar_jwt(val)
                if clean:
                    return clean
    except Exception as exc:
        logger.warning("[HISTORICO PAP] Não foi possível ler cookies do contexto: %s", exc)
    return ""


def _extrair_token(page) -> str:
    if not page:
        return ""
    # 1. Tentar ler do cookie "token" gerenciado pelo Playwright (imune ao path /administrativo)
    c_tok = _extrair_token_cookies(page)
    if c_tok:
        return c_tok
    # 2. Tentar via JS evaluation em localStorage/sessionStorage/document.cookie
    try:
        raw = page.evaluate(JS_TOKEN)
        if raw:
            return limpar_jwt((raw or "").strip())
    except Exception as exc:
        logger.warning("[HISTORICO PAP] Não foi possível ler token da página: %s", exc)
    return ""


def _gerar_anti_replay_hash() -> str:
    import base64
    from datetime import datetime, timezone
    
    key = '-5Hsrpt5gb93N5L9ePT2bBC9MI9ThLctvltkuoOqh2Q'
    dt_str = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    plaintext = f'"{dt_str}"'
    
    encoded = []
    for i, char in enumerate(plaintext):
        a = ord(char)
        b = a ^ ord(key[i % len(key)])
        encoded.append(b)
    return base64.b64encode(bytes(encoded)).decode('utf-8')


def _headers_auth(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://pap.niointernet.com.br",
        "Referer": "https://pap.niointernet.com.br/administrativo/historico",
    }
    if not token:
        return headers
        
    t = token.strip()
    
    # Se o token já tiver o hash antigo acoplado (length > 297 aprox), limpamos
    parts = t.split(".")
    if len(parts) == 3:
        sig = parts[2]
        if len(sig) > 43:
            t = t[:-36]

    headers["Authorization"] = t if t.startswith("Bearer") else f"Bearer {t}"
    return headers


def _fetch_json_http(url: str, headers: dict[str, str]) -> dict:
    try:
        resp = requests.get(url, headers=headers, timeout=60)
        status = resp.status_code
        text = resp.text
        try:
            json_body = resp.json()
        except Exception:
            json_body = None
            try:
                json_body = json.loads(text)
            except Exception:
                return {
                    "ok": False,
                    "status": status,
                    "error": "parse",
                    "preview": (text or "")[:280],
                }
        if status in (401, 403):
            logger.warning("[HISTORICO PAP] API HTTP %s — preview=%s", status, (text or "")[:180].replace("\n", " "))
        return {"ok": 200 <= status < 300, "status": status, "json": json_body}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": f"requests: {exc}"}


def _log_cookies_debug(page, dominio: str = "pap-api.niointernet.com.br") -> None:
    """Loga os cookies e Web Storage (local/session) presentes no contexto Playwright para diagnóstico."""
    if not page:
        return
    try:
        all_cookies = page.context.cookies()
        api_cookies = [c for c in all_cookies if dominio in (c.get("domain") or "")]
        front_cookies = [c for c in all_cookies if "pap.niointernet.com.br" in (c.get("domain") or "")]
        logger.warning(
            "[HISTORICO PAP][DEBUG] Cookies no contexto: total=%d pap-api=%d pap-front=%d",
            len(all_cookies), len(api_cookies), len(front_cookies),
        )
        for c in api_cookies:
            val = (c.get("value") or "")[:50]
            logger.warning(
                "[HISTORICO PAP][DEBUG] Cookie API: name=%s domain=%s path=%s val_inicio=%s",
                c.get("name"), c.get("domain"), c.get("path"), val,
            )
        for c in front_cookies:
            val = (c.get("value") or "")
            logger.warning(
                "[HISTORICO PAP][DEBUG] Cookie FRONT: name=%s domain=%s path=%s dots=%d len=%d val_inicio=%s val_fim=%s",
                c.get("name"), c.get("domain"), c.get("path"),
                val.count("."), len(val), val[:40], val[-20:],
            )
        
        # Dump Web Storage (LocalStorage e SessionStorage)
        try:
            ls_data = page.evaluate("() => { let d={}; for(let i=0; i<localStorage.length; i++) { let k=localStorage.key(i); d[k] = localStorage.getItem(k); } return d; }")
            ss_data = page.evaluate("() => { let d={}; for(let i=0; i<sessionStorage.length; i++) { let k=sessionStorage.key(i); d[k] = sessionStorage.getItem(k); } return d; }")
            
            logger.warning("[HISTORICO PAP][DEBUG] LocalStorage keys: %s", list(ls_data.keys()))
            for k, v in ls_data.items():
                if v and len(v) > 20:
                    logger.warning("[HISTORICO PAP][DEBUG] LocalStorage[%s] (len=%d): %s...%s", k, len(v), v[:40], v[-20:])
                else:
                    logger.warning("[HISTORICO PAP][DEBUG] LocalStorage[%s]: %s", k, v)
                    
            logger.warning("[HISTORICO PAP][DEBUG] SessionStorage keys: %s", list(ss_data.keys()))
        except Exception as exc_ws:
            logger.warning("[HISTORICO PAP][DEBUG] Falha ao ler Web Storage: %s", exc_ws)
            
    except Exception as exc:
        logger.warning("[HISTORICO PAP][DEBUG] Falha ao listar cookies: %s", exc)


def _fetch_json(page, url: str, token: str = "") -> dict:
    """
    Busca JSON da API do PAP.
    Estratégia (em ordem):
    1) APIRequestContext do Playwright SEM Authorization (só cookies do contexto — a API usa cookie de sessão).
    2) APIRequestContext do Playwright COM Authorization Bearer (se o token for válido JWT).
    3) HTTP direto via requests com Bearer.
    4) Evaluate fetch nativo do browser (com credentials: include).
    """
    tok = (token or "").strip()
    if not tok and page:
        tok = limpar_jwt(_extrair_token(page))
    headers_bearer = _headers_auth(tok)
    headers_sem_auth = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://pap.niointernet.com.br",
        "Referer": "https://pap.niointernet.com.br/administrativo/historico",
    }

    # 1) APIRequestContext SEM Authorization — a API usa cookie de sessão set no login
    if page:
        try:
            api = page.context.request
            resp = api.get(url, headers=headers_sem_auth, timeout=45000)
            status = resp.status
            text = resp.text()
            try:
                json_body = resp.json()
            except Exception:
                try:
                    json_body = json.loads(text)
                except Exception:
                    json_body = None
            if 200 <= status < 300:
                logger.info("[HISTORICO PAP] context.request (só cookies) OK: %s", status)
                return {"ok": True, "status": status, "json": json_body}
            if status in (401, 403):
                logger.warning(
                    "[HISTORICO PAP] context.request (só cookies) %s — preview=%s → tentando com Bearer",
                    status, (text or "")[:180].replace("\n", " "),
                )
                # Debug: logar todos os cookies ao falhar
                _log_cookies_debug(page)
        except Exception as exc:
            logger.warning("[HISTORICO PAP] context.request (só cookies) falhou (%s)", exc)

    # 2) APIRequestContext COM Authorization Bearer
    if page and tok:
        logger.info(
            "[HISTORICO PAP] Tentando context.request com Bearer (primeiros 30 chars): %s...",
            tok[:30],
        )
        try:
            api = page.context.request
            resp = api.get(url, headers=headers_bearer, timeout=45000)
            status = resp.status
            text = resp.text()
            try:
                json_body = resp.json()
            except Exception:
                try:
                    json_body = json.loads(text)
                except Exception:
                    json_body = None
            if 200 <= status < 300:
                logger.info("[HISTORICO PAP] context.request (Bearer) OK: %s", status)
                return {"ok": True, "status": status, "json": json_body}
            if status in (401, 403):
                logger.warning(
                    "[HISTORICO PAP] context.request (Bearer) %s — preview=%s (tentando fallback HTTP)",
                    status, (text or "")[:180].replace("\n", " "),
                )
        except Exception as exc:
            logger.warning("[HISTORICO PAP] context.request (Bearer) falhou (%s); tentando fallback HTTP direto", exc)

    # 3) Fallback direto HTTP sem browser (evita conflitos de cookies do Chromium)
    resp_http = _fetch_json_http(url, headers_bearer)
    if resp_http.get("ok"):
        return resp_http
    if resp_http.get("status") in (401, 403):
        logger.warning(
            "[HISTORICO PAP] HTTP direto (Bearer) %s — tok_len=%d tok_dots=%d tok_inicio=%s",
            resp_http.get("status"), len(tok), tok.count(".") if tok else 0, tok[:30],
        )

    # 4) Fallback para fetch nativo dentro do browser (com credentials: include)
    if page:
        try:
            auth_val = headers_bearer.get("Authorization", "")
            res = page.evaluate("""
            async ({ url, authVal }) => {
                try {
                    const hdrs = { 'Accept': 'application/json, text/plain, */*' };
                    if (authVal) hdrs['Authorization'] = authVal;
                    const r = await fetch(url, { method: 'GET', credentials: 'include', headers: hdrs });
                    const text = await r.text();
                    let json = null;
                    try { json = JSON.parse(text); } catch(e) {}
                    return { ok: r.ok, status: r.status, json: json, preview: text.slice(0, 280) };
                } catch(e) {
                    return { ok: false, status: 0, error: String((e && e.message) || e) };
                }
            }
            """, {"url": url, "authVal": auth_val})
            if isinstance(res, dict):
                logger.warning(
                    "[HISTORICO PAP] evaluate fetch resultado: status=%s ok=%s preview=%s",
                    res.get("status"), res.get("ok"), (res.get("preview") or "")[:180],
                )
                if res.get("ok"):
                    return res
        except Exception as exc:
            logger.warning("[HISTORICO PAP] evaluate fetch falhou (%s)", exc)

    return resp_http


def _navegar_ao_historico_spa(page) -> None:
    """Navega para o Histórico de Pedidos via menu lateral da SPA ou goto direto."""
    if not page:
        return
    url_atual = (page.url or "").lower()
    if "administrativo/historico" in url_atual:
        # Aguarda a página terminar de renderizar o React antes de continuar
        try:
            page.wait_for_selector('button#drawer-filter, button:has-text("Filtrar"), button:has-text("Buscar")', timeout=10000)
        except Exception:
            page.wait_for_timeout(3000)
        return
    # Tentar navegação suave pelo menu da SPA (como a Ana faz)
    try:
        btn_pedidos = page.query_selector('text="Pedidos"') or page.query_selector('div:has-text("Pedidos")')
        if btn_pedidos and btn_pedidos.is_visible():
            btn_pedidos.click()
            page.wait_for_timeout(800)
            btn_hist = page.query_selector('text="Histórico de Pedidos"') or page.query_selector('a[href*="historico"]')
            if btn_hist and btn_hist.is_visible():
                btn_hist.click()
                page.wait_for_timeout(2000)
                if "historico" in (page.url or "").lower():
                    logger.info("[HISTORICO PAP] Navegação ao Histórico via menu SPA concluída com sucesso!")
                    return
    except Exception as exc:
        logger.debug("[HISTORICO PAP] Navegação por menu SPA falhou (%s); usando goto direto", exc)

    # Fallback: goto direto
    try:
        page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
    except Exception as exc:
        logger.warning("[HISTORICO PAP] goto histórico: %s", exc)


def _tentar_clicar_filtrar(page) -> None:
    """Simula o clique no botão de filtrar/buscar preenchendo os inputs para disparar XHR da SPA."""
    if not page:
        return
        
    def _force_click(btn):
        try:
            btn.click(timeout=2000)
        except Exception:
            try:
                page.evaluate("el => el.click()", btn)
            except Exception:
                pass
                
    seletores_filtro = [
        'button:has-text("Filtrar")',
        'button:has-text("Buscar")',
        'button:has-text("FILTRAR")',
        'button:has-text("BUSCAR")',
        'button[class*="filtrar"]',
        'button.btn-filters-new',
        'button:has-text("Pesquisar")',
        'button:has-text("Aplicar")',
    ]
    seletores_abrir_filtro = [
        'span:has-text("Filtros")',
        'div:has-text("Filtro")',
    ]
    
    # 1. Tentar abrir o modal de filtros primeiro (se existir)
    for sel in seletores_abrir_filtro:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                logger.info("[HISTORICO PAP] Abrindo filtros com '%s'...", sel)
                _force_click(btn)
                page.wait_for_timeout(1500)
                break
        except Exception:
            pass
            
    # 2. Forçar preenchimento de inputs para passar na validação do frontend (Bypass React 16+)
    try:
        page.evaluate("""() => {
            const inputs = document.querySelectorAll('input');
            const now = new Date();
            const yyyy = now.getFullYear();
            const mm = String(now.getMonth() + 1).padStart(2, '0');
            const dd = String(now.getDate()).padStart(2, '0');
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            
            inputs.forEach(i => {
                if (!i.disabled) {
                    if (i.type === 'date') {
                        nativeInputValueSetter.call(i, `${yyyy}-${mm}-${dd}`);
                    } else if (i.type === 'text' || i.className.toLowerCase().includes('data') || i.placeholder.toLowerCase().includes('data')) {
                        nativeInputValueSetter.call(i, `${dd}/${mm}/${yyyy}`);
                    }
                    i.dispatchEvent(new Event('input', { bubbles: true }));
                    i.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });
        }""")
        logger.info("[HISTORICO PAP] Inputs preenchidos via JS (React Bypass) para disparar validacao.")
        page.wait_for_timeout(500)
    except Exception as e:
        logger.debug("[HISTORICO PAP] Falha ao preencher inputs: %s", e)

    # 3. Clicar no botão de Filtro/Buscar
    for sel in seletores_filtro:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                logger.info("[HISTORICO PAP] Clicando em '%s' para disparar XHR...", sel)
                _force_click(btn)
                page.wait_for_timeout(2000)
                return
        except Exception:
            pass
            
    logger.warning("[HISTORICO PAP] Nao encontrou botao de filtrar/buscar na pagina historico.")



def _run_django_sync(func, timeout_seconds: int = 120):
    import queue

    import django.db

    q = queue.Queue()

    def worker():
        try:
            django.db.close_old_connections()
            q.put(("ok", func()))
        except Exception as e:
            q.put(("err", e))
        finally:
            django.db.close_old_connections()

    t = threading.Thread(target=worker, daemon=True, name="hist-pap-orm")
    t.start()
    t.join(timeout=timeout_seconds)
    if not q.empty():
        kind, payload = q.get()
        if kind == "err":
            raise payload
        return payload
    raise TimeoutError("django_sync_timeout")


def _intervalo() -> float:
    lo = float(getattr(settings, "HISTORICO_PAP_INTERVALO_MIN_SEG", 4))
    hi = float(getattr(settings, "HISTORICO_PAP_INTERVALO_MAX_SEG", 6))
    if hi < lo:
        hi = lo
    return random.uniform(lo, hi)


def _validar_credenciais(usuario) -> Tuple[bool, str]:
    matricula = (getattr(usuario, "matricula_pap", None) or "").strip()
    senha = (getattr(usuario, "senha_pap", None) or "").strip()
    if not matricula or not senha:
        return False, (
            "O login Diretoria selecionado não tem matrícula/senha PAP. "
            "Cadastre na Governança antes de buscar o histórico."
        )
    return True, matricula


def busca_em_andamento():
    from crm_app.models import HistoricoPapBusca

    return (
        HistoricoPapBusca.objects.filter(
            status__in=[
                HistoricoPapBusca.STATUS_PENDENTE,
                HistoricoPapBusca.STATUS_EM_ANDAMENTO,
            ]
        )
        .select_related("login_pap")
        .order_by("-iniciado_em")
        .first()
    )


def registrar_exportacao(usuario, nome: str, content: bytes) -> dict:
    from crm_app.models import HistoricoPapPedido

    pares = parse_arquivo_exportacao(nome, content)
    if not pares:
        raise ValueError("Não achei a coluna Pedido (protocolo) neste arquivo.")

    conhecidos = set(
        HistoricoPapPedido.objects.filter(
            numero_pedido__in=[p[0] for p in pares]
        ).values_list("numero_pedido", flat=True)
    )
    novos = 0
    objs = []
    for ped, tipo, payload in pares:
        if ped in conhecidos:
            continue
        conhecidos.add(ped)
        objs.append(
            HistoricoPapPedido(
                numero_pedido=ped,
                tipo_venda=tipo or HistoricoPapPedido.TIPO_VENDA,
                origem="exportacao",
                payload=payload if isinstance(payload, dict) else {"numeroPedido": ped},
                pdv="",
            )
        )
        novos += 1
        if len(objs) >= 500:
            HistoricoPapPedido.objects.bulk_create(objs, ignore_conflicts=True)
            objs = []
    if objs:
        HistoricoPapPedido.objects.bulk_create(objs, ignore_conflicts=True)
    return {
        "lidos": len(pares),
        "novos": novos,
        "ja_existiam": len(pares) - novos,
        "total_base": HistoricoPapPedido.objects.count(),
        "grava_venda": False,
    }


def serializar_busca(busca, *, em_andamento: bool) -> dict:
    login_user = getattr(busca, "login_pap", None)
    return {
        "id": busca.id,
        "status": busca.status,
        "em_andamento": em_andamento,
        "data_inicio": busca.data_inicio.isoformat() if busca.data_inicio else "",
        "data_fim": busca.data_fim.isoformat() if busca.data_fim else "",
        "pdv": busca.pdv or "",
        "tipos": busca.tipos or [],
        "encontrados": busca.encontrados,
        "novos": busca.novos,
        "ignorados": busca.ignorados,
        "por_tipo": busca.por_tipo or {},
        "mensagem": busca.mensagem or "",
        "grava_venda": False,
        "login_pap": getattr(login_user, "username", None) or "",
        "iniciado_em": busca.iniciado_em.isoformat() if busca.iniciado_em else "",
        "finalizado_em": busca.finalizado_em.isoformat() if busca.finalizado_em else "",
    }


def criar_e_iniciar_busca(
    usuario,
    *,
    data_inicio: date,
    data_fim: date,
    pdv: str,
    tipos: list[str],
    token_manual: str = "",
):
    from django.db import transaction

    from crm_app.models import HistoricoPapBusca
    from crm_app.pool_historico_pap import obter_login_historico_pap

    if data_fim < data_inicio:
        return None, "Data fim anterior à data início."
    if (data_fim - data_inicio).days > MAX_DIAS_BUSCA:
        return None, f"O intervalo máximo é {MAX_DIAS_BUSCA} dias."

    tipos_ok = tipos_solicitados(tipos)
    pdv = (pdv or "").strip()
    token_manual = (token_manual or "").strip()

    with transaction.atomic():
        login_pap, err_pool = obter_login_historico_pap()
        if err_pool:
            return None, err_pool

        ok, msg = _validar_credenciais(login_pap)
        if not ok and not token_manual:
            return None, msg

        busca = HistoricoPapBusca.objects.create(
            usuario=usuario,
            login_pap=login_pap,
            status=HistoricoPapBusca.STATUS_EM_ANDAMENTO,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pdv=pdv,
            tipos=tipos_ok,
            mensagem=f"Usando login Diretoria: {login_pap.username}" + (" (Token manual)" if token_manual else ""),
            relatorio_json={"fase": "iniciando", "login_pap": login_pap.username, "token_manual": bool(token_manual)},
        )
        login_id = login_pap.id
        busca_id = busca.id

    t = threading.Thread(
        target=_runner,
        args=(busca_id, login_id, token_manual),
        name=f"hist-pap-{busca_id}",
        daemon=True,
    )
    t.start()
    return busca_id, None


def xlsx_novos_da_busca(busca_id: int) -> tuple[bytes, str]:
    from crm_app.models import HistoricoPapBusca, HistoricoPapPedido

    busca = HistoricoPapBusca.objects.get(pk=busca_id)
    numeros = [normalizar_pedido(n) for n in (busca.novos_numeros or [])]
    numeros = [n for n in numeros if n]
    linhas = []
    if numeros:
        qs = HistoricoPapPedido.objects.filter(numero_pedido__in=numeros)
        by_num = {p.numero_pedido: p for p in qs}
        for n in numeros:
            p = by_num.get(n)
            if not p:
                continue
            if p.payload:
                linhas.append(map_pedido_api(p.payload, p.tipo_venda))
            else:
                linhas.append({"tipo_venda": p.tipo_venda, "pedido": p.numero_pedido, "status": p.status})
    nome = f"Historico_PAP_{busca.data_inicio}_{busca.data_fim}.xlsx"
    return montar_xlsx_historico(linhas), nome


def _atualizar(busca_id: int, **kwargs):
    from crm_app.models import HistoricoPapBusca

    HistoricoPapBusca.objects.filter(pk=busca_id).update(**kwargs)


def _runner(busca_id: int, login_pap_id: int, token_manual: str = ""):
    import django.db

    django.db.close_old_connections()
    try:
        _executar_busca(busca_id, login_pap_id, token_manual=token_manual)
    except Exception as exc:
        logger.exception("[HISTORICO PAP] Falha no job %s", busca_id)
        msg = f"Falha ao buscar o histórico PAP: {exc}"[:500]
        try:
            _run_django_sync(
                lambda: _atualizar(
                    busca_id,
                    status="erro",
                    mensagem=msg,
                    finalizado_em=timezone.now(),
                )
            )
        except Exception:
            logger.exception("[HISTORICO PAP] Nem o status de erro pôde ser gravado.")
    finally:
        django.db.close_old_connections()


def _iso_inicio(d: date) -> str:
    return f"{d.isoformat()}T00:00:00-03:00"


def _iso_fim(d: date) -> str:
    return f"{d.isoformat()}T23:59:59-03:00"


def _pedido_conhecido(numero: str) -> bool:
    from crm_app.models import HistoricoPapPedido

    return HistoricoPapPedido.objects.filter(numero_pedido=numero).exists()


def _salvar_novo(numero: str, tipo: str, pdv: str, payload: dict) -> bool:
    from crm_app.models import HistoricoPapPedido

    if not numero:
        return False
        
    existente = HistoricoPapPedido.objects.filter(numero_pedido=numero).first()
    if existente:
        if existente.tipo_venda != tipo:
            existente.tipo_venda = tipo
            existente.save(update_fields=['tipo_venda'])
        return False
        
    data_criacao = None
    raw = payload.get("dataCriacao")
    if raw:
        try:
            data_criacao = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            data_criacao = None
    HistoricoPapPedido.objects.create(
        numero_pedido=numero,
        tipo_venda=tipo,
        pdv=pdv or "",
        status=str(payload.get("status") or payload.get("chaveStatusPrimario") or "")[:80],
        data_criacao_pap=data_criacao,
        origem="api",
        payload=payload,
    )
    return True





def _executar_loop_busca(page, *, busca_id: int, busca) -> tuple[bool, str]:
    """
    Busca dados do PAP via API direta usando o token da sessão autenticada.
    
    O browser (Playwright) é usado APENAS para login seguro — nenhum dado é coletado
    por scraping de UI. Após extrair o token da sessão, todas as chamadas são
    feitas diretamente para api/portal/vendas via HTTP.
    
    Isso resolve o problema das abas SPA que não respondem ao tipoVenda corretamente.
    """
    from crm_app.models import HistoricoPapBusca, HistoricoPapPedido
    from crm_app.historico_pap import normalizar_pedido, extrair_lista_api, montar_url_vendas, TIPO_API_ALIASES
    import re
    from django.utils import timezone

    encontrados = 0
    novos = 0
    ignorados = 0
    novos_numeros = []
    por_tipo = {}
    vendas_para_processar = []

    data_ini = _iso_inicio(busca.data_inicio)
    data_fim = _iso_fim(busca.data_fim)
    pdv = busca.pdv
    tipos = list(busca.tipos or [])
    
    # ─── PASSO 1: Extrair token da sessão autenticada ───────────────────────────
    # O browser já está logado (feito em _executar_busca antes de chamar aqui).
    # Extraímos o token JWT da sessão para usar nas chamadas de API direta.
    token = _extrair_token(page)
    if not token:
        # Tentar navegar ao histórico para acionar o token na SPA
        try:
            page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            token = _extrair_token(page)
        except Exception as exc:
            logger.warning("[HISTORICO PAP] Falha ao navegar ao histórico para extrair token: %s", exc)
    
    if not token:
        return False, (
            "Não foi possível extrair o token da sessão PAP. "
            "O login foi feito mas o token não está disponível no contexto do browser. "
            "Verifique se a Ana consegue acessar o Histórico PAP normalmente."
        )
    
    ok_jwt, payload_jwt, token_limpo = validar_e_decodificar_jwt(token)
    if not ok_jwt:
        return False, f"Token da sessão PAP inválido ou expirado: {token_limpo}"
    
    logger.info(
        "[HISTORICO PAP] Token da sessão extraído com sucesso. "
        "Iniciando busca via API direta (sem scraping de UI). "
        "Tipos: %s | Período: %s → %s",
        tipos or ["VENDA", "INTERESSE", "PRE_VENDA"], data_ini[:10], data_fim[:10]
    )
    
    # ─── PASSO 2: Para cada tipo, buscar via API direta ─────────────────────────
    for tipo_alvo in (tipos or ["VENDA", "INTERESSE", "PRE_VENDA"]):
        if _job_cancelado(busca_id):
            logger.info("[HISTORICO PAP] Job %s cancelado antes de buscar %s.", busca_id, tipo_alvo)
            break
        
        # INTERESSE usa alias "INTERESSE_SALVO" na API do PAP
        aliases = TIPO_API_ALIASES.get(tipo_alvo, (tipo_alvo,))
        
        # Definir status conforme tipo:
        # - VENDA: usar lista de status de vendas (ANALISE_BO, PEDIDO_GERADO, etc.)
        # - INTERESSE/PRE_VENDA: sem filtro de status (a API retorna tudo)
        if tipo_alvo == "VENDA":
            status_busca = STATUS_LISTA_PADRAO
        else:
            status_busca = None  # Sem filtro de status para INTERESSE e PRE_VENDA
        
        itens_tipo = []
        encontrou_dados = False
        
        for alias in aliases:
            logger.info(
                "[HISTORICO PAP] Buscando tipo=%s alias=%s via API direta...",
                tipo_alvo, alias
            )
            
            # Buscar primeira página para saber o total
            url_p1 = montar_url_vendas(
                data_inicio=data_ini,
                data_fim=data_fim,
                pdv=pdv or "",
                tipo_api=alias,
                page=1,
                limit=200,  # Limite alto para reduzir número de páginas
                status=status_busca,
            )
            
            resp_p1 = _fetch_json(page, url_p1, token=token_limpo)
            
            if not resp_p1.get("ok"):
                status_http = resp_p1.get("status", 0)
                err_msg = resp_p1.get("error", "")
                logger.warning(
                    "[HISTORICO PAP] API retornou erro para %s (alias=%s): status=%s err=%s",
                    tipo_alvo, alias, status_http, err_msg
                )
                # 401/403 = token inválido — abortar todos os tipos
                if status_http in (401, 403):
                    return False, (
                        f"Sessão/token rejeitado pela API do PAP ao buscar {tipo_alvo}. "
                        "O token foi extraído do browser mas a API não aceitou. "
                        "Isso pode indicar que a sessão expirou durante a busca."
                    )
                continue  # Tentar próximo alias
            
            lista_p1, total = extrair_lista_api(resp_p1.get("json"))
            lista_p1 = lista_p1 or []
            total = total or len(lista_p1)
            
            logger.info(
                "[HISTORICO PAP] API direta %s (alias=%s): total=%d, p1=%d itens",
                tipo_alvo, alias, total, len(lista_p1)
            )
            
            itens_tipo.extend(lista_p1)
            encontrou_dados = True
            
            # Buscar páginas adicionais se necessário
            paginas_necessarias = max(1, -(-total // 200))  # ceil division
            for pg in range(2, paginas_necessarias + 1):
                if _job_cancelado(busca_id):
                    break
                    
                url_pg = montar_url_vendas(
                    data_inicio=data_ini,
                    data_fim=data_fim,
                    pdv=pdv or "",
                    tipo_api=alias,
                    page=pg,
                    limit=200,
                    status=status_busca,
                )
                resp_pg = _fetch_json(page, url_pg, token=token_limpo)
                if resp_pg.get("ok"):
                    lista_pg, _ = extrair_lista_api(resp_pg.get("json"))
                    if lista_pg:
                        itens_tipo.extend(lista_pg)
                        logger.info(
                            "[HISTORICO PAP] Página %d/%d para %s: +%d itens",
                            pg, paginas_necessarias, tipo_alvo, len(lista_pg)
                        )
                    else:
                        break  # Sem mais itens
                else:
                    logger.warning(
                        "[HISTORICO PAP] Erro na página %d para %s: %s",
                        pg, tipo_alvo, resp_pg.get("error", resp_pg.get("status"))
                    )
                    break
                    
                time.sleep(_intervalo() * 0.5)  # Pausa menor pois é API direta
            
            break  # Sucesso com este alias, não precisar tentar o próximo
        
        if not encontrou_dados:
            logger.warning(
                "[HISTORICO PAP] Nenhum dado obtido para %s (aliases testados: %s). "
                "Verifique se o período contém registros deste tipo.",
                tipo_alvo, aliases
            )
        
        # Processar itens do tipo atual
        itens_dict = [v for v in itens_tipo if isinstance(v, dict)]
        logger.info(
            "[HISTORICO PAP] Total de itens válidos para %s: %d",
            tipo_alvo, len(itens_dict)
        )
        
        t_api = getattr(HistoricoPapPedido, f"TIPO_{tipo_alvo.replace('-', '_')}", tipo_alvo)
        for v in itens_dict:
            ped = normalizar_pedido(v.get("numeroPedido"))
            pdv_venda = str(v.get("identificadorPdv") or "").strip()
            if pdv and pdv_venda != pdv:
                continue
            if not ped:
                continue
            vendas_para_processar.append((ped, t_api, pdv_venda, v))
        
        time.sleep(_intervalo())

    # ─── PASSO 3: Gravar no banco ────────────────────────────────────────────────
    def _processar_banco():
        nonlocal encontrados, ignorados, novos, por_tipo, novos_numeros
        for ped, t_api, pdv_venda, v in vendas_para_processar:
            encontrados += 1
            
            if t_api not in por_tipo:
                por_tipo[t_api] = {"encontrados": 0, "novos": 0, "ignorados": 0}
            por_tipo[t_api]["encontrados"] += 1
            
            if _pedido_conhecido(ped):
                ignorados += 1
                por_tipo[t_api]["ignorados"] += 1
            else:
                if _salvar_novo(ped, t_api, pdv_venda, v):
                    novos += 1
                    por_tipo[t_api]["novos"] += 1
                    novos_numeros.append(ped)
                else:
                    ignorados += 1
                    por_tipo[t_api]["ignorados"] += 1
                    
    _run_django_sync(_processar_banco)

    status_final = HistoricoPapBusca.STATUS_CANCELADO if _job_cancelado(busca_id) else HistoricoPapBusca.STATUS_CONCLUIDO
    
    _run_django_sync(
        lambda: _atualizar(
            busca_id,
            status=status_final,
            encontrados=encontrados,
            novos=novos,
            ignorados=ignorados,
            por_tipo=por_tipo,
            novos_numeros=novos_numeros,
            mensagem="Busca efetuada via API direta (token de sessão).",
            finalizado_em=timezone.now(),
            relatorio_json={"fase": "concluido", "por_tipo": por_tipo},
        )
    )
    return True, ""





def _executar_busca(busca_id: int, login_pap_id: int, token_manual: str = ""):
    from django.contrib.auth import get_user_model
    from crm_app.models import HistoricoPapBusca
    from crm_app.services_pap_nio import PAPNioAutomation
    import os
    from django.conf import settings
    from django.utils import timezone

    User = get_user_model()
    login_pap = _run_django_sync(lambda: User.objects.get(pk=login_pap_id))
    busca = _run_django_sync(lambda: HistoricoPapBusca.objects.get(pk=busca_id))

    matricula = (getattr(login_pap, "matricula_pap", None) or "").strip()

    em_cooldown, seg_cooldown = verificar_cooldown_login(matricula)
    if em_cooldown:
        min_restantes = max(1, seg_cooldown // 60)
        msg_cd = (
            f"Cooldown de segurança ativo ({min_restantes} min restantes) para proteger "
            f"o usuário {login_pap.username} contra bloqueios de login na Nio. "
        )
        _run_django_sync(
            lambda: _atualizar(
                busca_id,
                status=HistoricoPapBusca.STATUS_ERRO,
                mensagem=msg_cd,
                finalizado_em=timezone.now(),
            )
        )
        return

    senha = (getattr(login_pap, "senha_pap", None) or "").strip()
    automacao = PAPNioAutomation(
        matricula_pap=matricula,
        senha_pap=senha,
        vendedor_nome=getattr(login_pap, "username", "Historico-PAP") or "Historico-PAP",
        headless=getattr(settings, "PAP_HEADLESS", True),
        capture_screenshots=False,
        optimize_for_credit=False,
        url_pos_login=PAP_HISTORICO_URL,
    )
    if hasattr(automacao, "storage_state_path") and os.path.exists(automacao.storage_state_path):
        try:
            os.remove(automacao.storage_state_path)
        except Exception:
            pass
            
    try:
        ok, msg = automacao.iniciar_sessao()
        if not ok:
            registrar_cooldown_login(matricula, 900)
            _run_django_sync(
                lambda: _atualizar(
                    busca_id,
                    status=HistoricoPapBusca.STATUS_ERRO,
                    mensagem=msg or "Falha ao logar no PAP. Cooldown anti-bloqueio ativado.",
                    finalizado_em=timezone.now(),
                )
            )
            return

        limpar_cooldown_login(matricula)
        page = automacao.page
        
        sucesso, err_msg = _executar_loop_busca(
            page=page,
            busca_id=busca_id,
            busca=busca,
        )
        
        if not sucesso:
            _run_django_sync(
                lambda: _atualizar(
                    busca_id,
                    status=HistoricoPapBusca.STATUS_ERRO,
                    mensagem=err_msg,
                    finalizado_em=timezone.now(),
                )
            )
    finally:
        try:
            automacao._fechar_sessao()
        except Exception:
            pass


def _job_cancelado(busca_id: int) -> bool:
    from crm_app.models import HistoricoPapBusca

    def _chk():
        st = HistoricoPapBusca.objects.filter(pk=busca_id).values_list("status", flat=True).first()
        return st == HistoricoPapBusca.STATUS_CANCELADO

    try:
        return bool(_run_django_sync(_chk))
    except Exception:
        return False


def _buscar_tipo(
    page, *, busca_id: int, tipo: str, data_ini: str, data_fim: str, pdv: str, token: str = ""
) -> dict:
    aliases = TIPO_API_ALIASES.get(tipo, (tipo,))
    last_err = ""
    for alias in aliases:
        if tipo == "PRE_VENDA":
            lista_status = ("PRE_VENDA", None)
        elif tipo in ("INTERESSE", "INTERESSE_SALVO"):
            lista_status = ("MINHAS_PENDENCIAS", None)
        else:
            lista_status = (STATUS_LISTA_PADRAO, None)

        for status in lista_status:
            url = montar_url_vendas(
                data_inicio=data_ini,
                data_fim=data_fim,
                pdv=pdv,
                tipo_api=alias,
                page=1,
                status=status,
            )
            resp = _fetch_json(page, url, token=token)
            if not isinstance(resp, dict):
                last_err = "resposta inválida"
                continue
            if not resp.get("ok"):
                last_err = f"HTTP {resp.get('status')} {resp.get('error') or ''}".strip()
                # 401/403: token/sessão inválidos — aborta todos os tipos
                if resp.get("status") in (401, 403):
                    return {
                        "encontrados": 0,
                        "novos": 0,
                        "ignorados": 0,
                        "novos_numeros": [],
                        "tipo_api": alias,
                        "erro": (
                            f"{last_err}. Sessão/token rejeitado pela API do PAP. "
                            "Não é bloqueio de login; verifique se a Ana abre o Histórico no PAP "
                            "e se a matrícula/senha estão corretas."
                        ),
                        "erro_fatal": True,
                    }
                continue
            lista, total = extrair_lista_api(resp.get("json"))
            if resp.get("status") == 200 and (lista is not None):
                # lista vazia com total 0 ainda é sucesso (período sem pedidos)
                return _paginar_tipo(
                    page,
                    busca_id=busca_id,
                    tipo=tipo,
                    tipo_api=alias,
                    data_ini=data_ini,
                    data_fim=data_fim,
                    pdv=pdv,
                    status=status,
                    primeira=lista or [],
                    total=total or 0,
                    
                )
        time.sleep(_intervalo())
    logger.warning("[HISTORICO PAP] Tipo %s não retornou dados (%s)", tipo, last_err)
    return {
        "encontrados": 0,
        "novos": 0,
        "ignorados": 0,
        "novos_numeros": [],
        "tipo_api": aliases[0],
        "erro": last_err,
    }


def _paginar_tipo(
    page,
    *,
    busca_id: int,
    tipo: str,
    tipo_api: str,
    data_ini: str,
    data_fim: str,
    pdv: str,
    status: Optional[str],
    primeira: list[dict],
    total: int,
    token: str = "",
) -> dict:
    encontrados = 0
    novos = 0
    ignorados = 0
    novos_numeros: list[str] = []
    paginas = max(1, (int(total or 0) + LIMIT_PAGINA - 1) // LIMIT_PAGINA) if total else 1
    paginas = min(paginas, 80)

    def _ingerir(lista: list[dict]):
        nonlocal encontrados, novos, ignorados
        for p in lista:
            ped = normalizar_pedido(p.get("numeroPedido") or p.get("pedido"))
            if not ped:
                continue
            encontrados += 1

            def _one():
                if _pedido_conhecido(ped):
                    return False
                return _salvar_novo(ped, tipo, pdv, p)

            if _run_django_sync(_one):
                novos += 1
                novos_numeros.append(ped)
            else:
                ignorados += 1

    _ingerir(primeira)
    for page_n in range(2, paginas + 1):
        if _job_cancelado(busca_id):
            break
        time.sleep(_intervalo())
        url = montar_url_vendas(
            data_inicio=data_ini,
            data_fim=data_fim,
            pdv=pdv,
            tipo_api=tipo_api,
            page=page_n,
            status=status,
        )
        resp = _fetch_json(page, url, token=token)
        if not isinstance(resp, dict) or not resp.get("ok"):
            logger.warning("[HISTORICO PAP] Falha página %s tipo %s: %s", page_n, tipo, resp)
            break
        lista, _ = extrair_lista_api(resp.get("json"))
        if not lista:
            break
        _ingerir(lista)
        _run_django_sync(
            lambda: _atualizar(
                busca_id,
                encontrados=encontrados,
                novos=novos,
                ignorados=ignorados,
                relatorio_json={"fase": f"{tipo} p.{page_n}/{paginas}"},
            )
        )
    return {
        "encontrados": encontrados,
        "novos": novos,
        "ignorados": ignorados,
        "novos_numeros": novos_numeros,
        "tipo_api": tipo_api,
    }
