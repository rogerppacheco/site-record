# crm_app/services_pap_nio.py
"""
Serviço de automação para vendas no PAP Nio via Playwright.
Permite que vendedores autorizados realizem vendas pelo WhatsApp.
"""

import os
import re
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Optional, Tuple, Any
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
        'btn_servicos': 'div:has-text("Serviços disponíveis")',
        'opcao_fixo': 'div.sc-dcmekm.dBGnOE:has-text("Fixo"), div:has-text("Fixo"):not([disabled])',
        'btn_streaming': 'div:has-text("Streaming e canais on-line")',
        'opcao_hbomax': 'div.sc-dcmekm.dBGnOE:has-text("HBO Max"), div:has-text("HBO Max"):not([disabled])',
        'opcao_globoplay_premium': 'div.sc-dcmekm:has-text("Plano Premium"):not([disabled])',
        'opcao_globoplay_basico': 'div.sc-dcmekm:has-text("Plano Padrão com Anúncios"), div:has-text("Plano Padrão"):not([disabled])',
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
}

# =============================================================================
# CLASSE PRINCIPAL DE AUTOMAÇÃO
# =============================================================================

class PAPNioAutomation:
    """
    Classe para automatizar vendas no PAP Nio.
    Cada instância representa uma sessão de venda.
    """
    
    def __init__(self, matricula_pap: str, senha_pap: str, vendedor_nome: str = None, headless: bool = True):
        """
        Inicializa a automação PAP.
        
        Args:
            matricula_pap: Matrícula do vendedor no PAP
            senha_pap: Senha + OTP do PAP
            vendedor_nome: Nome do vendedor (para logs)
            headless: Se False, abre o navegador visível (para testes)
        """
        self.matricula_pap = matricula_pap
        self.senha_pap = senha_pap
        self.vendedor_nome = vendedor_nome or matricula_pap
        self.headless = headless
        
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
        
        # Storage state para manter cookies
        self.storage_state_path = os.path.join(
            STORAGE_STATE_DIR, 
            f'pap_session_{self.matricula_pap}.json'
        )
    
    def _garantir_diretorio_sessoes(self):
        """Garante que o diretório de sessões existe"""
        os.makedirs(STORAGE_STATE_DIR, exist_ok=True)
    
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
            self.sessao_iniciada = True
            
            # Navegar para o PAP
            self.page.goto(PAP_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(3000)
            self.page.wait_for_load_state("networkidle", timeout=30000)
            
            # Verificar se precisa fazer login (URL ou formulário de login visível)
            current_url = self.page.url
            login_form_visivel = (
                self.page.query_selector('#inputMatricula') or
                self.page.query_selector('#passwordInput') or
                self.page.query_selector('input[placeholder*="Login"]') or
                self.page.query_selector('input[type="password"]')
            )
            
            if "login.vtal.com" in current_url or ("login" in current_url.lower() and "pap.niointernet.com.br" not in current_url) or login_form_visivel:
                sucesso, msg = self._fazer_login()
                if not sucesso:
                    return False, msg
            
            self.logado = True
            
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
                
                # Aguardar redirecionamento para PAP (pode haver múltiplos redirects via SSO)
                try:
                    self.page.wait_for_url(
                        lambda url: "pap.niointernet.com.br" in url and "login" not in url.lower(),
                        timeout=25000
                    )
                    logger.info(f"[PAP] Login bem-sucedido para {self.matricula_pap}")
                    return True, "Login realizado com sucesso!"
                except Exception:
                    current_url = self.page.url
                    pagina = self.page.content().lower()
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
            
            # Navegar para Novo Pedido
            try:
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                logger.warning(f"[PAP] goto domcontentloaded: {e}, tentando load...")
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="load", timeout=30000)
            self.page.wait_for_timeout(3000)
            self.page.wait_for_load_state("networkidle", timeout=10000)
            
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
                    return False, msg
                self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="domcontentloaded", timeout=30000)
                self.page.wait_for_timeout(2000)
                url_atual = self.page.url
            
            # Verificar se chegou na página correta
            if "pap.niointernet.com.br" not in url_atual:
                logger.warning(f"[PAP] URL atual: {url_atual}")
                return False, f"Não foi possível acessar a página de novo pedido. URL: {url_atual[:80]}..."
            
            # Aguardar campo matrícula ou página de novo pedido
            try:
                self.page.wait_for_selector(SELETORES['etapa1']['matricula_vendedor'], state="visible", timeout=15000)
            except Exception:
                # Tentar seletores alternativos
                for sel in ['input[placeholder*="matrícula"]', 'input[placeholder*="matricula"]', 'input[id*="vendedor"]']:
                    try:
                        self.page.wait_for_selector(sel, state="visible", timeout=5000)
                        break
                    except Exception:
                        continue
            
            # Campo de matrícula do vendedor
            matricula_input = self.page.query_selector(SELETORES['etapa1']['matricula_vendedor'])
            if matricula_input:
                # Focar no campo para abrir lista
                matricula_input.click()
                # Aguardar lista de vendedores aparecer
                self.page.wait_for_selector(SELETORES['etapa1']['lista_vendedores'], state="visible", timeout=5000)
                # Digitar matrícula
                matricula_input.fill(matricula_vendedor)
                # Aguardar lista atualizar e clicar na opção
                self.page.wait_for_timeout(500)  # debounce do autocomplete
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
                return False, "Não foi possível selecionar o vendedor. Verifique a matrícula."
            btn_avancar.click()
            self.page.wait_for_selector(SELETORES['etapa2']['cep'], state="visible", timeout=10000)
            self._extrair_protocolo_pedido()
            self.etapa_atual = 1
            self.dados_pedido['matricula_vendedor'] = matricula_vendedor
            return True, "Etapa 1 concluída! Vendedor selecionado."
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 1: {e}")
            return False, f"Erro na Etapa 1: {str(e)}"
    
    def etapa2_viabilidade(self, cep: str, numero: str, referencia: str) -> Tuple[bool, str, Optional[list]]:
        """
        Etapa 2: Consulta de viabilidade.
        Fluxo: CEP + Número -> Buscar -> aguardar endereço resolver ->
        preencher Referência (obrigatório) -> Avançar -> aguardar modal.
        """
        try:
            logger.info(f"[PAP] Etapa 2 - CEP: {cep}, Número: {numero}, Referência: {referencia}")
            
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
                    f'{end_inst_sel}, {ref_selector}',
                    state="visible",
                    timeout=15000
                )
            except Exception:
                pass
            self.page.wait_for_timeout(500)
            
            # 4b. Verificar múltiplos endereços (dropdown "Endereço de instalação")
            inp_end_inst = self.page.query_selector(end_inst_sel)
            if inp_end_inst:
                try:
                    inp_end_inst.click()
                    self.page.wait_for_timeout(600)
                    for sel_ul in [
                        'input[placeholder="Endereço de instalação"] ~ ul li',
                        'ul.sc-fQkuQJ.cUdcXF li', 'ul[class*="fQkuQJ"] li',
                        'ul[class*="cUdcXF"] li', 'ul li.sc-epGmkI',
                    ]:
                        lis = [el for el in self.page.query_selector_all(sel_ul) if el.is_visible()]
                        # Filtrar: endereços têm formato "Rua X, 123 - Bairro, Cidade - MG" (contém " - " e UF)
                        enderecos = []
                        for li in lis:
                            txt = (li.inner_text() or "").strip()
                            if len(txt) > 20 and (" - " in txt or ", " in txt) and any(u in txt.upper() for u in ["MG", "SP", "RJ", "BA", "PR", "RS", "SC", "DF", "ES", "GO"]):
                                enderecos.append({'indice': len(enderecos) + 1, 'texto': txt})
                        if len(enderecos) >= 2:
                            self.dados_pedido['cep'] = cep
                            self.dados_pedido['numero'] = str(numero)
                            return True, "Múltiplos endereços. Escolha um:", {'_codigo': 'MULTIPLOS_ENDERECOS', 'lista': enderecos}
                        elif len(enderecos) == 1:
                            target_txt = enderecos[0]['texto']
                            for li in lis:
                                if (li.inner_text() or "").strip() == target_txt:
                                    li.click()
                                    self.page.wait_for_timeout(400)
                                    break
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
            ref_input = self.page.query_selector(ref_selector)
            if ref_input:
                ref_input.click()
                ref_input.fill(referencia)
                self.page.keyboard.press("Tab")
            else:
                # Fallback: get_by_label ou buscar input com placeholder/label Referência
                try:
                    ref_loc = self.page.get_by_label("Referência", exact=False)
                    if ref_loc.count() > 0:
                        ref_loc.first.click()
                        ref_loc.first.fill(referencia)
                        self.page.keyboard.press("Tab")
                except Exception:
                    for inp in self.page.query_selector_all('input:not([disabled]):not([type="hidden"]), textarea:not([disabled])'):
                        ph = (inp.get_attribute("placeholder") or "")
                        name = (inp.get_attribute("name") or "")
                        id_attr = (inp.get_attribute("id") or "")
                        if "referência" in ph.lower() or "referencia" in ph.lower() or "referencia" in name.lower() or "referencia" in id_attr.lower():
                            inp.click()
                            inp.fill(referencia)
                            self.page.keyboard.press("Tab")
                            break

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
        """Clica em 'Sem complemento' (checkbox) quando o endereço tem complementos."""
        try:
            inp = self.page.query_selector('#semComplemento, input[id="semComplemento"]')
            if inp:
                try:
                    if not inp.is_checked():
                        inp.click()
                except Exception:
                    inp.click(force=True)
            else:
                lbl = self.page.query_selector('label[for="semComplemento"]')
                if lbl:
                    lbl.click()
                else:
                    self.page.evaluate("""() => {
                        const inp = document.getElementById('semComplemento');
                        const lbl = document.querySelector('label[for="semComplemento"]');
                        if (inp && !inp.checked) inp.click();
                        else if (lbl) lbl.click();
                    }""")
            self.page.wait_for_timeout(500)
            return True, "Sem complemento selecionado."
        except Exception as e:
            logger.error(f"[PAP] etapa2_selecionar_sem_complemento: {e}")
            return False, str(e)

    def etapa2_selecionar_complemento(self, indice: int) -> Tuple[bool, str]:
        """
        Seleciona um complemento da lista (ex.: Casa A, Casa B).
        Args:
            indice: 1-based (1 = primeiro complemento)
        """
        try:
            for sel in [
                'ul[class*="fQkuQJ"] li',
                'ul[class*="cUdcXF"] li',
                'input[placeholder*="omplemento"] ~ ul li',
            ]:
                lis = self.page.query_selector_all(sel)
                if indice > 0 and indice <= len(lis):
                    lis[indice - 1].click()
                    self.page.wait_for_timeout(500)
                    return True, "Complemento selecionado."
            return False, "Índice de complemento inválido."
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
            ref_selector = SELETORES['etapa2']['referencia']
            try:
                self.page.wait_for_selector(ref_selector, state="visible", timeout=8000)
            except Exception:
                ref_selector = 'input[name="referencia"]'
                self.page.wait_for_selector(ref_selector, state="visible", timeout=5000)
            ref_input = self.page.query_selector(ref_selector)
            if ref_input:
                ref_input.click()
                ref_input.fill(referencia)
                self.page.keyboard.press("Tab")
            else:
                ref_loc = self.page.get_by_label("Referência", exact=False)
                if ref_loc.count() > 0:
                    ref_loc.first.click()
                    ref_loc.first.fill(referencia)
                    self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(800)
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
            btn = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if not btn:
                return False, "Botão Avançar não habilitou.", None
            btn.click()
            self.page.wait_for_timeout(2000)
            try:
                self.page.wait_for_selector(
                    'h2:has-text("Disponível"), h2:has-text("Indisponível"), h3:has-text("Posse encontrada")',
                    state="visible", timeout=20000
                )
            except Exception:
                pass
            self.page.wait_for_timeout(500)
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
                    try:
                        self.page.wait_for_selector('input[name="documento"]', state="visible", timeout=10000)
                    except Exception:
                        self.page.wait_for_timeout(2000)
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
    
    def etapa3_cadastro_cliente(self, cpf: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        Etapa 3: Cadastro do cliente.
        Campo CPF/CNPJ: input[name="documento"]
        """
        try:
            logger.info(f"[PAP] Etapa 3 - CPF: {cpf}")
            
            # Avançar se necessário (da etapa anterior)
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
            
            # Aguardar campo CPF/CNPJ (documento) aparecer
            cpf_selector = SELETORES['etapa3']['cpf']
            try:
                self.page.wait_for_selector(cpf_selector, state="visible", timeout=10000)
            except Exception:
                cpf_selector = 'input[name=documento]'
                self.page.wait_for_selector(cpf_selector, state="visible", timeout=5000)
            
            # Preencher CPF/CNPJ (apenas dígitos)
            cpf_limpo = re.sub(r'\D', '', cpf)
            cpf_input = self.page.query_selector(cpf_selector)
            if cpf_input:
                cpf_input.click()
                cpf_input.fill(cpf_limpo)
                self.page.keyboard.press("Tab")
            else:
                self._set_valor_react(cpf_selector, cpf_limpo)
            
            # Clicar em Buscar e aguardar resultado (nome do cliente ou Avançar)
            btn_buscar = self.page.query_selector('button:has-text("Buscar"):not([disabled])')
            if not btn_buscar:
                btn_buscar = self.page.query_selector('button:has-text("Buscar")')
            if btn_buscar:
                btn_buscar.click()
                try:
                    self.page.wait_for_selector('button:has-text("Avançar"):not([disabled]), input[disabled][value], h2:has-text("OPS, OCORREU UM ERRO")', state="visible", timeout=15000)
                except Exception:
                    self.page.wait_for_timeout(3000)
            
            # Fechar modal "OPS, OCORREU UM ERRO!" se aparecer (CPF não encontrado, etc.)
            if self._fechar_modal_erro_ops():
                return False, "CPF não encontrado ou inválido.", None
            
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
                self.dados_pedido['nome_cliente'] = dados_cliente.get('nome', '')
                self.dados_pedido['nome_mae'] = dados_cliente.get('nome_mae', '')
                self.dados_pedido['mes_nascimento'] = dados_cliente.get('mes_nascimento')
                return True, f"Cliente encontrado: {dados_cliente.get('nome', 'N/A')}", dados_cliente
            else:
                return False, "CPF não encontrado ou inválido.", None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 3: {e}")
            return False, f"Erro na Etapa 3: {str(e)}", None
    
    def etapa4_contato(self, celular: str, email: str, celular_secundario: str = None) -> Tuple[bool, str, Optional[str]]:
        """
        Etapa 4: Informações de contato e análise de crédito.
        Campos: contato, confirmacaoContato, contatoSecundario, email, confirmarEmail
        Trata modal "Atenção!" (telefone/email repetidos, e-mail inválido) e modal de crédito.
        
        Returns:
            Tuple (sucesso, mensagem, resultado_credito)
            "TELEFONE_REJEITADO" | "EMAIL_REJEITADO" | "EMAIL_INVALIDO" | "CREDITO_NEGADO"
        """
        try:
            logger.info(f"[PAP] Etapa 4 - Celular: {celular}, Email: {email}")
            
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
                    self.page.wait_for_timeout(500)
            
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
            self.page.wait_for_timeout(800)
            
            # Verificar se o sistema exibiu "Celular inválido" (principal ou secundário)
            if "celular inválido" in self.page.content().lower():
                return False, "CELULAR_INVALIDO", None
            
            # Verificar modal "Atenção!" (email já usado ou inválido) - pode aparecer ao validar
            modal_atencao = self.page.query_selector('h2:has-text("Atenção!")')
            if modal_atencao:
                pagina = self.page.content().lower()
                btn_ok = self.page.query_selector('button:has-text("Ok")')
                if btn_ok:
                    btn_ok.click()
                    self.page.wait_for_timeout(500)
                if "email" in pagina and ("usado" in pagina or "pedido anterior" in pagina):
                    return False, "EMAIL_REJEITADO", None
                if "e-mail inválido" in pagina or "preencha um e-mail válido" in pagina:
                    return False, "EMAIL_INVALIDO", None
            
            # Clicar Avançar para disparar análise de crédito
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
            else:
                self.page.keyboard.press("Tab")
                self.page.wait_for_timeout(500)
                btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
                if btn_avancar:
                    btn_avancar.click()
            
            # Verificar modal "Atenção!" (obrigatório clicar Ok para destravar a tela)
            for _ in range(10):
                self.page.wait_for_timeout(1000)
                modal_atencao = self.page.query_selector('h2:has-text("Atenção!")')
                if modal_atencao:
                    pagina = self.page.content().lower()
                    btn_ok = self.page.query_selector('button:has-text("Ok")')
                    if btn_ok:
                        btn_ok.click()
                        self.page.wait_for_timeout(500)
                    if "excede" in pagina or "repetições" in pagina:
                        return False, "TELEFONE_REJEITADO", None
                    if "email" in pagina and ("usado" in pagina or "pedido anterior" in pagina):
                        return False, "EMAIL_REJEITADO", None
                    if "e-mail inválido" in pagina or "preencha um e-mail válido" in pagina:
                        return False, "EMAIL_INVALIDO", None
            
            # Aguardar modal "Resultado da análise de crédito" (ignorar spinner/overlay)
            try:
                self.page.wait_for_selector('h2:has-text("Resultado da análise de crédito")', state="visible", timeout=20000)
            except Exception:
                pass
            
            self.page.wait_for_timeout(2000)
            pagina_texto = self.page.content().lower()
            
            # Crédito negado - fechar modal antes de retornar
            if "crédito negado" in pagina_texto or "credito negado" in pagina_texto or ("negado" in pagina_texto and "aprovado" not in pagina_texto):
                for btn_text in ['Consultar outro CPF/CNPJ', 'Ok', 'Fechar']:
                    btn = self.page.query_selector(f'button:has-text("{btn_text}")')
                    if btn:
                        try:
                            btn.click()
                            self.page.wait_for_timeout(500)
                        except Exception:
                            pass
                        break
                return False, "CREDITO_NEGADO", None
            
            # Crédito aprovado (todas formas ou apenas cartão)
            if "crédito aprovado" in pagina_texto or "credito aprovado" in pagina_texto:
                if "apenas" in pagina_texto and "cartão" in pagina_texto:
                    resultado_credito = "Elegível apenas para Cartão de Crédito"
                else:
                    resultado_credito = "Elegível para todas as formas de pagamento"
                
                # Clicar Continuar - force=True ignora spinner/overlay que interceptam
                try:
                    self.page.locator('button:has-text("Continuar")').first.click(force=True, timeout=5000)
                    self.page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    # Fallback: clique via JS (ignora totalmente overlays)
                    self.page.evaluate("""() => {
                        const btn = document.querySelector('button');
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
                return True, f"Análise de crédito: APROVADO! ({resultado_credito})", resultado_credito
            
            # Site avançou direto para Etapa 5 (Pagamento/Ofertas) sem modal - crédito aprovado
            etapa5_visivel = (
                'pagamento' in pagina_texto and 'ofertas' in pagina_texto
            ) or self.page.query_selector('input[value="BOLETO"], input[value="CREDITO"], input[value="DACC"]')
            if etapa5_visivel:
                self.etapa_atual = 4
                self.dados_pedido['celular'] = celular
                self.dados_pedido['email'] = email
                if celular_secundario:
                    self.dados_pedido['celular_sec'] = celular_secundario
                return True, "Análise de crédito: APROVADO! (Elegível para todas as formas de pagamento)", "Elegível para todas as formas de pagamento"
            
            return False, "Não foi possível obter resultado da análise de crédito.", None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 4: {e}")
            return False, f"Erro na Etapa 4: {str(e)}", None
    
    def _etapa5_garantir_pagina(self):
        """Garante que a página da etapa 5 (pagamento/ofertas) está carregada."""
        self.page.wait_for_selector('input[value="BOLETO"], input[value="CREDITO"], input[value="DACC"]', state="visible", timeout=15000)

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

    def _fechar_modal_erro_ops(self) -> bool:
        """Fecha o modal 'OPS, OCORREU UM ERRO!' clicando em 'Tentar novamente'."""
        try:
            if "OPS, OCORREU UM ERRO" not in (self.page.content() or ""):
                return False
            btn = self.page.query_selector('button:has-text("Tentar novamente")')
            if btn:
                btn.click()
                self.page.wait_for_timeout(500)
                return True
            return False
        except Exception:
            return False

    def _etapa5_clicar_salvar_painel(self) -> bool:
        """
        Clica no botão "Salvar" do painel de serviços (NÃO "Salvar Interesse").
        O botão "Salvar Interesse" tem classe sc-dCaJBF - excluímos explicitamente.
        """
        try:
            btns = self.page.query_selector_all('button')
            for b in btns:
                txt = (b.inner_text() or "").strip()
                if txt == "Salvar":
                    # Excluir "Salvar Interesse" (texto exato)
                    cls = b.get_attribute("class") or ""
                    if "dCaJBF" in cls or "hBqtbW" in cls:
                        continue
                    if b.is_visible():
                        b.click()
                        self.page.wait_for_timeout(500)
                        return True
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

    def etapa5_selecionar_fixo(self, tem_fixo: bool) -> Tuple[bool, str]:
        """
        Seleciona Fixo (R$ 30). Fluxo: clicar seta Serviços disponíveis -> Fixo aparece
        -> clicar Fixo -> marcar opção no painel -> Salvar (NÃO Salvar Interesse).
        """
        try:
            self._etapa5_garantir_pagina()
            if tem_fixo:
                # 1. Expandir "Serviços adicionais" se colapsado
                serv_adic = self.page.query_selector('[class*="sc-"]:has-text("Serviços adicionais")')
                if serv_adic:
                    serv_adic.click()
                    self.page.wait_for_timeout(400)
                # 2. Clicar na seta de "Serviços disponíveis" para expandir (mostra Fixo)
                # A seta (svg) está na mesma linha que o texto
                serv_row = self.page.query_selector('div:has-text("Serviços disponíveis")')
                if serv_row:
                    serv_row.click()
                    self.page.wait_for_timeout(600)
                # 3. Clicar em "Fixo" (div.sc-dcmekm.dBGnOE) para abrir painel
                fixo_elem = self.page.query_selector('div.sc-dcmekm.dBGnOE:has-text("Fixo"), div:has-text("Fixo"):not([disabled])')
                if fixo_elem and fixo_elem.is_visible():
                    fixo_elem.click()
                    self.page.wait_for_timeout(600)
                # 4. Marcar opção no painel (checkbox/div com img)
                opc = self.page.query_selector('div.sc-jIyBzM.bSKio, div[class*="jIyBzM"]:has(img)')
                if not opc:
                    opc = self.page.query_selector('div:has(img)[class*="sc-"]')
                if opc and opc.is_visible():
                    opc.click()
                    self.page.wait_for_timeout(400)
                # 5. Clicar Salvar do painel (NUNCA Salvar Interesse)
                self._etapa5_clicar_salvar_painel()
            self.dados_pedido['tem_fixo'] = tem_fixo
            return True, "OK"
        except Exception as e:
            logger.error(f"[PAP] Erro ao selecionar fixo: {e}")
            return False, str(e)

    def etapa5_selecionar_streaming(self, tem_streaming: bool, streaming_opcoes: str = None, plano: str = "") -> Tuple[bool, str]:
        """
        Seleciona streaming. Fluxo: clicar "Streaming e canais on-line" -> marcar opções
        (HBO Max, Globoplay Premium, Globoplay Padrão) -> Salvar (NÃO Salvar Interesse).
        Plano Padrão com Anúncios não está disponível para 700Mb e 1Gb (já incluso).
        """
        try:
            self._etapa5_garantir_pagina()
            if not tem_streaming:
                self.dados_pedido['tem_streaming'] = False
                return True, "OK"
            # 1. Clicar em "Streaming e canais on-line" para expandir
            stream_row = self.page.query_selector('div:has-text("Streaming e canais on-line")')
            if stream_row:
                stream_row.click()
                self.page.wait_for_timeout(600)
            # 2. Marcar opções (div.sc-dcmekm.dBGnOE = clicável; kaHRcu = disabled)
            plano_lower = (plano or self.dados_pedido.get('plano', '')).lower()
            skip_padrao = '700mega' in plano_lower or '1giga' in plano_lower  # já incluso
            opts = (streaming_opcoes or '').lower().replace(' ', '').split(',')
            for o in opts:
                o = o.strip()
                if not o:
                    continue
                el = None
                if 'hbomax' in o or o == 'hbo':
                    el = self.page.query_selector('div.sc-dcmekm.dBGnOE:has-text("HBO Max"), div:has-text("HBO Max"):not([disabled])')
                elif 'globoplay_premium' in o or ('premium' in o and 'basico' not in o):
                    el = self.page.query_selector('div.sc-dcmekm:has-text("Plano Premium"):not([disabled])')
                elif ('globoplay_basico' in o or 'basico' in o or 'padrão' in o or 'padrao' in o) and not skip_padrao:
                    el = self.page.query_selector('div.sc-dcmekm:has-text("Plano Padrão com Anúncios"), div:has-text("Plano Padrão"):not([disabled])')
                if el and el.is_visible() and el.get_attribute('disabled') != 'true':
                    try:
                        el.click()
                    except Exception:
                        self.page.evaluate('(el) => el.click()', el)
                    self.page.wait_for_timeout(400)
            # 3. Clicar Salvar do painel (NUNCA Salvar Interesse)
            self._etapa5_clicar_salvar_painel()
            self.dados_pedido['tem_streaming'] = tem_streaming
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
        Usado na etapa de biometria para enviar ao cliente e validar o "sim".
        """
        d = self.dados_pedido
        nome = d.get('nome_cliente') or 'Cliente'
        cep = d.get('cep') or ''
        numero = d.get('numero') or ''
        ref = d.get('referencia') or ''
        endereco = f"CEP {cep}, Nº {numero}" + (f", Ref: {ref}" if ref else "")
        plano = (d.get('plano') or '500mega').upper()
        forma_raw = (d.get('forma_pagamento') or '').upper()
        cartao = 'CREDITO' in forma_raw or 'CARTÃO' in forma_raw or 'CARTAO' in forma_raw
        # 500Mb: boleto/débito R$100, cartão R$90 | 700Mb: boleto/débito R$130, cartão R$120 | 1Gb: boleto/débito R$160, cartão R$150
        valor_map = {
            '500MEGA': ('R$ 100,00/mês', 'R$ 90,00/mês'),  # (boleto/debito, cartao)
            '700MEGA': ('R$ 130,00/mês', 'R$ 120,00/mês'),
            '1GIGA': ('R$ 160,00/mês', 'R$ 150,00/mês'),
        }
        par = valor_map.get(plano.upper(), ('R$ --', 'R$ --'))
        valor = par[1] if cartao else par[0]
        forma = (d.get('forma_pagamento') or 'Boleto').replace('CREDITO', 'Cartão').replace('BOLETO', 'Boleto').replace('DACC', 'Débito')
        return (
            f"*RESUMO DO PEDIDO*\n\n"
            f"Nome do cliente: {nome}\n"
            f"Endereço: {endereco}\n"
            f"Plano: {plano}\n"
            f"Valor: {valor}\n"
            f"Forma de pagamento: {forma}\n"
            f"Fidelidade: 12 meses\n\n"
            f"Taxa de habilitação: Você ganha isenção da taxa de habilitação se permanecer no mínimo 12 meses com a gente."
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
            
            # Verificar status da biometria
            pagina_texto = (self.page.content() or "").lower()
            span_biometria = self.page.query_selector('span:has-text("Biometria")')
            status_biometria = (span_biometria.inner_text() or "").lower() if span_biometria else ""
            
            biometria_pendente = (
                'pendente' in pagina_texto or
                'pendente' in status_biometria or
                'aguardando' in pagina_texto or
                'em análise' in pagina_texto
            )
            
            # Verificar se botão Abrir OS está disponível (não disabled) = biometria aprovada
            btn_abrir_os = self.page.query_selector('button:has-text("Abrir OS"):not([disabled]), button:has-text("Abrir O.S"):not([disabled])')
            
            if btn_abrir_os:
                self.etapa_atual = 6
                return True, "Biometria APROVADA! Pronto para abrir O.S.", True
            elif biometria_pendente:
                return True, "Biometria PENDENTE. Peça ao cliente para realizar a biometria e digite CONSULTAR para verificar novamente.", False
            else:
                return False, "Biometria não aprovada ou não disponível.", False
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 6: {e}")
            return False, f"Erro na Etapa 6: {str(e)}", False
    
    def etapa7_ir_para_agendamento(self) -> Tuple[bool, str]:
        """Clica em Abrir OS e aguarda a tela de Agendamento aparecer."""
        try:
            btn = self.page.query_selector('button:has-text("Abrir OS"):not([disabled]), button:has-text("Abrir O.S"):not([disabled])')
            if not btn:
                return False, "Botão Abrir OS não disponível."
            btn.click()
            self.page.wait_for_timeout(2000)
            self.page.wait_for_selector('h3:has-text("Período"), [class*="react-datepicker"], [class*="Agendamento"]', state="visible", timeout=15000)
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
            # Períodos: li com "08h às 10h - Manhã", "10h às 12h - Manhã", etc
            periodos = self.page.query_selector_all('li:has-text("Manhã"), li:has-text("Tarde")')
            if not periodos:
                periodos = self.page.query_selector_all('li:has-text("às")')
            labels = []
            for i, p in enumerate(periodos):
                lbl = (p.inner_text() or "").strip()
                if lbl:
                    labels.append({"idx": i + 1, "label": lbl})
            return True, "OK", labels
        except Exception as e:
            logger.error(f"[PAP] etapa7_selecionar_data: {e}")
            return False, str(e), []

    def etapa7_selecionar_periodo(self, indice: int) -> Tuple[bool, str]:
        """Seleciona o período pelo índice. NÃO clica em Agendar (apenas seleciona o turno)."""
        try:
            periodos = self.page.query_selector_all('li:has-text("Manhã"), li:has-text("Tarde")')
            if not periodos:
                periodos = self.page.query_selector_all('li:has-text("às")')
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
