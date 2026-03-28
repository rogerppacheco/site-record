# crm_app/services_pap_nio.py
"""
Serviço de automação para vendas no PAP Nio via Playwright.
Permite que vendedores autorizados realizem vendas pelo WhatsApp.
"""

import base64
import os
import re
import unicodedata
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from django.conf import settings

logger = logging.getLogger(__name__)

# Tentar importar Playwright
try:
    from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    logger.warning("[PAP NIO] Playwright não instalado. Automação PAP desabilitada.")

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

PAP_LOGIN_URL = "https://pap.niointernet.com.br/"
PAP_VTAL_LOGIN_URL = "https://login.vtal.com/nidp/saml2/sso"
PAP_NOVO_PEDIDO_URL = "https://pap.niointernet.com.br/administrativo/novo-pedido"
PAP_CONSULTA_OS_URL = "https://pap.niointernet.com.br/administrativo/consulta-os"
DEFAULT_TIMEOUT = 30000  # 30 segundos
STORAGE_STATE_DIR = os.path.join(settings.BASE_DIR, 'pap_sessions')

# Semáforo para limitar sessões PAP simultâneas (evita sobrecarga)
_pap_semaphore = threading.Semaphore(2)  # Máximo 2 sessões simultâneas

# =============================================================================
# SELETORES DO SITE PAP NIO
# =============================================================================

SELETORES = {
    # Login Vtal (IDs podem mudar; fallbacks por placeholder/type)
    'login': {
        'matricula': '#inputMatricula, input[placeholder*="Login"], input[name*="matricula"], input[name*="username"], input[name*="login"], input[type="text"]:not([type="search"])',
        'senha': '#passwordInput, input[placeholder*="Senha"], input[placeholder*="OTP"], input[name*="password"], input[name*="senha"], input[type="password"]',
        'btn_login': 'button:has-text("EFETUAR"), button:has-text("Login"), button[type="submit"]',
    },
    
    # Etapa 1: Identificação PDV
    'etapa1': {
        'uf': 'input[placeholder*="UF"]',
        'pdv': 'input[placeholder*="PDV"]',
        # Campo de busca do vendedor: o PAP já mudou placeholder (ex.: só "Vendedor"); manter lista ampla.
        'matricula_vendedor': 'input[placeholder*="matrícula"]',
        'lista_vendedores': 'li',
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 2: Consulta de Viabilidade
    'etapa2': {
        'cep': 'input[placeholder=" "]',
        'numero': 'input[type="number"]',
        'sem_numero': 'input[type="checkbox"]',
        'btn_buscar': 'button:has-text("Buscar")',
        'endereco_instalacao': 'input[placeholder="Endereço de instalação"]',
        'endereco_resultado': 'input[disabled]',
        'lista_enderecos': 'li',
        'referencia': 'input[name="referencia"], input[placeholder*="referência"], input[placeholder*="Referência"], input[placeholder*="referencia"], textarea[placeholder*="referência"], textarea[placeholder*="Referência"]',
        'complementos': 'ul[class*="fQkuQJ"] li, ul[class*="cUdcXF"] li, input[placeholder*="omplemento"] ~ ul li, div:has(input[placeholder*="omplemento"]) ul li',
        'sem_complemento': '#semComplemento, input[id="semComplemento"], label[for="semComplemento"]',
        'btn_avancar': 'button:has-text("Avançar")',
        'btn_continuar_modal': 'button:has-text("Continuar")',
    },
    
    # Etapa 3: Cadastro do Cliente
    'etapa3': {
        'cpf': 'input[name="documento"]',
        'btn_buscar': 'button:has-text("Buscar")',
        'nome_cliente': 'input[disabled][value], input[name*="nome"]',  # Nome vem preenchido
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 4: Contato (campos: name contato, confirmacaoContato, contatoSecundario, email, confirmarEmail)
    'etapa4': {
        'celular_principal': 'input#contato, input[name="contato"]',
        'confirmar_celular': 'input#confirmacaoContato, input[name="confirmacaoContato"]',
        'celular_secundario': 'input#contatoSecundario, input[name="contatoSecundario"]',
        'email': 'input#email, input[name="email"]',
        'confirmar_email': 'input#confirmarEmail, input[name="confirma-email"]',
        'resultado_credito': '.resultado-credito, [class*="credito"], [class*="analise"]',
        'btn_continuar': 'button:has-text("Continuar")',
        'btn_avancar': 'button:has-text("Avançar")',
        'modal_atencao': 'h2:has-text("Atenção!")',
        'btn_modal_ok': 'button:has-text("Ok")',
    },
    
    # Etapa 5: Pagamento/Ofertas (values: BOLETO, CREDITO, DACC)
    'etapa5': {
        'forma_boleto': 'input[value="BOLETO"], label:has-text("Boleto")',
        'forma_cartao': 'input[value="CREDITO"], label:has-text("Cartão de Crédito")',
        'forma_debito': 'input[value="DACC"], label:has-text("Débito em Conta")',
        'banco_input': 'input[placeholder*="Selecione o Banco"], input[placeholder*="Banco"]',
        'agencia': 'input[name="agencia"]',
        'conta': 'input[name="conta"]',
        'digito': 'input[name="digito"]',
        'plano_1giga': 'label:has-text("1 Giga"), [class*="card"]:has-text("1 Giga")',
        'plano_700mega': 'label:has-text("700 Mega"), [class*="card"]:has-text("700 Mega")',
        'plano_500mega': 'label:has-text("500 Mega"), [class*="card"]:has-text("500 Mega")',
        'btn_servicos': 'button:has-text("Serviços disponíveis")',
        'card_fixo': 'div.sc-kUQWMX.bwZXDo:has-text("Fixo"), div.bwZXDo:has-text("Fixo"), div.sc-dcmekm.dBGnOE:has-text("Fixo")',
        'btn_fechar_modal_x': 'button:has(svg path[d*="M19 6.41"]), button[aria-label="Close"], button[aria-label="Fechar"]',
        'btn_streaming': 'button:has-text("Streaming e canais on-line")',
        'opcao_hbomax': 'div:has-text("HBO Max") div.sc-jIyBzM.bSKio, div:has-text("HBO Max") img',
        'opcao_globoplay_premium': 'div:has-text("Plano Premium"):not(:has-text("Padrão")) div.sc-jIyBzM.bSKio, div:has-text("Plano Premium") div.sc-jIyBzM img',
        'opcao_globoplay_basico': 'div:has-text("Plano Padrão com Anúncios") div.sc-jIyBzM.bSKio, div:has-text("Plano Padrão") div.sc-jIyBzM img',
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 6: Resumo
    'etapa6': {
        'status_biometria': '[class*="biometria"], [class*="status"]',
        'btn_abrir_os': 'button:has-text("Abrir OS"), button:has-text("Abrir O.S")',
    },
    
    # Etapa 7: Agendamento
    'etapa7': {
        'calendario': '[class*="calendario"], [class*="calendar"]',
        'data_disponivel': '[class*="disponivel"], [class*="available"]',
        'turno_manha': 'input[value*="manha"], label:has-text("Manhã")',
        'turno_tarde': 'input[value*="tarde"], label:has-text("Tarde")',
        'btn_confirmar': 'button:has-text("Confirmar")',
    },

    # Consulta OS (menu lateral e tela de filtros)
    'consulta_os': {
        'menu_consulta_os': 'a[href*="consulta-os"], span:has-text("Consulta OS"), div.sc-kAzzGY:has(img), [class*="sc-kAzzGY"]',
        'filtros': 'span.titulo-filtro:has-text("Filtros"), .titulo-filtro, span:has-text("Filtros")',
        'input_cpf_cnpj': 'input.input-text-filter[placeholder="Digite o CPF/CNPJ..."], input.input-text-filter',
        'btn_filtrar': 'button.btn-filters-new, button:has-text("Filtrar")',
        'periodo_de': 'input[placeholder*="De"], input[name*="dataInicio"], input[id*="periodo"], input[aria-label*="De"]',
        'periodo_ate': 'input[placeholder*="Até"], input[name*="dataFim"], input[id*="ate"]',
        'table_body_cells': 'td.MuiTableCell-root.MuiTableCell-body',
        'table_rows': 'table tbody tr, [class*="MuiTableBody"] tr',
        'link_detalhar': 'a.detalhar-link[href*="detalhe-os"]',
        'detalhe_status_agendamento': 'span.sc-jrOYZv.ldMRLh, span.ldMRLh',
    },
}

# Seletores OR para o campo "vendedor / matrícula" na etapa Novo Pedido (UI do PAP varia)
SELETORES_MATRICULA_VENDEDOR = [
    'input[placeholder*="matrícula"]',
    'input[placeholder*="matricula"]',
    'input[placeholder*="Matrícula"]',
    'input[placeholder*="vendedor"]',
    'input[placeholder*="Vendedor"]',
    'input[aria-label*="matrícula"]',
    'input[aria-label*="matricula"]',
    'input[aria-label*="vendedor"]',
    'input[aria-label*="Vendedor"]',
    'input[name*="vendedor"]',
    'input[name*="matricula"]',
    'input[id*="vendedor"]',
    'input[id*="matricula"]',
    'input[id*="Vendedor"]',
    'main input[type="search"]',
    '[role="main"] input[type="search"]',
]

SELETORES_MATRICULA_VENDEDOR_CSS = ", ".join(SELETORES_MATRICULA_VENDEDOR)

# Código retornado quando o modal "OPS, OCORREU UM ERRO!" aparece no PAP (erro do portal; orientar abrir chamado Nio)
PAP_ERRO_PORTAL_NIO = "PAP_ERRO_PORTAL_NIO"

# =============================================================================
# CLASSE PRINCIPAL DE AUTOMAÇÃO
# =============================================================================

class PAPNioAutomation:
    """
    Classe para automatizar vendas no PAP Nio.
    Cada instância representa uma sessão de venda.
    """
    
    def __init__(
        self,
        matricula_pap: str,
        senha_pap: str,
        vendedor_nome: str = None,
        headless: bool = True,
        capture_screenshots: bool = None,
        run_id: str = None,
        optimize_for_credit: bool = False,
    ):
        """
        Inicializa a automação PAP.
        
        Args:
            matricula_pap: Matrícula do vendedor no PAP
            senha_pap: Senha + OTP do PAP
            vendedor_nome: Nome do vendedor (para logs)
            headless: Se False, abre o navegador visível (para testes)
            capture_screenshots: Se True, salva screenshot em cada etapa (produção). None = usa settings.PAP_CAPTURE_SCREENSHOTS
            run_id: Identificador da sessão (ex: sessao_id) para nomear os arquivos de screenshot
            optimize_for_credit: Reduz esperas fixas no fluxo de consulta de crédito
        """
        self.matricula_pap = matricula_pap
        self.senha_pap = senha_pap
        self.vendedor_nome = vendedor_nome or matricula_pap
        self.headless = headless
        if capture_screenshots is None:
            try:
                from django.conf import settings
                capture_screenshots = getattr(settings, 'PAP_CAPTURE_SCREENSHOTS', False)
            except Exception:
                capture_screenshots = False
        self.capture_screenshots = capture_screenshots
        self.run_id = run_id or str(int(time.time()))
        self.optimize_for_credit = optimize_for_credit
        
        self.playwright = None  # sync_playwright instance; precisa .stop() para encerrar event loop
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        self.etapa_atual = 0
        self.dados_pedido: Dict[str, Any] = {}
        self.erros: list = []
        self.numero_pedido: Optional[str] = None
        
        # Estado da sessão
        self.logado = False
        self.sessao_iniciada = False
        self._trace_started = False  # Trace Playwright para inspecionar cliques em produção

        # Storage state para manter cookies
        self.storage_state_path = os.path.join(
            STORAGE_STATE_DIR, 
            f'pap_session_{self.matricula_pap}.json'
        )
    
    def _garantir_diretorio_sessoes(self):
        """Garante que o diretório de sessões existe"""
        os.makedirs(STORAGE_STATE_DIR, exist_ok=True)

    def _capture_screenshot(
        self,
        step_name: str,
        wait_selector: str = None,
        wait_timeout_ms: int = 15000,
        *,
        forcar: bool = False,
    ) -> None:
        """
        Salva screenshot em downloads/ e opcionalmente OneDrive.
        Por padrão só roda com capture_screenshots; use forcar=True em falhas quando
        PAP_SCREENSHOTS_ONEDRIVE estiver ligado (ver _capture_screenshot_falha_etapa1).
        """
        from django.conf import settings
        pode = self.capture_screenshots or forcar
        if not pode or not self.page:
            return
        try:
            # Esperar elemento indicar que a tela está pronta (evita print do loading/spinner)
            if wait_selector:
                try:
                    self.page.wait_for_selector(wait_selector, state="visible", timeout=wait_timeout_ms)
                except Exception:
                    pass
            # Pequena pausa para a UI terminar de pintar (React/animations)
            self.page.wait_for_timeout(800)
            base_dir = getattr(settings, 'BASE_DIR', None)
            if not base_dir:
                return
            downloads_dir = os.path.join(base_dir, 'downloads')
            os.makedirs(downloads_dir, exist_ok=True)
            safe_run = str(self.run_id).replace(os.sep, '_').replace('..', '_')[:50]
            safe_step = re.sub(r'[^\w\-]', '_', step_name)[:40]
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"pap_venda_{safe_run}_{safe_step}_{ts}.png"
            filepath = os.path.join(downloads_dir, filename)
            self.page.screenshot(path=filepath, full_page=False)
            logger.info(f"[PAP] Screenshot salvo: {filename}")
            # Enviar para OneDrive se configurado (mesma conta das outras ferramentas)
            if getattr(settings, 'PAP_SCREENSHOTS_ONEDRIVE', False):
                try:
                    from crm_app.onedrive_service import OneDriveUploader
                    folder = getattr(settings, 'PAP_ONEDRIVE_FOLDER', 'PAP_Screenshots')
                    with open(filepath, 'rb') as f:
                        uploader = OneDriveUploader()
                        web_url = uploader.upload_file(f, folder, filename)
                    logger.info(f"[PAP] Screenshot enviado ao OneDrive: {web_url or filename}")
                except Exception as e_od:
                    logger.warning(f"[PAP] Erro ao enviar screenshot ao OneDrive: {e_od}")
        except Exception as e:
            if "Execution context was destroyed" not in str(e) and "context was destroyed" not in str(e):
                logger.warning(f"[PAP] Erro ao salvar screenshot: {e}")

    def _capture_screenshot_falha_etapa1(self, step_name: str, wait_selector: str = None, wait_timeout_ms: int = 0) -> None:
        """
        Screenshot diagnóstico na Etapa 1 (novo pedido / vendedor).
        Grava se PAP_CAPTURE_SCREENSHOTS OU PAP_SCREENSHOTS_ONEDRIVE estiver ativo
        (assim dá para só subir falhas ao OneDrive sem printar todas as etapas).
        """
        from django.conf import settings
        forcar = self.capture_screenshots or getattr(settings, "PAP_SCREENSHOTS_ONEDRIVE", False)
        self._capture_screenshot(step_name, wait_selector=wait_selector, wait_timeout_ms=wait_timeout_ms, forcar=forcar)

    def _highlight_element(self, selector_or_element, duration_ms: int = 800) -> None:
        """
        Destaca visualmente um elemento (outline vermelho) antes de um clique, para debug.
        Se capture_screenshots estiver ativo, tira screenshot após highlight para ver onde vai clicar.
        """
        if not self.page:
            return
        try:
            el = selector_or_element if hasattr(selector_or_element, 'evaluate') else self.page.query_selector(selector_or_element)
            if not el:
                return
            el.evaluate("""el => {
                el.dataset._pap_original_outline = el.style.outline || '';
                el.style.outline = '3px solid red';
                el.style.outlineOffset = '2px';
            }""")
            self.page.wait_for_timeout(duration_ms)
            if self.capture_screenshots:
                self._capture_screenshot("_highlight_clique", wait_selector=None, wait_timeout_ms=0)
            el.evaluate("""el => {
                el.style.outline = el.dataset._pap_original_outline || '';
                el.style.outlineOffset = '';
            }""")
        except Exception as e:
            logger.debug(f"[PAP] Highlight ignorado: {e}")

    def _set_valor_react(self, selector: str, valor: str) -> bool:
        """
        Define valor em campo React de forma que o estado seja atualizado.
        
        Args:
            selector: Seletor CSS do campo
            valor: Valor a ser definido
            
        Returns:
            True se sucesso, False se erro
        """
        try:
            self.page.evaluate(f'''
                (function() {{
                    const element = document.querySelector('{selector}');
                    if (!element) return false;
                    
                    // Método para React
                    const valueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set;
                    const prototype = Object.getPrototypeOf(element);
                    const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
                    
                    if (valueSetter && valueSetter !== prototypeValueSetter) {{
                        prototypeValueSetter.call(element, '{valor}');
                    }} else if (valueSetter) {{
                        valueSetter.call(element, '{valor}');
                    }} else {{
                        element.value = '{valor}';
                    }}
                    
                    element.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    element.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    element.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                    
                    return true;
                }})()
            ''')
            return True
        except Exception as e:
            logger.error(f"[PAP] Erro ao definir valor em {selector}: {e}")
            return False
    
    def _clicar_elemento(self, selector: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
        """
        Clica em um elemento com tratamento de erros.
        
        Args:
            selector: Seletor CSS do elemento
            timeout: Timeout em ms
            
        Returns:
            True se sucesso, False se erro
        """
        try:
            self.page.wait_for_selector(selector, timeout=timeout)
            self.page.click(selector)
            return True
        except Exception as e:
            logger.error(f"[PAP] Erro ao clicar em {selector}: {e}")
            return False
    
    def _esperar_elemento(self, selector: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
        """
        Espera um elemento aparecer na página.
        
        Args:
            selector: Seletor CSS do elemento
            timeout: Timeout em ms
            
        Returns:
            True se encontrado, False se timeout
        """
        try:
            self.page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False
    
    def _extrair_texto(self, selector: str) -> Optional[str]:
        """Extrai texto de um elemento"""
        try:
            element = self.page.query_selector(selector)
            if element:
                return element.inner_text()
            return None
        except Exception:
            return None

    def _extrair_protocolo_pedido(self) -> Optional[str]:
        """Extrai o protocolo do pedido (título, URL, conteúdo). Ex: 'Novo pedido - 202602082408770809'."""
        try:
            self.page.wait_for_timeout(500)
            fontes = [
                lambda: self.page.title() or "",
                lambda: self.page.url or "",
                lambda: self.page.content() or "",
            ]
            for fonte in fontes:
                texto = fonte()
                for pat in [
                    r'Novo pedido\s*[-–]\s*(\d{10,25})',
                    r'novo-pedido[/-](\d+)',
                    r'protocolo[:\s]*(\d+)',
                    r'pedido[:\s]*(\d{12,25})',
                ]:
                    m = re.search(pat, texto, re.I)
                    if m:
                        protocolo = m.group(1)
                        self.dados_pedido['protocolo'] = protocolo
                        return protocolo
            return self.dados_pedido.get('protocolo')
        except Exception:
            return self.dados_pedido.get('protocolo')

    # =========================================================================
    # MÉTODOS DE ETAPAS
    # =========================================================================
    
    def iniciar_sessao(self) -> Tuple[bool, str]:
        """
        Inicia a sessão no navegador e faz login no PAP.
        
        Returns:
            Tuple (sucesso, mensagem)
        """
        if not HAS_PLAYWRIGHT:
            return False, "Playwright não está instalado no servidor."
        
        self._garantir_diretorio_sessoes()
        
        try:
            _pap_semaphore.acquire()
            logger.info(f"[PAP] Iniciando sessão para {self.vendedor_nome}")
            
            self.playwright = sync_playwright().start()
            playwright = self.playwright
            launch_opts = {"headless": self.headless}
            if not self.headless:
                launch_opts["slow_mo"] = 300  # 300ms entre ações para visualizar
            self.browser = playwright.chromium.launch(**launch_opts)
            
            # Tentar carregar sessão existente
            storage_state = self.storage_state_path if os.path.exists(self.storage_state_path) else None
            
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1280, "height": 800},
                storage_state=storage_state,
            )
            
            self.page = self.context.new_page()
            # Timeout padrão alto para evitar "Timeout 5000ms" em produção (rede/React lentos)
            self.page.set_default_timeout(25000)
            self.sessao_iniciada = True

            # Trace: grava todas as ações para inspecionar no Playwright Trace Viewer (ver onde os cliques foram feitos)
            if self.capture_screenshots:
                try:
                    self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    self._trace_started = True
                    logger.info("[PAP] Trace iniciado (gravação de ações para debug)")
                except Exception as e:
                    logger.warning(f"[PAP] Trace não iniciado: {e}")

            # Navegar para o PAP (reduzir waits para acelerar "Acesso reservado")
            self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(400 if self.optimize_for_credit else 1000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                try:
                    # SPAs/SSO muitas vezes não disparam "load" após domcontentloaded — não falhar a sessão por isso
                    self.page.wait_for_load_state("load", timeout=20000)
                except Exception:
                    pass
            # Dar tempo para redirects (ex.: PAP -> SSO); evita "Execution context was destroyed" ao ler url/query_selector
            self.page.wait_for_timeout(1000 if self.optimize_for_credit else 2500)

            # Verificar se precisa fazer login (URL ou formulário de login visível).
            # Retry se a página navegou e o contexto anterior foi destruído.
            current_url = ""
            login_form_visivel = None
            for _ in range(3):
                try:
                    current_url = self.page.url or ""
                    login_form_visivel = (
                        self.page.query_selector('#inputMatricula') or
                        self.page.query_selector('#passwordInput') or
                        self.page.query_selector('input[placeholder*="Login"]') or
                        self.page.query_selector('input[type="password"]')
                    )
                    break
                except Exception as e:
                    if "Execution context was destroyed" in str(e) or "context was destroyed" in str(e):
                        logger.warning("[PAP] Página ainda navegando, aguardando e tentando novamente...")
                        self.page.wait_for_timeout(2500)
                        continue
                    raise

            if "login.vtal.com" in current_url or ("login" in current_url.lower() and "pap.niointernet.com.br" not in current_url) or login_form_visivel:
                sucesso, msg = self._fazer_login()
                if not sucesso:
                    return False, msg
            
            self.logado = True
            # Screenshot só depois da primeira tela do PAP carregar (evita print do spinner)
            self._capture_screenshot(
                "01_login_ok",
                wait_selector=f"{SELETORES['etapa1']['matricula_vendedor']}, button:has-text('Avançar')",
                wait_timeout_ms=8000,
            )

            # Salvar estado da sessão
            try:
                self.context.storage_state(path=self.storage_state_path)
            except Exception as e:
                logger.warning(f"[PAP] Erro ao salvar estado da sessão: {e}")
            
            return True, "Sessão iniciada com sucesso!"
            
        except Exception as e:
            logger.error(f"[PAP] Erro ao iniciar sessão: {e}")
            self._fechar_sessao()
            return False, f"Erro ao iniciar sessão: {str(e)}"
    
    def _fazer_login(self) -> Tuple[bool, str]:
        """
        Realiza o login no PAP via Vtal.
        Trata "upstream request timeout" do SSO com recarregamento e nova tentativa.
        
        Returns:
            Tuple (sucesso, mensagem)
        """
        max_tentativas = 3
        for tentativa in range(1, max_tentativas + 1):
            try:
                logger.info(f"[PAP] Fazendo login para {self.matricula_pap} (tentativa {tentativa}/{max_tentativas})")
                
                # Garantir que estamos na página de login (pode ter vindo de retry após timeout)
                if "login.vtal.com" in self.page.url and "upstream request timeout" in (self.page.content() or "").lower():
                    logger.warning("[PAP] Erro upstream timeout detectado, recarregando página de login...")
                    self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                
                # Aguardar formulário de login estar visível
                matricula_sel = self.page.query_selector('#inputMatricula') or self.page.query_selector('input[placeholder*="Login"]') or self.page.query_selector('input[name*="matricula"]') or self.page.query_selector('input[type="text"]')
                if not matricula_sel:
                    self.page.wait_for_selector('#inputMatricula, input[placeholder*="Login"], input[name*="matricula"]', state="visible", timeout=15000)
                senha_sel = self.page.query_selector('#passwordInput') or self.page.query_selector('input[type="password"]')
                if not senha_sel:
                    self.page.wait_for_selector('#passwordInput, input[type="password"]', state="visible", timeout=10000)
                
                # Preencher matrícula e senha (tentar vários seletores)
                for sel in ['#inputMatricula', 'input[placeholder*="Login"]', 'input[name*="matricula"]', 'input[name*="username"]']:
                    try:
                        self.page.fill(sel, self.matricula_pap)
                        break
                    except Exception:
                        continue
                for sel in ['#passwordInput', 'input[type="password"]', 'input[placeholder*="Senha"]']:
                    try:
                        self.page.fill(sel, self.senha_pap)
                        break
                    except Exception:
                        continue
                
                # Clicar no botão de login
                btn = self.page.query_selector('button:has-text("EFETUAR")') or self.page.query_selector('button:has-text("Login")') or self.page.query_selector('button[type="submit"]')
                if btn:
                    btn.click()
                else:
                    self.page.click(SELETORES['login']['btn_login'])

                # Aguardar a página reagir (redirecionamento ou mensagem de erro).
                # Tempo suficiente para o redirect do SSO evitar "Execution context was destroyed".
                self.page.wait_for_timeout(1500 if self.optimize_for_credit else 3500)

                # Validar: se aparecer "Login failed, please try again" (ou similar), não avançar
                if self._pagina_tem_erro_login():
                    logger.warning("[PAP] Login falhou: mensagem de erro detectada na tela.")
                    return False, "Login falhou. Verifique matrícula, senha e OTP (se exigido). Tente novamente."

                # Aguardar redirecionamento para PAP (pode haver múltiplos redirects via SSO)
                try:
                    self.page.wait_for_url(
                        lambda url: "pap.niointernet.com.br" in url and "login" not in url.lower(),
                        timeout=14000 if self.optimize_for_credit else 22000
                    )
                    # Nova checagem: às vezes o redirect mostra PAP mas ainda com iframe de erro
                    if self._pagina_tem_erro_login():
                        return False, "Login falhou. Verifique matrícula, senha e OTP (se exigido). Tente novamente."
                    logger.info(f"[PAP] Login bem-sucedido para {self.matricula_pap}")
                    return True, "Login realizado com sucesso!"
                except Exception:
                    current_url = self.page.url
                    pagina = (self.page.content() or "").lower()
                    # Se a tela mostra erro de login, falhar de forma clara
                    if self._pagina_tem_erro_login():
                        return False, "Login falhou. Verifique matrícula, senha e OTP (se exigido). Tente novamente."
                    # Sucesso mesmo com exceção (ex: timeout no wait mas URL já correta)
                    if "pap.niointernet.com.br" in current_url and "login" not in current_url.lower():
                        return True, "Login realizado com sucesso!"
                    # Erro upstream timeout do SSO - recarregar e tentar de novo
                    if "upstream request timeout" in pagina:
                        logger.warning("[PAP] SSO retornou 'upstream request timeout', tentando novamente...")
                        if tentativa < max_tentativas:
                            self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                            self.page.wait_for_selector(SELETORES['login']['matricula'], state="visible", timeout=15000)
                            continue
                        return False, "SSO indisponível (upstream timeout). Tente novamente em instantes."
                    return False, "Falha no login. Verifique matrícula e senha."
                
            except Exception as e:
                logger.error(f"[PAP] Erro no login (tentativa {tentativa}): {e}")
                if tentativa < max_tentativas:
                    try:
                        self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                        self.page.wait_for_selector(SELETORES['login']['matricula'], state="visible", timeout=15000)
                    except Exception:
                        pass
                    continue
                return False, f"Erro no login: {str(e)}"
        
        return False, "Falha no login após múltiplas tentativas."

    def _pagina_tem_erro_login(self) -> bool:
        """
        Verifica se a página exibe mensagem de erro de login (ex.: "Login failed, please try again.").
        Retorna True se o erro estiver presente, para não avançar como se o login tivesse sucesso.
        """
        if not self.page:
            return False
        for tentativa in range(2):
            try:
                content = (self.page.content() or "").lower()
                url = (self.page.url or "").lower()
                break
            except Exception as e:
                if ("Execution context was destroyed" in str(e) or "context was destroyed" in str(e)) and tentativa == 0:
                    self.page.wait_for_timeout(2000)
                    continue
                return False
        try:
            # Textos que indicam falha de login (inglês e português)
            if "login failed" in content or "please try again" in content:
                logger.warning("[PAP] Mensagem de erro de login detectada (Login failed / please try again).")
                return True
            if "login falhou" in content or "tente novamente" in content:
                logger.warning("[PAP] Mensagem de erro de login detectada (pt).")
                return True
            if "credenciais inválidas" in content or "invalid credentials" in content:
                logger.warning("[PAP] Mensagem de erro de login detectada (credenciais).")
                return True
            # Se ainda estamos em página de login após o clique, e há indicação de erro
            if ("login" in url or "vtal.com" in url) and ("error" in content or "alert" in content):
                if "failed" in content or "falhou" in content or "inválid" in content:
                    return True
            return False
        except Exception as e:
            logger.debug(f"[PAP] Verificação de erro de login: {e}")
            return False

    def _sessao_expirada_detectada(self) -> bool:
        """
        Detecta quando a sessão do PAP foi invalidada por outro login.
        Ex.: modal "Não Autorizado" + "Sessão expirada. Por gentileza, logar novamente no Portal."
        """
        if not self.page:
            return False
        try:
            url = (self.page.url or "").lower()
            if "login.vtal.com" in url:
                return True
        except Exception:
            pass
        try:
            content = (self.page.content() or "").lower()
        except Exception:
            return False
        sinais = (
            "não autorizado",
            "nao autorizado",
            "sessão expirada",
            "sessao expirada",
            "logar novamente no portal",
        )
        return any(s in content for s in sinais)

    def _fechar_modal_sessao_expirada(self) -> None:
        """Tenta fechar modal de sessão expirada para liberar a UI antes do relogin."""
        if not self.page:
            return
        for sel in ['button:has-text("OK")', 'button:has-text("Ok")', 'button:has-text("Fechar")']:
            try:
                btn = self.page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(200 if self.optimize_for_credit else 400)
                    return
            except Exception:
                continue

    def garantir_sessao_ativa(self, target_url: Optional[str] = None) -> Tuple[bool, str]:
        """
        Garante que a sessão no PAP ainda está válida.
        Se detectar sessão expirada, faz relogin e opcionalmente volta para target_url.
        """
        if not self.page:
            return False, "Página não iniciada."
        try:
            if not self._sessao_expirada_detectada():
                return True, "Sessão ativa."

            logger.warning("[PAP] Sessão expirada detectada. Tentando relogin automático...")
            self._fechar_modal_sessao_expirada()
            self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            ok, msg = self._fazer_login()
            if not ok:
                self.logado = False
                return False, f"Sessão expirada e relogin falhou: {msg}"
            self.logado = True
            if target_url:
                self.page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            return True, "Sessão restaurada com sucesso."
        except Exception as e:
            self.logado = False
            return False, f"Erro ao validar/restaurar sessão: {e}"

    def _dispensar_modais_novo_pedido(self) -> None:
        """Fecha modais/overlays que impedem ver o formulário (tutorial, avisos)."""
        if not self.page:
            return
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(200 if self.optimize_for_credit else 350)
        except Exception:
            pass
        for _ in range(2):
            fechou = False
            for sel in (
                'button[aria-label="Close"]',
                'button[aria-label="Fechar"]',
                'button:has-text("Entendi")',
                'button:has-text("OK")',
                'button:has-text("Ok")',
                'button:has-text("Fechar")',
            ):
                try:
                    el = self.page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        self.page.wait_for_timeout(300 if self.optimize_for_credit else 450)
                        fechou = True
                except Exception:
                    continue
            if not fechou:
                break

    def _esperar_campo_matricula_vendedor(self, timeout_ms: int, modo_rapido: bool) -> bool:
        """True se o campo de vendedor/matrícula (etapa 1) estiver visível."""
        if not self.page:
            return False
        try:
            self.page.wait_for_selector(
                SELETORES_MATRICULA_VENDEDOR_CSS,
                state="visible",
                timeout=timeout_ms,
            )
            return True
        except Exception:
            pass
        chunk = max(1200, min(3500, timeout_ms // max(1, len(SELETORES_MATRICULA_VENDEDOR) // 3)))
        for sel in SELETORES_MATRICULA_VENDEDOR:
            try:
                self.page.wait_for_selector(sel, state="visible", timeout=chunk if modo_rapido else min(chunk + 800, 5000))
                return True
            except Exception:
                continue
        # Último recurso: combobox/autocomplete por rótulo próximo
        try:
            loc = self.page.get_by_label(re.compile(r"vendedor|matrícula|matricula", re.I))
            if loc.count() > 0:
                loc.first.wait_for(state="visible", timeout=4000)
                return True
        except Exception:
            pass
        return False

    def _query_matricula_vendedor_input(self):
        """Retorna o elemento input do vendedor ou None."""
        if not self.page:
            return None
        for sel in SELETORES_MATRICULA_VENDEDOR:
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    return el
            except Exception:
                continue
        try:
            loc = self.page.get_by_label(re.compile(r"vendedor|matrícula|matricula", re.I))
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first.element_handle()
        except Exception:
            pass
        return None

    def _clicar_menu_novo_pedido(self) -> bool:
        """
        Clica no item do menu lateral "Novo Pedido" (fallback quando goto não abre o formulário).
        Retorna True se encontrou e clicou, False caso contrário.
        """
        # Locators Playwright (acessibilidade + texto) — mais estáveis que só CSS
        def _apos_clique_menu() -> None:
            self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception:
                pass

        # Menu hambúrger / drawer fechado em viewports menores
        try:
            loc_abrir = self.page.get_by_role("button", name=re.compile(r"menu|abrir|navega", re.I))
            if loc_abrir.count() > 0:
                b = loc_abrir.first
                if b.is_visible():
                    logger.info("[PAP] Abrindo menu lateral (botão menu)")
                    b.click(timeout=4000)
                    self.page.wait_for_timeout(500)
        except Exception:
            pass

        for nome, loc in (
            ("link role Novo pedido", self.page.get_by_role("link", name=re.compile(r"Novo\s+pedido", re.I))),
            ("menuitem Novo pedido", self.page.get_by_role("menuitem", name=re.compile(r"Novo\s+pedido", re.I))),
            ("button role Novo pedido", self.page.get_by_role("button", name=re.compile(r"Novo\s+pedido", re.I))),
            ("aside/nav link", self.page.locator("aside a, nav a, [role='navigation'] a").filter(has_text=re.compile(r"Novo\s+pedido", re.I))),
            ("a[href*=novo-pedido]", self.page.locator("a[href*='novo-pedido']")),
            ("button texto Novo Pedido", self.page.locator("button:has-text('Novo Pedido')")),
        ):
            try:
                if loc.count() < 1:
                    continue
                alvo = loc.first
                alvo.wait_for(state="visible", timeout=8000)
                try:
                    alvo.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass
                logger.info(f"[PAP] Fallback: clicando menu Novo Pedido ({nome})")
                if self.capture_screenshots:
                    try:
                        h = alvo.element_handle()
                        if h:
                            self._highlight_element(h, duration_ms=500)
                    except Exception:
                        pass
                alvo.click(timeout=12000, force=True)
                _apos_clique_menu()
                return True
            except Exception as e:
                logger.debug(f"[PAP] Menu Novo Pedido ({nome}): {e}")
                continue

        seletores_menu = [
            'a[href*="novo-pedido"]',
            'a:has-text("Novo Pedido")',
            '[href*="novo-pedido"]',
            'nav a:has-text("Novo Pedido")',
            'a:has-text("Novo pedido")',
            'div:has-text("Novo Pedido")',
            "//a[contains(@href,'novo-pedido')]",
            "//*[contains(text(),'Novo Pedido') and (self::a or self::button or ancestor::a)]",
        ]
        for sel in seletores_menu:
            try:
                if sel.startswith("//"):
                    el = self.page.query_selector(f"xpath={sel}")
                else:
                    el = self.page.query_selector(sel)
                if el and el.is_visible():
                    logger.info(f"[PAP] Fallback: clicando no menu 'Novo Pedido' (seletor: {sel[:50]}...)")
                    if self.capture_screenshots:
                        self._highlight_element(el, duration_ms=500)
                    el.click()
                    self.page.wait_for_timeout(1500)
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=12000)
                    except Exception:
                        pass
                    return True
            except Exception as e:
                logger.debug(f"[PAP] Menu Novo Pedido seletor {sel[:30]}: {e}")
                continue
        return False

    def _clicar_menu_consulta_os(self) -> bool:
        """
        Clica no item do menu lateral "Consulta OS" (ou navega para a URL).
        Retorna True se encontrou e acessou a tela, False caso contrário.
        """
        # Tentar navegação direta primeiro
        try:
            ok_sessao, _ = self.garantir_sessao_ativa()
            if not ok_sessao:
                return False
            self.page.goto(PAP_CONSULTA_OS_URL, wait_until="domcontentloaded", timeout=30000)
            self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                try:
                    self.page.wait_for_load_state("load", timeout=15000)
                except Exception:
                    pass
            if "consulta-os" in (self.page.url or "").lower() or "pap.niointernet.com.br" in (self.page.url or ""):
                logger.info("[PAP] Navegação para Consulta OS OK (URL direta)")
                return True
        except Exception as e:
            logger.warning(f"[PAP] goto Consulta OS: {e}")

        seletores_menu = [
            'a[href*="consulta-os"]',
            'a:has-text("Consulta OS")',
            'span:has-text("Consulta OS")',
            'div.sc-kAzzGY:has(img)',
            '[class*="sc-kAzzGY"]:has(img)',
            "//span[contains(text(),'Consulta OS')]",
            "//a[contains(@href,'consulta-os')]",
        ]
        for sel in seletores_menu:
            try:
                if sel.startswith("//"):
                    el = self.page.query_selector(f"xpath={sel}")
                else:
                    el = self.page.query_selector(sel)
                if el and el.is_visible():
                    logger.info(f"[PAP] Clicando no menu 'Consulta OS' (seletor: {sel[:50]}...)")
                    if self.capture_screenshots:
                        self._highlight_element(el, duration_ms=500)
                    el.click()
                    self.page.wait_for_timeout(2000)
                    self.page.wait_for_load_state("domcontentloaded", timeout=8000)
                    return True
            except Exception as e:
                logger.debug(f"[PAP] Menu Consulta OS seletor {sel[:30]}: {e}")
                continue
        return False

    def abrir_consulta_os_e_filtrar_cpf(self, cpf: str) -> Tuple[bool, str]:
        """
        Após login no PAP: acessa Consulta OS, clica em Filtros e preenche o CPF/CNPJ.
        Não extrai resultado da tabela; apenas deixa a tela filtrada para o usuário.
        Args:
            cpf: CPF apenas dígitos (11 ou 14 para CNPJ).
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            cpf_limpo = re.sub(r'\D', '', cpf) if cpf else ""
            if not cpf_limpo:
                return False, "CPF/CNPJ inválido (vazio)."

            if not self.logado:
                sucesso, msg = self.iniciar_sessao()
                if not sucesso:
                    return False, msg
            else:
                ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_CONSULTA_OS_URL)
                if not ok_sessao:
                    return False, msg_sessao

            # Ir para Consulta OS (URL direta ou menu)
            if self.capture_screenshots:
                self._capture_screenshot("consulta_os_01_antes", wait_selector=None, wait_timeout_ms=0)
            ok_menu = self._clicar_menu_consulta_os()
            if not ok_menu:
                return False, "Não foi possível acessar a tela Consulta OS (menu ou URL)."
            self.page.wait_for_timeout(1500)

            # Clicar em Filtros
            sel_filtros = SELETORES['consulta_os']['filtros']
            filtro_el = None
            for sel in sel_filtros.split(", "):
                try:
                    el = self.page.query_selector(sel.strip())
                    if el and el.is_visible():
                        filtro_el = el
                        break
                except Exception:
                    continue
            if not filtro_el:
                filtro_el = self.page.query_selector('span:has-text("Filtros")')
            if not filtro_el or not filtro_el.is_visible():
                return False, "Não foi possível encontrar o botão/link 'Filtros' na tela Consulta OS."
            logger.info("[PAP] Clicando em Filtros")
            if self.capture_screenshots:
                self._highlight_element(filtro_el, duration_ms=500)
            filtro_el.click()
            self.page.wait_for_timeout(1200)

            # Preencher CPF/CNPJ no input do filtro (force=True evita interceptação pelo MuiDrawer)
            input_selector = 'input.input-text-filter[placeholder="Digite o CPF/CNPJ..."], input.input-text-filter'
            locator_cpf = self.page.locator(input_selector).first
            if locator_cpf.count() == 0:
                return False, "Não foi possível encontrar o campo CPF/CNPJ nos filtros."
            locator_cpf.fill(cpf_limpo, force=True, timeout=10000)
            self.page.wait_for_timeout(500)
            if self.capture_screenshots:
                self._capture_screenshot("consulta_os_02_cpf_preenchido", wait_selector=None, wait_timeout_ms=0)
            logger.info(f"[PAP] CPF/CNPJ preenchido nos filtros da Consulta OS: {cpf_limpo[:3]}***")
            return True, "Consulta OS aberta e filtro por CPF/CNPJ aplicado."
        except Exception as e:
            logger.exception(f"[PAP] abrir_consulta_os_e_filtrar_cpf: {e}")
            return False, str(e)

    def _screenshot_consulta_os_return_path(self, full_page: bool = True) -> Optional[str]:
        """
        Tira screenshot da tela atual (Consulta OS) e retorna o caminho do arquivo.
        Usado para enviar a imagem no WhatsApp. Sempre salva, independente de capture_screenshots.
        """
        if not self.page:
            return None
        try:
            from django.conf import settings
            base_dir = getattr(settings, 'BASE_DIR', None)
            if not base_dir:
                return None
            downloads_dir = os.path.join(base_dir, 'downloads')
            os.makedirs(downloads_dir, exist_ok=True)
            safe_run = str(self.run_id).replace(os.sep, '_').replace('..', '_')[:50]
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"consulta_os_{safe_run}_{ts}.png"
            filepath = os.path.join(downloads_dir, filename)
            self.page.wait_for_timeout(300)
            self.page.screenshot(path=filepath, full_page=full_page)
            logger.info(f"[PAP] Screenshot Consulta OS salvo: {filepath}")
            return filepath
        except Exception as e:
            logger.warning(f"[PAP] Erro ao salvar screenshot Consulta OS: {e}")
            return None

    def consulta_os_por_cpf_com_resultado(
        self, cpf: str, numero_os_filtro: Optional[str] = None
    ) -> Tuple[bool, str, List[Dict[str, Any]], Optional[str]]:
        """
        Fluxo completo: login, Consulta OS, Filtros, CPF, período 30 dias, Filtrar.
        Lê a tabela e por linha detecta se existe link Detalhar (nao_pertence_pdv=False) ou não (não pertence ao PDV).
        Para cada linha com link Detalhar: abre o detalhe, extrai status_agendamento, agendamento, pendência e tira screenshot da tela de detalhe.
        Se numero_os_filtro for informado, filtra o resultado para retornar somente aquela OS (comparando com e sem zeros à esquerda).
        Returns:
            (sucesso, mensagem, lista de dicts com status/plano/numero_os/data_hora, nao_pertence_pdv,
             e quando tem Detalhar: status_agendamento, agendamento, pendencia, detail_screenshot_path),
            list_screenshot_path (screenshot da lista; usado quando só 1 pedido e não pertence ao PDV).
            Se não houver pedidos: (True, "no_results", [], list_screenshot_path).
        """
        from datetime import timedelta
        cpf_limpo = re.sub(r'\D', '', cpf) if cpf else ""
        if not cpf_limpo:
            return False, "CPF/CNPJ inválido (vazio).", [], None

        if not self.logado:
            sucesso, msg = self.iniciar_sessao()
            if not sucesso:
                return False, msg, [], None
        else:
            ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_CONSULTA_OS_URL)
            if not ok_sessao:
                return False, msg_sessao, [], None

        ok_menu = self._clicar_menu_consulta_os()
        if not ok_menu:
            return False, "Não foi possível acessar a tela Consulta OS.", [], None
        self.page.wait_for_timeout(1000)

        # No PAP, o painel de Filtros abre ao PASSAR O MOUSE em cima de "Filtros" (hover), não ao clicar.
        input_selector = 'input.input-text-filter[placeholder="Digite o CPF/CNPJ..."], input.input-text-filter'
        try:
            self.page.locator('button:has-text("Filtros"), a:has-text("Filtros"), [role="button"]:has-text("Filtros")').first.hover(timeout=5000)
            self.page.wait_for_timeout(400)
        except Exception:
            try:
                self.page.locator('text=Filtros').first.hover(timeout=5000)
                self.page.wait_for_timeout(400)
            except Exception as e:
                logger.debug(f"[PAP] Hover em Filtros: {e}")
        try:
            self.page.wait_for_selector(input_selector, state="visible", timeout=5000)
        except Exception:
            try:
                self.page.locator('button:has-text("Filtros")').first.click(force=True, timeout=5000)
                self.page.wait_for_timeout(600)
            except Exception:
                self.page.locator('a:has-text("Filtros")').first.click(force=True, timeout=5000)
                self.page.wait_for_timeout(600)
            try:
                self.page.wait_for_selector(input_selector, state="visible", timeout=4000)
            except Exception:
                return False, "Painel de Filtros não abriu ou campo CPF/CNPJ não encontrado.", [], None

        # Preencher CPF/CNPJ e clicar Filtrar (reduzidos waits para agilizar)
        locator_cpf = self.page.locator(input_selector).first
        try:
            if locator_cpf.count() == 0:
                return False, "Campo CPF/CNPJ não encontrado nos filtros.", [], None
            locator_cpf.fill(cpf_limpo, force=True, timeout=8000)
        except Exception as e:
            logger.warning(f"[PAP] fill CPF com force falhou: {e}")
            return False, f"Não foi possível preencher CPF/CNPJ no filtro: {e}", [], None
        self.page.wait_for_timeout(150)

        # Período: últimos 30 dias (já costuma vir preenchido; preenche só se necessário)
        hoje = datetime.now().date()
        data_ate = hoje
        data_de = hoje - timedelta(days=30)
        str_de = data_de.strftime("%d/%m/%Y")
        str_ate = data_ate.strftime("%d/%m/%Y")
        date_inputs = self.page.query_selector_all('input[type="date"], input[placeholder*="/"], input[placeholder*="De"], input[placeholder*="Até"]')
        if len(date_inputs) >= 2:
            try:
                date_inputs[0].fill(str_de)
                self.page.wait_for_timeout(80)
                date_inputs[1].fill(str_ate)
                self.page.wait_for_timeout(80)
            except Exception:
                pass
        self.page.wait_for_timeout(100)

        # Clicar em Filtrar
        btn_selector = 'button.btn-filters-new, button:has-text("Filtrar")'
        locator_btn = self.page.locator(btn_selector).first
        try:
            if locator_btn.count() == 0:
                return False, "Botão 'Filtrar' não encontrado.", [], None
            locator_btn.click(force=True, timeout=8000)
        except Exception as e:
            logger.warning(f"[PAP] click Filtrar falhou: {e}")
            return False, f"Não foi possível clicar em Filtrar: {e}", [], None
        # Esperar a tabela de resultados carregar (pode demorar; colunas: STATUS, PLANO, NÚMERO DA OS, DATA E HORA [DA CRIAÇÃO], DETALHES)
        try:
            self.page.wait_for_selector(
                'td.MuiTableCell-root.MuiTableCell-body, table tbody td, [class*="MuiTableCell-body"]',
                state="visible",
                timeout=12000
            )
            self.page.wait_for_timeout(800)
        except Exception as e:
            logger.debug(f"[PAP] Espera da tabela Consulta OS: {e}")
        self.page.wait_for_timeout(500)

        # Ler tabela: 4 colunas de dados (0=STATUS, 1=PLANO, 2=NÚMERO DA OS, 3=DATA E HORA); 5ª coluna = DETALHES (link "Detalhar" ou vazio)
        detalhes: List[Dict[str, Any]] = []
        try:
            # Tentar por linhas da tabela
            rows = self.page.query_selector_all(SELETORES['consulta_os']['table_rows'])
            for row in rows:
                cells = row.query_selector_all('td.MuiTableCell-root.MuiTableCell-body, td[class*="MuiTableCell"], td')
                if len(cells) >= 4:
                    status = (cells[0].inner_text() or "").strip()
                    plano = (cells[1].inner_text() or "").strip()
                    numero_os = (cells[2].inner_text() or "").strip()
                    data_hora = (cells[3].inner_text() or "").strip()
                    # 5ª célula (DETALHES): se não tiver link "Detalhar" = pedido não pertence ao PDV
                    tem_detalhar = False
                    if len(cells) >= 5:
                        cell_detalhes = cells[4]
                        link = cell_detalhes.query_selector('a.detalhar-link[href*="detalhe-os"], a[href*="detalhe-os"]')
                        if link:
                            tem_detalhar = True
                        if not tem_detalhar and "detalhar" in (cell_detalhes.inner_text() or "").lower():
                            tem_detalhar = True
                    item = {
                        "status": status,
                        "plano": plano,
                        "numero_os": numero_os,
                        "data_hora": data_hora,
                        "nao_pertence_pdv": not tem_detalhar,
                    }
                    if status or plano or numero_os or data_hora:
                        detalhes.append(item)
            # Fallback: todas as células em sequência (4 ou 5 colunas por linha)
            if not detalhes:
                cells_direct = self.page.query_selector_all(
                    'td.MuiTableCell-root.MuiTableCell-body, td[class*="MuiTableCell-body"], table tbody td'
                )
                if cells_direct:
                    col_per_row = 5 if len(cells_direct) >= 5 and len(cells_direct) % 5 == 0 else 4
                    if len(cells_direct) % col_per_row != 0:
                        col_per_row = 4
                    idx = 0
                    while idx + 4 <= len(cells_direct):
                        status = (cells_direct[idx].inner_text() or "").strip()
                        plano = (cells_direct[idx + 1].inner_text() or "").strip()
                        numero_os = (cells_direct[idx + 2].inner_text() or "").strip()
                        data_hora = (cells_direct[idx + 3].inner_text() or "").strip()
                        tem_detalhar = False
                        if col_per_row >= 5 and idx + 5 <= len(cells_direct):
                            cell_d = cells_direct[idx + 4]
                            if cell_d.query_selector('a.detalhar-link[href*="detalhe-os"], a[href*="detalhe-os"]'):
                                tem_detalhar = True
                            elif "detalhar" in (cell_d.inner_text() or "").lower():
                                tem_detalhar = True
                        if status or plano or numero_os or data_hora:
                            detalhes.append({
                                "status": status,
                                "plano": plano,
                                "numero_os": numero_os,
                                "data_hora": data_hora,
                                "nao_pertence_pdv": not tem_detalhar,
                            })
                        idx += col_per_row
        except Exception as e:
            logger.warning(f"[PAP] Erro ao ler tabela Consulta OS: {e}")

        # Se for consulta por OS (via filtro), reduzir a lista antes de abrir detalhes para evitar abrir várias OS do mesmo CPF
        if detalhes and numero_os_filtro:
            filtro_raw = re.sub(r"\D", "", str(numero_os_filtro)).strip()
            filtro_sem_zero = (filtro_raw.lstrip("0") or filtro_raw) if filtro_raw else ""
            if filtro_raw:
                filtrados = []
                for d in detalhes:
                    os_tbl = re.sub(r"\D", "", str(d.get("numero_os") or "")).strip()
                    os_tbl_sem_zero = os_tbl.lstrip("0") or os_tbl
                    if os_tbl == filtro_raw or os_tbl_sem_zero == filtro_sem_zero:
                        filtrados.append(d)
                detalhes = filtrados

        # Screenshot da lista (usado quando só 1 pedido e não pertence ao PDV)
        list_screenshot_path = self._screenshot_consulta_os_return_path(full_page=True)

        # Para cada OS que tem link Detalhar: abrir detalhe, extrair dados + Pendência e tirar screenshot da tela de detalhe
        if detalhes:
            for row in detalhes:
                if row.get("nao_pertence_pdv"):
                    continue
                num_os = (row.get("numero_os") or "").strip()
                if not num_os:
                    continue
                st_ag, ag_texto, pendencia, detail_screenshot_path = self.abrir_detalhe_os_e_extrair(num_os)
                if st_ag is not None:
                    row["status_agendamento"] = st_ag
                if ag_texto is not None:
                    row["agendamento"] = ag_texto
                if pendencia is not None:
                    row["pendencia"] = pendencia
                if detail_screenshot_path:
                    row["detail_screenshot_path"] = detail_screenshot_path

        if detalhes:
            return True, "ok", detalhes, list_screenshot_path
        return True, "no_results", [], list_screenshot_path

    def abrir_detalhe_os_e_extrair(self, numero_os: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Na tela de Consulta OS (após filtrar), abre o link Detalhar da OS e extrai na página de detalhe:
        - Status agendamento: valor ao lado do rótulo "Status agendamento"
        - Agendamento: valor ao lado do rótulo "Agendamento"
        - Pendência: valor ao lado do rótulo "Pendência" (ex.: "7029 - AGENDAMENTO DO PEDIDO")
        Tira screenshot da tela de detalhe antes de voltar.
        Returns:
            (status_agendamento, agendamento, pendencia, screenshot_path)
        """
        num = (numero_os or "").strip()
        num_sem_zero = num.lstrip("0") or num
        try:
            link = self.page.locator(f'a.detalhar-link[href*="detalhe-os/{num}"]').first
            if link.count() == 0 and num_sem_zero != num:
                link = self.page.locator(f'a.detalhar-link[href*="detalhe-os/{num_sem_zero}"]').first
            if link.count() == 0:
                link = self.page.locator('a.detalhar-link[href*="detalhe-os"]').first
            if link.count() == 0:
                return None, None, None, None
            link.click(force=True, timeout=5000)
            self.page.wait_for_timeout(1500)
            url_atual = self.page.url
            if "detalhe-os" not in (url_atual or ""):
                self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            status_agendamento = None
            agendamento_texto = None
            pendencia_texto = None
            # Status agendamento
            try:
                loc_st = self.page.get_by_text("Status agendamento", exact=False).locator("..").locator("span.ldMRLh, span.sc-jrOYZv.ldMRLh").first
                if loc_st.count() > 0:
                    status_agendamento = (loc_st.inner_text() or "").strip()
            except Exception:
                pass
            # Agendamento
            try:
                loc_ag = self.page.get_by_text("Agendamento", exact=False).locator("..").locator("span.ldMRLh, span.sc-jrOYZv.ldMRLh").first
                if loc_ag.count() > 0:
                    agendamento_texto = (loc_ag.inner_text() or "").strip()
            except Exception:
                pass
            # Pendência (ex.: "7029 - AGENDAMENTO DO PEDIDO")
            try:
                loc_pend = self.page.get_by_text("Pendência", exact=False).locator("..").locator("span.ldMRLh, span.sc-jrOYZv.ldMRLh").first
                if loc_pend.count() > 0:
                    pendencia_texto = (loc_pend.inner_text() or "").strip()
            except Exception:
                pass
            # Fallback: spans genéricos
            if not status_agendamento or not agendamento_texto or not pendencia_texto:
                spans = self.page.locator('span.sc-jrOYZv.ldMRLh, span.ldMRLh').all()
                for s in spans:
                    t = (s.inner_text() or "").strip()
                    if not t:
                        continue
                    if re.match(r'\d{2}/\d{2}/\d{4}\s*-\s*(Tarde|Manhã)', t) and not agendamento_texto:
                        agendamento_texto = t
                    if ("concluído" in t.lower() or "sucesso" in t.lower()) and not status_agendamento:
                        status_agendamento = t
                    # Padrão "XXXX - TEXTO" pode ser pendência (código - descrição)
                    if re.match(r'^\d+\s*-\s*.+', t) and not pendencia_texto:
                        pendencia_texto = t
            self.page.wait_for_timeout(300)
            detail_screenshot_path = self._screenshot_consulta_os_return_path(full_page=True)
            self.page.go_back()
            self.page.wait_for_timeout(1000)
            return (
                status_agendamento or None,
                agendamento_texto or None,
                pendencia_texto or None,
                detail_screenshot_path,
            )
        except Exception as e:
            logger.warning(f"[PAP] abrir_detalhe_os_e_extrair {numero_os}: {e}")
            try:
                self.page.go_back()
            except Exception:
                pass
            return None, None, None, None

    def iniciar_novo_pedido(self, matricula_vendedor: str) -> Tuple[bool, str]:
        """
        Inicia um novo pedido (Etapa 1).
        
        Args:
            matricula_vendedor: Matrícula do vendedor que está fazendo a venda
            
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            logger.info(f"[PAP] Iniciando novo pedido - Vendedor: {matricula_vendedor}")
            modo_rapido_credito = self.optimize_for_credit
            ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
            if not ok_sessao:
                return False, msg_sessao

            # Screenshot do estado atual (ex.: tela de auditoria) antes de navegar
            if self.capture_screenshots:
                self._capture_screenshot("01a_antes_novo_pedido", wait_selector=None, wait_timeout_ms=0)
            
            # Navegar para Novo Pedido
            try:
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"[PAP] goto domcontentloaded: {e}, tentando load...")
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="load", timeout=30000)
            self.page.wait_for_timeout(300 if modo_rapido_credito else 1000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                try:
                    self.page.wait_for_load_state("load", timeout=20000)
                except Exception:
                    pass  # SPA: evita Timeout 5000/4000 ao iniciar pedido
            
            url_atual = self.page.url
            # Às vezes o PAP abre outra rota administrativa; forçar navegação ao fluxo novo pedido
            if "pap.niointernet.com.br" in (url_atual or "") and "novo-pedido" not in (url_atual or "").lower():
                logger.info(f"[PAP] URL sem novo-pedido ({url_atual[:80]}...), tentando menu lateral.")
                self._clicar_menu_novo_pedido()
                self.page.wait_for_timeout(800 if modo_rapido_credito else 1500)
                url_atual = self.page.url
            login_form = (
                self.page.query_selector('#inputMatricula') or
                self.page.query_selector('#passwordInput') or
                self.page.query_selector('input[placeholder*="Login"]') or
                self.page.query_selector('input[type="password"]')
            )
            precisa_login = (
                "login.vtal.com" in url_atual or
                ("login" in url_atual.lower() and "pap.niointernet.com.br" not in url_atual) or
                login_form
            )
            if precisa_login:
                sucesso, msg = self._fazer_login()
                if not sucesso:
                    self._capture_screenshot_falha_etapa1("01_err_login_pap", wait_selector=None, wait_timeout_ms=0)
                    return False, msg
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="domcontentloaded", timeout=30000)
                self.page.wait_for_timeout(300 if modo_rapido_credito else 1000)
                url_atual = self.page.url
            
            # Verificar se chegou na página correta
            if "pap.niointernet.com.br" not in url_atual:
                logger.warning(f"[PAP] URL atual: {url_atual}")
                self._capture_screenshot_falha_etapa1("01_err_url_fora_pap", wait_selector=None, wait_timeout_ms=0)
                return False, f"Não foi possível acessar a página de novo pedido. URL: {url_atual[:80]}..."

            if self.capture_screenshots:
                self._capture_screenshot("01b_apos_goto_novo_pedido", wait_selector=None, wait_timeout_ms=800)

            self._dispensar_modais_novo_pedido()

            # No crédito, quando o PAP prende na tela de Auditoria/Pedido, antecipar fallback do menu
            # evita esperar o timeout completo do campo de matrícula.
            if modo_rapido_credito:
                try:
                    pagina_atual = (self.page.content() or "").lower()
                except Exception:
                    pagina_atual = ""
                url_lower = (url_atual or "").lower()
                preso_em_auditoria = (
                    "auditoria" in url_lower
                    or "pedido" in url_lower
                    or "auditoria de pedidos" in pagina_atual
                )
                if preso_em_auditoria:
                    logger.info("[PAP] Modo rápido crédito: tela de auditoria detectada, tentando menu 'Novo Pedido' imediatamente.")
                    self._clicar_menu_novo_pedido()
                    self._dispensar_modais_novo_pedido()

            # Venda (WPP): mesma heurística — SPA às vezes permanece em auditoria mesmo com URL de admin
            if not modo_rapido_credito:
                try:
                    pagina_atual = (self.page.content() or "").lower()
                except Exception:
                    pagina_atual = ""
                url_lower = (url_atual or "").lower()
                if "auditoria" in url_lower or "auditoria de pedidos" in pagina_atual:
                    logger.info("[PAP] Tela de auditoria detectada (venda); tentando menu 'Novo Pedido'.")
                    self._clicar_menu_novo_pedido()
                    self._dispensar_modais_novo_pedido()

            t_first = 12000 if modo_rapido_credito else 16000
            matricula_visivel = self._esperar_campo_matricula_vendedor(t_first, modo_rapido_credito)

            if not matricula_visivel:
                logger.warning("[PAP] Campo matrícula não encontrado após goto. Tentando menu 'Novo Pedido' e nova espera...")
                if self._clicar_menu_novo_pedido():
                    if self.capture_screenshots:
                        self._capture_screenshot("01c_apos_clique_menu_novo_pedido", wait_selector=None, wait_timeout_ms=800)
                    self._dispensar_modais_novo_pedido()
                    matricula_visivel = self._esperar_campo_matricula_vendedor(
                        9000 if modo_rapido_credito else 14000,
                        modo_rapido_credito,
                    )

            if not matricula_visivel:
                logger.warning("[PAP] Ainda sem campo matrícula; recarregando rota novo-pedido uma vez...")
                try:
                    self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="load", timeout=35000)
                    self.page.wait_for_timeout(800 if modo_rapido_credito else 1500)
                    self._dispensar_modais_novo_pedido()
                    matricula_visivel = self._esperar_campo_matricula_vendedor(
                        10000 if modo_rapido_credito else 15000,
                        modo_rapido_credito,
                    )
                except Exception as e:
                    logger.warning(f"[PAP] Retry goto novo-pedido: {e}")

            if not matricula_visivel:
                try:
                    logger.error("[PAP] Falha etapa1 novo pedido. URL=%s", (self.page.url or "")[:160])
                except Exception:
                    pass
                self._capture_screenshot_falha_etapa1("01_err_campo_matricula_invisivel", wait_selector=None, wait_timeout_ms=0)
                return False, "Não foi possível acessar a página de novo pedido (campo matrícula não encontrado e menu 'Novo Pedido' não clicável)."

            matricula_input = self._query_matricula_vendedor_input()
            if not matricula_input:
                self._capture_screenshot_falha_etapa1("01_err_query_matricula_none", wait_selector=None, wait_timeout_ms=0)
                return False, "Não foi possível localizar o campo de vendedor/matrícula no formulário. O portal pode ter alterado a página."

            # Focar no campo para abrir lista
            matricula_input.click()
            # Aguardar lista de vendedores aparecer
            self.page.wait_for_selector(SELETORES['etapa1']['lista_vendedores'], state="visible", timeout=5000)
            # Digitar matrícula
            matricula_input.fill(matricula_vendedor)
            # Aguardar lista atualizar e clicar na opção
            self.page.wait_for_timeout(300)  # debounce do autocomplete
            lista_items = self.page.query_selector_all(SELETORES['etapa1']['lista_vendedores'])
            for item in lista_items:
                if matricula_vendedor in item.inner_text():
                    item.click()
                    break

            # Clicar Avançar (cria o pedido e gera o protocolo)
            try:
                self.page.wait_for_selector('button:has-text("Avançar"):not([disabled])', state="visible", timeout=5000)
            except Exception:
                pass
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if not btn_avancar:
                try:
                    n_li = len(lista_items)
                    amostras = [(i.inner_text() or "")[:80] for i in lista_items[:5]]
                    logger.warning(
                        "[PAP] Etapa1 sem botão Avançar. matricula=%s n_li=%s amostras=%s",
                        matricula_vendedor,
                        n_li,
                        amostras,
                    )
                except Exception as log_e:
                    logger.warning("[PAP] Etapa1 sem botão Avançar (log lista falhou): %s", log_e)
                self._capture_screenshot_falha_etapa1("01_err_sem_bot_avancar_apos_vendedor", wait_selector=None, wait_timeout_ms=0)
                return False, "Não foi possível selecionar o vendedor. Verifique a matrícula."
            if self.capture_screenshots:
                self._highlight_element(btn_avancar, duration_ms=400)
            btn_avancar.click()
            self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=10000)
            self._extrair_protocolo_pedido()
            self.etapa_atual = 1
            self.dados_pedido['matricula_vendedor'] = matricula_vendedor
            if self.capture_screenshots:
                self._capture_screenshot("01d_etapa1_concluida", wait_selector=SELETORES['etapa2']['cep'], wait_timeout_ms=3000)
            return True, "Etapa 1 concluída! Vendedor selecionado."
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 1: {e}")
            try:
                self._capture_screenshot_falha_etapa1("01_excecao_etapa1", wait_selector=None, wait_timeout_ms=0)
            except Exception:
                pass
            return False, f"Erro na Etapa 1: {str(e)}"

    def validar_tela_pronta_para_cep(self, timeout_ms: int = 8000) -> Tuple[bool, str]:
        """
        Verifica se a página está na etapa correta para digitar CEP (tela de novo pedido - etapa endereço).
        Só retorna True se o campo CEP ou o formulário de viabilidade estiver visível.
        """
        if not self.page:
            return False, "Sessão não está aberta."
        try:
            cep_sel = (
                self.page.query_selector(SELETORES['etapa2']['cep']) or
                self.page.query_selector('input[placeholder=" "]') or
                self.page.query_selector('input[type="number"]') or
                self.page.query_selector('button:has-text("Buscar")')
            )
            if cep_sel and cep_sel.is_visible():
                logger.info("[PAP] Tela validada: formulário de CEP/endereço visível.")
                return True, "Tela pronta para CEP."
            self.page.wait_for_timeout(800)
            cep_sel = self.page.query_selector(SELETORES['etapa2']['cep']) or self.page.query_selector('button:has-text("Buscar")')
            if cep_sel and cep_sel.is_visible():
                return True, "Tela pronta para CEP."
            return False, "Tela de endereço (CEP) não está visível. A página pode não ter carregado corretamente."
        except Exception as e:
            logger.warning(f"[PAP] Validação da tela CEP: {e}")
            return False, f"Não foi possível validar a tela: {str(e)}"

    def obter_nome_operador_logado(self) -> str:
        """
        Extrai o nome do operador (backoffice) logado no portal a partir do elemento
        que exibe "Olá, <br> NOME DO OPERADOR" (ex.: #operador ou div.Operador-info).
        Retorna string vazia se não encontrar.
        """
        if not self.page:
            return ""
        try:
            # Tentar #operador ou .Operador-info primeiro (estrutura: div com "Olá," e nome após <br>)
            el = self.page.query_selector('#operador') or self.page.query_selector('div.Operador-info')
            if not el:
                # Fallback: qualquer div que contenha "Olá," seguido do nome
                el = self.page.query_selector('div:has-text("Olá")')
            if not el:
                return ""
            texto = (el.inner_text() or "").strip()
            if not texto:
                return ""
            # Remover "Olá," (com vírgula e variações) e pegar o restante como nome
            texto = re.sub(r'^Olá\s*,?\s*', '', texto, flags=re.I).strip()
            # Se tiver quebra de linha, o nome costuma estar na segunda parte
            partes = [p.strip() for p in texto.split('\n') if p.strip()]
            nome = partes[-1] if partes else texto
            return nome.strip() if nome else ""
        except Exception as e:
            logger.warning(f"[PAP] obter_nome_operador_logado: {e}")
            return ""

    def etapa2_viabilidade(self, cep: str, numero: str, referencia: str) -> Tuple[bool, str, Optional[list]]:
        """
        Etapa 2: Consulta de viabilidade.
        Fluxo: CEP + Número -> Buscar -> aguardar endereço resolver ->
        preencher Referência (obrigatório) -> Avançar -> aguardar modal.
        """
        try:
            logger.info(f"[PAP] Etapa 2 - CEP: {cep}, Número: {numero}, Referência: {referencia}")
            ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
            if not ok_sessao:
                return False, msg_sessao, None
            
            # Avançar da etapa 1 já foi feito em iniciar_novo_pedido; garantir que estamos na tela CEP
            try:
                self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=5000)
            except Exception:
                btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
                if btn_avancar:
                    btn_avancar.click()
                    self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=10000)
                    self._extrair_protocolo_pedido()

            # 1. Preencher CEP
            cep_limpo = re.sub(r'\D', '', cep)
            self._set_valor_react(SELETORES['etapa2']['cep'], cep_limpo)
            
            # 2. Preencher número (ou marcar "Sem número")
            if str(numero).strip().upper() in ("SN", "S/N", "S N"):
                sem_numero = self.page.query_selector(SELETORES['etapa2']['sem_numero'])
                if sem_numero and not sem_numero.is_checked():
                    sem_numero.click()
            else:
                self._set_valor_react(SELETORES['etapa2']['numero'], str(numero))
            
            # 3. Clicar em Buscar
            btn_buscar = self.page.query_selector('button:has-text("Buscar"):not([disabled])')
            if not btn_buscar:
                return False, "Botão Buscar não disponível. Verifique CEP e número.", None
            btn_buscar.click()
            
            # 4. Aguardar o endereço ser resolvido - espera inteligente (retorna assim que elemento aparecer)
            # Primeiro: Endereço de instalação OU Referência
            end_inst_sel = SELETORES['etapa2']['endereco_instalacao']
            ref_selector = SELETORES['etapa2']['referencia']
            try:
                self.page.wait_for_selector(
                    f'{end_inst_sel}, {ref_selector}, h2:has-text("OPS, OCORREU UM ERRO")',
                    state="visible",
                    timeout=15000
                )
            except Exception:
                pass
            self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
            if self.verificar_modal_erro_ops_visivel():
                self._fechar_modal_erro_ops()
                return False, PAP_ERRO_PORTAL_NIO, None
            
            # 4b. Verificar múltiplos endereços (dropdown "Endereço de instalação")
            for end_sel in [
                end_inst_sel,
                'input[placeholder="Endereço de instalação"]',
                'input[placeholder*="ndereço de instalação"]',
                'input[placeholder*="Endereço"]',
            ]:
                inp_end_inst = self.page.query_selector(end_sel)
                if not inp_end_inst:
                    continue
                try:
                    inp_end_inst.click()
                    self.page.wait_for_timeout(350 if self.optimize_for_credit else 1000)
                    for sel_ul in [
                        'input[placeholder="Endereço de instalação"] ~ ul li',
                        'input[placeholder*="Endereço"] ~ ul li',
                        '[role="listbox"] li', '[role="option"]',
                        'ul.sc-fQkuQJ.cUdcXF li', 'ul[class*="fQkuQJ"] li',
                        'ul[class*="cUdcXF"] li', 'ul li.sc-epGmkI',
                        'ul[class*="dropdown"] li', 'ul[class*="menu"] li',
                    ]:
                        lis = [el for el in self.page.query_selector_all(sel_ul) if el.is_visible()]
                        enderecos = []
                        for li in lis:
                            txt = (li.inner_text() or "").strip()
                            if len(txt) > 15 and (" - " in txt or ", " in txt) and any(u in txt.upper() for u in ["MG", "SP", "RJ", "BA", "PR", "RS", "SC", "DF", "ES", "GO"]):
                                enderecos.append({'indice': len(enderecos) + 1, 'texto': txt})
                        if len(enderecos) >= 2:
                            self.dados_pedido['cep'] = cep
                            self.dados_pedido['numero'] = str(numero)
                            # Viabilidade não concluída: usuário precisa escolher o endereço
                            return False, "Múltiplos endereços. Escolha um:", {'_codigo': 'MULTIPLOS_ENDERECOS', 'lista': enderecos}
                        elif len(enderecos) == 1:
                            target_txt = enderecos[0]['texto']
                            for li in lis:
                                if (li.inner_text() or "").strip() == target_txt:
                                    li.click()
                                    self.page.wait_for_timeout(400)
                                    break
                        if enderecos or lis:
                            break
                    else:
                        self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
                    break
                except Exception:
                    pass
            
            # 4c. Aguardar Referência (se ainda não apareceu)
            try:
                self.page.wait_for_selector(ref_selector, state="visible", timeout=8000)
            except Exception:
                for sel in [
                    'input[placeholder*="eferência"]',
                    'textarea[placeholder*="eferência"]',
                    'input[id*="referencia"], input[name*="referencia"]',
                    'textarea[id*="referencia"], textarea[name*="referencia"]',
                ]:
                    try:
                        self.page.wait_for_selector(sel, state="visible", timeout=3000)
                        ref_selector = sel
                        break
                    except Exception:
                        continue

            # 5. Preencher Referência (obrigatório) - usar fill para disparar eventos
            ref_preenchido = False
            ref_input = self.page.query_selector(ref_selector)
            if ref_input and ref_input.is_visible():
                ref_input.click()
                self.page.wait_for_timeout(200)
                ref_input.fill(referencia)
                self.page.keyboard.press("Tab")
                ref_preenchido = True
                logger.info(f"[PAP] Referência preenchida (seletor): {referencia!r}")
            if not ref_preenchido:
                # Fallback: label "Referência (Obrigatório)" ou "Referência"
                for label_text in ["Referência (Obrigatório)", "Referência", "referência", "Ponto de referência"]:
                    try:
                        ref_loc = self.page.get_by_label(label_text, exact=False)
                        if ref_loc.count() > 0:
                            ref_loc.first.click()
                            self.page.wait_for_timeout(200)
                            ref_loc.first.fill(referencia)
                            self.page.keyboard.press("Tab")
                            ref_preenchido = True
                            logger.info(f"[PAP] Referência preenchida (label {label_text!r}): {referencia!r}")
                            break
                    except Exception:
                        continue
            if not ref_preenchido:
                for inp in self.page.query_selector_all('input:not([disabled]):not([type="hidden"]), textarea:not([disabled])'):
                    if not inp.is_visible():
                        continue
                    ph = (inp.get_attribute("placeholder") or "")
                    name = (inp.get_attribute("name") or "")
                    id_attr = (inp.get_attribute("id") or "")
                    if "referência" in ph.lower() or "referencia" in ph.lower() or "referencia" in name.lower() or "referencia" in id_attr.lower():
                        inp.click()
                        self.page.wait_for_timeout(200)
                        inp.fill(referencia)
                        self.page.keyboard.press("Tab")
                        ref_preenchido = True
                        logger.info(f"[PAP] Referência preenchida (fallback input): {referencia!r}")
                        break
            if not ref_preenchido:
                logger.warning("[PAP] Campo Referência não encontrado ou não preenchido - botão Avançar pode permanecer desabilitado")

            self.page.wait_for_timeout(1500)

            # 5b. Verificar se há complementos - a lista (ul/li) só aparece ao clicar no campo "Complemento"
            inp_complemento = self.page.query_selector('input[placeholder*="omplemento"], input[placeholder*="Complemento"]')
            if inp_complemento:
                try:
                    inp_complemento.click()
                    self.page.wait_for_timeout(800)
                    try:
                        self.page.wait_for_selector('ul[class*="fQkuQJ"] li, ul[class*="cUdcXF"] li', state="visible", timeout=3000)
                    except Exception:
                        pass
                except Exception:
                    pass
            for sel_comp in [
                'ul.sc-fQkuQJ.cUdcXF li',
                'ul[class*="fQkuQJ"] li',
                'ul[class*="cUdcXF"] li',
                'ul li.sc-epGmkI',
                'input[placeholder*="omplemento"] ~ ul li',
                'div:has(input[placeholder*="omplemento"]) ul li',
            ]:
                try:
                    lis = self.page.query_selector_all(sel_comp)
                    if len(lis) >= 1:
                        complementos = [{'indice': i + 1, 'texto': li.inner_text().strip()} for i, li in enumerate(lis) if li.inner_text().strip()]
                        if complementos:
                            self.dados_pedido['cep'] = cep
                            self.dados_pedido['numero'] = str(numero)
                            self.dados_pedido['referencia'] = referencia
                            return True, "Complementos encontrados. Escolha uma opção:", {'_codigo': 'COMPLEMENTOS', 'lista': complementos}
                except Exception:
                    continue

            # 6. Clicar Avançar e tratar modal
            return self._etapa2_clicar_avancar_e_tratar_modal(cep, numero, referencia)
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 2: {e}")
            return False, f"Erro na Etapa 2: {str(e)}", None

    def etapa2_modal_posse_clicar_consultar_outro(self) -> Tuple[bool, str]:
        """
        Clica em "Consultar outro endereço" no modal "Posse encontrada".
        Retorna à tela de consulta (CEP, Número) para o usuário informar novo endereço.
        """
        try:
            btn = self.page.query_selector('button:has-text("Consultar outro endereço")')
            if not btn:
                self.page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')];
                    const b = btns.find(x => x.textContent && x.textContent.includes('Consultar outro endereço'));
                    if (b) b.click();
                }""")
            else:
                btn.click(force=True, timeout=3000)
            self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=5000)
            except Exception:
                pass
            return True, "Pronto para consultar outro endereço."
        except Exception as e:
            logger.error(f"[PAP] etapa2_modal_posse_clicar_consultar_outro: {e}")
            return False, str(e)

    def etapa2_modal_indisponivel_clicar_voltar(self) -> Tuple[bool, str]:
        """
        Clica em "Voltar" no modal "Indisponível" (sem viabilidade técnica).
        Fecha o modal e retorna à tela de consulta (CEP, Número).
        """
        try:
            btn = self.page.query_selector('button:has-text("Voltar")')
            if not btn:
                self.page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')];
                    const b = btns.find(x => x.textContent && x.textContent.trim() === 'Voltar');
                    if (b) b.click();
                }""")
            else:
                btn.click(force=True, timeout=3000)
            self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_selector('button:has-text("Buscar"):not([disabled])', state="visible", timeout=5000)
            except Exception:
                try:
                    self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=5000)
                except Exception:
                    pass
            return True, "Pronto para consultar outro endereço."
        except Exception as e:
            logger.error(f"[PAP] etapa2_modal_indisponivel_clicar_voltar: {e}")
            return False, str(e)
    
    def etapa2_selecionar_sem_complemento(self) -> Tuple[bool, str]:
        """Marca 'Sem complemento' via check() (interação real) e força revalidação clicando no Avançar."""
        try:
            # 1. Fechar dropdown do complemento (etapa2_viabilidade abre ao detectar)
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
            # 2. Marcar checkbox com Playwright check() - interação real, React atualiza
            try:
                self.page.check('#semComplemento', force=True)
            except Exception:
                lbl = self.page.query_selector('label[for="semComplemento"]')
                if lbl and lbl.is_visible():
                    lbl.click()
            self.page.wait_for_timeout(400)
            # 3. Clicar no botão Avançar para disparar revalidação (habilita o botão)
            btn = self.page.query_selector('button:has-text("Avançar")')
            if btn and btn.is_visible():
                btn.click(force=True)
                self.page.wait_for_timeout(500)
            return True, "Sem complemento selecionado."
        except Exception as e:
            logger.error(f"[PAP] etapa2_selecionar_sem_complemento: {e}")
            return False, str(e)

    def etapa2_selecionar_complemento(self, indice: int) -> Tuple[bool, str]:
        """
        Seleciona um complemento da lista (ex.: Loja 1, Loja 2, Casa A).
        Usa os mesmos seletores do fluxo vender (etapa2_viabilidade / etapa2_preencher_referencia).
        Args:
            indice: 1-based (1 = primeiro complemento)
        """
        try:
            # Igual ao vender: abrir dropdown clicando no campo Complemento
            inp_comp = self.page.query_selector('input[placeholder*="omplemento"], input[placeholder*="Complemento"]')
            if inp_comp:
                inp_comp.click()
                self.page.wait_for_timeout(800)
                try:
                    self.page.wait_for_selector('ul[class*="fQkuQJ"] li, ul[class*="cUdcXF"] li', state="visible", timeout=3000)
                except Exception:
                    pass
            # Mesmos seletores do vender (etapa2_viabilidade e _etapa2_preencher_referencia)
            for sel_comp in [
                'ul.sc-fQkuQJ.cUdcXF li',
                'ul[class*="fQkuQJ"] li',
                'ul[class*="cUdcXF"] li',
                'ul li.sc-epGmkI',
                'input[placeholder*="omplemento"] ~ ul li',
                'div:has(input[placeholder*="omplemento"]) ul li',
            ]:
                try:
                    lis = self.page.query_selector_all(sel_comp)
                    vis = [el for el in lis if el.is_visible()]
                    if indice > 0 and indice <= len(vis):
                        texto = (vis[indice - 1].inner_text() or "").strip()
                        if texto:
                            vis[indice - 1].click()
                            self.page.wait_for_timeout(600)
                            logger.info(f"[PAP] Complemento selecionado (índice {indice}): {texto!r}")
                            return True, "Complemento selecionado."
                except Exception:
                    continue
            return False, "Índice de complemento inválido ou lista não encontrada."
        except Exception as e:
            logger.error(f"[PAP] etapa2_selecionar_complemento: {e}")
            return False, str(e)

    def etapa2_clicar_avancar_apos_complemento(self, cep: str = "", numero: str = "") -> Tuple[bool, str, Optional[list]]:
        """
        Clica Avançar após o usuário ter selecionado complemento ou "Sem complemento".
        A Referência já foi preenchida antes. Retorno igual a etapa2_viabilidade (sucesso, msg, extra).
        """
        ref = self.dados_pedido.get('referencia', '')
        return self._etapa2_clicar_avancar_e_tratar_modal(cep, numero, ref)

    def selecionar_endereco(self, indice: int) -> Tuple[bool, str]:
        """
        Seleciona um endereço da lista quando há múltiplos.
        
        Args:
            indice: Índice do endereço (1-based)
            
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            lista_enderecos = self.page.query_selector_all(SELETORES['etapa2']['lista_enderecos'])
            if indice > 0 and indice <= len(lista_enderecos):
                lista_enderecos[indice - 1].click()
                return True, "Endereço selecionado!"
            return False, "Índice de endereço inválido."
        except Exception as e:
            return False, f"Erro ao selecionar endereço: {str(e)}"

    def etapa2_selecionar_endereco_instalacao(self, indice: int) -> Tuple[bool, str]:
        """
        Seleciona um endereço do dropdown "Endereço de instalação" (quando há múltiplos).
        Args:
            indice: Índice 1-based (1 = primeiro endereço)
        """
        try:
            inp = self.page.query_selector(SELETORES['etapa2']['endereco_instalacao'])
            if inp:
                inp.click()
                self.page.wait_for_timeout(600)
            for sel in [
                'input[placeholder="Endereço de instalação"] ~ ul li',
                'ul.sc-fQkuQJ.cUdcXF li', 'ul[class*="fQkuQJ"] li', 'ul[class*="cUdcXF"] li',
            ]:
                lis = [el for el in self.page.query_selector_all(sel) if el.is_visible()]
                enderecos = [
                    {'i': i + 1, 'li': li}
                    for i, li in enumerate(lis)
                    if len((li.inner_text() or "").strip()) > 20
                    and (" - " in (li.inner_text() or "") or ", " in (li.inner_text() or ""))
                ]
                if indice > 0 and indice <= len(enderecos):
                    enderecos[indice - 1]['li'].click()
                    self.page.wait_for_timeout(500)
                    return True, "Endereço selecionado."
                if enderecos:
                    break
            return False, "Índice de endereço inválido."
        except Exception as e:
            logger.error(f"[PAP] etapa2_selecionar_endereco_instalacao: {e}")
            return False, str(e)

    def etapa2_preencher_referencia_e_continuar(self, cep: str, numero: str, referencia: str) -> Tuple[bool, str, Optional[list]]:
        """
        Preenche Referência e clica Avançar (após seleção de endereço quando havia múltiplos).
        Retorno igual a etapa2_viabilidade: (sucesso, msg, extra) com extra podendo ser COMPLEMENTOS, POSSE_ENCONTRADA, etc.
        """
        try:
            # Esperar formulário estabilizar após seleção do endereço (evita preencher durante validação/piscar da página)
            self.page.wait_for_timeout(1200)
            ref_selector = SELETORES['etapa2']['referencia']
            try:
                self.page.wait_for_selector(ref_selector, state="visible", timeout=8000)
            except Exception:
                ref_selector = 'input[name="referencia"]'
                try:
                    self.page.wait_for_selector(ref_selector, state="visible", timeout=5000)
                except Exception:
                    for sel in ['input[placeholder*="eferência"]', 'textarea[placeholder*="eferência"]', 'input[id*="referencia"]', 'textarea[id*="referencia"]']:
                        try:
                            self.page.wait_for_selector(sel, state="visible", timeout=2000)
                            ref_selector = sel
                            break
                        except Exception:
                            continue
            ref_preenchido = False
            ref_input = self.page.query_selector(ref_selector)
            if ref_input and ref_input.is_visible():
                ref_input.click()
                self.page.wait_for_timeout(200)
                ref_input.fill(referencia)
                self.page.keyboard.press("Tab")
                ref_preenchido = True
                logger.info(f"[PAP] Referência preenchida (seleção endereço): {referencia!r}")
            if not ref_preenchido:
                for label_text in ["Referência (Obrigatório)", "Referência", "referência", "Ponto de referência"]:
                    try:
                        ref_loc = self.page.get_by_label(label_text, exact=False)
                        if ref_loc.count() > 0:
                            ref_loc.first.click()
                            self.page.wait_for_timeout(200)
                            ref_loc.first.fill(referencia)
                            self.page.keyboard.press("Tab")
                            ref_preenchido = True
                            logger.info(f"[PAP] Referência preenchida (label {label_text!r}, seleção endereço): {referencia!r}")
                            break
                    except Exception:
                        continue
            if not ref_preenchido:
                for inp in self.page.query_selector_all('input:not([disabled]):not([type="hidden"]), textarea:not([disabled])'):
                    if not inp.is_visible():
                        continue
                    ph = (inp.get_attribute("placeholder") or "")
                    name = (inp.get_attribute("name") or "")
                    id_attr = (inp.get_attribute("id") or "")
                    if "referência" in ph.lower() or "referencia" in ph.lower() or "referencia" in name.lower() or "referencia" in id_attr.lower():
                        inp.click()
                        self.page.wait_for_timeout(200)
                        inp.fill(referencia)
                        self.page.keyboard.press("Tab")
                        ref_preenchido = True
                        logger.info(f"[PAP] Referência preenchida (fallback input, seleção endereço): {referencia!r}")
                        break
            if not ref_preenchido:
                logger.warning("[PAP] Campo Referência não encontrado em etapa2_preencher_referencia_e_continuar - botão Avançar pode permanecer desabilitado")
            # Garantir que o valor foi realmente preenchido (página pode ter limpado por validação)
            if referencia and ref_preenchido:
                self.page.wait_for_timeout(400)
                try:
                    inp_check = (
                        self.page.query_selector(ref_selector)
                        or self.page.query_selector('input[name="referencia"]')
                        or self.page.query_selector('input[placeholder*="eferência"]')
                        or self.page.query_selector('textarea[name="referencia"]')
                    )
                    if inp_check and inp_check.is_visible():
                        val = (inp_check.input_value() or "").strip()
                        if not val:
                            logger.info("[PAP] Campo referência estava vazio após fill; tentando preencher novamente.")
                            inp_check.click()
                            self.page.wait_for_timeout(200)
                            inp_check.fill(referencia)
                            self.page.keyboard.press("Tab")
                            self.page.wait_for_timeout(400)
                except Exception as e:
                    logger.debug("[PAP] Verificação do valor da referência: %s", e)
            # Esperar rede/página estabilizar antes de Avançar (reduz efeito de validação que desabilita o botão)
            try:
                self.page.wait_for_load_state("networkidle", timeout=2000)
            except Exception:
                self.page.wait_for_timeout(500)
            self.page.wait_for_timeout(400)
            # Verificar complementos
            inp_complemento = self.page.query_selector('input[placeholder*="omplemento"], input[placeholder*="Complemento"]')
            if inp_complemento:
                try:
                    inp_complemento.click()
                    self.page.wait_for_timeout(600)
                except Exception:
                    pass
            for sel_comp in [
                'ul.sc-fQkuQJ.cUdcXF li', 'ul[class*="fQkuQJ"] li', 'ul[class*="cUdcXF"] li',
                'input[placeholder*="omplemento"] ~ ul li', 'div:has(input[placeholder*="omplemento"]) ul li',
            ]:
                try:
                    lis = self.page.query_selector_all(sel_comp)
                    vis = [el for el in lis if el.is_visible()]
                    if len(vis) >= 1:
                        complementos = [{'indice': i + 1, 'texto': li.inner_text().strip()} for i, li in enumerate(vis) if li.inner_text().strip()]
                        if complementos:
                            self.dados_pedido['cep'] = cep
                            self.dados_pedido['numero'] = str(numero)
                            self.dados_pedido['referencia'] = referencia
                            return True, "Complementos encontrados. Escolha uma opção:", {'_codigo': 'COMPLEMENTOS', 'lista': complementos}
                except Exception:
                    continue
            # Sem complementos: clicar Avançar
            return self._etapa2_clicar_avancar_e_tratar_modal(cep, numero, referencia)
        except Exception as e:
            logger.error(f"[PAP] etapa2_preencher_referencia_e_continuar: {e}")
            return False, str(e), None

    def _etapa2_clicar_avancar_e_tratar_modal(self, cep: str, numero: str, referencia: str) -> Tuple[bool, str, Optional[list]]:
        """Clica Avançar e trata modal de viabilidade (Disponível, Posse, Indisponível)."""
        try:
            modal_sel = 'h2:has-text("Disponível"), h2:has-text("Indisponível"), h3:has-text("Posse encontrada")'
            modal_el = self.page.query_selector(modal_sel)
            spinner = self.page.query_selector('div[class*="spinner"]')
            # Se modal já visível: pular clique. Se spinner visível: Avançar já foi clicado, aguardar modal.
            if modal_el and modal_el.is_visible():
                self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
            elif spinner and spinner.is_visible():
                # Carregando (Avançar já clicado por etapa2_selecionar_sem_complemento) - aguardar modal
                try:
                    self.page.wait_for_selector(modal_sel, state="visible", timeout=18000 if self.optimize_for_credit else 25000)
                    self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
                except Exception:
                    return False, "Timeout aguardando resultado da viabilidade.", None
            else:
                # Avançar ainda não clicado (fluxo sem complementos)
                try:
                    self.page.wait_for_selector('button:has-text("Avançar"):not([disabled])', state="visible", timeout=4000)
                except Exception:
                    pass
                btn = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
                if not btn:
                    return False, "Botão Avançar não habilitou.", None
                btn.click(force=True)
                self.page.wait_for_timeout(700 if self.optimize_for_credit else 2000)
            try:
                self.page.wait_for_selector(
                    'h2:has-text("Disponível"), h2:has-text("Indisponível"), h3:has-text("Posse encontrada"), h2:has-text("OPS, OCORREU UM ERRO")',
                    state="visible", timeout=12000 if self.optimize_for_credit else 20000
                )
            except Exception:
                if self.verificar_modal_erro_ops_visivel():
                    self._fechar_modal_erro_ops()
                    return False, PAP_ERRO_PORTAL_NIO, None
                pass
            self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
            if self.verificar_modal_erro_ops_visivel():
                self._fechar_modal_erro_ops()
                return False, PAP_ERRO_PORTAL_NIO, None
            pagina = self.page.content()
            pagina_lower = pagina.lower()
            if "posse encontrada" in pagina_lower or ("pedido" in pagina_lower and "em andamento" in pagina_lower):
                return False, (
                    "❌ *Posse encontrada*\n\n"
                    "Não é possível abrir um pedido para o endereço consultado pois já existe um pedido em andamento.\n\n"
                    "Digite outro *CEP* para consultar outro endereço ou *CONCLUIR* para sair."
                ), "POSSE_ENCONTRADA"
            if "indisponível" in pagina_lower or "indisponivel" in pagina_lower or "sem viabilidade técnica" in pagina_lower:
                return False, (
                    "❌ *Endereço indisponível*\n\n"
                    "Sem viabilidade técnica para o endereço consultado.\n\n"
                    "Digite outro *CEP* ou *CONCLUIR* para sair."
                ), "INDISPONIVEL_TECNICO"
            if "disponível" in pagina_lower or "disponivel" in pagina_lower:
                btn_cont = self.page.query_selector('button:has-text("Continuar")')
                if btn_cont:
                    btn_cont.click()
                    # Aguardar tela de cadastro do cliente (CPF) carregar; timeout maior para rede lenta
                    try:
                        self.page.wait_for_selector('input[name="documento"]', state="visible", timeout=20000)
                    except Exception:
                        self.page.wait_for_timeout(3000)
                self._capture_screenshot("02_viabilidade_disponivel", wait_selector='input[name="documento"]', wait_timeout_ms=5000)
                self.etapa_atual = 2
                self.dados_pedido['cep'] = cep
                self.dados_pedido['numero'] = numero
                self.dados_pedido['referencia'] = referencia
                self._extrair_protocolo_pedido()
                return True, "Etapa 2 concluída! Endereço viável.", None
            return False, "Não foi possível obter o resultado da viabilidade.", None
        except Exception as e:
            logger.error(f"[PAP] _etapa2_clicar_avancar_e_tratar_modal: {e}")
            return False, str(e), None

    def _preencher_cpf_representante_apos_consultar_cnpj(self, cpf_rep_limpo: str) -> Tuple[bool, str]:
        """
        Após clicar em Buscar/Consultar com CNPJ, o PAP exibe dois botões:
        "Dados da empresa" e "Dados do representante legal". Só então o campo
        cpfRepresentante fica disponível — não adianta clicar antes do Buscar.
        """
        try:
            t_btn = 25000 if self.optimize_for_credit else 40000
            t_inp = 25000 if self.optimize_for_credit else 35000
            self.page.wait_for_timeout(500 if self.optimize_for_credit else 1000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                try:
                    self.page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass

            # Esperar qualquer um dos blocos CNPJ (empresa ou representante) — confirma que a consulta respondeu
            try:
                self.page.wait_for_selector(
                    'button:has-text("Dados do representante legal"), button:has-text("Dados da empresa")',
                    state="visible",
                    timeout=t_btn,
                )
            except Exception:
                logger.warning("[PAP] Botões CNPJ (empresa/representante) não apareceram no tempo esperado; seguindo tentativas.")

            # Não usar o primeiro button.sc-eklfrZ (seria "Dados da empresa"); filtrar pelo texto.
            clicou = False
            for locator in (
                self.page.get_by_role("button", name=re.compile(r"Dados\s+do\s+representante\s+legal", re.I)),
                self.page.locator('button:has-text("Dados do representante legal")').first,
                self.page.locator("button.sc-eklfrZ.jZwwQY").filter(
                    has_text=re.compile(r"representante\s+legal", re.I)
                ).first,
            ):
                try:
                    locator.wait_for(state="visible", timeout=min(t_btn, 15000))
                    locator.click(timeout=t_btn, force=True)
                    clicou = True
                    logger.info("[PAP] CNPJ: clicado em 'Dados do representante legal'")
                    break
                except Exception as e_try:
                    logger.debug(f"[PAP] Tentativa botão representante: {e_try}")
                    continue
            if not clicou:
                return False, (
                    "Não foi possível localizar o botão 'Dados do representante legal' após consultar o CNPJ. "
                    "O portal pode ter alterado a tela."
                )

            self.page.wait_for_timeout(500 if self.optimize_for_credit else 1000)
            sel_rep = 'input[name="cpfRepresentante"]'
            try:
                self.page.wait_for_selector(sel_rep, state="visible", timeout=t_inp)
            except Exception:
                try:
                    self.page.wait_for_selector(sel_rep, state="attached", timeout=10000)
                    self.page.locator(sel_rep).first.scroll_into_view_if_needed()
                    self.page.wait_for_timeout(400)
                    self.page.wait_for_selector(sel_rep, state="visible", timeout=t_inp)
                except Exception:
                    pass
            inp_rep = self.page.query_selector(sel_rep)
            if inp_rep:
                try:
                    inp_rep.click()
                except Exception:
                    self.page.locator(sel_rep).first.click(force=True, timeout=8000)
                inp_rep = self.page.query_selector(sel_rep)
                if inp_rep:
                    inp_rep.fill(cpf_rep_limpo)
                    self.page.keyboard.press("Tab")
            else:
                self._set_valor_react(sel_rep, cpf_rep_limpo)
            return True, ""
        except Exception as e:
            logger.error(f"[PAP] _preencher_cpf_representante_apos_consultar_cnpj: {e}")
            return False, f"Não foi possível preencher CPF do representante legal: {e}"
    
    def etapa3_cadastro_cliente(self, cpf: str, cpf_representante: str = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Etapa 3: Cadastro do cliente.
        Campo CPF/CNPJ: input[name="documento"]
        """
        try:
            logger.info(f"[PAP] Etapa 3 - Documento: {cpf}")
            ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
            if not ok_sessao:
                return False, msg_sessao, None
            
            # Esperar transição da etapa 2 (Continuar/disponível) para a tela de CPF - evita timeout
            self.page.wait_for_timeout(400 if self.optimize_for_credit else 1200)
            
            # Avançar só se o campo documento ainda não estiver visível (evita clicar no Avançar errado)
            doc_elem = self.page.query_selector('input[name="documento"]')
            doc_ja_visivel = bool(doc_elem and doc_elem.is_visible())
            if not doc_ja_visivel:
                btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
                if btn_avancar:
                    btn_avancar.click()
                    self.page.wait_for_timeout(700 if self.optimize_for_credit else 1800)
            
            # Aguardar campo CPF/CNPJ (documento) aparecer - timeout alto (rede/React podem demorar em produção)
            cpf_selector = None
            for sel in [
                SELETORES['etapa3']['cpf'],
                'input[name="documento"]',
                'input[name=documento]',
                'input#documento, input[id="documento"]',
                'input[placeholder*="CPF"], input[placeholder*="cpf"], input[placeholder*="ocumento"]',
                'input[aria-label*="CPF"], input[aria-label*="ocumento"]',
            ]:
                try:
                    self.page.wait_for_selector(sel, state="visible", timeout=25000)
                    cpf_selector = sel
                    break
                except Exception:
                    continue
            if not cpf_selector:
                cpf_selector = 'input[name=documento]'
                self.page.wait_for_selector(cpf_selector, state="visible", timeout=25000)
            
            # Preencher CPF/CNPJ (apenas dígitos)
            cpf_limpo = re.sub(r'\D', '', cpf)
            cpf_input = self.page.query_selector(cpf_selector)
            if cpf_input:
                cpf_input.click()
                cpf_input.fill(cpf_limpo)
                self.page.keyboard.press("Tab")
            else:
                self._set_valor_react(cpf_selector, cpf_limpo)

            # CNPJ: o CPF do representante só pode ser preenchido DEPOIS de Buscar/Consultar
            # (o portal mostra os botões "Dados da empresa" e "Dados do representante legal").
            if len(cpf_limpo) == 14:
                cpf_rep_chk = re.sub(r'\D', '', str(cpf_representante or ''))
                if len(cpf_rep_chk) != 11:
                    return False, "Para CNPJ, informe um CPF válido do representante legal.", None
            
            # Dar tempo para o site validar o documento (evita clicar em Buscar com botão desabilitado)
            self.page.wait_for_timeout(600 if self.optimize_for_credit else 1500)
            # Detectar "Documento inválido" na página e falhar rápido (evita timeout de 25s no click)
            try:
                doc_invalido = self.page.get_by_text("Documento inválido", exact=False).first
                if doc_invalido and doc_invalido.is_visible():
                    return False, "Documento inválido.", None
            except Exception:
                pass
            pagina_texto = (self.page.content() or "").lower()
            if "documento inválido" in pagina_texto or "documento invalido" in pagina_texto:
                return False, "Documento inválido.", None
            
            # Clicar em Buscar ou Consultar somente se estiver habilitado
            btn_buscar = self.page.query_selector('button:has-text("Buscar"):not([disabled])')
            if not btn_buscar:
                btn_buscar = self.page.query_selector('button:has-text("Consultar"):not([disabled])')
            if not btn_buscar:
                # Botão desabilitado = validação falhou no site; verificar de novo a mensagem
                self.page.wait_for_timeout(300 if self.optimize_for_credit else 800)
                pagina_texto = (self.page.content() or "").lower()
                if "documento inválido" in pagina_texto or "documento invalido" in pagina_texto:
                    return False, "Documento inválido.", None
                return False, "Documento inválido ou CPF não encontrado. Verifique o número digitado.", None
            btn_buscar.click()

            # CNPJ: após consultar, abrir "Dados do representante legal" e preencher o CPF
            if len(cpf_limpo) == 14:
                cpf_rep_limpo = re.sub(r'\D', '', str(cpf_representante or ''))
                ok_rep, msg_rep = self._preencher_cpf_representante_apos_consultar_cnpj(cpf_rep_limpo)
                if not ok_rep:
                    return False, msg_rep, None

            try:
                self.page.wait_for_selector('button:has-text("Avançar"):not([disabled]), input[disabled][value], h2:has-text("OPS, OCORREU UM ERRO")', state="visible", timeout=15000)
            except Exception:
                self.page.wait_for_timeout(1200 if self.optimize_for_credit else 3000)
            
            # Fechar modal "OPS, OCORREU UM ERRO!" se aparecer (erro do portal PAP → abrir chamado Nio)
            if self._fechar_modal_erro_ops():
                return False, PAP_ERRO_PORTAL_NIO, None
            
            self._capture_screenshot("03_cpf_cliente_ok", wait_selector='button:has-text("Avançar"):not([disabled])', wait_timeout_ms=5000)
            # Extrair dados do cliente (nome, nome_mae, data_nascimento para CRM)
            dados_cliente = {}
            nome_elem = self.page.query_selector(SELETORES['etapa3']['nome_cliente'])
            if nome_elem:
                dados_cliente['nome'] = (nome_elem.get_attribute('value') or nome_elem.inner_text() or '').strip()
            # Nome da mãe
            for sel in ['input[name*="mae"]', 'input[id*="mae"]']:
                mae_elem = self.page.query_selector(sel)
                if mae_elem:
                    val = (mae_elem.get_attribute('value') or '').strip()
                    if val:
                        dados_cliente['nome_mae'] = val
                        break
            # Data de nascimento: sempre exibida como **/MM/**** (apenas mês visível)
            for sel in ['input[name*="nascimento"]', 'input[id*="nascimento"]', 'input[placeholder*="nascimento"]']:
                dt_elem = self.page.query_selector(sel)
                if dt_elem:
                    val = (dt_elem.get_attribute('value') or '').strip()
                    if val:
                        # Formato comum: DD/MM/YYYY ou **/MM/**** - extrair mês
                        match = re.search(r'/(\d{1,2})/', val)
                        if match:
                            dados_cliente['mes_nascimento'] = int(match.group(1))
                        break
            
            # Verificar se pode avançar
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                self.etapa_atual = 3
                self.dados_pedido['cpf_cliente'] = cpf
                if cpf_representante:
                    self.dados_pedido['cpf_representante_legal'] = cpf_representante
                self.dados_pedido['nome_cliente'] = dados_cliente.get('nome', '')
                self.dados_pedido['nome_mae'] = dados_cliente.get('nome_mae', '')
                self.dados_pedido['mes_nascimento'] = dados_cliente.get('mes_nascimento')
                return True, f"Cliente encontrado: {dados_cliente.get('nome', 'N/A')}", dados_cliente
            else:
                return False, "CPF não encontrado ou inválido.", None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 3: {e}")
            return False, f"Erro na Etapa 3: {str(e)}", None
    
    def _etapa4_limpar_todos_campos_contato(self) -> None:
        """Limpa todos os campos da etapa Contato (principal, confirmação, secundário, email, confirmação) para nova tentativa."""
        try:
            for sel in [
                'input#contato, input[name="contato"]',
                'input#confirmacaoContato, input[name="confirmacaoContato"]',
                'input#contatoSecundario, input[name="contatoSecundario"]',
                'input#email, input[name="email"]',
                'input#confirmarEmail, input[name="confirma-email"]',
            ]:
                inp = self.page.query_selector(sel)
                if inp and inp.is_visible():
                    inp.fill('')
            self.page.wait_for_timeout(300)
        except Exception as e:
            logger.warning(f"[PAP] _etapa4_limpar_todos_campos_contato: {e}")

    def etapa4_contato(self, celular: str, email: str, celular_secundario: str = None, parar_no_modal_credito: bool = False) -> Tuple[bool, str, Optional[str], Optional[str]]:
        """
        Etapa 4: Informações de contato e análise de crédito.
        Campos: contato, confirmacaoContato, contatoSecundario, email, confirmarEmail
        Trata modal "Atenção!" (telefone/email repetidos, e-mail inválido) e modal de crédito.
        Em erro de celular (inválido/já utilizado/excede repetições): limpa TODOS os campos antes de retornar.
        
        parar_no_modal_credito: se True (fluxo análise de crédito via WhatsApp), NÃO clica em Continuar
        após obter o resultado - evita enviar link de biometria. Retorna com o resultado e encerra.
        
        Returns:
            Tuple (sucesso, mensagem, resultado_credito, screenshot_modal_b64)
            screenshot_modal_b64: base64 da imagem do modal de resultado (quando visível), para envio no WhatsApp.
            "TELEFONE_REJEITADO" | "EMAIL_REJEITADO" | "EMAIL_INVALIDO" | "CREDITO_NEGADO"
        """
        try:
            logger.info(f"[PAP] Etapa 4 - Celular: {celular}, Email: {email}")
            modo_rapido_credito = self.optimize_for_credit and parar_no_modal_credito
            ok_sessao, msg_sessao = self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
            if not ok_sessao:
                return False, msg_sessao, None, None
            
            # Clicar Avançar da Etapa 3 para ir para Etapa 4 (Contato), se ainda não estivermos lá
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
            
            # Aguardar formulário de contato
            self.page.wait_for_selector('input#contato, input[name="contato"]', state="visible", timeout=15000)
            
            # Fechar modal "Atenção!" se já estiver aberto (ex: de tentativa anterior)
            modal_atencao = self.page.query_selector('h2:has-text("Atenção!")')
            if modal_atencao:
                btn_ok = self.page.query_selector('button:has-text("Ok")')
                if btn_ok:
                    btn_ok.click()
                    self.page.wait_for_timeout(250 if modo_rapido_credito else 500)
            
            celular_limpo = re.sub(r'\D', '', celular)
            
            # Preencher celular principal e confirmação
            inp_contato = self.page.query_selector('input#contato, input[name="contato"]')
            inp_confirmar = self.page.query_selector('input#confirmacaoContato, input[name="confirmacaoContato"]')
            if inp_contato:
                inp_contato.fill(celular_limpo)
            if inp_confirmar:
                inp_confirmar.fill(celular_limpo)
            
            # Celular secundário (opcional)
            if celular_secundario:
                cel_sec_limpo = re.sub(r'\D', '', celular_secundario)
                inp_sec = self.page.query_selector('input#contatoSecundario, input[name="contatoSecundario"]')
                if inp_sec:
                    inp_sec.fill(cel_sec_limpo)
            
            # E-mail e confirmação
            inp_email = self.page.query_selector('input#email, input[name="email"]')
            inp_confirmar_email = self.page.query_selector('input#confirmarEmail, input[name="confirma-email"]')
            if inp_email:
                inp_email.fill(email)
            if inp_confirmar_email:
                inp_confirmar_email.fill(email)
            
            # Disparar validação (Tab para sair do último campo)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(300 if modo_rapido_credito else 800)
            
            pagina_lower = self.page.content().lower()
            # Celular inválido ou já utilizado (mensagem inline ou validação)
            if "celular inválido" in pagina_lower or "celular já utilizado" in pagina_lower:
                self._etapa4_limpar_todos_campos_contato()
                return False, "CELULAR_INVALIDO", None, None
            
            # Verificar modal "Atenção!" (email já usado ou inválido) - pode aparecer ao validar
            modal_atencao = self.page.query_selector('h2:has-text("Atenção!")')
            if modal_atencao:
                pagina = self.page.content().lower()
                btn_ok = self.page.query_selector('button:has-text("Ok")')
                if btn_ok:
                    btn_ok.click()
                    self.page.wait_for_timeout(250 if modo_rapido_credito else 500)
                if "email" in pagina and ("usado" in pagina or "pedido anterior" in pagina):
                    self._etapa4_limpar_todos_campos_contato()
                    return False, "EMAIL_REJEITADO", None, None
                if "e-mail inválido" in pagina or "preencha um e-mail válido" in pagina:
                    self._etapa4_limpar_todos_campos_contato()
                    return False, "EMAIL_INVALIDO", None, None
            
            # Clicar Avançar para disparar análise de crédito
            t_avancar = time.time()
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
            else:
                self.page.keyboard.press("Tab")
                self.page.wait_for_timeout(250 if modo_rapido_credito else 500)
                btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
                if btn_avancar:
                    btn_avancar.click()
            
            # Verificar modal "Atenção!" e modal "OPS, OCORREU UM ERRO!" (erro do portal)
            loops_atencao = 4 if modo_rapido_credito else 6
            pausa_atencao_ms = 300 if modo_rapido_credito else 500
            for _ in range(loops_atencao):
                self.page.wait_for_timeout(pausa_atencao_ms)
                if self.verificar_modal_erro_ops_visivel():
                    self._fechar_modal_erro_ops()
                    return False, PAP_ERRO_PORTAL_NIO, None, None
                modal_atencao = self.page.query_selector('h2:has-text("Atenção!")')
                if modal_atencao:
                    pagina = self.page.content().lower()
                    btn_ok = self.page.query_selector('button:has-text("Ok")')
                    if btn_ok:
                        btn_ok.click()
                        self.page.wait_for_timeout(250 if modo_rapido_credito else 500)
                    if "excede" in pagina or "repetições" in pagina or "celular já utilizado" in pagina:
                        self._etapa4_limpar_todos_campos_contato()
                        return False, "TELEFONE_REJEITADO", None, None
                    if "email" in pagina and ("usado" in pagina or "pedido anterior" in pagina):
                        self._etapa4_limpar_todos_campos_contato()
                        return False, "EMAIL_REJEITADO", None, None
                    if "e-mail inválido" in pagina or "preencha um e-mail válido" in pagina:
                        self._etapa4_limpar_todos_campos_contato()
                        return False, "EMAIL_INVALIDO", None, None
            t_apos_atencao = time.time()
            if parar_no_modal_credito:
                logger.info("[PAP] [CRÉDITO] Etapa4: loop Atenção=%.1fs (desde clique Avançar)", t_apos_atencao - t_avancar)
            
            # Fluxo crédito (parar_no_modal_credito): sempre esperar o modal "Resultado da análise de crédito"
            # para obter texto correto (apenas cartão vs todas as formas) e screenshot. Não usar atalho.
            # Fluxo venda: pode encerrar antes se Etapa 5 aparecer sem modal (aprovação todas as formas).
            modal_apareceu = False
            poll_iteracao = 0
            loops_modal = 16 if modo_rapido_credito else 24
            pausa_modal_ms = 300 if modo_rapido_credito else 500
            for _ in range(loops_modal):
                self.page.wait_for_timeout(pausa_modal_ms)
                poll_iteracao += 1
                if self.verificar_modal_erro_ops_visivel():
                    self._fechar_modal_erro_ops()
                    return False, PAP_ERRO_PORTAL_NIO, None, None
                pagina_texto = (self.page.content() or "").lower()
                etapa5_visivel = (
                    'pagamento' in pagina_texto and 'ofertas' in pagina_texto
                ) or self.page.query_selector('input[value="BOLETO"], input[value="CREDITO"], input[value="DACC"]')
                modal_credito = self.page.query_selector('h2:has-text("Resultado da análise de crédito")')
                # Só atalho quando NÃO é fluxo crédito: etapa 5 visível e modal não apareceu = todas as formas
                if not parar_no_modal_credito and etapa5_visivel and not (modal_credito and modal_credito.is_visible()):
                    self.etapa_atual = 4
                    self.dados_pedido['celular'] = celular
                    self.dados_pedido['email'] = email
                    if celular_secundario:
                        self.dados_pedido['celular_sec'] = celular_secundario
                    return True, "Análise de crédito: APROVADO! (Elegível para todas as formas de pagamento)", "Elegível para todas as formas de pagamento", None
                if modal_credito and modal_credito.is_visible():
                    modal_apareceu = True
                    t_modal_visivel = time.time()
                    if parar_no_modal_credito:
                        logger.info(
                            "[PAP] [CRÉDITO] Etapa4: modal 'Resultado análise crédito' visível em %.1fs (poll=%d x %.1fs)",
                            t_modal_visivel - t_avancar, poll_iteracao, (pausa_modal_ms / 1000),
                        )
                    break
            if not modal_apareceu:
                try:
                    self.page.wait_for_selector(
                        'h2:has-text("Resultado da análise de crédito")',
                        state="visible",
                        timeout=6000 if modo_rapido_credito else 10000,
                    )
                    modal_apareceu = True
                    t_modal_visivel = time.time()
                    if parar_no_modal_credito:
                        logger.info(
                            "[PAP] [CRÉDITO] Etapa4: modal visível via wait_for_selector em %.1fs (após %d iterações)",
                            t_modal_visivel - t_avancar, poll_iteracao,
                        )
                except Exception:
                    if self.verificar_modal_erro_ops_visivel():
                        self._fechar_modal_erro_ops()
                        return False, PAP_ERRO_PORTAL_NIO, None, None
                    pass
            self.page.wait_for_timeout(300 if modo_rapido_credito else 800)
            if parar_no_modal_credito and modal_apareceu:
                logger.info("[PAP] [CRÉDITO] Etapa4: total desde Avançar até leitura/screenshot=%.1fs", time.time() - t_avancar)
            if self.verificar_modal_erro_ops_visivel():
                self._fechar_modal_erro_ops()
                return False, PAP_ERRO_PORTAL_NIO, None, None
            pagina_texto = (self.page.content() or "").lower()
            # Normalizar para comparação: acentos e variações (cartão/cartao, etc.)
            pagina_norm = unicodedata.normalize("NFD", pagina_texto)
            pagina_norm = "".join(c for c in pagina_norm if unicodedata.category(c) != "Mn")
            # Crédito negado - capturar screenshot do modal e fechar antes de retornar
            if "crédito negado" in pagina_texto or "credito negado" in pagina_texto or ("negado" in pagina_texto and "aprovado" not in pagina_texto):
                screenshot_b64 = None
                try:
                    screenshot_bytes = self.page.screenshot(type="png")
                    if screenshot_bytes:
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
                except Exception as ex:
                    logger.warning("[PAP] Falha ao capturar screenshot do modal de crédito (negado): %s", ex)
                for btn_text in ['Consultar outro CPF/CNPJ', 'Ok', 'Fechar']:
                    btn = self.page.query_selector(f'button:has-text("{btn_text}")')
                    if btn:
                        try:
                            btn.click()
                            self.page.wait_for_timeout(250 if modo_rapido_credito else 500)
                        except Exception:
                            pass
                        break
                return False, "CREDITO_NEGADO", None, screenshot_b64
            # Crédito aprovado (todas formas ou apenas cartão) - modal visível: capturar screenshot
            if "crédito aprovado" in pagina_texto or "credito aprovado" in pagina_texto:
                screenshot_b64 = None
                try:
                    screenshot_bytes = self.page.screenshot(type="png")
                    if screenshot_bytes:
                        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
                except Exception as ex:
                    logger.warning("[PAP] Falha ao capturar screenshot do modal de crédito (aprovado): %s", ex)
                # Detectar "apenas/somente cartão": variações com e sem acento (pagina_norm = texto sem acentos)
                # Frase do site: "Elegível apenas para a forma de pagamento: Cartão de Crédito"
                indicadores_apenas_cartao = (
                    ("elegivel apenas para" in pagina_norm and "cartao" in pagina_norm)
                    or ("apenas" in pagina_norm and "cartao" in pagina_norm)
                    or ("somente" in pagina_norm and "cartao" in pagina_norm)
                    or ("so cartao" in pagina_norm)
                    or ("apenas para cartao" in pagina_norm)
                )
                indicador_todas_formas = (
                    "todas as formas" in pagina_norm
                    or "todas as formas de pagamento" in pagina_norm
                )
                if indicadores_apenas_cartao and not indicador_todas_formas:
                    resultado_credito = "Elegível apenas para Cartão de Crédito"
                    logger.info("[PAP] Análise de crédito: aprovado APENAS para Cartão de Crédito (modal detectado).")
                else:
                    resultado_credito = "Elegível para todas as formas de pagamento"
                    logger.info("[PAP] Análise de crédito: aprovado para todas as formas de pagamento (modal detectado).")
                # Não clicar Continuar quando parar_no_modal_credito (evita enviar link biometria)
                if not parar_no_modal_credito:
                    try:
                        self.page.locator('button:has-text("Continuar")').first.click(force=True, timeout=5000)
                        self.page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        self.page.evaluate("""() => {
                            const btns = [...document.querySelectorAll('button')];
                            const c = btns.find(b => b.textContent.includes('Continuar'));
                            if (c) c.click();
                        }""")
                        self.page.wait_for_timeout(2000)
                self.etapa_atual = 4
                self.dados_pedido['celular'] = celular
                self.dados_pedido['email'] = email
                if celular_secundario:
                    self.dados_pedido['celular_sec'] = celular_secundario
                return True, f"Análise de crédito: APROVADO! ({resultado_credito})", resultado_credito, screenshot_b64
            # Etapa 5 visível sem texto de modal (fallback)
            etapa5_visivel = (
                'pagamento' in pagina_texto and 'ofertas' in pagina_texto
            ) or self.page.query_selector('input[value="BOLETO"], input[value="CREDITO"], input[value="DACC"]')
            if etapa5_visivel:
                self.etapa_atual = 4
                self.dados_pedido['celular'] = celular
                self.dados_pedido['email'] = email
                if celular_secundario:
                    self.dados_pedido['celular_sec'] = celular_secundario
                return True, "Análise de crédito: APROVADO! (Elegível para todas as formas de pagamento)", "Elegível para todas as formas de pagamento", None
            return False, "Não foi possível obter resultado da análise de crédito.", None, None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 4: {e}")
            return False, f"Erro na Etapa 4: {str(e)}", None, None
    
    def _etapa5_garantir_pagina(self):
        """Garante que a página da etapa 5 (pagamento/ofertas) está carregada."""
        timeout_ms = 20000
        # Os radios usam name="radio-group" e podem estar ocultos por CSS (só o label é visível).
        try:
            self.page.locator(
                'input[name="radio-group"][value="BOLETO"], '
                'input[name="radio-group"][value="CREDITO"], '
                'input[name="radio-group"][value="DACC"]'
            ).first.wait_for(state="attached", timeout=timeout_ms)
        except Exception:
            self.page.wait_for_selector(
                'label:has-text("Boleto"), label:has-text("Cartão de Crédito"), label:has-text("Débito em Conta")',
                state="visible",
                timeout=timeout_ms,
            )

    def etapa5_selecionar_forma_pagamento(self, forma_pagamento: str) -> Tuple[bool, str]:
        """Seleciona a forma de pagamento na etapa 5 (Boleto/Cartão/Débito)."""
        try:
            self._etapa5_garantir_pagina()
            forma_map = {'boleto': 'BOLETO', 'cartao': 'CREDITO', 'cartão': 'CREDITO', 'debito': 'DACC', 'débito': 'DACC'}
            valor = forma_map.get(forma_pagamento.lower().strip(), 'BOLETO')
            self.page.wait_for_timeout(500)
            # Expandir seção "Forma de pagamento" se estiver colapsada
            try:
                header = self.page.query_selector('div:has-text("Forma de pagamento")')
                if header:
                    header.click()
                    self.page.wait_for_timeout(400)
            except Exception:
                pass
            radio = self.page.query_selector(f'input[name="radio-group"][value="{valor}"]')
            if not radio:
                radio = self.page.query_selector(f'input[value="{valor}"]')
            if radio:
                try:
                    radio.click(force=True)
                except Exception:
                    self.page.evaluate(f"""() => {{
                        const r = document.querySelector('input[value="{valor}"], input[name="radio-group"][value="{valor}"]');
                        if (r) r.click();
                    }}""")
            else:
                lbl_text = {'BOLETO': 'Boleto', 'CREDITO': 'Cartão de Crédito', 'DACC': 'Débito em Conta'}.get(valor, 'Boleto')
                lbl = self.page.query_selector(f'label:has-text("{lbl_text}")')
                if lbl:
                    lbl.click(force=True)
            self.page.wait_for_timeout(600)
            checked = self.page.query_selector(f'input[value="{valor}"]:checked, input[name="radio-group"][value="{valor}"]:checked')
            if not checked:
                logger.warning(f"[PAP] Forma {valor} pode não ter sido selecionada - radio não está checked")
            self.dados_pedido['forma_pagamento'] = forma_pagamento
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar forma: {e}")
            return False, str(e)

    def etapa5_preencher_debito(self, banco: str, agencia: str, conta: str, digito: str) -> Tuple[bool, str]:
        """Preenche campos de débito em conta. Chamar após selecionar forma débito."""
        try:
            self._etapa5_garantir_pagina()
            inp_banco = self.page.query_selector(SELETORES['etapa5']['banco_input'])
            if inp_banco and banco:
                inp_banco.click()
                inp_banco.fill(banco)
                self.page.wait_for_timeout(500)
                opt = self.page.query_selector(f'[role="option"]:has-text("{banco[:10]}"), li:has-text("{banco[:10]}")')
                if opt:
                    opt.click()
            if agencia:
                self.page.fill('input[name="agencia"]', agencia)
            if conta:
                self.page.fill('input[name="conta"]', conta)
            if digito:
                self.page.fill('input[name="digito"]', digito)
            self.dados_pedido['banco_dacc'] = banco
            self.dados_pedido['agencia_dacc'] = agencia
            self.dados_pedido['conta_dacc'] = conta
            self.dados_pedido['digito_dacc'] = digito
            self.page.wait_for_timeout(500)
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao preencher débito: {e}")
            return False, str(e)

    def etapa5_selecionar_plano(self, plano: str) -> Tuple[bool, str]:
        """Seleciona o plano (oferta): 1 Giga, 700 Mega ou 500 Mega. Clica no card/container correto."""
        try:
            self._etapa5_garantir_pagina()
            self.page.wait_for_timeout(500)
            plano_map = {'1giga': ('1 Giga', 'Velocidade 1 Giga'), '700mega': ('700 Mega', 'Velocidade 700 Mega'), '500mega': ('500 Mega', 'Velocidade 500 Mega')}
            txt_plano, txt_vel = plano_map.get(plano.lower().strip(), ('500 Mega', 'Velocidade 500 Mega'))
            # Encontrar o li "Velocidade X Mega/Giga" e clicar no card pai (evita clicar no card errado)
            li_vel = self.page.query_selector(f'li:has-text("Velocidade {txt_plano}")')
            if li_vel:
                li_vel.evaluate("""el => {
                    const card = el.closest('[class*="card"], [class*="Card"], [class*="sc-"]');
                    if (card) card.click();
                    else el.click();
                }""")
            else:
                card = self.page.query_selector(f'[class*="card"]:has-text("{txt_plano}")')
                if not card:
                    card = self.page.query_selector(f'div:has-text("{txt_plano}"):has-text("Velocidade")')
                if not card:
                    card = self.page.query_selector(f'label:has-text("{txt_plano}")')
                if card:
                    card.click(force=True)
            self.page.wait_for_timeout(600)
            self.dados_pedido['plano'] = plano
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar plano: {e}")
            return False, str(e)

    def verificar_modal_erro_ops_visivel(self) -> bool:
        """Verifica se o modal 'OPS, OCORREU UM ERRO!' está visível na página (h2 ou div com esse texto)."""
        try:
            if not self.page:
                return False
            el = self.page.query_selector('h2:has-text("OPS, OCORREU UM ERRO")') or self.page.query_selector('h2:has-text("OPS, OCORREU UM ERRO!")')
            if el and el.is_visible():
                return True
            if "OPS, OCORREU UM ERRO" in (self.page.content() or ""):
                return True
            return False
        except Exception:
            return False

    def _fechar_modal_erro_ops(self) -> bool:
        """
        Fecha o modal 'OPS, OCORREU UM ERRO!' clicando em 'Tentar novamente'.
        Retorna True se o modal estava presente e foi fechado (indica erro do portal PAP → abrir chamado Nio).
        """
        try:
            if not self.verificar_modal_erro_ops_visivel():
                return False
            btn = self.page.query_selector('button:has-text("Tentar novamente")')
            if btn and btn.is_visible():
                btn.click()
                self.page.wait_for_timeout(800)
                logger.warning("[PAP] Modal 'OPS, OCORREU UM ERRO!' fechado (Tentar novamente). Orientar abrir chamado na Nio.")
                return True
            return True
        except Exception as e:
            logger.warning("[PAP] _fechar_modal_erro_ops: %s", e)
            return False

    def _etapa5_clicar_salvar_painel(self) -> bool:
        """
        Clica no botão "Salvar" do painel de serviços (Fixo/Streaming).
        Preferir o botão com classe sc-izfUZz eKoZwI. NÃO "Salvar Interesse".
        Para streaming o painel pode ter estrutura diferente; tenta vários seletores.
        """
        try:
            self.page.wait_for_timeout(400)
            # 0. Botões do painel (classes mudam entre deploys)
            for sel in [
                'button.sc-guDjWT.gIsNuI',
                'button.gIsNuI.sc-guDjWT',
                'button.sc-izfUZz.eKoZwI',
                'button.eKoZwI.sc-izfUZz',
                'button[class*="eKoZwI"][class*="sc-izfUZz"]',
            ]:
                try:
                    btn = self.page.query_selector(sel)
                    if btn:
                        txt = (btn.inner_text() or "").strip()
                        if txt == "Salvar" and btn.is_visible():
                            cls = btn.get_attribute("class") or ""
                            if "dCaJBF" not in cls and "hBqtbW" not in cls:
                                btn.scroll_into_view_if_needed()
                                btn.click()
                                self.page.wait_for_timeout(500)
                                return True
                except Exception:
                    continue
            # 1. Playwright role (qualquer botão com nome "Salvar")
            try:
                btn = self.page.get_by_role("button", name="Salvar")
                if btn.count() > 0:
                    for i in range(btn.count()):
                        b = btn.nth(i)
                        if b.is_visible():
                            txt = (b.inner_text() or "").strip()
                            cls = (b.get_attribute("class") or "")
                            if txt == "Salvar" and "Interesse" not in cls and ("eKoZwI" in cls or "sc-izfUZz" in cls):
                                b.click()
                                self.page.wait_for_timeout(500)
                                return True
                    for i in range(btn.count()):
                        b = btn.nth(i)
                        if b.is_visible():
                            txt = (b.inner_text() or "").strip()
                            cls2 = (b.get_attribute("class") or "")
                            if txt == "Salvar" and "Interesse" not in cls2:
                                b.click()
                                self.page.wait_for_timeout(500)
                                return True
            except Exception:
                pass
            # 2. Classe eKoZwI / sc-izfUZz (painel Fixo/Streaming)
            for sel in ['button.sc-izfUZz.eKoZwI', 'button.eKoZwI', 'button.sc-izfUZz:has-text("Salvar")', '[class*="eKoZwI"]:has-text("Salvar")', 'button:has-text("Salvar")']:
                try:
                    btn = self.page.query_selector(sel)
                    if btn:
                        txt = (btn.inner_text() or "").strip()
                        if txt == "Salvar" and btn.is_visible():
                            cls = btn.get_attribute("class") or ""
                            if "dCaJBF" in cls or "hBqtbW" in cls:
                                continue
                            btn.scroll_into_view_if_needed()
                            btn.click()
                            self.page.wait_for_timeout(500)
                            return True
                except Exception:
                    continue
            # 3. Último botão visível com texto exato "Salvar" (streaming costuma ser o da direita)
            btns = self.page.query_selector_all('button')
            for b in reversed(btns):
                txt = (b.inner_text() or "").strip()
                if txt == "Salvar":
                    cls = b.get_attribute("class") or ""
                    if "dCaJBF" in cls or "hBqtbW" in cls:
                        continue
                    if b.is_visible():
                        try:
                            b.scroll_into_view_if_needed()
                            b.click()
                            self.page.wait_for_timeout(500)
                            return True
                        except Exception:
                            pass
            logger.warning("[PAP] _etapa5_clicar_salvar_painel: nenhum botão Salvar visível encontrado")
            return False
        except Exception as e:
            logger.error(f"[PAP] _etapa5_clicar_salvar_painel: {e}")
            return False

    def _fechar_modal_servicos_adicionais(self) -> bool:
        """Fecha o modal 'Escolher serviços adicionais' se estiver aberto (X ou Escape)."""
        try:
            if "Escolher serviços adicionais" not in (self.page.content() or ""):
                return False
            # Tentar botão X (aria-label, classe close, ou ícone ×)
            btn_x = self.page.query_selector('button[aria-label="Close"], button[aria-label="Fechar"], [class*="close"] button, button:has-text("×")')
            if btn_x:
                btn_x.click()
                self.page.wait_for_timeout(400)
                return True
            # Fallback: tecla Escape fecha a maioria dos modais
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
            return True
        except Exception:
            return False

    def _etapa5_clicar_fechar_modal_x(self) -> bool:
        """Clica no botão X para fechar o modal que abre à direita (Fixo/Streaming)."""
        try:
            for sel in [
                SELETORES['etapa5']['btn_fechar_modal_x'],
                'button:has(svg path[d*="M19 6.41"])',
                'button[aria-label="Close"]',
                'button[aria-label="Fechar"]',
                '[class*="close"] button',
            ]:
                btn = self.page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(400)
                    return True
            return False
        except Exception as e:
            logger.warning(f"[PAP] _etapa5_clicar_fechar_modal_x: {e}")
            return False

    def etapa5_selecionar_fixo(self, tem_fixo: bool) -> Tuple[bool, str]:
        """
        Seleciona Fixo (R$ 30/mês).
        Passo 1: Clicar no botão "Serviços disponíveis".
        Passo 2: Clicar no quadro/card que abre com "Fixo" (div.sc-kUQWMX.bwZXDo ou div.sc-dcmekm.dBGnOE).
        Passo 3: Clicar no X para fechar o modal que abre à direita.
        """
        try:
            self._etapa5_garantir_pagina()
            self.dados_pedido['tem_fixo'] = tem_fixo
            if not tem_fixo:
                return True, "OK"
            # 1. Clicar no BOTÃO "Serviços disponíveis" (class sc-wRHdD zRDVL)
            btn_servicos = self.page.query_selector(SELETORES['etapa5']['btn_servicos'])
            if not btn_servicos:
                btn_servicos = self.page.query_selector('button.sc-wRHdD:has-text("Serviços disponíveis")')
            if not btn_servicos:
                btn_servicos = self.page.query_selector('div:has-text("Serviços disponíveis")')
            if not btn_servicos or not btn_servicos.is_visible():
                return False, "Botão 'Serviços disponíveis' não encontrado."
            try:
                btn_servicos.scroll_into_view_if_needed()
                btn_servicos.click()
            except Exception:
                self.page.evaluate("(el) => el.click()", btn_servicos)
            self.page.wait_for_timeout(800)
            # 2. Clicar no quadro/card que contém "Fixo" (abre o modal à direita)
            fixo_card = None
            for sel in [
                'div.sc-kUQWMX.bwZXDo:has-text("Fixo")',
                'div.bwZXDo:has-text("Fixo")',
                'div.sc-dcmekm.dBGnOE:has-text("Fixo")',
                SELETORES['etapa5']['card_fixo'],
                'div:has-text("Fixo"):has-text("Faça ligações")',
                'div:has-text("Fixo"):has-text("R$ 30")',
            ]:
                fixo_card = self.page.query_selector(sel)
                if fixo_card and fixo_card.is_visible():
                    break
                fixo_card = None
            if not fixo_card or not fixo_card.is_visible():
                return False, "Opção Fixo não encontrada. Verifique se a seção 'Serviços disponíveis' está expandida."
            try:
                fixo_card.scroll_into_view_if_needed()
                fixo_card.click()
            except Exception:
                self.page.evaluate("(el) => el.click()", fixo_card)
            self.page.wait_for_timeout(700)
            # 3. Não clicar em Salvar aqui: o painel pode exibir portabilidade do fixo;
            #    o WhatsApp pergunta e etapa5_fixo_finalizar_portabilidade() confirma com Salvar.
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar fixo: {e}")
            return False, str(e)

    def etapa5_fixo_finalizar_portabilidade(
        self,
        quer_portabilidade: bool,
        numero_port: str = "",
        operadora_texto: str = "",
    ) -> Tuple[bool, str]:
        """
        Com o painel Fixo já aberto (após etapa5_selecionar_fixo(True)):
        opcionalmente marca portabilidade, preenche número e operadora, e clica Salvar.
        Se não houver bloco de portabilidade no DOM, apenas Salvar (compatível com layout antigo).
        """
        try:
            self._etapa5_garantir_pagina()
            self.page.wait_for_timeout(400)
            port_lbl = self.page.locator('label:has-text("Cliente deseja fazer portabilidade")').first
            has_port = port_lbl.count() > 0
            if has_port:
                try:
                    cb = port_lbl.locator('input[type="checkbox"]')
                    if cb.count() > 0:
                        want = bool(quer_portabilidade)
                        try:
                            checked = cb.is_checked()
                        except Exception:
                            checked = False
                        if want and not checked:
                            port_lbl.click()
                            self.page.wait_for_timeout(250)
                        elif not want and checked:
                            port_lbl.click()
                            self.page.wait_for_timeout(250)
                    elif quer_portabilidade:
                        port_lbl.click()
                        self.page.wait_for_timeout(250)
                except Exception as ex:
                    logger.warning("[PAP] etapa5_fixo_finalizar_portabilidade: toggle portabilidade: %s", ex)
                if quer_portabilidade:
                    digits = re.sub(r"\D", "", numero_port or "")
                    if len(digits) < 10:
                        return False, "Número para portabilidade inválido (informe DDD + número fixo)."
                    inp = self.page.query_selector("#contatoPortabilidade, input[name='contatoPortabilidade']")
                    if inp:
                        inp.fill(digits)
                        self.page.wait_for_timeout(200)
                    needle = (operadora_texto or "").strip()
                    if len(needle) < 2:
                        return False, "Informe a operadora de origem (ex.: Vivo, Claro, Tim)."
                    sel_el = self.page.query_selector('select[name="operadora"]')
                    if not sel_el:
                        return False, "Campo operadora não encontrado no painel."
                    matched = False
                    needle_l = needle.lower()
                    for opt in self.page.query_selector_all('select[name="operadora"] option'):
                        val = (opt.get_attribute("value") or "").strip()
                        if not val:
                            continue
                        label = (opt.inner_text() or "").strip()
                        if needle_l in label.lower() or label.lower() in needle_l:
                            try:
                                self.page.select_option('select[name="operadora"]', value=val)
                                matched = True
                                break
                            except Exception:
                                continue
                    if not matched:
                        return (
                            False,
                            "Operadora não encontrada na lista. Tente o nome curto (ex.: Vivo, Claro, OI, Tim).",
                        )
            if not self._etapa5_clicar_salvar_painel():
                return False, "Botão Salvar do painel Fixo não encontrado."
            self.dados_pedido["fixo_portabilidade"] = quer_portabilidade
            if quer_portabilidade:
                self.dados_pedido["fixo_portabilidade_numero"] = re.sub(r"\D", "", numero_port or "")
                self.dados_pedido["fixo_portabilidade_operadora"] = (operadora_texto or "").strip()
            self.page.wait_for_timeout(400)
            return True, "OK"
        except Exception as e:
            logger.error("[PAP] etapa5_fixo_finalizar_portabilidade: %s", e)
            return False, str(e)

    def etapa5_selecionar_streaming(self, tem_streaming: bool, streaming_opcoes: str = None, plano: str = "") -> Tuple[bool, str]:
        """
        Seleciona streaming.
        Passo 1: Clicar no botão "Streaming e canais on-line".
        Passo 2: Marcar cada opção clicando no ícone (div.sc-jIyBzM.bSKio ou img) da linha HBO Max / Globoplay Premium / Plano Padrão.
        Passo 3: Confirmar com Salvar (não usar X, pois desmarca as opções).
        Globoplay Premium e Plano Padrão são mutuamente exclusivos; Padrão não disponível para 700Mb/1Gb.
        """
        try:
            self._etapa5_garantir_pagina()
            self.dados_pedido['tem_streaming'] = tem_streaming
            self.dados_pedido['streaming_opcoes'] = (streaming_opcoes or '').strip()
            if not tem_streaming:
                return True, "OK"
            # 1. Clicar no BOTÃO "Streaming e canais on-line"
            btn_stream = self.page.query_selector(SELETORES['etapa5']['btn_streaming'])
            if not btn_stream:
                btn_stream = self.page.query_selector('button.sc-wRHdD:has-text("Streaming e canais on-line")')
            if not btn_stream:
                btn_stream = self.page.query_selector('div:has-text("Streaming e canais on-line")')
            if not btn_stream or not btn_stream.is_visible():
                return False, "Botão 'Streaming e canais on-line' não encontrado."
            try:
                btn_stream.scroll_into_view_if_needed()
                btn_stream.click()
            except Exception:
                self.page.evaluate("(el) => el.click()", btn_stream)
            self.page.wait_for_timeout(800)
            plano_lower = (plano or self.dados_pedido.get('plano', '')).lower()
            skip_padrao = '700mega' in plano_lower or '1giga' in plano_lower
            opts = [x.strip() for x in (streaming_opcoes or '').lower().replace(' ', '').split(',') if x.strip()]
            # 2. Para cada opção: clicar no ícone (img ou div.sc-jIyBzM.bSKio) da linha correspondente
            for o in opts:
                el = None
                if 'hbomax' in o or o == 'hbo':
                    for sel in [
                        'div:has-text("HBO Max") div.sc-jIyBzM.bSKio',
                        'div:has-text("HBO Max") img',
                        'div:has-text("HBO Max") [class*="jIyBzM"]',
                    ]:
                        el = self.page.query_selector(sel)
                        if el and el.is_visible():
                            break
                elif 'globoplay_premium' in o or ('premium' in o and 'basico' not in o):
                    # Globoplay – Plano Premium (não confundir com Plano Padrão)
                    for sel in [
                        'div:has-text("Globoplay"):has-text("Plano Premium") div.sc-jIyBzM.bSKio',
                        'div:has-text("Plano Premium") div.sc-jIyBzM.bSKio',
                        'div:has-text("Plano Premium") img',
                        'div:has-text("Plano Premium") [class*="jIyBzM"]',
                    ]:
                        el = self.page.query_selector(sel)
                        if el and el.is_visible():
                            break
                elif ('globoplay_basico' in o or 'basico' in o or 'padrão' in o or 'padrao' in o) and not skip_padrao:
                    for sel in [
                        'div:has-text("Plano Padrão com Anúncios") div.sc-jIyBzM.bSKio',
                        'div:has-text("Plano Padrão com Anúncios") img',
                        'div:has-text("Plano Padrão") div.sc-jIyBzM.bSKio',
                    ]:
                        el = self.page.query_selector(sel)
                        if el and el.is_visible():
                            break
                if not el or not el.is_visible():
                    continue
                try:
                    el.scroll_into_view_if_needed()
                    el.click()
                except Exception:
                    self.page.evaluate("(el) => el.click()", el)
                self.page.wait_for_timeout(500)
            # 3. Confirmar com Salvar (não usar X, pois desmarca as opções de streaming)
            self.page.wait_for_timeout(800)
            if not self._etapa5_clicar_salvar_painel():
                self.page.wait_for_timeout(700)
                self._etapa5_clicar_salvar_painel()
            self.page.wait_for_timeout(500)
            self._fechar_modal_servicos_adicionais()
            self.page.wait_for_timeout(300)
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar streaming: {e}")
            return False, str(e)

    def etapa5_clicar_avancar(self) -> Tuple[bool, str]:
        """Clica em Avançar para ir da etapa 5 (pagamento/ofertas) para etapa 6 (biometria)."""
        try:
            self._etapa5_garantir_pagina()
            # Fechar modal "Escolher serviços adicionais" se estiver aberto (bloqueia o Avançar)
            self._fechar_modal_servicos_adicionais()
            self.page.wait_for_timeout(500)
            # Aguardar spinner sumir (se houver)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=3000)
            except Exception:
                pass
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if not btn_avancar:
                return False, "Botão Avançar não disponível ou desabilitado."
            btn_avancar.click()
            self.page.wait_for_load_state("networkidle", timeout=10000)
            self.etapa_atual = 5
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao clicar Avançar: {e}")
            return False, str(e)

    def etapa5_pagamento_plano(
        self,
        forma_pagamento: str,
        plano: str,
        tem_fixo: bool = False,
        tem_streaming: bool = False,
        streaming_opcoes: str = None,
        banco: str = None,
        agencia: str = None,
        conta: str = None,
        digito: str = None,
    ) -> Tuple[bool, str]:
        """
        Etapa 5: Forma de pagamento, plano e serviços adicionais (chamada única).
        Usado pelo fluxo WhatsApp. Para fluxo incremental (terminal), use os métodos
        etapa5_selecionar_* e etapa5_clicar_avancar.
        """
        try:
            sucesso, msg = self.etapa5_selecionar_forma_pagamento(forma_pagamento)
            if not sucesso:
                return False, msg
            if forma_pagamento.lower() == 'debito' and (banco or agencia or conta or digito):
                sucesso, msg = self.etapa5_preencher_debito(banco or '', agencia or '', conta or '', digito or '')
                if not sucesso:
                    return False, msg
            sucesso, msg = self.etapa5_selecionar_plano(plano)
            if not sucesso:
                return False, msg
            sucesso, msg = self.etapa5_selecionar_fixo(tem_fixo)
            if not sucesso:
                return False, msg
            if tem_fixo:
                sucesso, msg = self.etapa5_fixo_finalizar_portabilidade(
                    quer_portabilidade=False, numero_port="", operadora_texto=""
                )
                if not sucesso:
                    return False, msg
            sucesso, msg = self.etapa5_selecionar_streaming(tem_streaming, streaming_opcoes, plano)
            if not sucesso:
                return False, msg
            sucesso, msg = self.etapa5_clicar_avancar()
            if not sucesso:
                return False, msg
            return True, f"Plano {plano.upper()} com pagamento via {forma_pagamento.upper()}!"
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 5: {e}")
            return False, f"Erro na Etapa 5: {str(e)}"
    
    def obter_resumo_pedido_para_cliente(self) -> str:
        """
        Monta o resumo do pedido a partir dos dados coletados no fluxo.
        Inclui plano, Fixo (R$ 30/mês), streaming (HBO Max R$ 44,90; Globoplay Premium R$ 39,90; Padrão R$ 22,90).
        Endereço no padrão: Logradouro, Nº - Complemento - Bairro, Cidade - UF, CEP.
        """
        d = self.dados_pedido
        nome = d.get('nome_cliente') or 'Cliente'
        cep = d.get('cep') or ''
        numero = d.get('numero') or ''
        ref = d.get('referencia') or ''
        # Endereço completo no padrão (ViaCEP): Logradouro, Nº - Complemento - Bairro, Cidade - UF, CEP
        endereco = self._formatar_endereco_completo(cep, numero, ref) if cep else ""
        if not endereco:
            partes = []
            if (str(cep or '').strip()): partes.append(f"CEP {cep}")
            if (str(numero or '').strip()): partes.append(f"Nº {numero}")
            if (str(ref or '').strip()): partes.append(f"Ref: {ref}")
            endereco = ", ".join(partes) if partes else (ref if ref else "Endereço a confirmar")
        plano = (d.get('plano') or '500mega').upper()
        forma_raw = (d.get('forma_pagamento') or '').upper()
        cartao = 'CREDITO' in forma_raw or 'CARTÃO' in forma_raw or 'CARTAO' in forma_raw
        valor_map = {
            '500MEGA': ('R$ 100,00/mês', 'R$ 90,00/mês'),
            '700MEGA': ('R$ 130,00/mês', 'R$ 120,00/mês'),
            '1GIGA': ('R$ 160,00/mês', 'R$ 150,00/mês'),
        }
        par = valor_map.get(plano.upper(), ('R$ --', 'R$ --'))
        valor = par[1] if cartao else par[0]
        plano_label = plano.replace('MEGA', ' Mega').replace('GIGA', ' Giga')
        forma_raw_val = (d.get('forma_pagamento') or 'Boleto').strip().lower()
        forma_display_map = {'boleto': 'Boleto', 'cartao': 'Cartão de Crédito', 'cartão': 'Cartão de Crédito', 'debito': 'Débito em Conta', 'débito': 'Débito em Conta'}
        forma = forma_display_map.get(forma_raw_val) or forma_raw_val.replace('credito', 'Cartão').replace('dacc', 'Débito').replace('boleto', 'Boleto').title()
        # Serviços adicionais com preços
        linhas_adic = []
        if d.get('tem_fixo'):
            linhas_adic.append("• Fixo: R$ 30,00/mês")
        opts_raw = (d.get('streaming_opcoes') or '').lower().replace(' ', '')
        opts_set = set(x.strip() for x in opts_raw.split(',') if x.strip())
        precos_streaming = [
            ('hbomax', 'HBO Max', 'R$ 44,90/mês'),
            ('globoplay_premium', 'Globoplay – Plano Premium', 'R$ 39,90/mês'),
            ('globoplay_basico', 'Globoplay – Plano Padrão com Anúncios', 'R$ 22,90/mês'),
        ]
        for key, label, preco in precos_streaming:
            if key in opts_set:
                linhas_adic.append(f"• {label}: {preco}")
        bloco_adic = "\n".join(linhas_adic) if linhas_adic else "Nenhum"
        return (
            "📋 *RESUMO DO PEDIDO*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *Cliente:* {nome}\n\n"
            f"📍 *Endereço:*\n{endereco}\n\n"
            f"📦 *Plano:* {plano_label} – {valor}\n\n"
            f"💳 *Forma de pagamento:* {forma}\n\n"
            f"✨ *Serviços adicionais:*\n{bloco_adic}\n\n"
            f"📅 *Fidelidade:* 12 meses\n\n"
            "💰 *Taxa de habilitação:*\n"
            "Você ganha isenção da taxa de habilitação se permanecer no mínimo 12 meses conosco.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Para confirmar, responda *SIM*."
        )

    def etapa6_extrair_resumo_oferta(self) -> Tuple[bool, str]:
        """
        Etapa 6: Extrai o resumo da oferta (Detalhes da oferta) da página.
        
        Returns:
            Tuple (sucesso, texto_resumo)
        """
        try:
            logger.info("[PAP] Etapa 6 - Extraindo resumo da oferta")
            self.page.wait_for_load_state("networkidle", timeout=10000)
            linhas = []
            # Detalhes da oferta - pegar seção inteira (título + conteúdo abaixo)
            secao = self.page.query_selector('div:has-text("Detalhes da oferta")')
            if secao:
                try:
                    # Pegar container pai que engloba título + conteúdo
                    texto = secao.evaluate("el => { const p = el.closest('div') || el.parentElement; return (p ? p.innerText : el.innerText) || ''; }")
                    if isinstance(texto, str) and texto.strip() and len(texto.strip()) > 5:
                        linhas.append(texto.strip())
                except Exception:
                    pass
                if not linhas:
                    try:
                        texto = secao.inner_text()
                        if texto:
                            linhas.append(texto.strip())
                    except Exception:
                        pass
            # Fallback: blocos com plano, preço
            if not linhas:
                blocos = self.page.query_selector_all('div:has-text("Nio Fibra"), div:has-text("Giga"), div:has-text("Mega"), div:has-text("R$")')
                vistos = set()
                for b in blocos[:8]:
                    try:
                        t = (b.inner_text() or "").strip()
                        if t and len(t) < 120 and t not in vistos:
                            vistos.add(t)
                            linhas.append(t)
                    except Exception:
                        pass
            resumo = "\n".join(linhas) if linhas else "Resumo da oferta não disponível."
            self.dados_pedido['resumo_oferta'] = resumo
            return True, resumo
        except Exception as e:
            logger.error(f"[PAP] Erro ao extrair resumo: {e}")
            return False, f"Erro: {str(e)}"

    def _obter_endereco_via_cep(self, cep: str, numero: str = "", complemento: str = "") -> str:
        """Consulta ViaCEP e retorna endereço completo."""
        try:
            import requests
            cep_limpo = re.sub(r'\D', '', str(cep or ''))[:8]
            if len(cep_limpo) != 8:
                return ""
            url = f"https://viacep.com.br/ws/{cep_limpo}/json/"
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            d = r.json()
            if d.get('erro'):
                return ""
            logradouro = d.get('logradouro', '')
            bairro = d.get('bairro', '')
            localidade = d.get('localidade', '')
            uf = d.get('uf', '')
            cep_fmt = d.get('cep', cep_limpo)
            partes = [p for p in [logradouro, numero, complemento, bairro, f"{localidade}-{uf}", f"CEP {cep_fmt}"] if p]
            return ", ".join(partes)
        except Exception as e:
            logger.warning(f"[PAP] ViaCEP erro: {e}")
            return ""

    def _formatar_endereco_completo(self, cep: str, numero: str = "", complemento: str = "") -> str:
        """
        Retorna endereço no padrão: Logradouro, Nº - Complemento - Bairro, Cidade - UF, CEP
        Ex.: R. Cachopa, 108 - Casa 1 - São João, Betim - MG, 32655-612
        Complemento (ex.: referencia) vem após o número da fachada.
        """
        try:
            import requests
            cep_limpo = re.sub(r'\D', '', str(cep or ''))[:8]
            if len(cep_limpo) != 8:
                return ""
            url = f"https://viacep.com.br/ws/{cep_limpo}/json/"
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            d = r.json()
            if d.get('erro'):
                return ""
            logradouro = (d.get('logradouro') or '').strip()
            bairro = (d.get('bairro') or '').strip()
            localidade = (d.get('localidade') or '').strip()
            uf = (d.get('uf') or '').strip()
            cep_fmt = d.get('cep', cep_limpo)
            numero_s = str(numero or '').strip()
            complemento_s = str(complemento or '').strip()
            # Formato: Logradouro, Nº - Complemento - Bairro, Cidade - UF, CEP
            parte1 = f"{logradouro}, {numero_s}" if logradouro else (numero_s or "")
            if complemento_s:
                parte1 = f"{parte1} - {complemento_s}" if parte1 else complemento_s
            parte2 = f"{bairro}, {localidade} - {uf}, {cep_fmt}" if bairro else f"{localidade} - {uf}, {cep_fmt}"
            if parte1 and parte2:
                return f"{parte1} - {parte2}"
            if parte2:
                return parte2
            return f"{parte1}, {cep_fmt}" if parte1 else ""
        except Exception as e:
            logger.warning(f"[PAP] _formatar_endereco_completo: {e}")
            return ""

    def etapa6_consultar_biometria(self) -> Tuple[bool, str]:
        """Clica no botão Consultar Biometria na etapa 6."""
        try:
            logger.info("[PAP] Etapa 6 - Clicando Consultar Biometria")
            btn = self.page.query_selector('button:has-text("Consultar Biometria"), button.btn-consult-new')
            if not btn:
                return False, "Botão Consultar Biometria não encontrado."
            btn.click()
            self.page.wait_for_load_state("networkidle", timeout=10000)
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao consultar biometria: {e}")
            return False, str(e)

    def etapa6_verificar_biometria(self, consultar_primeiro: bool = False) -> Tuple[bool, str, bool]:
        """
        Etapa 6: Verificar status da biometria.

        Fonte da verdade: (1) botão "Abrir OS" habilitado = biometria aprovada;
        (2) estar na tela Etapa 6 (Resumo) sem indicação de biometria pendente no contexto da biometria.

        Args:
            consultar_primeiro: Se True, clica em "Consultar Biometria" antes de verificar (para atualizar status)

        Returns:
            Tuple (sucesso, mensagem, biometria_aprovada)
        """
        try:
            logger.info("[PAP] Etapa 6 - Verificando biometria")

            # Aguardar spinner desaparecer (bloqueia cliques)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=10000)
            except Exception:
                self.page.wait_for_timeout(2000)

            self.page.wait_for_load_state("networkidle", timeout=8000)

            # Se solicitado, clicar em Consultar Biometria para atualizar status
            if consultar_primeiro:
                self.etapa6_consultar_biometria()
                self.page.wait_for_timeout(2500)
                try:
                    self.page.wait_for_selector('div.spinner', state="hidden", timeout=10000)
                except Exception:
                    self.page.wait_for_timeout(2000)

            # Avançar se ainda houver botão Avançar (transição etapa 5 -> 6)
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                try:
                    btn_avancar.click()
                    self.page.wait_for_timeout(1500)
                    try:
                        self.page.wait_for_selector('div.spinner', state="hidden", timeout=10000)
                    except Exception:
                        self.page.wait_for_timeout(2000)
                    self.page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass

            # 1) Botão "Abrir OS" habilitado = biometria aprovada (não validar como se ainda estivesse na Etapa 5)
            btn_abrir_os = self.page.query_selector(
                'button:has-text("Abrir OS"):not([disabled]), '
                'button:has-text("Abrir O.S"):not([disabled]), '
                'button:has-text("Abrir O.S."):not([disabled])'
            )
            if btn_abrir_os:
                self.etapa_atual = 6
                return True, "Biometria APROVADA! Pronto para abrir O.S.", True

            # 2) Restringir "pendente" ao contexto da biometria (evitar falso "pendente" em texto da tela Resumo)
            span_biometria = self.page.query_selector('span:has-text("Biometria")')
            contexto_biometria = ""
            if span_biometria:
                try:
                    # Texto da linha/célula ou do container que contém o label Biometria
                    contexto_biometria = (
                        span_biometria.evaluate(
                            "el => (el.closest('tr') || el.closest('div'))?.innerText || el.innerText || ''"
                        ) or ""
                    ).lower()
                except Exception:
                    contexto_biometria = (span_biometria.inner_text() or "").lower()
            biometria_pendente = (
                'pendente' in contexto_biometria
                or 'aguardando' in contexto_biometria
                or 'em análise' in contexto_biometria
            )

            # 3) Fallback: estar na Etapa 6 (Resumo) sem pendente no contexto da biometria = aprovada
            pagina_texto = (self.page.content() or "").lower()
            na_etapa_resumo = bool(
                'resumo' in pagina_texto
                or self.page.query_selector('h2:has-text("Resumo"), h3:has-text("Resumo"), [class*="resumo"]')
            )
            if na_etapa_resumo and not biometria_pendente:
                self.etapa_atual = 6
                return True, "Biometria APROVADA (Etapa Resumo). Pronto para abrir O.S.", True

            if biometria_pendente:
                return True, "Biometria PENDENTE. Peça ao cliente para realizar a biometria e digite CONSULTAR para verificar novamente.", False
            return False, "Biometria não aprovada ou não disponível.", False

        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 6: {e}")
            return False, f"Erro na Etapa 6: {str(e)}", False
    
    def etapa7_ir_para_agendamento(self) -> Tuple[bool, str]:
        """Clica em Abrir OS e aguarda a tela de Agendamento aparecer.
        O portal executa 9 validações ('Consultando os slots para agendamento' 1 de 9 ... 9 de 9)
        antes de exibir a tela; timeout alto para não falhar durante as validações."""
        try:
            btn = self.page.query_selector('button:has-text("Abrir OS"):not([disabled]), button:has-text("Abrir O.S"):not([disabled])')
            if not btn:
                return False, "Botão Abrir OS não disponível."
            btn.click()
            self.page.wait_for_timeout(2000)
            # 9 validações no portal; aguardar até 90s pela tela de Período/Agendamento
            self.page.wait_for_selector('h3:has-text("Período"), [class*="react-datepicker"], [class*="Agendamento"]', state="visible", timeout=90000)
            self.page.wait_for_load_state("networkidle", timeout=10000)
            return True, "Tela de Agendamento exibida."
        except Exception as e:
            logger.error(f"[PAP] etapa7_ir_para_agendamento: {e}")
            return False, str(e)

    def etapa7_obter_datas_disponiveis(self) -> Tuple[bool, str, list]:
        """Extrai as datas disponíveis no calendário (dias clicáveis). Retorna lista de números de dia."""
        try:
            dias = self.page.query_selector_all('.react-datepicker__day:not(.react-datepicker__day--disabled):not(.react-datepicker__day--outside-month)')
            nums = []
            for d in dias:
                txt = (d.inner_text() or "").strip()
                if txt.isdigit() and 1 <= int(txt) <= 31:
                    nums.append(int(txt))
            nums = sorted(set(nums))
            return True, "OK", nums
        except Exception as e:
            logger.error(f"[PAP] etapa7_obter_datas: {e}")
            return False, str(e), []

    def etapa7_selecionar_data_e_obter_periodos(self, dia: int) -> Tuple[bool, str, list]:
        """Clica no dia no calendário e retorna os períodos disponíveis. Períodos: [{idx, label}]."""
        try:
            # Tentar por aria-label ou classe (ex: day-10, day-011)
            elem = self.page.query_selector(f'.react-datepicker__day[aria-label="day-{dia}"], .react-datepicker__day[aria-label="day-{dia:02d}"]')
            if not elem:
                elem = self.page.query_selector(f'.react-datepicker__day--0{dia:02d}:not(.react-datepicker__day--disabled)')
            if not elem:
                elems = self.page.query_selector_all('.react-datepicker__day:not(.react-datepicker__day--disabled)')
                for e in elems:
                    if (e.inner_text() or "").strip() == str(dia):
                        elem = e
                        break
            if not elem:
                return False, f"Dia {dia} não encontrado no calendário.", []
            elem.click()
            self.page.wait_for_timeout(1500)
            # Períodos: 2 (08h às 12h - Manhã, 13h às 18h - Tarde) ou 4 (08h-10h, 10h-12h, 13h-15h, 15h-18h)
            # Garantir ordem do DOM e reconhecer ambos os formatos
            periodos = self._etapa7_obter_lista_periodos()
            labels = []
            for i, p in enumerate(periodos):
                lbl = (p.inner_text() or "").strip()
                if lbl:
                    labels.append({"idx": i + 1, "label": lbl})
            return True, "OK", labels
        except Exception as e:
            logger.error(f"[PAP] etapa7_selecionar_data: {e}")
            return False, str(e), []

    def _etapa7_obter_lista_periodos(self):
        """Retorna lista de elementos li de período em ordem do DOM.
        Reconhece 2 períodos (08h às 12h - Manhã, 13h às 18h - Tarde) ou 4 períodos."""
        # Padrão "Xh às Yh" (ex.: 08h às 12h - Manhã, 13h às 18h - Tarde)
        try:
            all_li = self.page.query_selector_all('li')
            periodos = []
            pattern = re.compile(r'\d+h\s*às\s*\d+h', re.IGNORECASE)
            for li in all_li:
                text = (li.inner_text() or "").strip()
                if pattern.search(text):
                    periodos.append(li)
            if periodos:
                return periodos
        except Exception as e:
            logger.debug("[PAP] _etapa7_obter_lista_periodos (regex): %s", e)
        # Fallback: li com Manhã ou Tarde
        periodos = self.page.query_selector_all('li:has-text("Manhã"), li:has-text("Tarde")')
        if periodos:
            return periodos
        return self.page.query_selector_all('li:has-text("às")')

    def etapa7_selecionar_periodo(self, indice: int) -> Tuple[bool, str]:
        """Seleciona o período pelo índice. NÃO clica em Agendar (apenas seleciona o turno)."""
        try:
            periodos = self._etapa7_obter_lista_periodos()
            if indice < 1 or indice > len(periodos):
                return False, f"Período {indice} inválido."
            periodos[indice - 1].click()
            self.page.wait_for_timeout(500)
            return True, "Período selecionado. (Botão Agendar não acionado.)"
        except Exception as e:
            logger.error(f"[PAP] etapa7_selecionar_periodo: {e}")
            return False, str(e)

    def etapa7_clicar_agendar(self) -> Tuple[bool, str]:
        """
        Clica em Agendar e aguarda o modal "Agendado para" aparecer.
        O número do pedido NÃO está neste modal - aparece depois de clicar Continuar.
        Returns: (sucesso, mensagem)
        """
        try:
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=5000)
            except Exception:
                pass
            btn = self.page.query_selector('button:has-text("Agendar")')
            if not btn:
                return False, "Botão Agendar não encontrado."
            try:
                btn.click(force=True, timeout=5000)
            except Exception:
                self.page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')];
                    const ag = btns.find(x => x.textContent && x.textContent.includes('Agendar'));
                    if (ag) ag.click();
                }""")
            self.page.wait_for_timeout(2000)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_selector('h3:has-text("Agendado para")', state="visible", timeout=12000)
            self.page.wait_for_timeout(500)
            return True, "Modal de confirmação exibido."
        except Exception as e:
            logger.error(f"[PAP] etapa7_clicar_agendar: {e}")
            return False, str(e)

    def etapa7_modal_clicar_continuar(self) -> Tuple[bool, str, Optional[str]]:
        """
        Clica em Continuar no modal "Agendado para", aguarda o modal "Sucesso!",
        extrai o número da OS e clica em Ok.
        Returns: (sucesso, mensagem, numero_pedido)
        """
        try:
            btn = self.page.query_selector('button:has-text("Continuar")')
            if not btn:
                return False, "Botão Continuar não encontrado no modal.", None
            try:
                btn.click(force=True, timeout=5000)
            except Exception:
                self.page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')];
                    const c = btns.find(x => x.textContent && x.textContent.includes('Continuar'));
                    if (c) c.click();
                }""")
            self.page.wait_for_timeout(2000)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_load_state("networkidle", timeout=10000)
            self.page.wait_for_timeout(1500)
            # Aguarda o modal "Sucesso!"
            try:
                self.page.wait_for_selector('h3:has-text("Sucesso!")', state="visible", timeout=15000)
            except Exception:
                pass
            self.page.wait_for_timeout(500)
            # Extrai o número da OS do span "Concluída a abertura da OS número XXXX, pedido salvo"
            numero_os = None
            span = self.page.query_selector('span:has-text("Concluída a abertura")')
            if span:
                texto = span.inner_text() or ""
                m = re.search(r'OS número (\d+)[,\s]+pedido salvo', texto, re.I)
                if m:
                    numero_os = m.group(1)
            if not numero_os:
                pagina = self.page.content()
                m = re.search(r'Concluída a abertura da OS número (\d+)[,\s]*pedido salvo', pagina, re.I)
                if m:
                    numero_os = m.group(1)
            if numero_os:
                self.dados_pedido['numero_pedido_agendamento'] = numero_os
                self.dados_pedido['numero_os'] = numero_os
                self.numero_pedido = numero_os
            # Clica em Ok para fechar o modal
            btn_ok = self.page.query_selector('button:has-text("Ok")')
            if btn_ok:
                try:
                    btn_ok.click(force=True, timeout=3000)
                except Exception:
                    self.page.evaluate("""() => {
                        const btns = [...document.querySelectorAll('button')];
                        const ok = btns.find(x => x.textContent && x.textContent.trim() === 'Ok');
                        if (ok) ok.click();
                    }""")
            self.page.wait_for_timeout(1000)
            if numero_os:
                return True, f"Agendamento realizado! Número do pedido: {numero_os}", numero_os
            return True, "Agendamento realizado! (Número do pedido não identificado.)", None
        except Exception as e:
            logger.error(f"[PAP] etapa7_modal_clicar_continuar: {e}")
            return False, str(e), None

    def etapa7_modal_fechar(self) -> Tuple[bool, str]:
        """
        Fecha o modal "Agendado para" clicando no X.
        Retorna para a tela de calendário para o usuário alterar data/turno.
        """
        try:
            for sel in [
                'button:has(img.img)',
                'button:has(img[alt=""])',
                '[aria-label="Fechar"]',
                '[aria-label="Close"]',
                'button[class*="close"]',
                '[class*="modal"] button:has(svg)',
                '[class*="Modal"] button:has(svg)',
            ]:
                btn = self.page.query_selector(sel)
                if btn:
                    try:
                        btn.click(force=True, timeout=3000)
                        self.page.wait_for_timeout(1000)
                        return True, "Modal fechado."
                    except Exception:
                        continue
            self.page.evaluate("""() => {
                const modal = document.querySelector('h3');
                if (modal && modal.textContent && modal.textContent.includes('Agendado')) {
                    const container = modal.closest('[class*="modal"], [class*="Modal"], [role="dialog"]') || modal.closest('div');
                    const btns = container ? container.querySelectorAll('button, [role="button"]') : [];
                    const xBtn = [...btns].find(b => {
                        const txt = (b.textContent || '').trim();
                        const hasSvg = b.querySelector('svg') || b.querySelector('img');
                        return hasSvg && !txt.includes('Continuar') && txt.length < 5;
                    });
                    if (xBtn) xBtn.click();
                }
            }""")
            self.page.wait_for_timeout(1000)
            return True, "Modal fechado."
        except Exception as e:
            logger.error(f"[PAP] etapa7_modal_fechar: {e}")
            return False, str(e)

    def etapa7_abrir_os(self, data_agendamento: str = None, turno: str = 'manha') -> Tuple[bool, str, Optional[str]]:
        """
        Etapa 7: Abrir O.S. e agendar instalação.
        
        Args:
            data_agendamento: Data no formato DD/MM/YYYY (se None, usa primeira disponível)
            turno: 'manha' ou 'tarde'
            
        Returns:
            Tuple (sucesso, mensagem, numero_os)
        """
        try:
            logger.info(f"[PAP] Etapa 7 - Abrindo O.S. Data: {data_agendamento}, Turno: {turno}")
            
            # Clicar em Abrir OS
            btn_abrir_os = self.page.query_selector('button:has-text("Abrir OS"):not([disabled]), button:has-text("Abrir O.S"):not([disabled])')
            if btn_abrir_os:
                btn_abrir_os.click()
                self.page.wait_for_selector('button:has-text("Confirmar"), [class*="calendario"], [class*="calendar"]', state="visible", timeout=10000)
            else:
                return False, "Botão Abrir O.S. não disponível. Verifique a biometria.", None
            
            # Se data específica foi informada, tentar encontrar
            if data_agendamento:
                data_elem = self.page.query_selector(f'[data-date="{data_agendamento}"], :has-text("{data_agendamento}")')
                if data_elem:
                    data_elem.click()
            else:
                # Clicar na primeira data disponível
                data_disponivel = self.page.query_selector(SELETORES['etapa7']['data_disponivel'])
                if data_disponivel:
                    data_disponivel.click()
            
            # Selecionar turno
            turno_selector = SELETORES['etapa7']['turno_manha'] if turno.lower() == 'manha' else SELETORES['etapa7']['turno_tarde']
            turno_elem = self.page.query_selector(turno_selector)
            if turno_elem:
                turno_elem.click()
            
            # Confirmar e aguardar conclusão
            btn_confirmar = self.page.query_selector('button:has-text("Confirmar"):not([disabled])')
            if btn_confirmar:
                btn_confirmar.click()
                # Aguardar página de sucesso ou número da OS
                self.page.wait_for_load_state("networkidle", timeout=15000)
            
            # Extrair número da O.S.
            pagina_texto = self.page.content()
            
            # Procurar padrões de número de pedido/OS
            padrao_os = re.search(r'(\d{15,20})', pagina_texto)
            padrao_pedido = re.search(r'Pedido[:\s]*(\d+)', pagina_texto, re.IGNORECASE)
            
            numero_os = None
            if padrao_os:
                numero_os = padrao_os.group(1)
            elif padrao_pedido:
                numero_os = padrao_pedido.group(1)
            
            if numero_os:
                self.etapa_atual = 7
                self.numero_pedido = numero_os
                self.dados_pedido['numero_os'] = numero_os
                self.dados_pedido['data_agendamento'] = data_agendamento
                self.dados_pedido['turno'] = turno
                return True, f"🎉 VENDA CONCLUÍDA!\n\nNúmero do Pedido: {numero_os}", numero_os
            else:
                # Verificar se houve sucesso mesmo sem extrair número
                if 'sucesso' in pagina_texto.lower() or 'concluído' in pagina_texto.lower():
                    return True, "Venda concluída! Número do pedido não identificado.", None
                return False, "Não foi possível confirmar a abertura da O.S.", None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 7: {e}")
            return False, f"Erro na Etapa 7: {str(e)}", None
    
    def _clicar_sair(self) -> bool:
        """Clica em Sair para fazer logout. Usa force e JS se overlay interceptar."""
        try:
            if not self.page:
                return False
            sair = self.page.query_selector('#sair, p#sair, [id="sair"]')
            if sair:
                try:
                    sair.click(force=True, timeout=3000)
                except Exception:
                    self.page.evaluate("""() => {
                        const el = document.querySelector('#sair, p#sair, [id="sair"]');
                        if (el) el.click();
                    }""")
                self.page.wait_for_timeout(1500)
                return True
            return False
        except Exception as e:
            logger.warning(f"[PAP] Erro ao clicar Sair: {e}")
            return False

    def _fechar_sessao(self):
        """Fecha a sessão do navegador e libera recursos. Clica em Sair antes para não travar login."""
        if not self.sessao_iniciada:
            return
        try:
            # Salvar trace antes de fechar (permite ver cada clique no https://trace.playwright.dev)
            if getattr(self, '_trace_started', False) and self.context:
                try:
                    from django.conf import settings as _st
                    base_dir = getattr(_st, 'BASE_DIR', None)
                    if base_dir:
                        downloads_dir = os.path.join(base_dir, 'downloads')
                        os.makedirs(downloads_dir, exist_ok=True)
                        safe_run = str(self.run_id).replace(os.sep, '_').replace('..', '_')[:50]
                        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                        trace_path = os.path.join(downloads_dir, f"pap_trace_{safe_run}_{ts}.zip")
                        self.context.tracing.stop(path=trace_path)
                        logger.info(f"[PAP] Trace salvo: {os.path.basename(trace_path)} (abrir em https://trace.playwright.dev)")
                except Exception as e:
                    logger.warning(f"[PAP] Erro ao salvar trace: {e}")
                self._trace_started = False
            if self.page:
                self._clicar_sair()
            if self.context:
                try:
                    self.context.storage_state(path=self.storage_state_path)
                except:
                    pass

            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass
                self.playwright = None
        except Exception as e:
            logger.error(f"[PAP] Erro ao fechar sessão: {e}")
        finally:
            if self.playwright:
                try:
                    self.playwright.stop()
                except Exception:
                    pass
                self.playwright = None
            _pap_semaphore.release()
            self.sessao_iniciada = False
            logger.info(f"[PAP] Sessão encerrada para {self.vendedor_nome}")
    
    def __del__(self):
        """Destrutor para garantir limpeza de recursos"""
        if self.sessao_iniciada:
            self._fechar_sessao()


# =============================================================================
# GERENCIADOR DE SESSÕES DE VENDA VIA WHATSAPP
# =============================================================================

# Cache de sessões ativas (por telefone do vendedor)
_sessoes_venda: Dict[str, Dict] = {}
_sessoes_lock = threading.Lock()


def obter_sessao_venda(telefone: str) -> Optional[Dict]:
    """Obtém a sessão de venda ativa para um telefone"""
    with _sessoes_lock:
        return _sessoes_venda.get(telefone)


def criar_sessao_venda(telefone: str, usuario_id: int, dados: Dict) -> Dict:
    """Cria uma nova sessão de venda"""
    with _sessoes_lock:
        _sessoes_venda[telefone] = {
            'usuario_id': usuario_id,
            'etapa': 'inicio',
            'dados': dados,
            'automacao': None,
            'criado_em': datetime.now(),
            'atualizado_em': datetime.now(),
        }
        return _sessoes_venda[telefone]


def atualizar_sessao_venda(telefone: str, etapa: str = None, dados: Dict = None, automacao: Any = None):
    """Atualiza uma sessão de venda existente"""
    with _sessoes_lock:
        if telefone in _sessoes_venda:
            if etapa:
                _sessoes_venda[telefone]['etapa'] = etapa
            if dados:
                _sessoes_venda[telefone]['dados'].update(dados)
            if automacao is not None:
                _sessoes_venda[telefone]['automacao'] = automacao
            _sessoes_venda[telefone]['atualizado_em'] = datetime.now()


def encerrar_sessao_venda(telefone: str):
    """Encerra uma sessão de venda"""
    with _sessoes_lock:
        if telefone in _sessoes_venda:
            sessao = _sessoes_venda[telefone]
            if sessao.get('automacao'):
                try:
                    sessao['automacao']._fechar_sessao()
                except:
                    pass
            del _sessoes_venda[telefone]


def limpar_sessoes_expiradas(timeout_minutos: int = 30):
    """Remove sessões que expiraram"""
    with _sessoes_lock:
        agora = datetime.now()
        expiradas = []
        for telefone, sessao in _sessoes_venda.items():
            delta = (agora - sessao['atualizado_em']).total_seconds() / 60
            if delta > timeout_minutos:
                expiradas.append(telefone)
        
        for telefone in expiradas:
            if _sessoes_venda[telefone].get('automacao'):
                try:
                    _sessoes_venda[telefone]['automacao']._fechar_sessao()
                except:
                    pass
            del _sessoes_venda[telefone]
            logger.info(f"[PAP] Sessão expirada removida: {telefone}")
