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

# Fluxo CRÉDITO (parar_no_modal_credito): não concluir sem o modal "Resultado da análise de crédito" visível
# (evita falso "aprovado" se a etapa de pagamento carregar antes do modal).
MSG_CREDITO_SEM_TELA_RESULTADO = (
    "A tela com o resultado da consulta de crédito não foi exibida. "
    "Digite *CRÉDITO* e envie o CPF ou CNPJ novamente para repetir a consulta."
)

# Após reset do portal (ex.: modal "Ocorreu um erro" + Ok → Etapa 1), até qual subpasso reaplicar
# para alinhar o browser com a etapa atual do WhatsApp. Ver PAPNioAutomation.tentar_recuperar_portal_reset_etapa1.
# 0=só novo pedido (tela CEP); 1=viabilidade ok; 2=+CPF; 3=+contato; 4=+forma; 5=+débito se houver ou já em planos;
# 6=+plano; 7=+fixo; 8=+portabilidade fixo; 9=+streaming e Avançar até resumo.
WPP_ETAPA_REPLAY_TARGET_SN = {
    "venda_cep": 0,
    "venda_numero": 0,
    "venda_referencia": 0,
    "venda_selecionar_endereco": 1,
    "venda_selecionar_complemento": 1,
    "venda_posse_consultar_outro": 1,
    "venda_indisponivel_voltar": 1,
    "venda_corrigir_celular": 3,
    "venda_corrigir_email": 3,
    "venda_corrigir_cpf": 2,
    "venda_cpf": 1,
    "venda_celular": 2,
    "venda_celular_sec": 2,
    "venda_email": 3,
    "venda_forma_pagamento": 3,
    "venda_debito_banco": 4,
    "venda_debito_agencia": 4,
    "venda_debito_conta": 4,
    "venda_debito_digito": 4,
    "venda_plano": 5,
    "venda_fixo": 6,
    "venda_fixo_portabilidade": 7,
    "venda_fixo_portabilidade_numero": 7,
    "venda_fixo_portabilidade_operadora": 7,
    "venda_streaming": 8,
    "venda_streaming_opcoes": 8,
    "venda_confirmar": 9,
    "venda_aguardando_confirmacao": 9,
    "venda_aguardando_biometria": 9,
    "venda_aguardando_abrir_os": 9,
    "venda_agendamento_dia": 9,
    "venda_agendamento_confirmar_data": 9,
    "venda_agendamento_periodo": 9,
    "venda_agendamento_confirmar_turno": 9,
    "venda_agendamento_sim_agendar": 9,
    "venda_agendamento_final": 9,
}

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
        slow_mo: Optional[int] = None,
        record_trace: bool = False,
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
            slow_mo: Milissegundos entre ações do Playwright (None = 300 se headless False, 0 se headless)
            record_trace: Se True, grava trace Playwright (inspect em trace.playwright.dev) sem exigir todos os screenshots
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
        self.slow_mo = slow_mo
        self.record_trace = record_trace

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
        self._pap_slot_held = False  # slot do semáforo global (liberar mesmo se login falhar antes de sessao_iniciada)
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
            if not _pap_semaphore.acquire(timeout=180):
                logger.warning("[PAP] Semáforo ocupado (>180s) — outras automações podem estar travadas.")
                return False, "Sistema PAP ocupado. Aguarde e tente novamente em instantes."
            self._pap_slot_held = True
            logger.info(f"[PAP] Iniciando sessão para {self.vendedor_nome}")
            
            self.playwright = sync_playwright().start()
            playwright = self.playwright
            launch_opts = {"headless": self.headless}
            _sm = self.slow_mo
            if _sm is None and not self.headless:
                _sm = 300  # pausa entre ações para visualizar cliques
            if _sm is not None:
                launch_opts["slow_mo"] = int(_sm)
            self.browser = playwright.chromium.launch(**launch_opts)
            
            # Tentar carregar sessão existente
            storage_state = self.storage_state_path if os.path.exists(self.storage_state_path) else None
            
            self.context = self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                # Altura maior: drawer de streaming tem Salvar no rodapé (abaixo da dobra em 800px).
                viewport={"width": 1280, "height": 960},
                storage_state=storage_state,
            )
            
            self.page = self.context.new_page()
            # Timeout padrão alto para evitar "Timeout 5000ms" em produção (rede/React lentos)
            self.page.set_default_timeout(25000)
            self.sessao_iniciada = True

            # Trace: grava todas as ações para inspecionar no Playwright Trace Viewer (ver onde os cliques foram feitos)
            if self.capture_screenshots or self.record_trace:
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
                    self._fechar_sessao()
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
    
    def _contexto_destruido(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "execution context was destroyed" in msg or "context was destroyed" in msg

    def _aguardar_pagina_estavel(self, retries: int = 3, delay_ms: int = 2500) -> None:
        """Aguarda redirects SSO terminarem antes de ler URL/DOM."""
        if not self.page:
            return
        for _ in range(retries):
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_timeout(800 if self.optimize_for_credit else 1500)
            try:
                _ = self.page.url
                return
            except Exception as e:
                if self._contexto_destruido(e):
                    self.page.wait_for_timeout(delay_ms)
                    continue
                raise

    def _ler_url_e_conteudo(self) -> Tuple[str, str]:
        """Lê URL e HTML com retry quando o SSO ainda está redirecionando."""
        for tentativa in range(3):
            try:
                return (self.page.url or ""), (self.page.content() or "")
            except Exception as e:
                if self._contexto_destruido(e) and tentativa < 2:
                    logger.warning("[PAP] Página ainda navegando (login), aguardando...")
                    self.page.wait_for_timeout(2500)
                    continue
                raise
        return "", ""

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
                self._aguardar_pagina_estavel()

                # Garantir que estamos na página de login (pode ter vindo de retry após timeout)
                current_url, pagina_html = self._ler_url_e_conteudo()
                if "login.vtal.com" in current_url and "upstream request timeout" in pagina_html.lower():
                    logger.warning("[PAP] Erro upstream timeout detectado, recarregando página de login...")
                    self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                    self._aguardar_pagina_estavel()
                
                # Aguardar formulário (evita query_selector durante redirect SSO)
                self.page.wait_for_selector(
                    '#inputMatricula, input[placeholder*="Login"], input[name*="matricula"], input[type="text"]',
                    state="visible",
                    timeout=15000,
                )
                self.page.wait_for_selector(
                    '#passwordInput, input[type="password"], input[placeholder*="Senha"]',
                    state="visible",
                    timeout=10000,
                )
                
                # Preencher matrícula e senha (tentar vários seletores)
                for sel in ['#inputMatricula', 'input[placeholder*="Login"]', 'input[name*="matricula"]', 'input[name*="username"]']:
                    try:
                        self.page.fill(sel, self.matricula_pap, timeout=5000)
                        break
                    except Exception:
                        continue
                for sel in ['#passwordInput', 'input[type="password"]', 'input[placeholder*="Senha"]']:
                    try:
                        self.page.fill(sel, self.senha_pap, timeout=5000)
                        break
                    except Exception:
                        continue
                
                # Clicar no botão de login (sem query_selector — mesmo problema de contexto)
                clicou = False
                for sel_btn in [
                    'button:has-text("EFETUAR")',
                    'button:has-text("Login")',
                    'button[type="submit"]',
                    SELETORES['login']['btn_login'],
                ]:
                    try:
                        self.page.click(sel_btn, timeout=5000)
                        clicou = True
                        break
                    except Exception:
                        continue
                if not clicou:
                    return False, "Botão de login não encontrado no PAP."

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
                    current_url, pagina = self._ler_url_e_conteudo()
                    pagina = pagina.lower()
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
                if self._contexto_destruido(e) and tentativa < max_tentativas:
                    logger.warning("[PAP] Contexto destruído no login — aguardando redirect e tentando de novo...")
                    self.page.wait_for_timeout(3000)
                    continue
                if tentativa < max_tentativas:
                    try:
                        self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                        self._aguardar_pagina_estavel()
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
        Detecta quando a sessão do PAP foi invalidada por outro login ou timeout no IdP Vtal.
        Inclui a tela de logout: login.vtal.com/.../logout*.html com "Sessão finalizada".
        """
        if not self.page:
            return False
        try:
            url = (self.page.url or "").lower()
            # Logout explícito do IdP (ex.: /nidp/logout_vtal/logout.html)
            if "login.vtal.com" in url and "logout" in url:
                return True
            # Qualquer tela do IdP Vtal sem PAP aberto costuma indicar sessão perdida no fluxo
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
            "sessão finalizada",
            "sessao finalizada",
            "feche seu navegador",
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

    def _pap_garantir_sessao_antes_resumo(self) -> Tuple[bool, str]:
        """
        Antes da etapa 6 (resumo/biometria): se o IdP deslogou, tenta relogin.
        Retorna (True, '') para continuar; (False, msg) para abortar (pedido perdido ou falha).
        """
        if not self.page:
            return False, "Página não iniciada."
        if not self._sessao_expirada_detectada():
            return True, ""
        logger.warning("[PAP] Sessão inativa na etapa resumo/biometria; relogin automático.")
        ok, msg = self.garantir_sessao_ativa(PAP_NOVO_PEDIDO_URL)
        if not ok:
            return False, f"Sessão expirou e relogin falhou: {msg}"
        return False, (
            "Sessão do portal foi renovada; o pedido em tela foi perdido. "
            "Digite *VENDER* para reenviar ou continue no PAP manualmente."
        )

    def esperar_selector_com_keepalive_sessao(
        self,
        selector: str,
        timeout_ms: int = 90000,
        poll_ms: int = 5000,
        target_after_relogin: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Espera um seletor visível em fatias de poll_ms. Entre fatias, se a sessão Vtal cair
        (logout / «Sessão finalizada»), tenta relogin. Se precisar relogar, o pedido atual no
        browser em geral se perde — retorna (False, mensagem) para o chamador decidir.
        """
        if not self.page:
            return False, "Página não iniciada."
        target_after_relogin = target_after_relogin or PAP_NOVO_PEDIDO_URL
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            if self._sessao_expirada_detectada():
                logger.warning("[PAP] Sessão perdida durante espera (selector); relogin automático.")
                ok, msg = self.garantir_sessao_ativa(target_after_relogin)
                if not ok:
                    return False, f"Sessão expirou durante a espera e relogin falhou: {msg}"
                return (
                    False,
                    "Sessão do portal expirou durante a espera; reconexão feita. "
                    "O pedido em tela pode ter sido perdido — use *CONSULTAR* ou *VENDER* conforme o caso.",
                )
            # Modal "Ocorreu um erro" (ex.: falha ao abrir OS) bloqueia a UI — não esperar o timeout inteiro
            if self._pap_modal_titulo_ocorreu_erro_visivel():
                trecho_m = self._pap_extrair_texto_modal_proximo_a_titulo_erro()
                self._pap_fechar_modal_ocorreu_erro_h3_ok()
                self.page.wait_for_timeout(400)
                low_m = (trecho_m or "").lower()
                if (
                    "não foi possível abrir o pedido" in low_m
                    or "nao foi possivel abrir o pedido" in low_m
                    or "abrir o pedido" in low_m
                ):
                    return (
                        False,
                        "O portal exibiu erro ao abrir o pedido/OS durante a espera pelo agendamento. "
                        "Tente mais tarde ou abra chamado na Nio; o fluxo pode ter voltado à Etapa 1.",
                    )
                return (
                    False,
                    (trecho_m or "Ocorreu um erro no portal").strip()[:400],
                )
            restante_ms = max(1000, int((deadline - time.monotonic()) * 1000))
            chunk = min(poll_ms, restante_ms)
            try:
                self.page.wait_for_selector(selector, state="visible", timeout=chunk)
                return True, None
            except Exception:
                continue
        return False, f"Timeout ({timeout_ms} ms) aguardando: {selector[:160]}"

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

    def _redirecionar_se_rota_bloqueia_novo_pedido(self) -> bool:
        """
        Se o navegador cair em rotas laterais (ex.: /administrativo/download) onde não há
        formulário de vendedor, força goto direto em novo-pedido. Evita falso negativo
        “matrícula não encontrada” quando o menu ou um clique desvia a SPA.
        """
        try:
            url = (self.page.url or "").lower()
        except Exception:
            return False
        if "pap.niointernet.com.br" not in url:
            return False
        bloqueadas = ("/administrativo/download", "/administrativo/download/")
        if not any(b in url for b in bloqueadas):
            return False
        logger.warning(
            "[PAP] URL fora do fluxo novo pedido (%s); forçando goto novo-pedido.",
            (self.page.url or "")[:180],
        )
        try:
            self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="domcontentloaded", timeout=35000)
            self.page.wait_for_timeout(600)
            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            self._dispensar_modais_novo_pedido()
            return True
        except Exception as e:
            logger.warning("[PAP] Falha ao redirecionar para novo-pedido após rota bloqueada: %s", e)
            return False

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
        rapido = self.optimize_for_credit
        # Tentar navegação direta primeiro
        try:
            ok_sessao, _ = self.garantir_sessao_ativa()
            if not ok_sessao:
                return False
            self.page.goto(PAP_CONSULTA_OS_URL, wait_until="domcontentloaded", timeout=30000)
            self.page.wait_for_timeout(400 if rapido else 1500)
            if rapido:
                try:
                    self.page.wait_for_selector(
                        'input.input-text-filter[placeholder*="CPF"], '
                        'button:has-text("Filtros"), button.btn-filters-new',
                        state="visible",
                        timeout=8000,
                    )
                except Exception:
                    pass
            else:
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

    def _screenshot_consulta_os_return_path(self, full_page: Optional[bool] = None) -> Optional[str]:
        """
        Tira screenshot da tela atual (Consulta OS) e retorna o caminho do arquivo.
        Usado para enviar a imagem no WhatsApp. Sempre salva, independente de capture_screenshots.
        """
        if not self.page:
            return None
        if full_page is None:
            full_page = not self.optimize_for_credit
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
            self.page.wait_for_timeout(100 if self.optimize_for_credit else 300)
            self.page.screenshot(path=filepath, full_page=full_page)
            logger.info(f"[PAP] Screenshot Consulta OS salvo: {filepath}")
            return filepath
        except Exception as e:
            logger.warning(f"[PAP] Erro ao salvar screenshot Consulta OS: {e}")
            return None

    def consulta_os_por_cpf_com_resultado(
        self,
        cpf: str,
        numero_os_filtro: Optional[str] = None,
        os_prioridade_crm: Optional[set] = None,
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

        rapido = self.optimize_for_credit
        ok_menu = self._clicar_menu_consulta_os()
        if not ok_menu:
            return False, "Não foi possível acessar a tela Consulta OS.", [], None
        self.page.wait_for_timeout(350 if rapido else 1000)

        # No PAP, o painel de Filtros abre ao PASSAR O MOUSE em cima de "Filtros" (hover), não ao clicar.
        input_selector = 'input.input-text-filter[placeholder="Digite o CPF/CNPJ..."], input.input-text-filter'
        hover_wait = 250 if rapido else 400
        try:
            self.page.locator('button:has-text("Filtros"), a:has-text("Filtros"), [role="button"]:has-text("Filtros")').first.hover(timeout=5000)
            self.page.wait_for_timeout(hover_wait)
        except Exception:
            try:
                self.page.locator('text=Filtros').first.hover(timeout=5000)
                self.page.wait_for_timeout(hover_wait)
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
                timeout=12000 if not rapido else 10000,
            )
            self.page.wait_for_timeout(250 if rapido else 800)
        except Exception as e:
            logger.debug(f"[PAP] Espera da tabela Consulta OS: {e}")
        self.page.wait_for_timeout(200 if rapido else 500)

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
                    detalhe_href = None
                    if len(cells) >= 5:
                        cell_detalhes = cells[4]
                        link = cell_detalhes.query_selector('a.detalhar-link[href*="detalhe-os"], a[href*="detalhe-os"]')
                        if link:
                            tem_detalhar = True
                            try:
                                detalhe_href = link.get_attribute("href")
                            except Exception:
                                pass
                        if not tem_detalhar and "detalhar" in (cell_detalhes.inner_text() or "").lower():
                            tem_detalhar = True
                    item = {
                        "status": status,
                        "plano": plano,
                        "numero_os": numero_os,
                        "data_hora": data_hora,
                        "nao_pertence_pdv": not tem_detalhar,
                        "detalhe_href": detalhe_href,
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
                        detalhe_href_fb = None
                        if col_per_row >= 5 and idx + 5 <= len(cells_direct):
                            cell_d = cells_direct[idx + 4]
                            link_fb = cell_d.query_selector(
                                'a.detalhar-link[href*="detalhe-os"], a[href*="detalhe-os"]'
                            )
                            if link_fb:
                                tem_detalhar = True
                                try:
                                    detalhe_href_fb = link_fb.get_attribute("href")
                                except Exception:
                                    pass
                            elif "detalhar" in (cell_d.inner_text() or "").lower():
                                tem_detalhar = True
                        if status or plano or numero_os or data_hora:
                            detalhes.append({
                                "status": status,
                                "plano": plano,
                                "numero_os": numero_os,
                                "data_hora": data_hora,
                                "nao_pertence_pdv": not tem_detalhar,
                                "detalhe_href": detalhe_href_fb,
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

        from crm_app.utils import ordenar_detalhes_pap_por_os_prioridade

        detalhes = ordenar_detalhes_pap_por_os_prioridade(detalhes, os_prioridade_crm or set())

        list_screenshot_path = None

        # Para cada OS que tem link Detalhar: abrir detalhe, extrair dados + Pendência e tirar screenshot da tela de detalhe
        if detalhes:
            for row in detalhes:
                if row.get("nao_pertence_pdv"):
                    continue
                num_os = (row.get("numero_os") or "").strip()
                if not num_os:
                    continue
                st_ag, ag_texto, pendencia, detail_screenshot_path = self.abrir_detalhe_os_e_extrair(
                    num_os, detalhe_href=row.get("detalhe_href")
                )
                if st_ag is not None:
                    row["status_agendamento"] = st_ag
                if ag_texto is not None:
                    row["agendamento"] = ag_texto
                if pendencia is not None:
                    row["pendencia"] = pendencia
                if detail_screenshot_path:
                    row["detail_screenshot_path"] = detail_screenshot_path

        # Screenshot da lista só quando necessário (sem print de detalhe / não pertence ao PDV)
        if detalhes:
            precisa_lista = any(
                row.get("nao_pertence_pdv") or not row.get("detail_screenshot_path")
                for row in detalhes
            )
            if precisa_lista:
                list_screenshot_path = self._screenshot_consulta_os_return_path()

        if detalhes:
            return True, "ok", detalhes, list_screenshot_path
        list_screenshot_path = self._screenshot_consulta_os_return_path()
        return True, "no_results", [], list_screenshot_path

    _RE_PENDENCIA_CODIGO_PAP = re.compile(r"^\d{4}\s*-\s*.+", re.I)

    def _extrair_valor_rotulo_detalhe_pap(self, rotulo_exato: str) -> Optional[str]:
        """
        Lê o valor ao lado de um rótulo exato na tela de detalhe OS
        (ex.: rótulo <span>Pendência</span> → valor <span>7029 - AGENDAMENTO DO PEDIDO</span>).
        """
        try:
            label = self.page.get_by_text(rotulo_exato, exact=True).first
            if label.count() == 0:
                return None
            candidatos = []
            for loc in (
                label.locator("xpath=following-sibling::span[1]"),
                label.locator("xpath=../span[contains(@class,'fLfXPS')]"),
                label.locator("xpath=../following-sibling::span[1]"),
                label.locator("xpath=ancestor::*[1]//span[contains(@class,'fLfXPS')]"),
            ):
                try:
                    if loc.count() > 0:
                        t = (loc.first.inner_text() or "").strip()
                        if t and t.lower() != rotulo_exato.lower():
                            candidatos.append(t)
                except Exception:
                    pass
            for t in candidatos:
                if self._RE_PENDENCIA_CODIGO_PAP.match(t) or rotulo_exato != "Pendência":
                    return t
            return candidatos[0] if candidatos else None
        except Exception:
            return None

    def _buscar_pendencia_codigo_detalhe_pap(self) -> Optional[str]:
        """Busca texto de pendência com código (7029 - …), ignorando rótulos genéricos."""
        try:
            t_rotulo = self._extrair_valor_rotulo_detalhe_pap("Pendência")
            if t_rotulo and self._RE_PENDENCIA_CODIGO_PAP.match(t_rotulo.strip()):
                return t_rotulo.strip()
        except Exception:
            pass
        try:
            for s in self.page.locator("span.sc-gOhSNZ.fLfXPS, span.fLfXPS").all():
                t = (s.inner_text() or "").strip()
                if t and self._RE_PENDENCIA_CODIGO_PAP.match(t):
                    return t
        except Exception:
            pass
        try:
            for s in self.page.locator(
                "span.sc-jrOYZv.ldMRLh, span.ldMRLh, span.sc-gOhSNZ.fLfXPS"
            ).all():
                t = (s.inner_text() or "").strip()
                if t and self._RE_PENDENCIA_CODIGO_PAP.match(t):
                    return t
        except Exception:
            pass
        return None

    def abrir_detalhe_os_e_extrair(
        self, numero_os: str, detalhe_href: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
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
            link = None
            href = (detalhe_href or "").strip()
            if href:
                link = self.page.locator(f'a.detalhar-link[href="{href}"]').first
                if link.count() == 0:
                    link = self.page.locator(f'a[href="{href}"]').first
                if link.count() == 0:
                    frag = href.split("detalhe-os/")[-1].strip("/")
                    if frag:
                        link = self.page.locator(f'a.detalhar-link[href*="detalhe-os/{frag}"]').first
            if not link or link.count() == 0:
                link = self.page.locator(f'a.detalhar-link[href*="detalhe-os/{num}"]').first
            if link.count() == 0 and num_sem_zero != num:
                link = self.page.locator(f'a.detalhar-link[href*="detalhe-os/{num_sem_zero}"]').first
            if link.count() == 0:
                logger.warning("[PAP] Link Detalhar não encontrado para OS %s (href=%s)", num, href or "-")
                return None, None, None, None
            rapido = self.optimize_for_credit
            link.click(force=True, timeout=5000)
            if rapido:
                try:
                    self.page.wait_for_url(re.compile(r"detalhe-os", re.I), timeout=8000)
                except Exception:
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                self.page.wait_for_timeout(200)
            else:
                self.page.wait_for_timeout(1500)
                url_atual = self.page.url
                if "detalhe-os" not in (url_atual or ""):
                    self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            status_agendamento = None
            agendamento_texto = None
            pendencia_texto = None
            # Status agendamento
            try:
                loc_st = self.page.get_by_text("Status agendamento", exact=False).locator(
                    ".."
                ).locator(
                    "span.ldMRLh, span.sc-jrOYZv.ldMRLh, span.sc-gOhSNZ.fLfXPS"
                ).first
                if loc_st.count() > 0:
                    status_agendamento = (loc_st.inner_text() or "").strip()
            except Exception:
                pass
            # Agendamento (exact=True evita casar com o rótulo "Status agendamento")
            try:
                loc_ag = self.page.get_by_text("Agendamento", exact=True).locator(
                    ".."
                ).locator(
                    "span.ldMRLh, span.sc-jrOYZv.ldMRLh, span.sc-gOhSNZ.fLfXPS"
                ).first
                if loc_ag.count() > 0:
                    agendamento_texto = (loc_ag.inner_text() or "").strip()
            except Exception:
                pass
            # Pendência (ex.: "7029 - AGENDAMENTO DO PEDIDO") — rótulo exato, não "Pendência Cliente"
            pendencia_texto = self._buscar_pendencia_codigo_detalhe_pap()
            # Fallback: outros spans do detalhe
            if not status_agendamento or not agendamento_texto or not pendencia_texto:
                spans = self.page.locator(
                    'span.sc-jrOYZv.ldMRLh, span.ldMRLh, span.sc-gOhSNZ.fLfXPS'
                ).all()
                for s in spans:
                    t = (s.inner_text() or "").strip()
                    if not t:
                        continue
                    if re.match(r'\d{2}/\d{2}/\d{4}\s*-\s*(Tarde|Manhã)', t) and not agendamento_texto:
                        agendamento_texto = t
                    if ("concluído" in t.lower() or "sucesso" in t.lower()) and not status_agendamento:
                        status_agendamento = t
                    if self._RE_PENDENCIA_CODIGO_PAP.match(t) and not pendencia_texto:
                        pendencia_texto = t
            if pendencia_texto and not self._RE_PENDENCIA_CODIGO_PAP.match(pendencia_texto):
                codigo_ok = self._buscar_pendencia_codigo_detalhe_pap()
                if codigo_ok:
                    pendencia_texto = codigo_ok
            self.page.wait_for_timeout(150 if rapido else 300)
            detail_screenshot_path = self._screenshot_consulta_os_return_path()
            self.page.go_back()
            if rapido:
                self.page.wait_for_timeout(400)
                try:
                    self.page.wait_for_selector(
                        'td.MuiTableCell-root.MuiTableCell-body, table tbody tr',
                        state="visible",
                        timeout=5000,
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(150)
            else:
                self.page.wait_for_timeout(1000)
                try:
                    self.page.wait_for_selector(
                        'td.MuiTableCell-root.MuiTableCell-body, table tbody tr',
                        state="visible",
                        timeout=10000,
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(400)
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

            self._redirecionar_se_rota_bloqueia_novo_pedido()

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
                self._redirecionar_se_rota_bloqueia_novo_pedido()
                matricula_visivel = self._esperar_campo_matricula_vendedor(
                    8000 if modo_rapido_credito else 12000,
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
            # Modal OPS na consulta: clicar "Tentar novamente" e reenviar Buscar (até 2 tentativas)
            for _ops_tentativa in range(2):
                if not self.verificar_modal_erro_ops_visivel():
                    break
                if not self._fechar_modal_erro_ops():
                    return False, PAP_ERRO_PORTAL_NIO, None
                self.page.wait_for_timeout(800 if self.optimize_for_credit else 1200)
                btn_buscar_retry = self.page.query_selector('button:has-text("Buscar"):not([disabled])')
                if btn_buscar_retry and btn_buscar_retry.is_visible():
                    btn_buscar_retry.click()
                try:
                    self.page.wait_for_selector(
                        f'{end_inst_sel}, {ref_selector}, h2:has-text("OPS, OCORREU UM ERRO")',
                        state="visible",
                        timeout=15000,
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(250 if self.optimize_for_credit else 500)
            if self.verificar_modal_erro_ops_visivel():
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

    def etapa2_credito_selecionar_complemento_e_avancar(
        self, cep: str, numero: str, indice_complemento: int
    ) -> Tuple[bool, str, Optional[Any]]:
        """
        Fluxo CRÉDITO: quando o PAP lista complementos obrigatórios, o portal pode não aceitar
        apenas "Sem complemento". Seleciona um item da lista (1 = primeiro) e avança a viabilidade.
        """
        if indice_complemento < 1:
            return False, "Índice de complemento inválido (use 1, 2, 3…).", None
        ok, msg_sel = self.etapa2_selecionar_complemento(indice_complemento)
        if not ok:
            return False, msg_sel or "Falha ao selecionar complemento.", None
        return self.etapa2_clicar_avancar_apos_complemento(cep, numero)

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
            
            # Modal "OPS, OCORREU UM ERRO!" após consultar documento (portal instável → orientar chamado Nio)
            if self.verificar_modal_erro_ops_visivel():
                self._fechar_modal_erro_ops()
                return False, PAP_ERRO_PORTAL_NIO, None
            
            self._capture_screenshot("03_cpf_cliente_ok", wait_selector='button:has-text("Avançar"):not([disabled])', wait_timeout_ms=5000)
            # Extrair dados do cliente (nome, nome_mae mascarado, mês da data **/MM/**** para CRM)
            dados_cliente = {}
            nome_elem = self.page.query_selector(SELETORES['etapa3']['nome_cliente'])
            if nome_elem:
                dados_cliente['nome'] = (nome_elem.get_attribute('value') or nome_elem.inner_text() or '').strip()
            # Nome da mãe: campo oficial do portal é nomeMae (disabled, valor com asteriscos)
            mae_elem = self.page.query_selector('input[name="nomeMae"]') or self.page.query_selector(
                'input[name*="mae"]'
            ) or self.page.query_selector('input[id*="mae"]')
            if mae_elem:
                val = (mae_elem.get_attribute('value') or '').strip()
                if val:
                    dados_cliente['nome_mae'] = val
            # Data de nascimento: portal usa dataNascimento; máscara **/MM/**** — só o mês é confiável
            dt_elem = self.page.query_selector('input[name="dataNascimento"]') or self.page.query_selector(
                'input[name*="nascimento"]'
            ) or self.page.query_selector('input[id*="nascimento"]')
            if dt_elem:
                val = (dt_elem.get_attribute('value') or '').strip()
                if val:
                    match = re.search(r'/(\d{1,2})/', val)
                    if match:
                        try:
                            dados_cliente['mes_nascimento'] = int(match.group(1))
                        except ValueError:
                            pass
            
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
            Códigos/mensagens de erro comuns: TELEFONE_REJEITADO, EMAIL_REJEITADO, EMAIL_INVALIDO, CREDITO_NEGADO,
            MSG_CREDITO_SEM_TELA_RESULTADO (modal de resultado não exibido — repetir *CRÉDITO* com o documento).
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
            if parar_no_modal_credito and not modal_apareceu:
                neg_sem_modal = (
                    "crédito negado" in pagina_texto
                    or "credito negado" in pagina_texto
                    or ("negado" in pagina_texto and "aprovado" not in pagina_texto)
                )
                if not neg_sem_modal:
                    logger.warning(
                        "[PAP] [CRÉDITO] Etapa4: modal 'Resultado da análise de crédito' não apareceu; "
                        "não concluir como aprovado (etapa 5 ou texto isolado não bastam)."
                    )
                    return False, MSG_CREDITO_SEM_TELA_RESULTADO, None, None
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
            # Crédito aprovado (todas formas ou apenas cartão): exige modal visível no fluxo CRÉDITO
            if "crédito aprovado" in pagina_texto or "credito aprovado" in pagina_texto:
                if parar_no_modal_credito and not modal_apareceu:
                    logger.warning(
                        "[PAP] [CRÉDITO] Etapa4: texto de aprovado sem modal oficial; tratando como sem resultado."
                    )
                    return False, MSG_CREDITO_SEM_TELA_RESULTADO, None, None
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
            # Etapa 5 visível sem modal de resultado (fallback só para fluxo venda completa)
            etapa5_visivel = (
                'pagamento' in pagina_texto and 'ofertas' in pagina_texto
            ) or self.page.query_selector('input[value="BOLETO"], input[value="CREDITO"], input[value="DACC"]')
            if etapa5_visivel:
                if parar_no_modal_credito and not modal_apareceu:
                    logger.warning(
                        "[PAP] [CRÉDITO] Etapa4: etapa pagamento visível sem modal de resultado; não concluir como aprovado."
                    )
                    return False, MSG_CREDITO_SEM_TELA_RESULTADO, None, None
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
        timeout_ms = 35000
        self.page.wait_for_timeout(350)

        def _fechar_continuar_modal_credito():
            try:
                loc = self.page.locator('button:has-text("Continuar")').first
                if loc.is_visible(timeout=900):
                    loc.click(force=True, timeout=5000)
                    self.page.wait_for_timeout(500)
            except Exception:
                pass

        def _expandir_secao_forma_pagamento():
            for sel in (
                'span:has-text("Forma de pagamento")',
                'div:has-text("Forma de pagamento")',
                'button:has-text("Forma de pagamento")',
            ):
                try:
                    el = self.page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        self.page.wait_for_timeout(400)
                        return
                except Exception:
                    continue

        # Radios da forma de pagamento (value fixo no PAP); não exige name="radio-group" (UI muda).
        radio_js_fn = """() => {
            const vals = ['BOLETO','CREDITO','DACC'];
            for (const inp of document.querySelectorAll('input[type="radio"]')) {
                if (vals.includes(inp.value)) return true;
            }
            return false;
        }"""

        deadline = time.time() + (timeout_ms / 1000.0)
        last_err = None
        for _ in range(6):
            _fechar_continuar_modal_credito()
            _expandir_secao_forma_pagamento()
            remaining_ms = max(1500, int((deadline - time.time()) * 1000))
            try:
                self.page.wait_for_function(radio_js_fn, timeout=min(8000, remaining_ms))
                return
            except Exception as e:
                last_err = e
            try:
                self.page.keyboard.press("PageDown")
                self.page.wait_for_timeout(250)
                self.page.keyboard.press("End")
                self.page.wait_for_timeout(350)
            except Exception:
                pass
            if time.time() >= deadline:
                break

        try:
            self.page.wait_for_selector(
                'input[type="radio"][value="BOLETO"], input[type="radio"][value="CREDITO"], input[type="radio"][value="DACC"]',
                state="attached",
                timeout=max(2000, int((deadline - time.time()) * 1000)),
            )
            return
        except Exception as e:
            last_err = e

        _fechar_continuar_modal_credito()
        _expandir_secao_forma_pagamento()

        try:
            self.page.locator(
                'input[name="radio-group"][value="BOLETO"], input[name="radio-group"][value="CREDITO"], input[name="radio-group"][value="DACC"]'
            ).first.wait_for(state="attached", timeout=12000)
            return
        except Exception as e:
            last_err = e

        try:
            self.page.locator('input[name="radio-group"]').first.wait_for(state="attached", timeout=8000)
            return
        except Exception as e:
            last_err = e

        # Textos visíveis (acentos / capitalização diferentes no React)
        for pattern in (
            re.compile(r"Boleto"),
            re.compile(r"Cart[aã]o.*[Cc]r[eé]dito"),
            re.compile(r"D[eé]bito.*[Cc]onta"),
            re.compile(r"forma\s+de\s+pagamento", re.I),
        ):
            try:
                self.page.get_by_text(pattern).first.wait_for(state="visible", timeout=7000)
                return
            except Exception as e:
                last_err = e
                continue

        if last_err:
            raise last_err
        raise TimeoutError("_etapa5_garantir_pagina: sem indicadores de forma de pagamento")

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
            radio = self.page.query_selector(f'input[type="radio"][value="{valor}"]')
            if not radio:
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

    def etapa5_verificar_plano_selecionado_no_dom(self, plano: str) -> Tuple[bool, str]:
        """
        Confere no DOM da etapa 5 se o plano desejado está selecionado (sem clicar de novo).
        O PAP usa <li> com ícone SVG (MuiSvgIcon check em círculo) + texto "Velocidade X", sem radio nativo.
        Deve ser chamado logo após etapa5_selecionar_plano, antes de Fixo/Streaming.
        """
        pl = plano.lower().strip()
        if pl not in ("1giga", "700mega", "500mega"):
            return True, ""
        try:
            r = self.page.evaluate(
                """(planoKey) => {
                    const norm = (t) => (t || '').replace(/\\s+/g, ' ').trim();
                    const mapNeed = {
                        '1giga': '1 Giga',
                        '700mega': '700 Mega',
                        '500mega': '500 Mega',
                    };
                    const needShort = mapNeed[planoKey] || '500 Mega';
                    const needLine = 'Velocidade ' + needShort;

                    function matchSpeedLine(li) {
                        const t = norm(li.textContent);
                        if (!t.includes('Velocidade')) return false;
                        if (planoKey === '500mega') return /Velocidade\\s+500\\s+Mega/i.test(t);
                        if (planoKey === '700mega') return /Velocidade\\s+700\\s+Mega/i.test(t);
                        if (planoKey === '1giga') return /Velocidade\\s+1\\s*Giga/i.test(t);
                        return false;
                    }

                    function isCheckmarkSvg(li) {
                        const svg = li && li.querySelector('svg');
                        if (!svg) return false;
                        if (svg.classList && svg.classList.contains('MuiSvgIcon-root')) {
                            const paths = svg.querySelectorAll('path');
                            for (const p of paths) {
                                const d = (p.getAttribute('d') || '');
                                if (d.includes('M12 2C6.48')) return true;
                                if (d.includes('M9 16.17')) return true;
                                if (d.includes('M4.25 4.25')) return true;
                            }
                        }
                        const paths = svg.querySelectorAll('path');
                        for (const p of paths) {
                            const d = (p.getAttribute('d') || '');
                            if (d.length > 40 && (d.includes('M12 2C6') || d.includes('12 2C6.48'))) return true;
                        }
                        return false;
                    }

                    const lis = [...document.querySelectorAll('li')];
                    for (const li of lis) {
                        if (!matchSpeedLine(li)) continue;
                        if (isCheckmarkSvg(li)) return { ok: true, msg: '' };
                    }

                    for (const li of lis) {
                        if (!matchSpeedLine(li)) continue;
                        const svg = li.querySelector('svg');
                        if (svg && svg.querySelector('path[d*="M12 2C6"]')) return { ok: true, msg: '' };
                    }

                    for (const li of lis) {
                        if (!matchSpeedLine(li)) continue;
                        const inp = li.querySelector('input[type=radio], input[type=checkbox]');
                        if (inp && inp.checked) return { ok: true, msg: '' };
                    }

                    let outroComCheck = '';
                    for (const li of lis) {
                        const t = norm(li.textContent);
                        if (!/Velocidade\\s+(1\\s*Giga|700\\s*Mega|500\\s*Mega)/i.test(t)) continue;
                        if (!isCheckmarkSvg(li)) continue;
                        const m = t.match(/Velocidade\\s+(1\\s*Giga|700\\s*Mega|500\\s*Mega)/i);
                        outroComCheck = m ? m[0] : t.slice(0, 80);
                        break;
                    }
                    return {
                        ok: false,
                        msg: outroComCheck
                            ? ('Outra velocidade com ícone de confirmação: ' + outroComCheck
                                + ' (esperado: ' + needLine + ').')
                            : ('Não encontramos o <li> com texto "' + needLine + '" e SVG de check (ex.: path M12 2C6.48). '
                                + 'Confira no navegador se o card certo está selecionado.'),
                    };
                }""",
                pl,
            )
            if r and r.get("ok"):
                return True, ""
            return False, (r or {}).get("msg") or "Validação do plano falhou."
        except Exception as e:
            logger.warning("[PAP] etapa5_verificar_plano_selecionado_no_dom: %s", e)
            return False, str(e)

    def etapa5_selecionar_plano_com_validacao(self, plano: str) -> Tuple[bool, str]:
        """
        Seleciona o plano e valida no DOM antes de seguir para serviços adicionais.
        Repete a seleção uma vez se a validação falhar (sem resetar Fixo/Streaming — ainda não foram preenchidos).
        """
        ultimo_erro = ""
        for tentativa in range(2):
            ok, msg = self.etapa5_selecionar_plano(plano)
            if not ok:
                return False, msg
            self.page.wait_for_timeout(500)
            vok, vmsg = self.etapa5_verificar_plano_selecionado_no_dom(plano)
            if vok:
                return True, "OK"
            ultimo_erro = vmsg
            logger.warning(
                "[PAP] Plano não confirmado no DOM após seleção (tentativa %s/2): %s",
                tentativa + 1,
                vmsg,
            )
            if tentativa == 0:
                self.page.wait_for_timeout(400)
        return (
            False,
            (ultimo_erro or "Plano não confirmado no portal.")
            + " Ajuste manualmente a velocidade antes de continuar ou repita a etapa do plano.",
        )

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
        Usa vários seletores (texto, role, classes styled-components) e fallback via JS.
        Retorna True somente se o clique foi disparado; False se o modal não estava visível ou o botão não foi encontrado.
        """
        try:
            if not self.page:
                return False
            if not self.verificar_modal_erro_ops_visivel():
                return False
            clicked = False
            # 1) get_by_role (melhor para acessibilidade / texto variando)
            try:
                first = self.page.get_by_role("button", name=re.compile(r"tentar\s+novamente", re.I)).first
                if first.is_visible():
                    first.click(timeout=8000)
                    clicked = True
            except Exception as e_try:
                logger.debug("[PAP] _fechar_modal_erro_ops get_by_role: %s", e_try)
            # 2) Botão no mesmo bloco do h2 OPS (estrutura sc-gKLXLV / sc-* do PAP)
            if not clicked:
                try:
                    b = (
                        self.page.locator("div:has(h2:has-text('OPS'))")
                        .locator("button")
                        .filter(has_text=re.compile(r"tentar\s+novamente", re.I))
                        .first
                    )
                    if b.is_visible():
                        b.click(timeout=8000)
                        clicked = True
                except Exception as e_try:
                    logger.debug("[PAP] _fechar_modal_erro_ops escopo OPS: %s", e_try)
            # 3) :has-text clássico
            if not clicked:
                btn = self.page.query_selector('button:has-text("Tentar novamente")')
                if btn and btn.is_visible():
                    btn.click()
                    clicked = True
            # 4) Classe do botão (ex.: sc-hXhGGG eOQbpS no portal Nio)
            if not clicked:
                for sel in (
                    'button.sc-hXhGGG',
                    'button[class*="sc-hXhGGG"]',
                    'div.sc-gKLXLV button',
                    'div[class*="sc-gKLXLV"] button',
                ):
                    try:
                        cand = self.page.query_selector(sel)
                        if cand and cand.is_visible():
                            txt = (cand.inner_text() or "").strip().lower()
                            if "tentar" in txt and "novamente" in txt:
                                cand.click()
                                clicked = True
                                break
                    except Exception:
                        continue
            # 5) Fallback: qualquer button com o texto
            if not clicked:
                clicked = bool(
                    self.page.evaluate(
                        """
                        () => {
                          const btns = [...document.querySelectorAll('button')];
                          const b = btns.find(x => /tentar\\s*novamente/i.test((x.textContent || '').trim()));
                          if (b) { b.click(); return true; }
                          return false;
                        }
                        """
                    )
                )
            if clicked:
                self.page.wait_for_timeout(800 if not self.optimize_for_credit else 400)
                logger.warning("[PAP] Modal 'OPS, OCORREU UM ERRO!': clicado em 'Tentar novamente'.")
                return True
            logger.warning("[PAP] Modal OPS visível mas botão 'Tentar novamente' não encontrado.")
            return False
        except Exception as e:
            logger.warning("[PAP] _fechar_modal_erro_ops: %s", e)
            return False

    def _pap_detectar_texto_modal_visivel(self) -> str:
        """Texto agregado de diálogos/modais visíveis (MUI e genéricos)."""
        partes = []
        try:
            for sel in ('[role="dialog"]', '.MuiDialog-root', '[class*="Dialog"]'):
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    t = (el.inner_text() or "").strip()
                    if t and len(t) > 2:
                        partes.append(t[:1200])
        except Exception:
            pass
        return "\n".join(partes)

    def _pap_modal_erro_aparente(self, texto: str) -> bool:
        if not texto:
            return False
        low = texto.lower()
        if "nenhum erro" in low or "sem erro" in low or "0 erro" in low:
            return False
        markers = (
            "error",
            "erro",
            "falha",
            "não foi possível",
            "nao foi possivel",
            "tente novamente",
            "ops,",
            "ocorreu um erro",
        )
        return any(m in low for m in markers)

    def _pap_fechar_dialogos_erro_conhecidos(self) -> Tuple[bool, str]:
        """
        Fecha modais de erro genéricos (título/corpo com error, erro, falha).
        Retorna (fechou_algum, trecho_do_texto_visto).
        """
        texto_antes = self._pap_detectar_texto_modal_visivel()
        fechou = False
        try:
            for btn_txt in (
                "OK",
                "Ok",
                "Entendi",
                "Fechar",
                "Fechar dialog",
                "Tentar novamente",
                "Continuar",
            ):
                btn = self.page.query_selector(
                    f'[role="dialog"] button:has-text("{btn_txt}"), '
                    f'.MuiDialog-root button:has-text("{btn_txt}")'
                )
                if btn and btn.is_visible():
                    btn.click()
                    self.page.wait_for_timeout(500)
                    fechou = True
                    break
            if not fechou:
                xbtn = self.page.query_selector(
                    '[role="dialog"] button[aria-label="Close"], '
                    '.MuiDialog-root button[aria-label="Close"]'
                )
                if xbtn and xbtn.is_visible():
                    xbtn.click()
                    self.page.wait_for_timeout(500)
                    fechou = True
        except Exception as e:
            logger.debug("[PAP] _pap_fechar_dialogos_erro_conhecidos: %s", e)
        return fechou, (texto_antes or "")[:400]

    def _pap_modal_titulo_ocorreu_erro_visivel(self) -> bool:
        """True se h2/h3 'Ocorreu um erro' estiver visível (portal Nio usa h2 em vários builds)."""
        try:
            if not self.page:
                return False
            for sel in (
                'h2:has-text("Ocorreu um erro")',
                'h3:has-text("Ocorreu um erro")',
            ):
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    return True
            return "Ocorreu um erro" in (self.page.content() or "")
        except Exception:
            return False

    def _pap_extrair_texto_modal_proximo_a_titulo_erro(self) -> str:
        """Texto do bloco do modal (para decidir se é erro ao abrir pedido/OS)."""
        try:
            for sel in ('h2:has-text("Ocorreu um erro")', 'h3:has-text("Ocorreu um erro")'):
                el = self.page.query_selector(sel)
                if not el or not el.is_visible():
                    continue
                try:
                    root = el.evaluate(
                        """e => {
                          let n = e;
                          for (let i = 0; i < 12 && n; i++) {
                            if (n.getAttribute && n.getAttribute('role') === 'dialog') return n.innerText || '';
                            const cls = (n.className && String(n.className)) || '';
                            if (cls.includes('modal') || cls.includes('Modal') || cls.includes('sc-')) {
                              const t = (n.innerText || '').trim();
                              if (t.length > 20 && t.length < 4000) return t;
                            }
                            n = n.parentElement;
                          }
                          return (e.closest('div') || e).innerText || '';
                        }"""
                    )
                    if root and len(str(root).strip()) > 5:
                        return str(root).strip()[:2000]
                except Exception:
                    pass
                try:
                    return (el.evaluate("e => (e.closest('div') || e).innerText || ''") or "")[:2000]
                except Exception:
                    return (el.inner_text() or "")[:800]
        except Exception:
            pass
        return ""

    def _pap_fechar_modal_ocorreu_erro_h3_ok(self) -> bool:
        """
        Fecha modal 'Ocorreu um erro' (h2 ou h3) clicando em Ok.
        O PAP costuma usar styled-components (ex.: div.sc-*) sem role=\"dialog\" — por isso vários fallbacks.
        """
        try:
            if not self.page:
                return False
            if not self._pap_modal_titulo_ocorreu_erro_visivel():
                return False
            clicked = False
            try:
                box = self.page.locator(
                    "div:has(h2:has-text('Ocorreu um erro')), div:has(h3:has-text('Ocorreu um erro'))"
                ).first
                if box.is_visible():
                    for label in ("Ok", "OK"):
                        try:
                            b = box.locator(f"button:has-text('{label}')").first
                            if b.is_visible():
                                b.click(timeout=5000)
                                clicked = True
                                break
                        except Exception:
                            continue
            except Exception as e_try:
                logger.debug("[PAP] fechar modal ocorreu erro (box): %s", e_try)
            if not clicked:
                for sel in (
                    '[role="dialog"] button:has-text("Ok")',
                    '[role="dialog"] button:has-text("OK")',
                    '.MuiDialog-root button:has-text("Ok")',
                    'button:has-text("Ok")',
                    'button:has-text("OK")',
                ):
                    try:
                        btn = self.page.query_selector(sel)
                        if btn and btn.is_visible():
                            btn.click()
                            clicked = True
                            break
                    except Exception:
                        continue
            if not clicked:
                clicked = bool(
                    self.page.evaluate(
                        """
                        () => {
                          const heads = [...document.querySelectorAll('h2, h3')];
                          const h = heads.find(el => /ocorreu\\s+um\\s+erro/i.test((el.textContent || '').trim()));
                          if (!h) return false;
                          let root = h.closest('[role="dialog"]') || h.parentElement;
                          for (let depth = 0; depth < 14 && root; depth++) {
                            const btns = [...root.querySelectorAll('button')];
                            const okb = btns.find(b => /^ok$/i.test((b.textContent || '').trim()));
                            if (okb && okb.offsetParent !== null) { okb.click(); return true; }
                            root = root.parentElement;
                          }
                          const vis = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
                          const greenOk = vis.find(b => /^ok$/i.test((b.textContent || '').trim()));
                          if (greenOk) { greenOk.click(); return true; }
                          return false;
                        }
                        """
                    )
                )
            if clicked:
                self.page.wait_for_timeout(600)
                logger.warning("[PAP] Modal 'Ocorreu um erro' fechado (Ok).")
                return True
            self._pap_fechar_dialogos_erro_conhecidos()
            return False
        except Exception as e:
            logger.debug("[PAP] _pap_fechar_modal_ocorreu_erro_h3_ok: %s", e)
            return False

    def detectar_tela_etapa1_identificacao_pdv(self) -> bool:
        """True se o fluxo voltou à identificação PDV (Etapa 1 / matrícula vendedor)."""
        try:
            if not self.page:
                return False
            span = self.page.locator('span:has-text("Etapa 1")').first
            if not span.is_visible():
                return False
            mi = self._query_matricula_vendedor_input()
            return bool(mi and mi.is_visible())
        except Exception:
            return False

    def _pap_merge_dados_sessao_para_replay(self, dados_sessao: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Une dados da sessão WhatsApp com dados_pedido já preenchidos na automação (replay após reset)."""
        out: Dict[str, Any] = {}
        try:
            out.update(self.dados_pedido or {})
        except Exception:
            pass
        if dados_sessao:
            out.update(dados_sessao)
        return out

    def _pap_replay_viabilidade_com_dados(self, d: Dict[str, Any]) -> Tuple[bool, str, Any]:
        """
        Refaz consulta de viabilidade e ramificações (múltiplos endereços / complementos) usando dados salvos.
        Retorno extra: None=disponível e Continuar aplicado; dict MULTIPLOS/COMPLEMENTOS=parado na escolha;
        POSSE_ENCONTRADA / INDISPONIVEL_TECNICO = erro.
        """
        cep = (d.get("cep") or "").strip()
        numero = d.get("numero", "")
        ref = (d.get("referencia") or "").strip()
        if not cep or numero is None or numero == "" or not ref:
            return False, "Dados de endereço incompletos para recuperação automática.", None
        numero_s = str(numero).strip()
        sucesso, msg, extra = self.etapa2_viabilidade(cep, numero_s, ref)
        if isinstance(extra, dict) and extra.get("_codigo") == "MULTIPLOS_ENDERECOS":
            idx = d.get("pap_replay_endereco_idx")
            if idx is None or str(idx).strip() == "":
                return True, "", extra
            try:
                idx_i = int(idx)
            except (TypeError, ValueError):
                return False, "Índice de endereço salvo inválido para replay.", None
            ok_sel, msg_sel = self.etapa2_selecionar_endereco_instalacao(idx_i)
            if not ok_sel:
                return False, msg_sel or "Replay endereço", None
            sucesso2, msg2, extra2 = self.etapa2_preencher_referencia_e_continuar(cep, numero_s, ref)
            return self._pap_replay_resolve_pos_referencia(cep, numero_s, ref, sucesso2, msg2, extra2, d)
        if isinstance(extra, dict) and extra.get("_codigo") == "COMPLEMENTOS":
            return self._pap_replay_complemento_ou_avancar(cep, numero_s, ref, d, extra)
        if extra in ("POSSE_ENCONTRADA", "INDISPONIVEL_TECNICO"):
            return False, msg, extra
        if sucesso:
            return True, msg or "", None
        if msg == PAP_ERRO_PORTAL_NIO:
            return False, msg, None
        return False, msg or "Viabilidade", None

    def _pap_replay_resolve_pos_referencia(
        self,
        cep: str,
        numero_s: str,
        ref: str,
        sucesso2: bool,
        msg2: str,
        extra2: Any,
        d: Dict[str, Any],
    ) -> Tuple[bool, str, Any]:
        if isinstance(extra2, dict) and extra2.get("_codigo") == "COMPLEMENTOS":
            return self._pap_replay_complemento_ou_avancar(cep, numero_s, ref, d, extra2)
        if extra2 in ("POSSE_ENCONTRADA", "INDISPONIVEL_TECNICO"):
            return False, msg2, extra2
        if sucesso2:
            return True, msg2 or "", None
        if msg2 == PAP_ERRO_PORTAL_NIO:
            return False, msg2, None
        return False, msg2 or "Referência/viabilidade", None

    def _pap_replay_complemento_ou_avancar(
        self, cep: str, numero_s: str, ref: str, d: Dict[str, Any], extra_comp: dict
    ) -> Tuple[bool, str, Any]:
        esc = (d.get("pap_replay_complemento_escolha") or "").strip()
        if not esc:
            return True, "", extra_comp
        esc_up = esc.upper()
        if esc_up in ("0", "SEM", "SEM COMPLEMENTO", "NAO", "NÃO", "N"):
            ok_c, msg_c = self.etapa2_selecionar_sem_complemento()
        elif esc.isdigit():
            ok_c, msg_c = self.etapa2_selecionar_complemento(int(esc))
        else:
            return False, "Complemento salvo inválido para replay.", None
        if not ok_c:
            return False, msg_c or "Replay complemento", None
        sucesso3, msg3, extra3 = self.etapa2_clicar_avancar_apos_complemento(cep, numero_s)
        if extra3 in ("POSSE_ENCONTRADA", "INDISPONIVEL_TECNICO"):
            return False, msg3, extra3
        if sucesso3:
            return True, msg3 or "", None
        if msg3 == PAP_ERRO_PORTAL_NIO:
            return False, msg3, None
        return False, msg3 or "Avançar pós-complemento", None

    def _pap_replay_target_sn_para_etapa(self, etapa_whatsapp: str) -> int:
        if not etapa_whatsapp:
            return 0
        if etapa_whatsapp in WPP_ETAPA_REPLAY_TARGET_SN:
            return WPP_ETAPA_REPLAY_TARGET_SN[etapa_whatsapp]
        if etapa_whatsapp.startswith("venda_") and etapa_whatsapp not in (
            "venda_erro_retry",
            "venda_aguardando_pap",
            "venda_confirmar_matricula",
        ):
            return 9
        return 0

    def _pap_executar_replay_ate_target_sn(
        self, d: Dict[str, Any], matricula_vendedor: str, target_sn: int
    ) -> Tuple[bool, str]:
        """Executa subpassos 0..target_sn para alinhar o PAP com a sessão WhatsApp."""
        if target_sn < 0:
            return True, ""
        ok, msg = self.iniciar_novo_pedido(matricula_vendedor)
        if not ok:
            return False, msg
        if target_sn < 1:
            return True, ""
        v_ok, v_msg, v_extra = self._pap_replay_viabilidade_com_dados(d)
        if not v_ok:
            return False, v_msg or "Replay viabilidade"
        if isinstance(v_extra, dict) and v_extra.get("_codigo") in ("MULTIPLOS_ENDERECOS", "COMPLEMENTOS"):
            if target_sn <= 1:
                return True, ""
            return False, "Faltam pap_replay_endereco_idx ou pap_replay_complemento_escolha para concluir o replay."
        if target_sn < 2:
            return True, ""
        cpf = re.sub(r"\D", "", (d.get("cpf_cliente") or ""))
        if len(cpf) < 11:
            return False, "CPF do cliente ausente nos dados salvos."
        ok3, msg3, _ = self.etapa3_cadastro_cliente(cpf)
        if not ok3:
            return False, msg3 or "Replay etapa 3"
        if target_sn < 3:
            return True, ""
        cel = re.sub(r"\D", "", (d.get("celular") or ""))
        email = (d.get("email") or "").strip()
        if not cel or not email:
            return False, "Celular ou e-mail ausente nos dados salvos."
        cel_sec = d.get("celular_sec") or None
        if cel_sec:
            cel_sec = re.sub(r"\D", "", str(cel_sec)) or None
        ok4, msg4, _, _ = self.etapa4_contato(cel, email, celular_secundario=cel_sec, parar_no_modal_credito=False)
        if not ok4:
            if msg4 == PAP_ERRO_PORTAL_NIO:
                return False, msg4
            return False, msg4 or "Replay contato"
        if target_sn < 4:
            return True, ""
        forma = (d.get("forma_pagamento") or "").strip().lower()
        if forma not in ("boleto", "cartao", "debito"):
            return False, "Forma de pagamento ausente ou inválida nos dados salvos."
        okf, msgf = self.etapa5_selecionar_forma_pagamento(forma)
        if not okf:
            return False, msgf or "Replay forma pagamento"
        if target_sn < 5:
            return True, ""
        if forma == "debito":
            banco = (d.get("banco") or d.get("banco_dacc") or "").strip()
            agencia = (d.get("agencia") or d.get("agencia_dacc") or "").strip()
            conta = (d.get("conta") or d.get("conta_dacc") or "").strip()
            digito = (d.get("digito") or d.get("digito_dacc") or "").strip()
            if not (banco and agencia and conta and digito):
                return False, "Dados de débito em conta incompletos nos dados salvos."
            okd, msgd = self.etapa5_preencher_debito(banco, agencia, conta, digito)
            if not okd:
                return False, msgd or "Replay débito"
        if target_sn < 6:
            return True, ""
        plano = (d.get("plano") or "").strip().lower()
        if plano not in ("1giga", "700mega", "500mega"):
            return False, "Plano ausente nos dados salvos."
        okp, msgp = self.etapa5_selecionar_plano_com_validacao(plano)
        if not okp:
            return False, msgp or "Replay plano"
        if target_sn < 7:
            return True, ""
        tem_fixo = bool(d.get("tem_fixo"))
        okfx, msgfx = self.etapa5_selecionar_fixo(tem_fixo)
        if not okfx:
            return False, msgfx or "Replay fixo"
        if target_sn < 8:
            return True, ""
        if tem_fixo:
            quer = bool(d.get("fixo_portabilidade"))
            num_p = (d.get("fixo_portabilidade_numero") or "").strip()
            op_p = (d.get("fixo_portabilidade_operadora") or "").strip()
            okpb, msgpb = self.etapa5_fixo_finalizar_portabilidade(quer, num_p, op_p)
            if not okpb:
                return False, msgpb or "Replay portabilidade fixo"
        if target_sn < 9:
            return True, ""
        tem_st = bool(d.get("tem_streaming"))
        sop = (d.get("streaming_opcoes") or "").strip()
        oks, msgs = self.etapa5_selecionar_streaming(tem_st, sop, plano)
        if not oks:
            return False, msgs or "Replay streaming"
        oka, msga = self.etapa5_clicar_avancar()
        if not oka:
            return False, msga or "Replay avançar pós-ofertas"
        return True, ""

    def tentar_recuperar_portal_reset_etapa1(
        self,
        dados_sessao: Optional[Dict[str, Any]],
        matricula_vendedor: str,
        etapa_whatsapp: str,
    ) -> Tuple[bool, str]:
        """
        Detecta modal 'Ocorreu um erro' e/ou retorno à Etapa 1 e reaplica o fluxo com dados salvos.
        Retorna (True, "") se não havia reset ou a recuperação foi ok; (False, msg) em falha.
        """
        if not self.page or not matricula_vendedor:
            return True, ""
        try:
            self._pap_fechar_modal_ocorreu_erro_h3_ok()
            self._fechar_modal_erro_ops()
            if self._pap_modal_erro_aparente(self._pap_detectar_texto_modal_visivel()):
                self._pap_fechar_dialogos_erro_conhecidos()
                self.page.wait_for_timeout(400)
        except Exception as e:
            logger.debug("[PAP] tentar_recuperar: fechar modais: %s", e)
        if not self.detectar_tela_etapa1_identificacao_pdv():
            return True, ""
        if not etapa_whatsapp or etapa_whatsapp in (
            "inicial",
            "venda_aguardando_pap",
            "venda_confirmar_matricula",
            "venda_erro_retry",
        ):
            return True, ""
        d = self._pap_merge_dados_sessao_para_replay(dados_sessao)
        target = self._pap_replay_target_sn_para_etapa(etapa_whatsapp)
        logger.warning(
            "[PAP] Reset para Etapa 1 detectado — reaplicando fluxo até sn=%s (etapa_wpp=%s).",
            target,
            etapa_whatsapp,
        )
        ok, msg = self._pap_executar_replay_ate_target_sn(d, matricula_vendedor, target)
        if ok:
            return True, ""
        return False, msg or "Falha ao reaplicar dados após reset do portal."

    def _pap_tratar_modais_apos_acao_pap(self) -> Tuple[bool, str]:
        """
        Após cliques (Consultar Biometria, Abrir OS): OPS do portal + diálogos com 'error'/erro.
        Trata também o modal h2/h3 'Ocorreu um erro' (sem role=dialog), comum após Abrir OS falhar.
        Retorna (pode_continuar, mensagem_erro_ou_vazia). Se pode_continuar False, houve erro explícito.
        """
        try:
            self._fechar_modal_erro_ops()
            self.page.wait_for_timeout(400)
            if self._pap_modal_titulo_ocorreu_erro_visivel():
                trecho_modal = self._pap_extrair_texto_modal_proximo_a_titulo_erro()
                self._pap_fechar_modal_ocorreu_erro_h3_ok()
                self.page.wait_for_timeout(400)
                low = (trecho_modal or "").lower()
                if (
                    "não foi possível abrir o pedido" in low
                    or "nao foi possivel abrir o pedido" in low
                    or "abrir o pedido" in low
                ):
                    return (
                        False,
                        "O portal não conseguiu abrir o pedido/OS. "
                        "A mensagem pede para tentar mais tarde; em geral o fluxo volta à Etapa 1. "
                        "Abra chamado na Nio se necessário ou inicie nova venda.",
                    )
                return False, (trecho_modal.strip()[:500] if trecho_modal else "O portal exibiu 'Ocorreu um erro'.")
            txt = self._pap_detectar_texto_modal_visivel()
            if self._pap_modal_erro_aparente(txt):
                self._pap_fechar_dialogos_erro_conhecidos()
                logger.warning("[PAP] Modal de erro detectado após ação: %s", txt[:200])
                return False, txt.strip()[:500]
            return True, ""
        except Exception as e:
            logger.debug("[PAP] _pap_tratar_modais_apos_acao_pap: %s", e)
            return True, ""

    def pap_inspecionar_contexto_etapa(self) -> Dict[str, Any]:
        """
        Indica onde o fluxo parece estar (para recuperação e logs após timeout/erro).
        """
        out: Dict[str, Any] = {
            "url": "",
            "provavel": "desconhecido",
            "tem_abrir_os": False,
            "tem_consultar_biometria": False,
            "tem_periodo_agendamento": False,
            "trecho_modal": "",
        }
        try:
            out["url"] = self.page.url or ""
            u = out["url"].lower()
            if "novo-pedido" in u and "administrativo" in u:
                out["provavel"] = "fluxo_pedido"
            btn_os = self.page.query_selector(
                'button:has-text("Abrir OS"):not([disabled]), button:has-text("Abrir O.S"):not([disabled])'
            )
            out["tem_abrir_os"] = bool(btn_os and btn_os.is_visible())
            btn_cb = self.page.query_selector('button:has-text("Consultar Biometria")')
            out["tem_consultar_biometria"] = bool(btn_cb and btn_cb.is_visible())
            per = self.page.query_selector(
                'h3:has-text("Período"), [class*="react-datepicker"], h2:has-text("Agendamento"), h3:has-text("Agendamento")'
            )
            out["tem_periodo_agendamento"] = bool(per and per.is_visible())
            out["trecho_modal"] = self._pap_detectar_texto_modal_visivel()[:300]
            if out["tem_periodo_agendamento"]:
                out["provavel"] = "agendamento"
            elif out["tem_abrir_os"] or out["tem_consultar_biometria"]:
                out["provavel"] = "resumo_biometria"
        except Exception as e:
            logger.debug("[PAP] pap_inspecionar_contexto_etapa: %s", e)
        return out

    def _etapa5_bloquear_backdrop_drawer_mui(self) -> None:
        """
        O PAP usa drawer/modal MUI: clique na área escura (backdrop) fecha o painel e
        interrompe o fluxo antes do Salvar. Desabilita pointer-events no backdrop.
        """
        try:
            self.page.evaluate(
                """
                () => {
                  document.querySelectorAll(
                    '.MuiBackdrop-root, .MuiModal-backdrop, [class*="MuiBackdrop-root"]'
                  ).forEach((el) => {
                    if (el instanceof HTMLElement) {
                      if (el.dataset.papBackdropPe === undefined) {
                        el.dataset.papBackdropPe = el.style.pointerEvents || '';
                      }
                      el.style.pointerEvents = 'none';
                    }
                  });
                }
                """
            )
        except Exception as ex:
            logger.debug("[PAP] _etapa5_bloquear_backdrop_drawer_mui: %s", ex)

    def _etapa5_restaurar_backdrop_drawer_mui(self) -> None:
        """Restaura o backdrop após concluir o painel (opcional; ao fechar o drawer o nó some)."""
        try:
            self.page.evaluate(
                """
                () => {
                  document.querySelectorAll(
                    '.MuiBackdrop-root, .MuiModal-backdrop, [class*="MuiBackdrop-root"]'
                  ).forEach((el) => {
                    if (!(el instanceof HTMLElement)) return;
                    const prev = el.dataset.papBackdropPe;
                    if (prev !== undefined) {
                      el.style.pointerEvents = prev;
                      delete el.dataset.papBackdropPe;
                    }
                  });
                }
                """
            )
        except Exception:
            pass

    def _etapa5_drawer_titulo_servicos_visivel(self) -> bool:
        """True se o painel lateral de serviços adicionais está aberto (título visível)."""
        try:
            t = self.page.get_by_text("Escolher serviços adicionais", exact=False).first
            return t.is_visible()
        except Exception:
            return False

    def _etapa5_ui_fixo_portabilidade_visivel(self) -> bool:
        """True se já dá para preencher portabilidade ou clicar Salvar no fluxo Fixo."""
        try:
            if self.page.locator("#contatoPortabilidade").count() > 0:
                if self.page.locator("#contatoPortabilidade").first.is_visible():
                    return True
            if self.page.locator('select[name="operadora"]').count() > 0:
                if self.page.locator('select[name="operadora"]').first.is_visible():
                    return True
            if self.page.locator('label:has-text("Cliente deseja fazer portabilidade")').count() > 0:
                if self.page.locator('label:has-text("Cliente deseja fazer portabilidade")').first.is_visible():
                    return True
            loc = self.page.locator("button.sc-guDjWT.gIsNuI").filter(has_text="Salvar")
            if loc.count() > 0 and loc.first.is_visible():
                return True
            loc2 = self.page.get_by_role("button", name=re.compile(r"^\s*Salvar\s*$", re.I))
            if loc2.count() > 0:
                for i in range(loc2.count()):
                    b = loc2.nth(i)
                    if b.is_visible() and (b.inner_text() or "").strip() == "Salvar":
                        return True
        except Exception:
            pass
        return False

    def _etapa5_fixo_servico_marcado_no_drawer(self) -> bool:
        """True se o add-on Fixo já foi selecionado (checkbox / aria-checked no card)."""
        try:
            try:
                ac = self.page.locator('div:has-text("Fixo") [aria-checked="true"]')
                if ac.count() > 0 and ac.first.is_visible():
                    return True
            except Exception:
                pass
            for sel in (
                'div:has-text("Fixo") input[type="checkbox"]',
                'div:has-text("Faça ligações") input[type="checkbox"]',
            ):
                inp = self.page.locator(sel).first
                if inp.count() == 0:
                    continue
                try:
                    if inp.is_checked():
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _etapa5_drawer_fixo_pronto(self) -> bool:
        """Portabilidade/Salvar visível OU Fixo já marcado (o site só mostra a próxima etapa depois)."""
        return self._etapa5_ui_fixo_portabilidade_visivel() or self._etapa5_fixo_servico_marcado_no_drawer()

    def _etapa5_scroll_painel_lateral_ate_rodape(self) -> None:
        """Garante scroll até o rodapé do drawer (Salvar fica embaixo)."""
        try:
            self.page.evaluate(
                """
                () => {
                  const salvarBtn = [...document.querySelectorAll('button.sc-guDjWT.gIsNuI')].find(
                    b => (b.textContent || '').trim() === 'Salvar'
                  ) || [...document.querySelectorAll('button')].find(
                    b => (b.textContent || '').trim() === 'Salvar'
                  );
                  const alvo =
                    salvarBtn ||
                    document.querySelector('#contatoPortabilidade') ||
                    document.querySelector('select[name="operadora"]');
                  if (!alvo) return;
                  let p = alvo;
                  for (let i = 0; i < 22 && p; i++) {
                    const st = window.getComputedStyle(p);
                    if (p.scrollHeight > p.clientHeight + 2 || /auto|scroll/.test(st.overflowY || '')) {
                      try { p.scrollTop = p.scrollHeight; } catch (e) {}
                    }
                    p = p.parentElement;
                  }
                }
                """
            )
            self.page.wait_for_timeout(200)
        except Exception:
            pass

    def _etapa5_drawer_streaming_titulo_visivel(self) -> bool:
        try:
            t = self.page.get_by_text("Escolher plataformas", exact=False).first
            return t.is_visible()
        except Exception:
            return False

    def _etapa5_locator_drawer_streaming(self):
        """Container do drawer lateral de streaming (título Escolher plataformas…)."""
        try:
            for sel in (
                'aside:has-text("Escolher plataformas")',
                'div:has-text("Escolher plataformas de streaming")',
            ):
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    c = loc.first
                    if c.is_visible():
                        return c
        except Exception:
            pass
        return None

    def _etapa5_scroll_drawer_streaming_ate_salvar(self) -> None:
        """Scroll no drawer de streaming: cards + botão Salvar ficam em áreas roláveis separadas."""
        try:
            self.page.evaluate(
                """
                () => {
                  const titulo = [...document.querySelectorAll('div, aside, header, section')].find(
                    el => (el.textContent || '').includes('Escolher plataformas')
                  );
                  let n = titulo;
                  for (let i = 0; i < 24 && n; i++) {
                    if (n.scrollHeight > n.clientHeight + 2) {
                      try { n.scrollTop = n.scrollHeight; } catch (e) {}
                    }
                    n = n.parentElement;
                  }
                  document.querySelectorAll(
                    '.MuiDrawer-paper, aside, [class*="Drawer-paper"], [class*="sc-kqEXUp"]'
                  ).forEach(el => {
                    try { el.scrollTop = el.scrollHeight; } catch (e) {}
                  });
                  const b = [...document.querySelectorAll('button.sc-guDjWT.gIsNuI')].find(
                    x => (x.textContent || '').trim() === 'Salvar' &&
                      (x.closest('aside') || x.closest('[class*="Drawer"]') || x.closest('div'))
                  );
                  if (b) {
                    try { b.scrollIntoView({ block: 'end', inline: 'nearest' }); } catch (e) {}
                  }
                }
                """
            )
            self.page.wait_for_timeout(280)
        except Exception:
            pass

    def _etapa5_streaming_map_opcao_para_preco(self, o: str, skip_padrao: bool) -> Optional[str]:
        o = (o or "").lower()
        if "hbomax" in o or o == "hbo":
            return "44,90"
        if "globoplay_premium" in o or (
            "premium" in o and "basico" not in o and "padrao" not in o and "padrão" not in o
        ):
            return "39,90"
        if ("globoplay_basico" in o or "basico" in o or "padrão" in o or "padrao" in o) and not skip_padrao:
            return "22,90"
        return None

    def _etapa5_clicar_preco_streaming(self, preco: str) -> bool:
        """Clica no preço (div.sc-hQfrgq.frojRS) correspondente, ex.: R$ 44,90."""
        dr = self._etapa5_locator_drawer_streaming()
        roots = []
        if dr is not None:
            roots.append(dr)
        roots.append(self.page.locator("body"))
        for root in roots:
            for sel in (
                f'div.sc-hQfrgq.frojRS:has-text("{preco}")',
                f'div.frojRS:has-text("{preco}")',
                f'div:has-text("R$ {preco}")',
            ):
                try:
                    el = root.locator(sel).first
                    if el.is_visible():
                        el.scroll_into_view_if_needed()
                        el.click(timeout=8000)
                        self.page.wait_for_timeout(400)
                        return True
                except Exception:
                    continue
        try:
            ok = self.page.evaluate(
                """(preco) => {
                  const nodes = [...document.querySelectorAll('div.sc-hQfrgq.frojRS, div.frojRS')];
                  const el = nodes.find(n => (n.innerText || '').includes(preco));
                  if (!el) return false;
                  el.click();
                  return true;
                }""",
                preco,
            )
            self.page.wait_for_timeout(400)
            return bool(ok)
        except Exception:
            return False

    def _etapa5_streaming_preco_parece_selecionado(self, preco: str) -> bool:
        """Verifica input/aria-checked/Mui-checked na linha do card que contém o preço."""
        try:
            return bool(
                self.page.evaluate(
                    """(preco) => {
                  const nodes = [...document.querySelectorAll('div.sc-hQfrgq.frojRS, div.frojRS')];
                  const priceEl = nodes.find(n => (n.innerText || '').includes(preco));
                  if (!priceEl) return false;
                  let card = priceEl;
                  for (let i = 0; i < 16 && card; i++) {
                    const inp = card.querySelector(
                      'input[type="checkbox"]:checked, input[type="radio"]:checked'
                    );
                    if (inp) return true;
                    const ac = card.querySelector('[aria-checked="true"]');
                    if (ac) return true;
                    if (card.querySelector('.Mui-checked, [class*="Mui-checked"], [class*="MuiSwitch"]')) {
                      return true;
                    }
                    card = card.parentElement;
                  }
                  return false;
                }""",
                    preco,
                )
            )
        except Exception:
            return False

    def _etapa5_clicar_servicos_disponiveis(self) -> bool:
        """Abre o drawer clicando apenas no botão 'Serviços disponíveis'."""
        try:
            loc_btn = self.page.get_by_role(
                "button", name=re.compile(r"Serviços\s*disponíveis", re.I)
            )
            if loc_btn.count() > 0:
                b0 = loc_btn.first
                if b0.is_visible():
                    b0.scroll_into_view_if_needed()
                    b0.click(timeout=8000)
                    return True
            el = self.page.query_selector(SELETORES["etapa5"]["btn_servicos"])
            if not el:
                el = self.page.query_selector('button.sc-izfUZz:has-text("Serviços disponíveis")')
            if not el:
                el = self.page.query_selector('button.fVoKDo:has-text("Serviços disponíveis")')
            if not el or not el.is_visible():
                return False
            el.scroll_into_view_if_needed()
            el.click()
            return True
        except Exception:
            return False

    def _etapa5_clicar_opcao_fixo_no_drawer(self) -> bool:
        """
        Marca o serviço Fixo. No PAP atual: preço R$ 30,00 em div.sc-hQfrgq.frojRS ou checkbox/img no card.
        """
        drawer = self._etapa5_locator_drawer_paper_visivel()
        scopes = []
        if drawer is not None:
            scopes.append(drawer)
        scopes.append(self.page.locator("body"))

        for scope in scopes:
            for sel in [
                "div.sc-hQfrgq.frojRS",
                'div.frojRS:has-text("30,00")',
                'div:has-text("R$ 30,00")',
                'div:has-text("Fixo") input[type="checkbox"]',
                'div:has-text("Faça ligações") input[type="checkbox"]',
                'div:has-text("Fixo") img[src^="data:image/png"]',
                'div:has-text("Fixo") img[src^="data:image"]',
                'div:has-text("Fixo"):has-text("30,00") img',
                'div:has-text("Fixo"):has-text("R$ 30") img',
                'div:has-text("Fixo") img',
                'div.sc-kUQWMX.bwZXDo:has-text("Fixo") img',
                'div.bwZXDo:has-text("Fixo") img',
                'div:has-text("Fixo"):has-text("Faça ligações") img',
                'div.sc-kUQWMX.bwZXDo:has-text("Fixo")',
                'div.bwZXDo:has-text("Fixo")',
                'div.sc-dcmekm.dBGnOE:has-text("Fixo")',
                SELETORES["etapa5"]["card_fixo"],
                'div:has-text("Fixo"):has-text("Faça ligações")',
                'div:has-text("Fixo"):has-text("R$ 30,00")',
                'div:has-text("Fixo"):has-text("R$ 30")',
            ]:
                try:
                    el = scope.locator(sel).first
                    if el.is_visible():
                        el.scroll_into_view_if_needed()
                        el.click(timeout=8000)
                        self.page.wait_for_timeout(550)
                        if self._etapa5_fixo_servico_marcado_no_drawer() or self._etapa5_drawer_fixo_pronto():
                            return True
                except Exception:
                    continue

        try:
            clicked = self.page.evaluate(
                r"""
                () => {
                  const precisaFixo30 = (txt) =>
                    /R\$\s*30\s*[,.]\s*00/i.test(txt || '') ||
                    /^[\s]*30\s*[,.]\s*00[\s]*$/i.test((txt || '').trim());
                  const prices = document.querySelectorAll('div.sc-hQfrgq.frojRS, div.frojRS');
                  for (const price of prices) {
                    const raw = price.innerText || '';
                    if (!precisaFixo30(raw)) continue;
                    let el = price;
                    for (let i = 0; i < 14 && el; i++) {
                      const block = el.textContent || '';
                      if (block.includes('Fixo')) {
                        price.click();
                        return 'price';
                      }
                      el = el.parentElement;
                    }
                  }
                  const cards = document.querySelectorAll('div');
                  for (const card of cards) {
                    const t = card.textContent || '';
                    if (!t.includes('Fixo')) continue;
                    if (!/R\$\s*30\s*[,.]\s*00/i.test(t)) continue;
                    const cb = card.querySelector('input[type="checkbox"]');
                    if (cb) { cb.click(); return 'checkbox'; }
                    const im = card.querySelector('img[src^="data:image"]');
                    if (im) { im.click(); return 'img'; }
                    const pr = card.querySelector('div.frojRS, div.sc-hQfrgq');
                    if (pr) {
                      const pt = pr.innerText || '';
                      if (precisaFixo30(pt)) { pr.click(); return 'frojRS'; }
                    }
                  }
                  return '';
                }
                """
            )
            self.page.wait_for_timeout(700)
            if clicked and (
                self._etapa5_fixo_servico_marcado_no_drawer() or self._etapa5_drawer_fixo_pronto()
            ):
                logger.info("[PAP] Clique Fixo via JS (%s)", clicked)
                return True
        except Exception as ex:
            logger.debug("[PAP] clique Fixo evaluate: %s", ex)
        return False

    def _etapa5_garantir_drawer_fixo_para_portabilidade(self, max_ciclos: int = 3) -> Tuple[bool, str]:
        """
        Garante que o drawer 'Escolher serviços adicionais' está aberto e o painel Fixo
        (portabilidade / Salvar) está acessível — reabre e remarca Fixo se necessário.
        """
        for ciclo in range(max_ciclos):
            self._etapa5_bloquear_backdrop_drawer_mui()
            if self._etapa5_drawer_titulo_servicos_visivel() and self._etapa5_drawer_fixo_pronto():
                logger.info("[PAP] Drawer Fixo/Portabilidade OK (ciclo %s)", ciclo + 1)
                return True, ""
            logger.warning(
                "[PAP] Drawer Fixo incompleto; reabrindo (ciclo %s/%s)",
                ciclo + 1,
                max_ciclos,
            )
            if not self._etapa5_drawer_titulo_servicos_visivel():
                if not self._etapa5_clicar_servicos_disponiveis():
                    self._etapa5_restaurar_backdrop_drawer_mui()
                    return False, "Não foi possível clicar em 'Serviços disponíveis' para reabrir o painel."
                try:
                    self.page.wait_for_selector(
                        'text=Escolher serviços adicionais', timeout=15000
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(400)
                self._etapa5_bloquear_backdrop_drawer_mui()
            if not self._etapa5_clicar_opcao_fixo_no_drawer():
                self._etapa5_restaurar_backdrop_drawer_mui()
                return False, "Não foi possível marcar a opção Fixo no painel."
            self.page.wait_for_timeout(700)
            self._etapa5_bloquear_backdrop_drawer_mui()
            if self._etapa5_drawer_fixo_pronto():
                logger.info("[PAP] Fixo marcado ou portabilidade visível (ciclo %s)", ciclo + 1)
                return True, ""

        if self._etapa5_drawer_fixo_pronto():
            return True, ""
        return False, "Painel Fixo/portabilidade não ficou disponível após várias tentativas."

    def _etapa5_locator_drawer_paper_visivel(self):
        """
        Locator do painel branco lateral (serviços adicionais / streaming), não o backdrop.
        Prefere painéis que expõem o botão Salvar.
        """
        try:
            salvar_rx = re.compile(r"^\s*Salvar\s*$", re.I)
            selectors = (
                "div.MuiDrawer-paperAnchorRight",
                "div.MuiDrawer-paper.MuiDrawer-paperAnchorRight",
                '[class*="Drawer-paperAnchorRight"]',
                "aside.MuiDrawer-paper",
            )
            found_any = None
            for sel in selectors:
                loc = self.page.locator(sel)
                try:
                    n = loc.count()
                except Exception:
                    continue
                for i in range(n):
                    p = loc.nth(i)
                    try:
                        if not p.is_visible():
                            continue
                    except Exception:
                        continue
                    try:
                        if p.get_by_role("button", name=salvar_rx).count() > 0:
                            return p
                    except Exception:
                        pass
                    if found_any is None:
                        found_any = p
            try:
                dialogs = self.page.get_by_role("dialog")
                nd = dialogs.count()
                for i in range(nd):
                    d = dialogs.nth(i)
                    if not d.is_visible():
                        continue
                    if d.get_by_role("button", name=salvar_rx).count() > 0:
                        return d
            except Exception:
                pass
            for sel in (
                'aside:has-text("Escolher serviços adicionais")',
                'aside:has-text("Escolher plataformas")',
                'div:has-text("Escolher serviços adicionais"):has(button:has-text("Salvar"))',
            ):
                try:
                    loc = self.page.locator(sel)
                    if loc.count() == 0:
                        continue
                    cand = loc.first
                    if not cand.is_visible():
                        continue
                    if cand.get_by_role("button", name=salvar_rx).count() > 0:
                        return cand
                    if cand.locator("button.sc-guDjWT.gIsNuI").count() > 0:
                        return cand
                except Exception:
                    continue
            return found_any
        except Exception:
            return None

    def _etapa5_clicar_salvar_painel(self) -> bool:
        """
        Clica no botão "Salvar" do painel lateral (Fixo/Streaming).
        Prioriza o drawer MUI visível para não acionar o backdrop nem outro Salvar da página.
        NÃO usar "Salvar Interesse". Classes atuais incluem sc-guDjWT gIsNuI.
        """
        try:
            self.page.wait_for_timeout(400)
            self._etapa5_scroll_painel_lateral_ate_rodape()
            salvar_rx = re.compile(r"^\s*Salvar\s*$", re.I)
            try:
                btns_sc = self.page.locator("button.sc-guDjWT.gIsNuI")
                for j in range(btns_sc.count() - 1, -1, -1):
                    bx = btns_sc.nth(j)
                    try:
                        if not bx.is_visible():
                            continue
                        tx = (bx.inner_text() or "").strip()
                        if tx != "Salvar" or "Interesse" in tx:
                            continue
                        bx.scroll_into_view_if_needed()
                        bx.click(force=True, timeout=8000)
                        self.page.wait_for_timeout(500)
                        return True
                    except Exception:
                        continue
            except Exception:
                pass
            roots = []
            paper = self._etapa5_locator_drawer_paper_visivel()
            if paper is not None:
                roots.append(paper)
            roots.append(self.page)

            def _try_salvar_em_root(root, use_force: bool) -> bool:
                try:
                    loc = root.get_by_role("button", name=salvar_rx)
                    for i in range(loc.count()):
                        b = loc.nth(i)
                        try:
                            if not b.is_visible():
                                continue
                            t = (b.inner_text() or "").strip()
                            if "Interesse" in t or t != "Salvar":
                                continue
                            b.scroll_into_view_if_needed()
                            b.click(force=use_force, timeout=8000)
                            self.page.wait_for_timeout(500)
                            return True
                        except Exception:
                            continue
                except Exception:
                    pass
                for sel in [
                    "button.sc-guDjWT.gIsNuI",
                    "button.gIsNuI.sc-guDjWT",
                    'button.sc-guDjWT:has-text("Salvar")',
                    "button.sc-izfUZz.eKoZwI",
                    "button.eKoZwI.sc-izfUZz",
                    'button[class*="gIsNuI"][class*="sc-guDjWT"]',
                ]:
                    try:
                        bl = root.locator(sel).first
                        if not bl.is_visible():
                            continue
                        tx = (bl.inner_text() or "").strip()
                        if tx != "Salvar" or "Interesse" in tx:
                            continue
                        cls = bl.get_attribute("class") or ""
                        if "dCaJBF" in cls or "hBqtbW" in cls:
                            continue
                        bl.scroll_into_view_if_needed()
                        bl.click(force=use_force, timeout=8000)
                        self.page.wait_for_timeout(500)
                        return True
                    except Exception:
                        continue
                return False

            for root in roots:
                if _try_salvar_em_root(root, use_force=False):
                    return True
            for root in roots:
                if _try_salvar_em_root(root, use_force=True):
                    return True

            for sel in ['[role="button"]:has-text("Salvar")', 'div[role="button"]:has-text("Salvar")']:
                try:
                    for el in self.page.query_selector_all(sel):
                        if not el or not el.is_visible():
                            continue
                        tx = (el.inner_text() or "").strip()
                        if tx != "Salvar" or "Interesse" in tx:
                            continue
                        el.scroll_into_view_if_needed()
                        el.click(force=True)
                        self.page.wait_for_timeout(500)
                        return True
                except Exception:
                    continue
            for sel in ['button.sc-izfUZz:has-text("Salvar")', '[class*="eKoZwI"]:has-text("Salvar")', 'button:has-text("Salvar")']:
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
            btns = self.page.query_selector_all("button")
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
        Abre "Serviços disponíveis", bloqueia backdrop, marca Fixo (preferindo o ícone img)
        e confirma que o painel lateral está pronto para portabilidade/Salvar.
        """
        try:
            self._etapa5_garantir_pagina()
            self.dados_pedido['tem_fixo'] = tem_fixo
            if not tem_fixo:
                return True, "OK"
            if not self._etapa5_clicar_servicos_disponiveis():
                return False, "Botão 'Serviços disponíveis' não encontrado."
            self.page.wait_for_timeout(400)
            try:
                self.page.wait_for_selector(
                    'text=Escolher serviços adicionais', timeout=15000
                )
            except Exception:
                logger.warning("[PAP] Título do drawer de serviços não apareceu a tempo.")
            self._etapa5_bloquear_backdrop_drawer_mui()
            self.page.wait_for_timeout(300)
            if not self._etapa5_clicar_opcao_fixo_no_drawer():
                self._etapa5_restaurar_backdrop_drawer_mui()
                return False, "Opção Fixo não encontrada no painel de serviços adicionais."

            ok, msg = self._etapa5_garantir_drawer_fixo_para_portabilidade(max_ciclos=2)
            if not ok:
                return False, msg or "Painel Fixo não ficou pronto."
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
            ok_g, msg_g = self._etapa5_garantir_drawer_fixo_para_portabilidade(max_ciclos=3)
            if not ok_g:
                return False, msg_g or "Painel Fixo não está aberto; não foi possível reabrir."
            self._etapa5_bloquear_backdrop_drawer_mui()
            self._etapa5_scroll_painel_lateral_ate_rodape()
            drawer = self._etapa5_locator_drawer_paper_visivel()
            ctx = drawer if drawer is not None else self.page
            port_lbl = ctx.locator('label:has-text("Cliente deseja fazer portabilidade")').first
            try:
                has_port = port_lbl.is_visible()
            except Exception:
                has_port = False
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
                        self._etapa5_restaurar_backdrop_drawer_mui()
                        return False, "Número para portabilidade inválido (informe DDD + número fixo)."
                    inp = self.page.query_selector("#contatoPortabilidade, input[name='contatoPortabilidade']")
                    if inp:
                        inp.fill(digits)
                        self.page.wait_for_timeout(200)
                    needle = (operadora_texto or "").strip()
                    if len(needle) < 2:
                        self._etapa5_restaurar_backdrop_drawer_mui()
                        return False, "Informe a operadora de origem (ex.: Vivo, Claro, Tim)."
                    sel_el = self.page.query_selector('select[name="operadora"]')
                    if not sel_el:
                        self._etapa5_restaurar_backdrop_drawer_mui()
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
                        self._etapa5_restaurar_backdrop_drawer_mui()
                        return (
                            False,
                            "Operadora não encontrada na lista. Tente o nome curto (ex.: Vivo, Claro, OI, Tim).",
                        )
            # Salvar fica no rodapé do painel lateral; sem scroll o Playwright não acha "visível"
            try:
                for scroll_sel in (
                    'select[name="operadora"]',
                    "#contatoPortabilidade",
                    'label:has-text("portabilidade")',
                    'button:has-text("Salvar")',
                ):
                    eloc = ctx.locator(scroll_sel).first
                    try:
                        if eloc.is_visible():
                            eloc.scroll_into_view_if_needed()
                            self.page.wait_for_timeout(150)
                    except Exception:
                        pass
                self.page.evaluate("""() => {
                    const roots = document.querySelectorAll('aside, [class*="Drawer"], [class*="drawer"], [role="dialog"]');
                    roots.forEach(r => { try { r.scrollTop = r.scrollHeight; } catch (e) {} });
                }""")
                self.page.wait_for_timeout(200)
            except Exception:
                pass
            if not self._etapa5_clicar_salvar_painel():
                self._etapa5_restaurar_backdrop_drawer_mui()
                return False, "Botão Salvar do painel Fixo não encontrado."
            self._etapa5_restaurar_backdrop_drawer_mui()
            self.dados_pedido["fixo_portabilidade"] = quer_portabilidade
            if quer_portabilidade:
                self.dados_pedido["fixo_portabilidade_numero"] = re.sub(r"\D", "", numero_port or "")
                self.dados_pedido["fixo_portabilidade_operadora"] = (operadora_texto or "").strip()
            self.page.wait_for_timeout(400)
            return True, "OK"
        except Exception as e:
            logger.error("[PAP] etapa5_fixo_finalizar_portabilidade: %s", e)
            self._etapa5_restaurar_backdrop_drawer_mui()
            return False, str(e)

    def etapa5_selecionar_streaming(self, tem_streaming: bool, streaming_opcoes: str = None, plano: str = "") -> Tuple[bool, str]:
        """
        Seleciona streaming no drawer "Escolher plataformas de streaming…".
        Clica nos preços em div.sc-hQfrgq.frojRS (44,90 / 39,90 / 22,90), valida seleção e Salvar.
        Premium e Padrão Globoplay são excludentes; 700Mb/1Gb não oferece Padrão.
        """
        try:
            self._etapa5_garantir_pagina()
            self.dados_pedido['tem_streaming'] = tem_streaming
            self.dados_pedido['streaming_opcoes'] = (streaming_opcoes or '').strip()
            if not tem_streaming:
                return True, "OK"

            plano_lower = (plano or self.dados_pedido.get("plano", "")).lower()
            skip_padrao = "700mega" in plano_lower or "1giga" in plano_lower
            opts = [x.strip() for x in (streaming_opcoes or "").lower().replace(" ", "").split(",") if x.strip()]
            if not opts:
                return False, "Nenhuma opção de streaming informada (streaming_opcoes vazio)."

            precos: List[str] = []
            for o in opts:
                p = self._etapa5_streaming_map_opcao_para_preco(o, skip_padrao)
                if p:
                    precos.append(p)
            if not precos:
                return False, "Opções de streaming não reconhecidas (use hbomax, globoplay_premium, globoplay_basico, etc.)."

            if "39,90" in precos and "22,90" in precos:
                precos = [x for x in precos if x != "22,90"]
                logger.info("[PAP] Globoplay Premium e Padrão juntos: mantendo só Premium (39,90).")

            btn_ok = False
            try:
                lb = self.page.get_by_role(
                    "button",
                    name=re.compile(r"Streaming\s+e\s+canais\s+on[-\s]?line", re.I),
                )
                if lb.count() > 0:
                    b0 = lb.first
                    if b0.is_visible():
                        b0.scroll_into_view_if_needed()
                        b0.click(timeout=8000)
                        btn_ok = True
            except Exception:
                pass
            if not btn_ok:
                btn_stream = self.page.query_selector(SELETORES["etapa5"]["btn_streaming"])
                if not btn_stream:
                    btn_stream = self.page.query_selector(
                        'button.sc-wRHdD:has-text("Streaming e canais on-line")'
                    )
                if not btn_stream:
                    btn_stream = self.page.query_selector(
                        'button.sc-izfUZz:has-text("Streaming e canais on-line")'
                    )
                if not btn_stream:
                    btn_stream = self.page.query_selector('div:has-text("Streaming e canais on-line")')
                if not btn_stream or not btn_stream.is_visible():
                    return False, "Botão 'Streaming e canais on-line' não encontrado."
                try:
                    btn_stream.scroll_into_view_if_needed()
                    btn_stream.click()
                except Exception:
                    self.page.evaluate("(el) => el.click()", btn_stream)

            self.page.wait_for_timeout(500)
            try:
                self.page.wait_for_selector('text=Escolher plataformas', timeout=15000)
            except Exception:
                pass
            if not self._etapa5_drawer_streaming_titulo_visivel():
                return (
                    False,
                    "Drawer de streaming não abriu (texto 'Escolher plataformas' não visível).",
                )
            self._etapa5_bloquear_backdrop_drawer_mui()
            self.page.wait_for_timeout(300)
            self._etapa5_scroll_drawer_streaming_ate_salvar()

            for preco in precos:
                self._etapa5_scroll_drawer_streaming_ate_salvar()
                if not self._etapa5_clicar_preco_streaming(preco):
                    self._etapa5_restaurar_backdrop_drawer_mui()
                    return False, f"Não foi possível clicar na linha do streaming (preço R$ {preco})."
                if not self._etapa5_streaming_preco_parece_selecionado(preco):
                    logger.warning("[PAP] Streaming R$ %s: seleção não confirmada; repetindo clique.", preco)
                    self._etapa5_clicar_preco_streaming(preco)
                    self.page.wait_for_timeout(450)
                if not self._etapa5_streaming_preco_parece_selecionado(preco):
                    self._etapa5_restaurar_backdrop_drawer_mui()
                    return (
                        False,
                        f"Streaming R$ {preco} não ficou selecionado (checkbox/estado não detectado).",
                    )

            self.page.wait_for_timeout(500)
            self._etapa5_scroll_drawer_streaming_ate_salvar()
            self._etapa5_scroll_painel_lateral_ate_rodape()

            salvar_ok = self._etapa5_clicar_salvar_painel()
            if not salvar_ok:
                self.page.wait_for_timeout(600)
                self._etapa5_scroll_drawer_streaming_ate_salvar()
                self._etapa5_scroll_painel_lateral_ate_rodape()
                salvar_ok = self._etapa5_clicar_salvar_painel()
            if not salvar_ok:
                self._etapa5_restaurar_backdrop_drawer_mui()
                return False, "Botão Salvar do painel de streaming não encontrado ou não clicável."

            self._etapa5_restaurar_backdrop_drawer_mui()
            self.page.wait_for_timeout(400)
            try:
                if "Escolher plataformas" in (self.page.content() or ""):
                    self.page.keyboard.press("Escape")
                    self.page.wait_for_timeout(200)
            except Exception:
                pass
            self.page.wait_for_timeout(200)
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar streaming: {e}")
            try:
                self._etapa5_restaurar_backdrop_drawer_mui()
            except Exception:
                pass
            return False, str(e)

    def etapa5_clicar_avancar(self) -> Tuple[bool, str]:
        """Clica em Avançar para ir da etapa 5 (pagamento/ofertas) para etapa 6 (biometria)."""
        try:
            self._etapa5_garantir_pagina()
            # Fechar modal "Escolher serviços adicionais" se estiver aberto (bloqueia o Avançar)
            self._fechar_modal_servicos_adicionais()
            self.page.wait_for_timeout(400)
            plano_dp = (self.dados_pedido.get("plano") or "").strip().lower()
            # Não reaplicar o plano aqui: isso resetaria Fixo/Streaming já configurados.
            self.page.wait_for_timeout(400)
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
            if plano_dp in ("1giga", "700mega", "500mega"):
                try:
                    self.page.wait_for_selector('h2:has-text("Resumo")', state="visible", timeout=25000)
                except Exception:
                    logger.warning("[PAP] Título Resumo não apareceu no tempo esperado após Avançar.")
                ok_v, msg_v, lido = self.etapa6_validar_plano_resumo(plano_dp)
                if not ok_v:
                    logger.error("[PAP] Validação plano Resumo falhou: %s (lido=%r)", msg_v, lido)
                    return False, msg_v
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
            sucesso, msg = self.etapa5_selecionar_plano_com_validacao(plano)
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
        Inclui Fixo e streaming na seção de serviços adicionais apenas quando contratados (com preços).
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
        partes_apos_forma = []
        if linhas_adic:
            partes_apos_forma.append("✨ *Serviços adicionais:*\n" + "\n".join(linhas_adic))
        if d.get("tem_fixo") and d.get("fixo_portabilidade"):
            raw_num = re.sub(r"\D", "", str(d.get("fixo_portabilidade_numero") or ""))
            op_p = (d.get("fixo_portabilidade_operadora") or "").strip() or "—"
            if len(raw_num) >= 10:
                if len(raw_num) == 11:
                    num_fmt = f"({raw_num[:2]}) {raw_num[2:7]}-{raw_num[7:]}"
                else:
                    num_fmt = f"({raw_num[:2]}) {raw_num[2:6]}-{raw_num[6:]}"
            else:
                num_fmt = d.get("fixo_portabilidade_numero") or raw_num or "—"
            partes_apos_forma.append(
                f"📲 *Portabilidade do fixo:* {num_fmt} — operadora *{op_p}*"
            )
        bloco_apos_forma = (
            "\n\n".join(partes_apos_forma) + "\n\n" if partes_apos_forma else ""
        )
        texto_fatura = (
            "Sua primeira fatura irá vencer *25 dias* após a instalação da internet; nos demais meses, "
            "o vencimento segue o ciclo de *30 em 30 dias*.\n\n"
        )
        return (
            "📋 *RESUMO DO PEDIDO*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *Cliente:* {nome}\n\n"
            f"📍 *Endereço:*\n{endereco}\n\n"
            f"📦 *Plano:* {plano_label} – {valor}\n\n"
            f"💳 *Forma de pagamento:* {forma}\n\n"
            f"{bloco_apos_forma}"
            f"📅 *Fidelidade:* 12 meses\n\n"
            "💰 *Taxa de habilitação:*\n"
            "Você ganha isenção da taxa de habilitação se permanecer no mínimo 12 meses conosco.\n\n"
            f"{texto_fatura}"
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

    def _plano_normalizar_de_texto_resumo(self, texto: str) -> Optional[str]:
        """Converte texto exibido no PAP (ex.: '1 Giga', '500 Mega') para chave interna."""
        if not texto:
            return None
        t = texto.replace("\u00a0", " ").lower().strip()
        if re.search(r"\b1\s*giga\b", t):
            return "1giga"
        if re.search(r"\b700\s*mega\b", t):
            return "700mega"
        if re.search(r"\b500\s*mega\b", t):
            return "500mega"
        return None

    def etapa6_ler_plano_detalhes_oferta_resumo(self) -> Tuple[bool, str]:
        """
        Na tela Resumo, lê o plano exibido em Detalhes da oferta (ex.: div com 1 Giga / 500 Mega).
        """
        try:
            self.page.wait_for_selector('h2:has-text("Resumo")', state="visible", timeout=20000)
        except Exception:
            return False, ""
        try:
            raw = self.page.evaluate(
                r"""() => {
                  const pick = (t) => (t || '').trim();
                  const el1 = document.querySelector('div.sc-kOnlKp.bVXyze');
                  if (el1) {
                    const t = pick(el1.textContent);
                    if (/Mega|Giga/i.test(t) && t.length < 80) return t;
                  }
                  for (const el2 of document.querySelectorAll('[class*="bVXyze"]')) {
                    const t = pick(el2.textContent);
                    if (/Mega|Giga/i.test(t) && t.length < 80) return t;
                  }
                  const h2 = [...document.querySelectorAll('h2')].find(
                    (e) => pick(e.textContent) === 'Resumo'
                  );
                  const root = h2
                    ? h2.closest('main') || h2.closest('[class*="sc-"]') || document.body
                    : document.body;
                  const cand = root.querySelectorAll('div, span');
                  for (const k of cand) {
                    const t = pick(k.textContent);
                    if (/^1\s*Giga$/i.test(t) || /^700\s*Mega$/i.test(t) || /^500\s*Mega$/i.test(t)) {
                      return t;
                    }
                  }
                  const blob = (root.innerText || '').replace(/\s+/g, ' ');
                  const m = blob.match(/\b(1\s*Giga|700\s*Mega|500\s*Mega)\b/i);
                  if (m) return m[1].replace(/\s+/g, ' ').trim();
                  return '';
                }"""
            )
            return True, (raw or "").strip()
        except Exception as e:
            logger.warning("[PAP] etapa6_ler_plano_detalhes_oferta_resumo: %s", e)
            return False, ""

    def etapa6_validar_plano_resumo(self, plano_interno: str) -> Tuple[bool, str, str]:
        """
        Garante que o plano em Detalhes da oferta confere com o escolhido no fluxo.
        Retorna (ok, mensagem_erro_vazia_se_ok, texto_lido).
        """
        esp = (plano_interno or self.dados_pedido.get("plano") or "").strip().lower()
        if esp not in ("1giga", "700mega", "500mega"):
            return True, "", ""
        ok_r, lido = self.etapa6_ler_plano_detalhes_oferta_resumo()
        if not ok_r or not lido:
            return (
                False,
                "Não foi possível ler o plano na tela Resumo (Detalhes da oferta). "
                "Confira no navegador se a oferta está correta antes de seguir.",
                lido or "",
            )
        achado = self._plano_normalizar_de_texto_resumo(lido)
        if achado is None:
            return (
                False,
                f"Plano na tela Resumo não reconhecido ({lido!r}). Esperado: {esp}. Ajuste manualmente no PAP.",
                lido,
            )
        if achado != esp:
            mapa = {"1giga": "1 Giga", "700mega": "700 Mega", "500mega": "500 Mega"}
            return (
                False,
                f"Plano no PAP ({lido!r}) não confere com o escolhido no fluxo ({mapa.get(esp, esp)}). "
                "O portal pode ter resetado a oferta ao abrir serviços; corrija no site ou reinicie a venda.",
                lido,
            )
        return True, "", lido

    def _etapa6_avancar_ate_tela_biometria(self, max_cliques: int = 3) -> None:
        """
        Se o usuário voltou no navegador, o portal pode exibir só a etapa anterior (ex.: Resumo/ofertas)
        com *Avançar* em vez da etapa 6 com biometria. Clica Avançar até aparecer Abrir OS ou
        Consultar Biometria, ou até não haver mais Avançar habilitado.
        """
        sel_abrir = (
            'button:has-text("Abrir OS"):not([disabled]), '
            'button:has-text("Abrir O.S"):not([disabled]), '
            'button:has-text("Abrir O.S."):not([disabled])'
        )
        sel_consultar = 'button:has-text("Consultar Biometria"), button.btn-consult-new'

        def _vis(el):
            try:
                return el and el.is_visible()
            except Exception:
                return False

        for i in range(max_cliques):
            btn_os = self.page.query_selector(sel_abrir)
            if _vis(btn_os):
                return
            btn_c = self.page.query_selector(sel_consultar)
            if _vis(btn_c):
                return
            btn_av = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if not _vis(btn_av):
                return
            logger.info(
                "[PAP] Etapa 6 - Clicando Avançar para atingir a tela de biometria "
                "(ex.: voltou no navegador; passo %s/%s)",
                i + 1,
                max_cliques,
            )
            try:
                btn_av.click()
            except Exception as e:
                logger.warning("[PAP] Etapa 6 - Falha ao clicar Avançar: %s", e)
                return
            self.page.wait_for_timeout(1000)
            try:
                self.page.wait_for_selector("div.spinner", state="hidden", timeout=12000)
            except Exception:
                self.page.wait_for_timeout(1500)
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

    def etapa6_consultar_biometria(self) -> Tuple[bool, str]:
        """Clica no botão Consultar Biometria na etapa 6."""
        try:
            pode, err = self._pap_garantir_sessao_antes_resumo()
            if not pode:
                return False, err
            self._etapa6_avancar_ate_tela_biometria()
            logger.info("[PAP] Etapa 6 - Clicando Consultar Biometria")
            btn = self.page.query_selector('button:has-text("Consultar Biometria"), button.btn-consult-new')
            if not btn:
                return False, "Botão Consultar Biometria não encontrado."
            btn.click()
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            self.page.wait_for_timeout(800)
            ok_modal, err_modal = self._pap_tratar_modais_apos_acao_pap()
            if not ok_modal and err_modal:
                return False, f"Portal exibiu erro após consultar biometria: {err_modal}"
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao consultar biometria: {e}")
            return False, str(e)

    def etapa6_verificar_biometria(self, consultar_primeiro: bool = False) -> Tuple[bool, str, bool]:
        """
        Etapa 6: Verificar status da biometria.

        Fonte da verdade: (1) botão "Abrir OS" habilitado = biometria aprovada;
        (2) texto explícito de aprovação no contexto do rótulo Biometria (aprovada/apto/liberado);
        Não inferir aprovação só por estar na tela Resumo sem "pendente" (evita falso positivo).

        Args:
            consultar_primeiro: Se True, clica em "Consultar Biometria" antes de verificar (para atualizar status)

        Returns:
            Tuple (sucesso, mensagem, biometria_aprovada)
        """
        try:
            logger.info("[PAP] Etapa 6 - Verificando biometria")

            pode, err = self._pap_garantir_sessao_antes_resumo()
            if not pode:
                return False, err, False

            # Aguardar spinner desaparecer (bloqueia cliques)
            try:
                self.page.wait_for_selector('div.spinner', state="hidden", timeout=10000)
            except Exception:
                self.page.wait_for_timeout(2000)

            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            # Voltar no navegador pode deixar a tela na etapa anterior (só Avançar). Ir à etapa 6 antes de consultar.
            self._etapa6_avancar_ate_tela_biometria()

            def _btn_abrir_os_visivel():
                return self.page.query_selector(
                    'button:has-text("Abrir OS"):not([disabled]), '
                    'button:has-text("Abrir O.S"):not([disabled]), '
                    'button:has-text("Abrir O.S."):not([disabled])'
                )

            # 1) Sempre checar Abrir OS *antes* de "Consultar Biometria": após aprovação o portal
            #    pode ocultar a linha Biometria; clicar em Consultar sem necessidade gera falso "pendente".
            btn_abrir_os = _btn_abrir_os_visivel()
            if btn_abrir_os:
                self.dados_pedido["_pap_biometria_aprovada"] = True
                self.etapa_atual = 6
                return True, "Biometria APROVADA! Pronto para abrir O.S.", True

            # 2) Consultar só se pedido e ainda não há Abrir OS (atualiza status quando pendente)
            if consultar_primeiro:
                ok_c, msg_c = self.etapa6_consultar_biometria()
                if not ok_c:
                    return False, msg_c, False
                self.page.wait_for_timeout(2500)
                try:
                    self.page.wait_for_selector('div.spinner', state="hidden", timeout=10000)
                except Exception:
                    self.page.wait_for_timeout(2000)
                btn_abrir_os = _btn_abrir_os_visivel()
                if btn_abrir_os:
                    self.dados_pedido["_pap_biometria_aprovada"] = True
                    self.etapa_atual = 6
                    return True, "Biometria APROVADA! Pronto para abrir O.S.", True

            # Última tentativa: às vezes após consulta o portal volta a mostrar só Avançar
            self._etapa6_avancar_ate_tela_biometria(max_cliques=2)

            btn_abrir_os = _btn_abrir_os_visivel()
            if btn_abrir_os:
                self.dados_pedido["_pap_biometria_aprovada"] = True
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
            biometria_aprovada_texto = False
            if contexto_biometria:
                biometria_aprovada_texto = any(
                    x in contexto_biometria
                    for x in (
                        'aprovad',
                        'apto',
                        'liberad',
                        'concluíd',
                        'concluid',
                        'validad',
                        'documento apto',
                    )
                )

            if span_biometria and biometria_aprovada_texto and not biometria_pendente:
                self.dados_pedido["_pap_biometria_aprovada"] = True
                self.etapa_atual = 6
                return True, "Biometria APROVADA (status na linha Biometria). Pronto para abrir O.S.", True

            if self.dados_pedido.get("_pap_biometria_aprovada"):
                return True, "Biometria já aprovada neste pedido.", True

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
            btn = self.page.query_selector(
                'button:has-text("Abrir OS"):not([disabled]), '
                'button:has-text("Abrir O.S"):not([disabled]), '
                'button:has-text("Abrir O.S."):not([disabled])'
            )
            if not btn:
                ctx = self.pap_inspecionar_contexto_etapa()
                return (
                    False,
                    f"Botão Abrir OS não disponível. Onde parece estar: {ctx.get('provavel')} — "
                    f"consulte biometria no PAP e use CONSULTAR de novo.",
                )
            btn.click()
            self.page.wait_for_timeout(2000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            ok_modal, err_modal = self._pap_tratar_modais_apos_acao_pap()
            if not ok_modal and err_modal:
                ctx = self.pap_inspecionar_contexto_etapa()
                return (
                    False,
                    f"Modal de erro no portal após Abrir OS: {err_modal} "
                    f"(tela provável: {ctx.get('provavel')}). Feche o aviso no navegador se ainda estiver aberto "
                    f"e tente CONSULTAR novamente.",
                )
            # 9 validações no portal; aguardar até 90s — seletores alternativos (UI muda entre builds)
            sel_ag = (
                'h3:has-text("Período"), h2:has-text("Período"), '
                'p:has-text("Período"), span:has-text("Período"), '
                '[class*="react-datepicker"], .react-datepicker, '
                'h2:has-text("Agendamento"), h3:has-text("Agendamento"), '
                '[class*="Agendamento"], [class*="agendamento"]'
            )
            _t7_ms = int(getattr(settings, "PAP_ETAPA7_AGENDAMENTO_TIMEOUT_MS", 120000) or 120000)
            ok_wait, err_wait = self.esperar_selector_com_keepalive_sessao(
                sel_ag,
                timeout_ms=max(90000, _t7_ms),
                poll_ms=5000,
                target_after_relogin=PAP_NOVO_PEDIDO_URL,
            )
            if not ok_wait:
                if err_wait and "Sessão do portal expirou durante a espera" in err_wait:
                    return False, err_wait
                ctx = self.pap_inspecionar_contexto_etapa()
                logger.error(
                    "[PAP] etapa7 timeout aguardando UI. url=%s ctx=%s err=%s",
                    ctx.get("url"),
                    ctx,
                    err_wait,
                )
                return (
                    False,
                    f"{err_wait or 'timeout'} Onde parece estar: {ctx.get('provavel')}. "
                    f"Se voltou ao início do pedido ou há aviso de erro, corrija no PAP e repita CONSULTAR. "
                    f"Modal visível: {ctx.get('trecho_modal')[:180] if ctx.get('trecho_modal') else '(nenhum)'}",
                )
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            return True, "Tela de Agendamento exibida."
        except Exception as e:
            logger.error(f"[PAP] etapa7_ir_para_agendamento: {e}")
            ctx = self.pap_inspecionar_contexto_etapa()
            return False, f"{e} (contexto: {ctx.get('provavel')})"

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
        tinha_sessao = self.sessao_iniciada
        try:
            if not tinha_sessao:
                return
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
            if self._pap_slot_held:
                try:
                    _pap_semaphore.release()
                except ValueError:
                    pass
                self._pap_slot_held = False
            self.sessao_iniciada = False
            if tinha_sessao or self.vendedor_nome:
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
