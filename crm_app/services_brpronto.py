# crm_app/services_brpronto.py
"""
Consulta de biometria no Br Pronto PDV (ged360) via Playwright.
Usado na ferramenta de auditoria para checar se existe "Doc. Apto para Venda" para um CPF.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

BRPRONTO_LOGIN_URL = "https://ged360.niointernet.com.br/brprontopdv/autenticacao/index"
STATUS_APTO_VENDA = "Doc. Apto para Venda"
COL_RESULTADO_ANALISE = 11  # índice da coluna "Resultado da Análise" na tabela
COL_DATA_ENVIO = 4         # índice "Data de Envio da Digitalização"


def _normalizar_cpf(cpf: str) -> str:
    """Retorna apenas dígitos do CPF."""
    if not cpf:
        return ""
    return re.sub(r"\D", "", str(cpf))


def consultar_biometria_brpronto(
    login: str,
    senha: str,
    cpf: str,
    dominio: Optional[str] = None,
    headless: bool = True,
    timeout_ms: int = 60000,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """
    Consulta o Br Pronto PDV por CPF e retorna se existe biometria aprovada e a lista de registros.

    Args:
        login: Login Br Pronto (prkUsuario).
        senha: Senha Br Pronto (desSenha).
        cpf: CPF a consultar (apenas dígitos ou formatado).
        dominio: Domínio no login (opcional).
        headless: Se True, navegador em modo headless.
        timeout_ms: Timeout geral em ms.

    Returns:
        Tuple (sucesso, mensagem_erro, resultado).
        resultado: {
            "aprovada": bool,
            "data_mais_recente_apta": str | None,  # ex: "12/02/2026 23:02:51"
            "registros": [ { "protocolo", "cpf_cnpj", "n_linha", "linha_provisoria", "data_envio", "data_conferencia", "regional", "cod_pdv", "login", "tipo_servico", "nome_fantasia", "resultado_analise", "versao_app" }, ... ]
        }
        Em caso de falha: (False, mensagem, {}).
    """
    if not HAS_PLAYWRIGHT:
        return False, "Playwright não está instalado.", {}

    cpf_limpo = _normalizar_cpf(cpf)
    if len(cpf_limpo) != 11:
        return False, "CPF deve ter 11 dígitos.", {}

    if not login or not senha:
        return False, "Login e senha Br Pronto são obrigatórios. Configure no seu cadastro.", {}

    resultado: Dict[str, Any] = {"aprovada": False, "data_mais_recente_apta": None, "registros": []}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)

            # 1) Login
            page.goto(BRPRONTO_LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(2000)

            usuario = page.query_selector('#prkUsuario')
            if not usuario:
                usuario = page.query_selector('input[name="prkUsuario"]')
            if not usuario:
                browser.close()
                return False, "Página de login Br Pronto não encontrou campo de usuário.", {}

            usuario.fill(login)
            page.query_selector('#desSenha') or page.query_selector('input[name="desSenha"]')
            senha_el = page.query_selector('#desSenha') or page.query_selector('input[name="desSenha"]')
            if senha_el:
                senha_el.fill(senha)

            # Domínio (opcional): pode ser select ou input
            if dominio:
                dom_el = page.query_selector('input[name*="dominio"], select[name*="dominio"], #dominio')
                if dom_el:
                    try:
                        dom_el.fill(dominio)
                    except Exception:
                        try:
                            page.select_option('select[name*="dominio"], #dominio', label=dominio)
                        except Exception:
                            pass

            # Submeter login
            btn = page.query_selector('input[type="submit"], button[type="submit"], .submit')
            if btn:
                btn.click()
            else:
                page.keyboard.press("Enter")
            page.wait_for_timeout(3000)

            # 2) Menu Relatórios -> Detalhado
            relatorios = page.locator('div.item').filter(has_text="Relatórios").first
            if relatorios.count():
                relatorios.click()
                page.wait_for_timeout(1500)
            detalhado = page.locator('div.item').filter(has_text="Detalhado").first
            if detalhado.count():
                detalhado.click()
            page.wait_for_timeout(2000)

            # 3) Campo CPF e Filtrar
            cpf_input = page.query_selector('#cpf') or page.query_selector('input[name="num_cpf"]')
            if not cpf_input:
                browser.close()
                return False, "Página de relatório detalhado não encontrou campo CPF.", {}

            cpf_input.fill(cpf_limpo)
            page.wait_for_timeout(500)

            btn_filtrar = page.query_selector('input.bt-filtro[name="btnFiltrar"], input[value="Filtrar"]')
            if not btn_filtrar:
                btn_filtrar = page.query_selector('input[type="submit"][value="Filtrar"]')
            if btn_filtrar:
                btn_filtrar.click()
            else:
                page.keyboard.press("Enter")
            page.wait_for_timeout(4000)

            # 4) Resultado da consulta - tabela
            h1 = page.query_selector('h1:has-text("Resultado da Consulta")')
            table = page.query_selector('#table-protocolo') or page.query_selector('table.registros-table')
            if not table:
                browser.close()
                return True, None, {**resultado, "registros": [], "aprovada": False}

            # Parsing: thead para ordem das colunas (já sabemos pela doc)
            # Colunas: Protocolo, CPF/CNPJ, N. da Linha, Linha Provisória, Data de Envio da Digitalização,
            #          Data da Conferência, Regional, Cód. PDV, Login, Tipo de Serviço, Nome Fantasia, Resultado da Análise, Versão APP
            registros: List[Dict[str, str]] = []
            rows = table.query_selector_all('tbody tr')
            datas_aptas: List[str] = []

            for tr in rows:
                cells = tr.query_selector_all('td')
                if len(cells) < 12:
                    continue
                # Extrair texto de cada célula (em .lines pode ter div)
                def cell_text(cell):
                    div = cell.query_selector('div')
                    if div:
                        return (div.inner_text() or "").strip()
                    return (cell.inner_text() or "").strip()

                textos = [cell_text(c) for c in cells]
                if len(textos) <= COL_RESULTADO_ANALISE:
                    continue

                protocolo = textos[0] if len(textos) > 0 else ""
                cpf_cnpj = textos[1] if len(textos) > 1 else ""
                n_linha = textos[2] if len(textos) > 2 else ""
                linha_provisoria = textos[3] if len(textos) > 3 else ""
                data_envio = textos[4] if len(textos) > 4 else ""
                data_conferencia = textos[5] if len(textos) > 5 else ""
                regional = textos[6] if len(textos) > 6 else ""
                cod_pdv = textos[7] if len(textos) > 7 else ""
                login_pdv = textos[8] if len(textos) > 8 else ""
                tipo_servico = textos[9] if len(textos) > 9 else ""
                nome_fantasia = textos[10] if len(textos) > 10 else ""
                resultado_analise = textos[11] if len(textos) > 11 else ""
                versao_app = textos[12] if len(textos) > 12 else ""

                registros.append({
                    "protocolo": protocolo,
                    "cpf_cnpj": cpf_cnpj,
                    "n_linha": n_linha,
                    "linha_provisoria": linha_provisoria,
                    "data_envio": data_envio,
                    "data_conferencia": data_conferencia,
                    "regional": regional,
                    "cod_pdv": cod_pdv,
                    "login": login_pdv,
                    "tipo_servico": tipo_servico,
                    "nome_fantasia": nome_fantasia,
                    "resultado_analise": resultado_analise,
                    "versao_app": versao_app,
                })

                if STATUS_APTO_VENDA in resultado_analise and data_envio:
                    datas_aptas.append(data_envio)

            resultado["registros"] = registros

            # Ordenar datas (formato DD/MM/YYYY HH:MM:SS) e pegar a mais recente
            def parse_data(s: str) -> Optional[Tuple[int, int, int, int, int, int]]:
                m = re.match(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})", s.strip())
                if m:
                    return (int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4)), int(m.group(5)), int(m.group(6)))
                return None

            datas_parseadas = [(parse_data(d), d) for d in datas_aptas if parse_data(d)]
            datas_parseadas.sort(key=lambda x: x[0], reverse=True)
            if datas_parseadas:
                resultado["aprovada"] = True
                resultado["data_mais_recente_apta"] = datas_parseadas[0][1]

            browser.close()
            return True, None, resultado

    except Exception as e:
        logger.exception("[BrPronto] Erro ao consultar biometria: %s", e)
        return False, str(e), {}
