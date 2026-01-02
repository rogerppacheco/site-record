# crm_app/services_nio.py
"""
Serviço para automação de consulta de faturas no site da Nio Internet
"""
import os
import time
import re
from datetime import datetime
from urllib.parse import urlparse
from decimal import Decimal
import requests
from io import BytesIO
from django.conf import settings

# Selenium (fallback legado)
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    HAS_PLAYWRIGHT = False

# Caminho default para storage_state (cookies/recaptcha resolvida manualmente)
DEFAULT_STORAGE_STATE = getattr(settings, "NIO_STORAGE_STATE", os.path.join(settings.BASE_DIR, ".playwright_state.json"))
NIO_BASE_URL = "https://negociacao.niointernet.com.br"


class NioFaturaService:
    """Serviço para buscar faturas no site da Nio Internet"""
    
    BASE_URL = "https://servicos.niointernet.com.br/ajuda/servicos/segunda-via"
    
    def __init__(self, headless=True):
        """
        Inicializa o serviço
        :param headless: Se True, executa navegador em background (sem interface)
        """
        self.headless = headless
        self.driver = None
    
    def _setup_driver(self):
        """Configura o WebDriver do Chrome"""
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--window-size=1920,1080')
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--start-maximized')
        
        # Habilita download automático
        prefs = {
            "download.default_directory": "/tmp",
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        self.driver = webdriver.Chrome(options=chrome_options)
        if not self.headless:
            self.driver.maximize_window()
    
    def _close_driver(self):
        """Fecha o navegador"""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def _tenta_fechar_banner(self, wait):
        """Fecha banners de cookies ou popups simples para liberar a tela"""
        try:
            buttons = self.driver.find_elements(
                By.XPATH,
                "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'aceitar') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'fechar') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'continuar')]"
            )
            for btn in buttons:
                if btn.is_displayed() and btn.is_enabled():
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(0.5)
        except Exception:
            # Se não houver banner, segue sem bloquear
            pass
    
    def buscar_fatura(self, cpf_cnpj, timeout=30):
        """
        Busca dados da fatura no site da Nio
        
        :param cpf_cnpj: CPF ou CNPJ do cliente (sem formatação)
        :param timeout: Tempo máximo de espera em segundos
        :return: dict com dados da fatura ou None se não encontrar
        """
        try:
            self._setup_driver()
            
            # Acessa a página
            self.driver.get(self.BASE_URL)
            time.sleep(2)
            
            wait = WebDriverWait(self.driver, timeout)

            # Se houver banner de cookies, tenta fechar para liberar os elementos
            self._tenta_fechar_banner(wait)

            # Aguarda campo de CPF/CNPJ estar disponível e clicável
            input_selectors = [
                (By.ID, "document-input"),
                (By.ID, "document-input-menu"),
                (By.XPATH, "//input[contains(@placeholder, 'CPF') or contains(@placeholder, 'CNPJ') or contains(@name, 'cpf') or contains(@name, 'documento')]") ,
                (By.CSS_SELECTOR, "input[type='text']"),
            ]

            input_cpf = None
            for by, selector in input_selectors:
                try:
                    candidate = wait.until(EC.presence_of_element_located((by, selector)))
                    input_cpf = candidate
                    break
                except TimeoutException:
                    continue
            if not input_cpf:
                raise NoSuchElementException("Campo de CPF/CNPJ não localizado")

            try:
                input_cpf.clear()
                input_cpf.send_keys(cpf_cnpj)
                input_cpf.send_keys(Keys.ENTER)
            except Exception:
                # Força preenchimento via JS se não for interativo
                self.driver.execute_script(
                    "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
                    input_cpf,
                    cpf_cnpj,
                )
            time.sleep(1)

            # Procura botão de busca/consulta e força clique via JS para evitar overlay
            btn_selectors = [
                (By.XPATH, "//input[@id='document-input']/following-sibling::button"),
                (By.XPATH, "//button[@aria-label='Consultar segunda via' or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'consultar segunda via') or @type='submit']"),
                (By.CSS_SELECTOR, "form button[type='submit']"),
                (By.XPATH, "//form//button"),
                (By.XPATH, "//input[@type='submit']"),
            ]

            btn_buscar = None
            for by, selector in btn_selectors:
                try:
                    candidate = wait.until(EC.presence_of_element_located((by, selector)))
                    btn_buscar = candidate
                    break
                except TimeoutException:
                    continue

            if btn_buscar:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn_buscar)
                self.driver.execute_script("arguments[0].click();", btn_buscar)

            # Aguarda carregamento dos dados
            time.sleep(5)
            
            # Extrai dados da página
            dados = self._extrair_dados_pagina()
            
            return dados
            
        except TimeoutException:
            print(f"❌ Timeout ao buscar fatura para CPF/CNPJ: {cpf_cnpj}")
            return None
        
        except NoSuchElementException as e:
            print(f"❌ Elemento não encontrado: {str(e)}")
            return None
        
        except Exception as e:
            print(f"❌ Erro ao buscar fatura: {str(e)}")
            return None
        
        finally:
            self._close_driver()
    
    def _extrair_dados_pagina(self):
        """
        Extrai dados da fatura da página após consulta
        
        :return: dict com valor, codigo_pix, codigo_barras, pdf_url
        """
        dados = {
            'valor': None,
            'codigo_pix': None,
            'codigo_barras': None,
            'pdf_url': None,
            'data_vencimento': None,
        }
        
        try:
            # Busca valor da fatura
            # Ajustar seletores conforme estrutura real do site
            try:
                valor_element = self.driver.find_element(
                    By.XPATH, 
                    "//*[contains(text(), 'R$') or contains(text(), 'Valor') or contains(text(), 'Total')]"
                )
                texto_valor = valor_element.text
                # Extrai valor numérico
                match = re.search(r'R\$?\s*(\d+[.,]\d{2})', texto_valor)
                if match:
                    dados['valor'] = float(match.group(1).replace(',', '.'))
            except:
                pass
            
            # Busca código de barras
            try:
                cod_barras = self.driver.find_element(
                    By.XPATH,
                    "//*[contains(@class, 'barcode') or contains(@id, 'barcode') or contains(text(), 'Código de barras')]"
                )
                # Extrai apenas números
                codigo = re.sub(r'\D', '', cod_barras.text)
                if len(codigo) >= 44:  # Código de barras padrão tem 47 dígitos
                    dados['codigo_barras'] = codigo[:47]
            except:
                pass
            
            # Busca código PIX
            try:
                pix_element = self.driver.find_element(
                    By.XPATH,
                    "//*[contains(@class, 'pix') or contains(text(), 'Pix') or contains(text(), 'Copiar')]"
                )
                # Código PIX geralmente está em um input ou textarea
                if pix_element.tag_name in ['input', 'textarea']:
                    dados['codigo_pix'] = pix_element.get_attribute('value')
                else:
                    dados['codigo_pix'] = pix_element.text
            except:
                pass
            
            # Busca link do PDF
            try:
                pdf_link = self.driver.find_element(
                    By.XPATH,
                    "//a[contains(@href, '.pdf') or contains(text(), 'PDF') or contains(text(), 'Boleto')]"
                )
                dados['pdf_url'] = pdf_link.get_attribute('href')
            except:
                pass
            
            # Busca data de vencimento
            try:
                venc_element = self.driver.find_element(
                    By.XPATH,
                    "//*[contains(text(), 'Vencimento') or contains(text(), 'vencimento')]"
                )
                texto_venc = venc_element.text
                # Extrai data no formato DD/MM/YYYY
                match = re.search(r'(\d{2})[/-](\d{2})[/-](\d{4})', texto_venc)
                if match:
                    data_str = f"{match.group(1)}/{match.group(2)}/{match.group(3)}"
                    dados['data_vencimento'] = datetime.strptime(data_str, '%d/%m/%Y').date()
            except:
                pass
            
            return dados
            
        except Exception as e:
            print(f"❌ Erro ao extrair dados: {str(e)}")
            return dados
    
    def baixar_pdf(self, pdf_url):
        """
        Baixa o PDF da fatura
        
        :param pdf_url: URL do PDF
        :return: BytesIO com conteúdo do PDF ou None
        """
        try:
            response = requests.get(pdf_url, timeout=30)
            response.raise_for_status()
            
            if response.headers.get('content-type') == 'application/pdf':
                return BytesIO(response.content)
            
            return None
            
        except Exception as e:
            print(f"❌ Erro ao baixar PDF: {str(e)}")
            return None


def buscar_todas_faturas_nio_por_cpf(cpf, incluir_pdf=True):
    """
    Busca TODAS as faturas disponíveis no Nio para um CPF (para matching por vencimento)
    
    Args:
        cpf: CPF do cliente
        incluir_pdf: Se True, tenta buscar via Playwright para pegar PDF (mais lento)
                     Se False, usa apenas API (mais rápido, mas sem PDF)
    """
    cpf_limpo = re.sub(r'\D', '', cpf or '')
    if not cpf_limpo:
        return []

    # Se precisa do PDF, usa Playwright direto (scraping completo)
    if incluir_pdf and HAS_PLAYWRIGHT:
        try:
            print(f"🔍 [DEBUG] Buscando fatura via Playwright (com PDF) para CPF: {cpf_limpo}")
            # Playwright retorna apenas 1 fatura por vez, mas com PDF
            dados = _buscar_fatura_playwright(cpf_limpo)
            if dados:
                return [dados]  # Retorna como lista
        except Exception as e:
            print(f"⚠️ [DEBUG] Playwright falhou, usando API sem PDF: {e}")

    # Usa API Nio (mais rápido, mas sem PDF)
    try:
        from crm_app.nio_api import consultar_dividas_nio
        print(f"🔍 [DEBUG] Buscando TODAS faturas via API Nio para CPF: {cpf_limpo}")
        # Busca até 10 faturas (ajuste se necessário)
        resultado = consultar_dividas_nio(cpf_limpo, offset=0, limit=10)
        
        if not resultado or not resultado.get('invoices'):
            print(f"⚠️ [DEBUG] Nenhuma invoice encontrada")
            return []
        
        faturas = []
        for invoice in resultado['invoices']:
            # Converte data de vencimento
            vencimento = None
            if invoice.get('due_date_raw'):
                try:
                    vencimento = datetime.strptime(invoice['due_date_raw'], '%Y%m%d').date()
                except Exception:
                    pass
            
            faturas.append({
                'valor': Decimal(str(invoice.get('amount', 0))) if invoice.get('amount') else None,
                'codigo_pix': invoice.get('pix'),
                'codigo_barras': invoice.get('barcode'),
                'data_vencimento': vencimento,
                'pdf_url': invoice.get('pdf_url'),  # Geralmente None na API
            })
        
        print(f"✅ [DEBUG] {len(faturas)} faturas retornadas do Nio")
        return faturas
    except Exception as e:
        print(f"❌ Erro ao buscar faturas: {e}")
        return []


def buscar_fatura_nio_por_cpf(cpf, incluir_pdf=False):
    """
    Busca fatura usando a API Nio (com solver de captcha integrado) ou Playwright/Selenium como fallback.
    
    Args:
        cpf: CPF do cliente
        incluir_pdf: Se True, força uso do Playwright para capturar PDF (mais lento)
    """

    cpf_limpo = re.sub(r'\D', '', cpf or '')
    if not cpf_limpo:
        return None

    print(f"🔍 [DEBUG] incluir_pdf={incluir_pdf}, HAS_PLAYWRIGHT={HAS_PLAYWRIGHT}")
    
    # NOTA: Playwright sempre falha por causa do captcha (botão desabilitado)
    # Portanto, não tentamos mais via Playwright por padrão
    # A API Nio fornece todos os dados necessários (PIX, código de barras, valor)
    # exceto o link do PDF, que pode ser baixado manualmente pelo usuário

    # 1) Tenta via API Nio (nio_api.py) com solver de captcha integrado
    try:
        from crm_app.nio_api import consultar_dividas_nio, get_invoice_pdf_url
        import requests
        
        print(f"🔍 [DEBUG] Buscando fatura via API Nio para CPF: {cpf_limpo}")
        resultado = consultar_dividas_nio(cpf_limpo, offset=0, limit=1)
        
        print(f"🔍 [DEBUG] Resultado API: {resultado}")
        
        if resultado and resultado.get('invoices'):
            # Pega a primeira fatura (mais recente)
            invoice = resultado['invoices'][0]
            print(f"🔍 [DEBUG] Invoice encontrada: {invoice}")
            
            # Converte data de vencimento
            vencimento = None
            if invoice.get('due_date_raw'):
                try:
                    vencimento = datetime.strptime(invoice['due_date_raw'], '%Y%m%d').date()
                except Exception:
                    pass
            
            dados = {
                'valor': Decimal(str(invoice.get('amount', 0))) if invoice.get('amount') else None,
                'codigo_pix': invoice.get('pix'),
                'codigo_barras': invoice.get('barcode'),
                'data_vencimento': vencimento,
                'pdf_url': invoice.get('pdf_url'),  # Tenta pegar da API (geralmente None)
            }
            
            # O link do PDF é gerado dinamicamente no frontend, não vem da API
            # NOTA: Playwright não consegue capturar porque o captcha sempre bloqueia o botão
            # O usuário pode baixar o PDF manualmente acessando o site da Nio
            # TODO: Implementar solução com cookies válidos ou API alternativa
            if not dados.get('pdf_url'):
                print(f"ℹ️ [PDF] Link do PDF não disponível via automação. Usuário deve baixar manualmente em: https://negociacao.niointernet.com.br")
            
            print(f"✅ [DEBUG] Dados retornados: {dados}")
            return dados
        else:
            print(f"⚠️ [DEBUG] Nenhuma invoice encontrada no resultado")
            # Retorna um dict especial indicando que não há dívidas
            return {
                'sem_dividas': True,
                'mensagem': 'CPF sem dívidas no momento. Fatura ainda não gerada ou já paga.'
            }
    except Exception as e:
        error_msg = str(e)
        # Se for erro 400, provavelmente é CPF sem dívidas na base da Nio
        if '400' in error_msg or 'Bad Request' in error_msg:
            print(f"ℹ️ [DEBUG] CPF sem dívidas na Nio (400 Bad Request)")
            return {
                'sem_dividas': True,
                'mensagem': 'CPF sem dívidas no momento. Fatura ainda não gerada ou já paga.'
            }
        print(f"❌ API Nio falhou: {e}")
        import traceback
        traceback.print_exc()

    # 2) Fallback: Playwright (scraping legado com storage_state)
    if HAS_PLAYWRIGHT:
        try:
            dados = _buscar_fatura_playwright(cpf_limpo)
            if dados:
                return dados
        except Exception as e:  # pragma: no cover
            print(f"❌ Playwright falhou, tentando Selenium: {e}")

    # 3) Fallback Selenium legado
    try:
        service = NioFaturaService(headless=True)
        return service.buscar_fatura(cpf_limpo)
    except Exception as e:  # pragma: no cover
        print(f"❌ Selenium falhou: {e}")
        return None


def buscar_pdf_url_nio(cpf, debt_id, invoice_id, api_base, token, session_id):
    """
    Busca APENAS a URL do PDF usando Playwright com tokens da API.
    Injeta os tokens para pular captcha e navega pelo fluxo normal.
    
    Args:
        cpf: CPF do cliente
        debt_id: ID da dívida (da API)
        invoice_id: ID da invoice (da API)
        api_base: Base URL da API
        token: Token de autorização
        session_id: ID da sessão
    
    Returns:
        URL do PDF ou None
    """
    if not HAS_PLAYWRIGHT:
        return None
    
    try:
        from playwright.sync_api import sync_playwright
        
        print(f"🔍 [PDF] Buscando PDF via Playwright + API tokens para CPF: {cpf}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            # Usa storage_state se disponível
            state_path = DEFAULT_STORAGE_STATE if os.path.exists(DEFAULT_STORAGE_STATE) else None
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 800},
                storage_state=state_path,
                accept_downloads=True,
            )
            
            page = context.new_page()
            
            # Vai para a página inicial
            print(f"🔍 [PDF] Navegando para página inicial...")
            page.goto(f"{NIO_BASE_URL}/negociar", wait_until="networkidle", timeout=15000)
            page.wait_for_timeout(1000)
            
            # Injeta os tokens da API no localStorage
            print(f"🔑 [PDF] Injetando tokens da API no navegador...")
            page.evaluate(f"""
                localStorage.setItem('token', '{token}');
                localStorage.setItem('apiServerUrl', '{api_base}');
                localStorage.setItem('sessionId', '{session_id}');
            """)
            
            # Recarrega para aplicar os tokens
            page.reload(wait_until="networkidle", timeout=10000)
            page.wait_for_timeout(1500)
            
            # Preenche o CPF e consulta
            print(f"🔍 [PDF] Consultando CPF...")
            page.locator('input[type="text"]').first.fill(cpf)
            page.wait_for_timeout(500)
            
            # O botão pode estar habilitado agora por causa dos tokens
            page.locator('button:has-text("Consultar")').first.click(timeout=10000)
            page.wait_for_timeout(2000)
            page.wait_for_load_state("networkidle", timeout=15000)
            
            # Clica em "ver detalhes" se existir
            ver_detalhes = page.locator('text=/ver detalhes/i').first
            if ver_detalhes.count() > 0:
                ver_detalhes.click()
                page.wait_for_timeout(1000)
            
            # Clica em "Pagar conta"
            print(f"🔍 [PDF] Navegando para página de pagamento...")
            page.locator('button:has-text("Pagar conta")').first.click(timeout=10000)
            page.wait_for_url('**/payment**', timeout=15000)
            page.wait_for_timeout(1500)
            
            # Clica em "Gerar boleto"
            print(f"🔍 [PDF] Gerando boleto...")
            page.locator('div[data-context="btn_container_gerar-boleto"]').first.click(timeout=10000)
            page.wait_for_url('**/paymentbillet**', timeout=10000)
            page.wait_for_timeout(1500)
            
            # Captura o PDF
            print(f"🔍 [PDF] Capturando link do PDF...")
            pdf_url = None
            with context.expect_page(timeout=10000) as popup_info:
                page.locator('text="Baixar PDF"').first.click()
            pdf_page = popup_info.value
            pdf_page.wait_for_load_state('networkidle', timeout=5000)
            pdf_url = pdf_page.url
            print(f'✅ [PDF] Link capturado: {pdf_url[:100]}...')
            pdf_page.close()
            
            browser.close()
            return pdf_url
                
    except Exception as e:
        print(f"❌ [PDF] Erro: {e}")
        import traceback
        traceback.print_exc()
        return None


def _buscar_fatura_playwright(cpf: str):
    """Fluxo headless replicando o script test_nio_completo.py"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        state_path = DEFAULT_STORAGE_STATE if os.path.exists(DEFAULT_STORAGE_STATE) else None
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
            storage_state=state_path,
            accept_downloads=True,
        )

        page = context.new_page()
        page.goto(NIO_BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        page.locator('input[type="text"]').first.fill(cpf)
        page.locator('button:has-text("Consultar")').first.click()
        page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle", timeout=20000)

        ver_detalhes = page.locator('text=/ver detalhes/i').first
        if ver_detalhes.count() > 0:
            ver_detalhes.click()
            page.wait_for_timeout(800)

        html_expandido = page.content()
        vencimento = None
        m = re.search(r'(\d{2}/\d{2}/\d{4})', html_expandido)
        if m:
            try:
                vencimento = datetime.strptime(m.group(1), "%d/%m/%Y").date()
            except Exception:
                pass

        pagar_btn = page.locator('button:has-text("Pagar conta")').first
        pagar_btn.click()
        page.wait_for_url('**/payment**', timeout=15000)
        page.wait_for_timeout(1200)

        html_pagto = page.content()
        valor = None
        vm = re.search(r'R\$\s*&nbsp;\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))', html_pagto, re.IGNORECASE)
        if not vm:
            vm = re.search(r'R\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))', html_pagto, re.IGNORECASE)
        if vm:
            try:
                valor = Decimal(vm.group(1).replace('.', '').replace(',', '.'))
            except Exception:
                pass

        # PIX
        page.locator('div[data-context="btn_container_pagar-online"]').first.click()
        page.wait_for_url('**/paymentpix**', timeout=12000)
        page.wait_for_timeout(1200)
        html_pix = page.content()
        pix_matches = re.findall(r'00020126[0-9a-zA-Z]{100,}', html_pix)
        if not pix_matches:
            pix_matches = re.findall(r'[a-zA-Z0-9]{80,150}', html_pix)
        codigo_pix = pix_matches[0] if pix_matches else None

        # Volta para payment
        page.go_back()
        page.wait_for_url('**/payment**', timeout=12000)
        page.wait_for_timeout(800)

        # Boleto
        page.locator('div[data-context="btn_container_gerar-boleto"]').first.click()
        page.wait_for_url('**/paymentbillet**', timeout=12000)
        page.wait_for_timeout(1200)
        html_boleto = page.content()

        codigo_barras = None
        codigos = re.findall(r'\b(\d{44,50})\b', html_boleto)
        if codigos:
            preferidos = [c for c in codigos if c.startswith('0339')]
            codigo_barras = preferidos[0] if preferidos else codigos[0]

        # PDF - Captura o link quando abre o popup (na página do boleto)
        pdf_url = None
        try:
            print('🔍 [PDF] Tentando capturar link do PDF...')
            with context.expect_page(timeout=10000) as popup_info:
                page.locator('text="Baixar PDF"').first.click()
            pdf_page = popup_info.value
            pdf_page.wait_for_load_state('networkidle', timeout=5000)
            pdf_url = pdf_page.url
            print(f'✅ [PDF] Link capturado com sucesso: {pdf_url}')
            pdf_page.close()
        except Exception as e:
            print(f'⚠️ [PDF] Erro ao capturar link do PDF: {e}')
            import traceback
            traceback.print_exc()

        browser.close()

        return {
            'valor': valor,
            'codigo_pix': codigo_pix,
            'codigo_barras': codigo_barras,
            'data_vencimento': vencimento,
            'pdf_url': pdf_url,
        }
