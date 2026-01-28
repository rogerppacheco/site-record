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
    # Login Vtal
    'login': {
        'matricula': '#inputMatricula',
        'senha': '#passwordInput',
        'btn_login': 'button',
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
        'endereco_resultado': 'input[disabled]',
        'lista_enderecos': 'li',
        'referencia': 'input[placeholder*="referência"], textarea[placeholder*="referência"]',
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 3: Cadastro do Cliente
    'etapa3': {
        'cpf': 'input[placeholder*="CPF"]',
        'btn_buscar': 'button:has-text("Buscar")',
        'nome_cliente': 'input[disabled][value]',  # Nome vem preenchido
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 4: Contato
    'etapa4': {
        'celular_principal': 'input[placeholder*="celular"], input[name*="celular"]',
        'confirmar_celular': 'input[placeholder*="confirme"], input[name*="confirmar"]',
        'celular_secundario': 'input[placeholder*="secundário"]',
        'email': 'input[type="email"], input[placeholder*="email"]',
        'confirmar_email': 'input[placeholder*="confirme"][type="email"]',
        'resultado_credito': '.resultado-credito, [class*="credito"], [class*="analise"]',
        'btn_continuar': 'button:has-text("Continuar")',
        'btn_avancar': 'button:has-text("Avançar")',
    },
    
    # Etapa 5: Pagamento/Ofertas
    'etapa5': {
        'forma_boleto': 'input[value="boleto"], label:has-text("Boleto")',
        'forma_cartao': 'input[value="cartao"], label:has-text("Cartão")',
        'forma_debito': 'input[value="debito"], label:has-text("Débito")',
        'plano_1giga': '[class*="card"]:has-text("1 Giga"), [class*="plano"]:has-text("1 Giga")',
        'plano_700mega': '[class*="card"]:has-text("700 Mega"), [class*="plano"]:has-text("700 Mega")',
        'plano_500mega': '[class*="card"]:has-text("500 Mega"), [class*="plano"]:has-text("500 Mega")',
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
    
    def __init__(self, matricula_pap: str, senha_pap: str, vendedor_nome: str = None):
        """
        Inicializa a automação PAP.
        
        Args:
            matricula_pap: Matrícula do vendedor no PAP
            senha_pap: Senha + OTP do PAP
            vendedor_nome: Nome do vendedor (para logs)
        """
        self.matricula_pap = matricula_pap
        self.senha_pap = senha_pap
        self.vendedor_nome = vendedor_nome or matricula_pap
        
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
            
            playwright = sync_playwright().start()
            self.browser = playwright.chromium.launch(headless=True)
            
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
            self.page.goto(PAP_LOGIN_URL, wait_until="networkidle", timeout=60000)
            self.page.wait_for_timeout(2000)
            
            # Verificar se precisa fazer login
            current_url = self.page.url
            
            if "login.vtal.com" in current_url or "login" in current_url.lower():
                # Fazer login
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
        
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            logger.info(f"[PAP] Fazendo login para {self.matricula_pap}")
            
            # Preencher matrícula
            self.page.fill(SELETORES['login']['matricula'], self.matricula_pap)
            self.page.wait_for_timeout(500)
            
            # Preencher senha
            self.page.fill(SELETORES['login']['senha'], self.senha_pap)
            self.page.wait_for_timeout(500)
            
            # Clicar no botão de login
            self.page.click(SELETORES['login']['btn_login'])
            
            # Aguardar redirecionamento
            self.page.wait_for_timeout(5000)
            
            # Verificar se login foi bem-sucedido
            current_url = self.page.url
            if "pap.niointernet.com.br" in current_url and "login" not in current_url.lower():
                logger.info(f"[PAP] Login bem-sucedido para {self.matricula_pap}")
                return True, "Login realizado com sucesso!"
            else:
                return False, "Falha no login. Verifique matrícula e senha."
                
        except Exception as e:
            logger.error(f"[PAP] Erro no login: {e}")
            return False, f"Erro no login: {str(e)}"
    
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
            self.page.goto(PAP_NOVO_PEDIDO_URL, wait_until="networkidle", timeout=60000)
            self.page.wait_for_timeout(3000)
            
            # Verificar se chegou na página correta
            if "novo-pedido" not in self.page.url:
                return False, "Não foi possível acessar a página de novo pedido."
            
            # Aguardar campos carregarem
            self.page.wait_for_timeout(2000)
            
            # Campo de matrícula do vendedor
            matricula_input = self.page.query_selector(SELETORES['etapa1']['matricula_vendedor'])
            if matricula_input:
                # Focar no campo para abrir lista
                matricula_input.click()
                self.page.wait_for_timeout(1000)
                
                # Digitar matrícula
                matricula_input.fill(matricula_vendedor)
                self.page.wait_for_timeout(1500)
                
                # Procurar e clicar na opção da lista
                lista_items = self.page.query_selector_all(SELETORES['etapa1']['lista_vendedores'])
                for item in lista_items:
                    if matricula_vendedor in item.inner_text():
                        item.click()
                        self.page.wait_for_timeout(500)
                        break
            
            # Verificar se botão Avançar está habilitado
            self.page.wait_for_timeout(1000)
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            
            if btn_avancar:
                self.etapa_atual = 1
                self.dados_pedido['matricula_vendedor'] = matricula_vendedor
                return True, "Etapa 1 concluída! Vendedor selecionado."
            else:
                return False, "Não foi possível selecionar o vendedor. Verifique a matrícula."
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 1: {e}")
            return False, f"Erro na Etapa 1: {str(e)}"
    
    def etapa2_viabilidade(self, cep: str, numero: str, referencia: str) -> Tuple[bool, str, Optional[list]]:
        """
        Etapa 2: Consulta de viabilidade.
        
        Args:
            cep: CEP do endereço
            numero: Número do endereço
            referencia: Referência do endereço
            
        Returns:
            Tuple (sucesso, mensagem, lista_enderecos_se_multiplos)
        """
        try:
            logger.info(f"[PAP] Etapa 2 - CEP: {cep}, Número: {numero}")
            
            # Clicar em Avançar da etapa anterior se ainda não avançou
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
                self.page.wait_for_timeout(2000)
            
            # Preencher CEP
            cep_limpo = re.sub(r'\D', '', cep)
            self._set_valor_react(SELETORES['etapa2']['cep'], cep_limpo)
            self.page.wait_for_timeout(500)
            
            # Preencher número
            self._set_valor_react(SELETORES['etapa2']['numero'], numero)
            self.page.wait_for_timeout(500)
            
            # Clicar em Buscar
            btn_buscar = self.page.query_selector('button:has-text("Buscar"):not([disabled])')
            if btn_buscar:
                btn_buscar.click()
                self.page.wait_for_timeout(3000)
            else:
                return False, "Botão Buscar não disponível. Verifique CEP e número.", None
            
            # Verificar se há múltiplos endereços
            lista_enderecos = self.page.query_selector_all(SELETORES['etapa2']['lista_enderecos'])
            if len(lista_enderecos) > 1:
                # Retornar lista de endereços para o usuário escolher
                enderecos = []
                for i, item in enumerate(lista_enderecos):
                    enderecos.append({
                        'indice': i + 1,
                        'texto': item.inner_text()
                    })
                return True, "Múltiplos endereços encontrados. Escolha um:", enderecos
            
            # Verificar se viabilidade OK
            self.page.wait_for_timeout(2000)
            
            # Preencher referência
            referencia_input = self.page.query_selector(SELETORES['etapa2']['referencia'])
            if referencia_input:
                referencia_input.fill(referencia)
                self.page.wait_for_timeout(500)
            
            # Verificar se pode avançar
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                self.etapa_atual = 2
                self.dados_pedido['cep'] = cep
                self.dados_pedido['numero'] = numero
                self.dados_pedido['referencia'] = referencia
                return True, "Etapa 2 concluída! Endereço viável.", None
            else:
                # Verificar mensagem de erro de viabilidade
                erro = self._extrair_texto('[class*="erro"], [class*="error"], [class*="alert"]')
                if erro:
                    return False, f"Endereço sem viabilidade: {erro}", None
                return False, "Endereço pode não ter viabilidade. Verifique os dados.", None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 2: {e}")
            return False, f"Erro na Etapa 2: {str(e)}", None
    
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
                self.page.wait_for_timeout(1000)
                return True, "Endereço selecionado!"
            return False, "Índice de endereço inválido."
        except Exception as e:
            return False, f"Erro ao selecionar endereço: {str(e)}"
    
    def etapa3_cadastro_cliente(self, cpf: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        Etapa 3: Cadastro do cliente.
        
        Args:
            cpf: CPF do cliente
            
        Returns:
            Tuple (sucesso, mensagem, dados_cliente)
        """
        try:
            logger.info(f"[PAP] Etapa 3 - CPF: {cpf}")
            
            # Avançar se necessário
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
                self.page.wait_for_timeout(2000)
            
            # Preencher CPF
            cpf_limpo = re.sub(r'\D', '', cpf)
            self._set_valor_react(SELETORES['etapa3']['cpf'], cpf_limpo)
            self.page.wait_for_timeout(500)
            
            # Buscar cliente
            btn_buscar = self.page.query_selector('button:has-text("Buscar"):not([disabled])')
            if btn_buscar:
                btn_buscar.click()
                self.page.wait_for_timeout(3000)
            
            # Extrair dados do cliente
            dados_cliente = {}
            nome_elem = self.page.query_selector(SELETORES['etapa3']['nome_cliente'])
            if nome_elem:
                dados_cliente['nome'] = nome_elem.get_attribute('value') or nome_elem.inner_text()
            
            # Verificar se pode avançar
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                self.etapa_atual = 3
                self.dados_pedido['cpf_cliente'] = cpf
                self.dados_pedido['nome_cliente'] = dados_cliente.get('nome', '')
                return True, f"Cliente encontrado: {dados_cliente.get('nome', 'N/A')}", dados_cliente
            else:
                return False, "CPF não encontrado ou inválido.", None
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 3: {e}")
            return False, f"Erro na Etapa 3: {str(e)}", None
    
    def etapa4_contato(self, celular: str, email: str, celular_secundario: str = None) -> Tuple[bool, str, Optional[str]]:
        """
        Etapa 4: Informações de contato e análise de crédito.
        
        Args:
            celular: Celular principal
            email: E-mail do cliente
            celular_secundario: Celular secundário (opcional)
            
        Returns:
            Tuple (sucesso, mensagem, resultado_credito)
        """
        try:
            logger.info(f"[PAP] Etapa 4 - Celular: {celular}, Email: {email}")
            
            # Avançar se necessário
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
                self.page.wait_for_timeout(2000)
            
            # Preencher celular principal
            celular_limpo = re.sub(r'\D', '', celular)
            inputs_celular = self.page.query_selector_all('input[placeholder*="celular"], input[type="tel"]')
            if len(inputs_celular) >= 2:
                # Primeiro campo: celular principal
                inputs_celular[0].fill(celular_limpo)
                self.page.wait_for_timeout(300)
                # Segundo campo: confirmação
                inputs_celular[1].fill(celular_limpo)
                self.page.wait_for_timeout(300)
            
            # Preencher celular secundário se informado
            if celular_secundario:
                cel_sec_limpo = re.sub(r'\D', '', celular_secundario)
                cel_sec_input = self.page.query_selector('input[placeholder*="secundário"]')
                if cel_sec_input:
                    cel_sec_input.fill(cel_sec_limpo)
                    self.page.wait_for_timeout(300)
            
            # Preencher email
            inputs_email = self.page.query_selector_all('input[type="email"]')
            if len(inputs_email) >= 2:
                inputs_email[0].fill(email)
                self.page.wait_for_timeout(300)
                inputs_email[1].fill(email)
                self.page.wait_for_timeout(300)
            
            # Aguardar análise de crédito
            self.page.wait_for_timeout(3000)
            
            # Extrair resultado da análise de crédito
            resultado_credito = self._extrair_texto(SELETORES['etapa4']['resultado_credito'])
            if not resultado_credito:
                resultado_credito = self._extrair_texto('[class*="resultado"], [class*="analise"]')
            
            # Verificar se elegível
            pagina_texto = self.page.content().lower()
            elegivel = 'elegível' in pagina_texto or 'aprovado' in pagina_texto or 'continuar' in pagina_texto
            
            if elegivel:
                # Clicar em Continuar se houver (para biometria)
                btn_continuar = self.page.query_selector('button:has-text("Continuar"):not([disabled])')
                if btn_continuar:
                    btn_continuar.click()
                    self.page.wait_for_timeout(2000)
                
                self.etapa_atual = 4
                self.dados_pedido['celular'] = celular
                self.dados_pedido['email'] = email
                return True, "Análise de crédito: APROVADO!", resultado_credito
            else:
                return False, f"Análise de crédito negada ou pendente. {resultado_credito or ''}", resultado_credito
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 4: {e}")
            return False, f"Erro na Etapa 4: {str(e)}", None
    
    def etapa5_pagamento_plano(self, forma_pagamento: str, plano: str) -> Tuple[bool, str]:
        """
        Etapa 5: Escolha de forma de pagamento e plano.
        
        Args:
            forma_pagamento: 'boleto', 'cartao' ou 'debito'
            plano: '1giga', '700mega' ou '500mega'
            
        Returns:
            Tuple (sucesso, mensagem)
        """
        try:
            logger.info(f"[PAP] Etapa 5 - Pagamento: {forma_pagamento}, Plano: {plano}")
            
            # Avançar se necessário
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
                self.page.wait_for_timeout(2000)
            
            # Selecionar forma de pagamento
            forma_map = {
                'boleto': SELETORES['etapa5']['forma_boleto'],
                'cartao': SELETORES['etapa5']['forma_cartao'],
                'debito': SELETORES['etapa5']['forma_debito'],
            }
            
            if forma_pagamento.lower() in forma_map:
                forma_elem = self.page.query_selector(forma_map[forma_pagamento.lower()])
                if forma_elem:
                    forma_elem.click()
                    self.page.wait_for_timeout(1000)
            
            # Selecionar plano
            plano_map = {
                '1giga': SELETORES['etapa5']['plano_1giga'],
                '700mega': SELETORES['etapa5']['plano_700mega'],
                '500mega': SELETORES['etapa5']['plano_500mega'],
            }
            
            if plano.lower() in plano_map:
                plano_elem = self.page.query_selector(plano_map[plano.lower()])
                if plano_elem:
                    plano_elem.click()
                    self.page.wait_for_timeout(1000)
            
            # Verificar se pode avançar
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                self.etapa_atual = 5
                self.dados_pedido['forma_pagamento'] = forma_pagamento
                self.dados_pedido['plano'] = plano
                return True, f"Plano {plano.upper()} com pagamento via {forma_pagamento.upper()} selecionados!"
            else:
                return False, "Não foi possível selecionar plano/pagamento."
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 5: {e}")
            return False, f"Erro na Etapa 5: {str(e)}"
    
    def etapa6_verificar_biometria(self) -> Tuple[bool, str, bool]:
        """
        Etapa 6: Verificar status da biometria.
        
        Returns:
            Tuple (sucesso, mensagem, biometria_aprovada)
        """
        try:
            logger.info("[PAP] Etapa 6 - Verificando biometria")
            
            # Avançar se necessário
            btn_avancar = self.page.query_selector('button:has-text("Avançar"):not([disabled])')
            if btn_avancar:
                btn_avancar.click()
                self.page.wait_for_timeout(2000)
            
            # Verificar status da biometria
            pagina_texto = self.page.content().lower()
            
            biometria_aprovada = (
                'aprovada' in pagina_texto or 
                'biometria ok' in pagina_texto or
                'análise aprovada' in pagina_texto
            )
            
            biometria_pendente = (
                'pendente' in pagina_texto or
                'aguardando' in pagina_texto or
                'em análise' in pagina_texto
            )
            
            # Verificar se botão Abrir OS está disponível
            btn_abrir_os = self.page.query_selector('button:has-text("Abrir OS"):not([disabled]), button:has-text("Abrir O.S"):not([disabled])')
            
            if btn_abrir_os:
                self.etapa_atual = 6
                return True, "Biometria APROVADA! Pronto para abrir O.S.", True
            elif biometria_pendente:
                return True, "Biometria PENDENTE. Aguarde o cliente completar a biometria e tente novamente.", False
            else:
                return False, "Biometria não aprovada ou não disponível.", False
                
        except Exception as e:
            logger.error(f"[PAP] Erro na Etapa 6: {e}")
            return False, f"Erro na Etapa 6: {str(e)}", False
    
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
                self.page.wait_for_timeout(3000)
            else:
                return False, "Botão Abrir O.S. não disponível. Verifique a biometria.", None
            
            # Aguardar modal de calendário
            self.page.wait_for_timeout(2000)
            
            # Se data específica foi informada, tentar encontrar
            if data_agendamento:
                # Tentar clicar na data específica
                data_elem = self.page.query_selector(f'[data-date="{data_agendamento}"], :has-text("{data_agendamento}")')
                if data_elem:
                    data_elem.click()
                    self.page.wait_for_timeout(500)
            else:
                # Clicar na primeira data disponível
                data_disponivel = self.page.query_selector(SELETORES['etapa7']['data_disponivel'])
                if data_disponivel:
                    data_disponivel.click()
                    self.page.wait_for_timeout(500)
            
            # Selecionar turno
            turno_selector = SELETORES['etapa7']['turno_manha'] if turno.lower() == 'manha' else SELETORES['etapa7']['turno_tarde']
            turno_elem = self.page.query_selector(turno_selector)
            if turno_elem:
                turno_elem.click()
                self.page.wait_for_timeout(500)
            
            # Confirmar
            btn_confirmar = self.page.query_selector('button:has-text("Confirmar"):not([disabled])')
            if btn_confirmar:
                btn_confirmar.click()
                self.page.wait_for_timeout(5000)
            
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
    
    def _fechar_sessao(self):
        """Fecha a sessão do navegador e libera recursos"""
        try:
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
                
        except Exception as e:
            logger.error(f"[PAP] Erro ao fechar sessão: {e}")
        finally:
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
