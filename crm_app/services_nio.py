# crm_app/services_nio.py
"""
Serviço para automação de consulta de faturas no site da Nio Internet
"""

import re
import os
import logging
from datetime import datetime
from decimal import Decimal
from django.conf import settings

logger = logging.getLogger(__name__)

# Tentar importar Playwright
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("[AVISO] Playwright não instalado. Busca automática desabilitada.")

# Configurações
NIO_BASE_URL = "https://www.niointernet.com.br/ajuda/servicos/segunda-via/"  # Plano A
NIO_NEGOCIA_URL = "https://negociacao.niointernet.com.br/negociar"  # Plano B
DEFAULT_STORAGE_STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".playwright_state.json")


def buscar_fatura_nio_por_cpf(cpf, incluir_pdf=True, mes_referencia=None, numero_contrato=None, usar_plano_b=True):
    """
    Busca fatura no site da Nio Internet por CPF com múltiplos métodos (Plano A e Plano B)
    
    Args:
        cpf: CPF do cliente
        incluir_pdf: Se True, busca também o PDF (mais lento)
        mes_referencia: Mês de referência da fatura (YYYYMM) para nomear o arquivo
        numero_contrato: Número do contrato para validação no método Nio Negocia (opcional)
        usar_plano_b: Se True, tenta método Nio Negocia se Plano A falhar
        
    Returns:
        dict com: valor, codigo_pix, codigo_barras, data_vencimento, pdf_url, pdf_path, metodo_usado
        ou None se não encontrou
    """
    if not HAS_PLAYWRIGHT:
        return None
    
    try:
        cpf_limpo = re.sub(r'\D', '', cpf or '')
        if not cpf_limpo:
            return None
        
        # PLANO A: Método atual (Segunda Via)
        logger.info(f"[BUSCA FATURA] Tentando Plano A (Segunda Via) para CPF: {cpf_limpo}")
        try:
            resultado = _buscar_fatura_playwright(cpf_limpo)
            
            # Se precisa do PDF e ainda não tem, tenta baixar
            if incluir_pdf and resultado and not resultado.get('pdf_url') and not resultado.get('pdf_path'):
                pdf_path = _baixar_pdf_como_humano(cpf_limpo, mes_referencia, resultado.get('data_vencimento'))
                if pdf_path:
                    if isinstance(pdf_path, dict):
                        resultado['pdf_path'] = pdf_path.get('local_path')
                        resultado['pdf_url'] = pdf_path.get('onedrive_url') or pdf_path.get('local_path')
                    else:
                        resultado['pdf_path'] = pdf_path
                    logger.info(f"✅ [PDF] Arquivo salvo em: {pdf_path if isinstance(pdf_path, str) else pdf_path.get('local_path')}")
            
            # Verificar se resultado é válido ou se não há dívidas
            if resultado and resultado.get('sem_dividas'):
                logger.info(f"[BUSCA FATURA] ℹ️ Plano A (Segunda Via) - Sem dívidas para este CPF")
                resultado['metodo_usado'] = 'segunda_via'
                return resultado
            elif resultado and (resultado.get('valor') or resultado.get('codigo_pix') or resultado.get('codigo_barras')):
                resultado['metodo_usado'] = 'segunda_via'
                logger.info(f"[BUSCA FATURA] ✅ Plano A (Segunda Via) sucedeu")
                return resultado
            else:
                logger.warning(f"[BUSCA FATURA] ⚠️ Plano A (Segunda Via) não retornou dados válidos")
        except Exception as e:
            logger.warning(f"[BUSCA FATURA] ⚠️ Plano A (Segunda Via) falhou: {e}")
            import traceback
            logger.debug(f"[BUSCA FATURA] Traceback Plano A: {traceback.format_exc()}")
        
        # PLANO B: Método Nio Negocia (se habilitado)
        if usar_plano_b:
            logger.info(f"[BUSCA FATURA] Tentando Plano B (Nio Negocia) para CPF: {cpf_limpo}")
            try:
                resultado_b = _buscar_fatura_nio_negocia(
                    cpf_limpo,
                    numero_contrato=numero_contrato,
                    incluir_pdf=incluir_pdf,
                    mes_referencia=mes_referencia
                )
                
                if resultado_b and (resultado_b.get('valor') or resultado_b.get('codigo_pix') or resultado_b.get('codigo_barras')):
                    resultado_b['metodo_usado'] = 'nio_negocia'
                    logger.info(f"[BUSCA FATURA] ✅ Plano B (Nio Negocia) sucedeu")
                    return resultado_b
                else:
                    logger.warning(f"[BUSCA FATURA] ⚠️ Plano B (Nio Negocia) não retornou dados válidos")
            except Exception as e:
                logger.warning(f"[BUSCA FATURA] ⚠️ Plano B (Nio Negocia) falhou: {e}")
                import traceback
                logger.debug(f"[BUSCA FATURA] Traceback Plano B: {traceback.format_exc()}")
        
        logger.error(f"[BUSCA FATURA] ❌ Todos os métodos falharam para CPF: {cpf_limpo}")
        return None
        
    except Exception as e:
        logger.error(f"[BUSCA FATURA] Erro geral: {e}")
        import traceback
        traceback.print_exc()
        return None


def _baixar_pdf_como_humano(cpf, mes_referencia=None, data_vencimento=None):
    """
    Replica o comportamento humano para baixar PDF:
    1. Clica em "Gerar boleto"
    2. Clica em "Download" ou "Baixar PDF"
    3. Salva na pasta downloads com nome: CPF_mes_vencimento.pdf
    
    Returns:
        Caminho do arquivo salvo ou None
    """
    if not HAS_PLAYWRIGHT:
        return None
    
    try:
        from playwright.sync_api import sync_playwright
        
        # Criar pasta downloads se não existir
        downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Nome do arquivo: CPF_mes_vencimento.pdf
        if mes_referencia:
            nome_arquivo = f"{cpf}_{mes_referencia}.pdf"
        elif data_vencimento:
            # Converter data_vencimento para formato YYYYMM
            if isinstance(data_vencimento, str):
                try:
                    from datetime import datetime
                    if len(data_vencimento) == 8 and data_vencimento.isdigit():
                        # Formato YYYYMMDD
                        data = datetime.strptime(data_vencimento, '%Y%m%d')
                        mes_ref = data.strftime('%Y%m')
                    else:
                        mes_ref = data_vencimento[:6] if len(data_vencimento) >= 6 else 'unknown'
                except:
                    mes_ref = 'unknown'
            else:
                mes_ref = data_vencimento.strftime('%Y%m') if hasattr(data_vencimento, 'strftime') else 'unknown'
            nome_arquivo = f"{cpf}_{mes_ref}.pdf"
        else:
            from datetime import datetime
            mes_ref = datetime.now().strftime('%Y%m')
            nome_arquivo = f"{cpf}_{mes_ref}.pdf"
        
        caminho_completo = os.path.join(downloads_dir, nome_arquivo)
        
        print(f"[DEBUG PDF DOWNLOAD] 🚀 INICIANDO download como humano para CPF: {cpf}")
        print(f"[DEBUG PDF DOWNLOAD] 📁 Arquivo será salvo em: {caminho_completo}")
        print(f"[DEBUG PDF DOWNLOAD] 📋 Parâmetros: mes_ref={mes_referencia}, data_venc={data_vencimento}")
        logger.info(f"[PDF HUMANO] Iniciando download como humano para CPF: {cpf}")
        logger.info(f"[PDF HUMANO] Arquivo será salvo em: {caminho_completo}")
        logger.info(f"[PDF HUMANO] Parâmetros: mes_ref={mes_referencia}, data_venc={data_vencimento}")
        
        print(f"[DEBUG PDF DOWNLOAD] 🌐 Iniciando Playwright (headless=True)...")
        logger.info(f"[PDF HUMANO] Iniciando Playwright...")
        
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
            
            # 1. Ir para página inicial
            print(f"[DEBUG PDF DOWNLOAD] 📍 PASSO 1: Navegando para {NIO_BASE_URL}")
            logger.info(f"[PDF HUMANO] Passo 1: Navegando para {NIO_BASE_URL}")
            try:
                page.goto(NIO_BASE_URL, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                print(f"[DEBUG PDF DOWNLOAD] ✅ PASSO 1: Página carregada com sucesso")
                logger.info(f"[PDF HUMANO] Página carregada com sucesso")
            except Exception as e:
                print(f"[DEBUG PDF DOWNLOAD] ❌ PASSO 1: Erro ao carregar página: {e}")
                logger.error(f"[PDF HUMANO] Erro ao carregar página inicial: {e}")
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[PDF HUMANO] Traceback: {tb}")
                print(f"[DEBUG PDF DOWNLOAD] Traceback: {tb}")
                browser.close()
                return None
            
            # Debug: capturar screenshot e HTML para análise
            try:
                screenshot_path = os.path.join(downloads_dir, f"debug_{cpf}_pagina_inicial.png")
                page.screenshot(path=screenshot_path)
                logger.info(f"[PDF HUMANO] Screenshot salvo: {screenshot_path}")
            except Exception as e:
                logger.warning(f"[PDF HUMANO] Erro ao salvar screenshot: {e}")
            
            # 2. Preencher CPF e consultar
            print(f"[DEBUG PDF DOWNLOAD] 📍 PASSO 2: Preenchendo CPF e consultando...")
            logger.info(f"[PDF HUMANO] Passo 2: Preenchendo CPF e consultando...")
            
            # Aguardar um pouco mais para garantir que a página carregou completamente
            page.wait_for_timeout(2000)
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            print(f"[DEBUG PDF DOWNLOAD] 🔍 Tentando encontrar campo de CPF...")
            logger.info(f"[PDF HUMANO] Tentando encontrar campo de CPF...")
            
            # Tentar vários seletores possíveis para o campo CPF
            campo_cpf = None
            seletores_cpf = [
                '#cpf-cnpj',  # Seletor correto por ID
                'input#cpf-cnpj',  # Input com ID específico
                'input[name="cpf-cnpj"]',  # Por name attribute
                'input.segunda-via__input',  # Por classe
                'input[placeholder*="CPF" i]',  # case insensitive
                'input[placeholder*="cpf" i]',
                'input[placeholder*="CPF/CNPJ" i]',
                'input[name*="cpf" i]',
                'input[name*="CPF" i]',
                'input[id*="cpf" i]',
                'input[id*="CPF" i]',
                'input[class*="cpf" i]',
                'input[class*="CPF" i]',
                'input[type="text"]',
                'input[type="tel"]',
                'input[type="number"]',
                'input',
            ]
            
            for seletor in seletores_cpf:
                try:
                    locator = page.locator(seletor).first
                    count = locator.count()
                    logger.debug(f"[PDF HUMANO] Seletor '{seletor}': encontrados {count} elementos")
                    if count > 0:
                        # Verificar se está visível e editável
                        try:
                            if locator.is_visible(timeout=3000):
                                # Verificar se é editável
                                if locator.is_editable(timeout=2000):
                                    campo_cpf = locator
                                    logger.info(f"[PDF HUMANO] ✅ Campo CPF encontrado com seletor: {seletor}")
                                    break
                                else:
                                    logger.debug(f"[PDF HUMANO] Seletor '{seletor}' encontrado mas não é editável")
                            else:
                                logger.debug(f"[PDF HUMANO] Seletor '{seletor}' encontrado mas não está visível")
                        except Exception as e_vis:
                            logger.debug(f"[PDF HUMANO] Erro ao verificar visibilidade/editabilidade do seletor '{seletor}': {e_vis}")
                except Exception as e:
                    logger.debug(f"[PDF HUMANO] Seletor '{seletor}' falhou: {e}")
                    continue
            
            if not campo_cpf:
                print(f"[DEBUG PDF DOWNLOAD] ❌ PASSO 2: Nenhum campo de CPF encontrado após tentar {len(seletores_cpf)} seletores!")
                logger.error(f"[PDF HUMANO] ❌ Nenhum campo de CPF encontrado após tentar {len(seletores_cpf)} seletores!")
                # Salvar HTML para debug
                try:
                    html_path = os.path.join(downloads_dir, f"debug_{cpf}_html.html")
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(page.content())
                    print(f"[DEBUG PDF DOWNLOAD] 💾 HTML salvo para debug: {html_path}")
                    logger.info(f"[PDF HUMANO] HTML salvo para debug: {html_path}")
                except Exception as e_html:
                    logger.warning(f"[PDF HUMANO] Erro ao salvar HTML: {e_html}")
                browser.close()
                return None
            
            # Preencher CPF
            try:
                print(f"[DEBUG PDF DOWNLOAD] ✍️ Preenchendo campo CPF com: {cpf}")
                logger.info(f"[PDF HUMANO] Preenchendo campo CPF com: {cpf}")
                campo_cpf.fill(cpf, timeout=10000)
                print(f"[DEBUG PDF DOWNLOAD] ✅ CPF preenchido com sucesso")
                logger.info(f"[PDF HUMANO] ✅ CPF preenchido com sucesso")
            except Exception as e:
                print(f"[DEBUG PDF DOWNLOAD] ❌ Erro ao preencher CPF: {e}")
                logger.error(f"[PDF HUMANO] ❌ Erro ao preencher CPF: {e}")
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[PDF HUMANO] Traceback: {tb}")
                print(f"[DEBUG PDF DOWNLOAD] Traceback: {tb}")
                browser.close()
                return None
            
            # Clicar em Consultar - tentar botão ou ícone de seta
            try:
                logger.info(f"[PDF HUMANO] Procurando botão Consultar ou ícone de seta...")
                btn_consultar = None
                
                # Tentar primeiro o botão
                seletores_consultar = [
                    'button.segunda-via__button[type="submit"]',  # Botão principal
                    'button[type="submit"]',  # Botão submit genérico
                    'img.segunda-via__icon-button[alt*="seta" i]',  # Ícone de seta por classe e alt
                    'img[alt*="Ícone de seta" i]',  # Ícone de seta por alt text
                    'img.segunda-via__icon-button',  # Ícone de seta por classe
                    'img[src*="ArrowRigth.svg"]',  # Ícone de seta por src
                ]
                
                for seletor in seletores_consultar:
                    try:
                        btn = page.locator(seletor).first
                        count = btn.count()
                        if count > 0:
                            if btn.is_visible(timeout=2000):
                                btn_consultar = btn
                                logger.info(f"[PDF HUMANO] Elemento Consultar encontrado com seletor: {seletor}")
                                break
                    except Exception as e_sel:
                        logger.debug(f"[PDF HUMANO] Seletor '{seletor}' falhou: {e_sel}")
                        continue
                
                if btn_consultar and btn_consultar.count() > 0:
                    btn_consultar.click(timeout=10000)
                    logger.info(f"[PDF HUMANO] ✅ Botão/Ícone Consultar clicado")
                else:
                    logger.error(f"[PDF HUMANO] ❌ Nenhum botão/ícone Consultar encontrado após tentar {len(seletores_consultar)} seletores!")
                    browser.close()
                    return None
            except Exception as e:
                logger.error(f"[PDF HUMANO] ❌ Erro ao clicar em Consultar: {e}")
                import traceback
                logger.error(f"[PDF HUMANO] Traceback: {traceback.format_exc()}")
                browser.close()
                return None
            
            page.wait_for_timeout(2000)
            page.wait_for_load_state("networkidle", timeout=20000)
            
            # 3. Clicar em "ver detalhes" se existir - usando seletor correto: span.resultados-entry__action-text
            logger.info(f"[PDF HUMANO] Passo 3: Verificando se precisa expandir detalhes...")
            try:
                ver_detalhes = page.locator('span.resultados-entry__action-text:has-text("Ver detalhes")').first
                count = ver_detalhes.count()
                if count > 0:
                    logger.info(f"[PDF HUMANO] Encontrado 'Ver detalhes', clicando...")
                    ver_detalhes.click()
                    page.wait_for_timeout(5000)  # Aumentado para 5 segundos
                    page.wait_for_load_state("networkidle", timeout=20000)  # Aumentado para 20 segundos
                    logger.info(f"[PDF HUMANO] ✅ Detalhes expandidos")
                    
                    # DIAGNÓSTICO: Capturar screenshot e HTML após expandir detalhes
                    try:
                        screenshot_path = os.path.join(downloads_dir, f"debug_{cpf}_apos_ver_detalhes.png")
                        page.screenshot(path=screenshot_path, full_page=True)
                        print(f"[DEBUG PDF DOWNLOAD] 📸 Screenshot após 'Ver detalhes': {screenshot_path}")
                        logger.info(f"[PDF HUMANO] Screenshot após 'Ver detalhes': {screenshot_path}")
                        
                        html_path = os.path.join(downloads_dir, f"debug_{cpf}_apos_ver_detalhes.html")
                        with open(html_path, 'w', encoding='utf-8') as f:
                            f.write(page.content())
                        print(f"[DEBUG PDF DOWNLOAD] 📄 HTML após 'Ver detalhes': {html_path}")
                        logger.info(f"[PDF HUMANO] HTML após 'Ver detalhes': {html_path}")
                    except Exception as e_debug:
                        logger.warning(f"[PDF HUMANO] Erro ao salvar debug após 'Ver detalhes': {e_debug}")
                else:
                    logger.debug(f"[PDF HUMANO] Não foi necessário expandir detalhes (não encontrado)")
            except Exception as e:
                logger.debug(f"[PDF HUMANO] Não foi necessário expandir detalhes ou erro: {e}")
            
            # DIAGNÓSTICO: Verificar estado do modal via JavaScript
            print(f"[DEBUG PDF DOWNLOAD] 🔍 Investigando estado do modal via JavaScript...")
            logger.info(f"[PDF HUMANO] Investigando estado do modal via JavaScript...")
            try:
                modal_info = page.evaluate("""
                    () => {
                        const info = {
                            modalExists: false,
                            modalVisible: false,
                            boletoExists: false,
                            boletoVisible: false,
                            gerarBoletoExists: false,
                            gerarBoletoVisible: false,
                            allElements: []
                        };
                        
                        // Verificar modal
                        const modal = document.querySelector('div[class*="payment"], div.desktop-payment__item-button-text');
                        if (modal) {
                            info.modalExists = true;
                            const style = window.getComputedStyle(modal);
                            info.modalVisible = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                        }
                        
                        // Verificar opção Boleto
                        const boleto = document.querySelector('div.desktop-payment__item-button-text:has-text("Boleto"), div:has-text("Boleto")');
                        if (boleto) {
                            info.boletoExists = true;
                            const style = window.getComputedStyle(boleto);
                            info.boletoVisible = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                        }
                        
                        // Verificar botão Gerar boleto
                        const gerarBoleto = document.querySelector('a#desktop-generate-boleto, a#generate-boleto');
                        if (gerarBoleto) {
                            info.gerarBoletoExists = true;
                            const style = window.getComputedStyle(gerarBoleto);
                            info.gerarBoletoVisible = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                        }
                        
                        // Listar todos os elementos relacionados
                        const allPayment = document.querySelectorAll('div[class*="payment"], a[id*="boleto"], a[id*="Boleto"]');
                        allPayment.forEach(el => {
                            const style = window.getComputedStyle(el);
                            info.allElements.push({
                                tag: el.tagName,
                                id: el.id,
                                classes: el.className,
                                text: el.textContent?.substring(0, 50),
                                visible: style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0',
                                display: style.display,
                                visibility: style.visibility,
                                opacity: style.opacity
                            });
                        });
                        
                        return info;
                    }
                """)
                print(f"[DEBUG PDF DOWNLOAD] 📊 Estado do modal: {modal_info}")
                logger.info(f"[PDF HUMANO] Estado do modal: {modal_info}")
                
                # Se modal existe mas não está visível, tentar forçar visibilidade
                if modal_info.get('modalExists') and not modal_info.get('modalVisible'):
                    print(f"[DEBUG PDF DOWNLOAD] 🔧 Modal existe mas não está visível, tentando forçar visibilidade...")
                    logger.warning(f"[PDF HUMANO] Modal existe mas não está visível, tentando forçar visibilidade...")
                    page.evaluate("""
                        () => {
                            const modal = document.querySelector('div[class*="payment"], div.desktop-payment__item-button-text');
                            if (modal) {
                                modal.style.display = 'block';
                                modal.style.visibility = 'visible';
                                modal.style.opacity = '1';
                            }
                        }
                    """)
                    page.wait_for_timeout(2000)
            except Exception as e_js:
                print(f"[DEBUG PDF DOWNLOAD] ⚠️ Erro ao investigar modal via JS: {e_js}")
                logger.warning(f"[PDF HUMANO] Erro ao investigar modal via JS: {e_js}")
            
            # Aguardar modal "Escolha como pagar" aparecer
            print(f"[DEBUG PDF DOWNLOAD] ⏳ Aguardando modal 'Escolha como pagar' aparecer...")
            logger.info(f"[PDF HUMANO] Aguardando modal 'Escolha como pagar' aparecer...")
            try:
                # Aguardar até que o modal apareça (verificar por elementos característicos do modal)
                page.wait_for_selector('div.desktop-payment__item-button-text, a#desktop-generate-boleto, div[class*="payment"]', timeout=10000, state='visible')
                page.wait_for_timeout(2000)  # Aguardar animação do modal
                print(f"[DEBUG PDF DOWNLOAD] ✅ Modal apareceu")
                logger.info(f"[PDF HUMANO] ✅ Modal 'Escolha como pagar' apareceu")
            except Exception as e:
                print(f"[DEBUG PDF DOWNLOAD] ⚠️ Modal pode não ter aparecido, continuando mesmo assim: {e}")
                logger.warning(f"[PDF HUMANO] ⚠️ Modal pode não ter aparecido, continuando mesmo assim: {e}")
                page.wait_for_timeout(3000)  # Aguardar um pouco mais
            
            # PASSO 1 (NOVO): Clicar em "Boleto" primeiro (antes de "Gerar boleto")
            print(f"[DEBUG PDF DOWNLOAD] 📍 PASSO 1: Clicando em 'Boleto'...")
            logger.info(f"[PDF HUMANO] Passo 1: Clicando em 'Boleto'...")
            page.wait_for_timeout(1000)
            
            try:
                boleto_option = None
                seletores_boleto = [
                    'div.desktop-payment__item-button-text:has-text("Boleto")',  # Seletor exato fornecido pelo usuário
                    'div.desktop-payment__item-button-text span.desktop-payment__item-title:has-text("Boleto")',
                    'div[class*="desktop-payment__item-button-text"]:has-text("Boleto")',
                    'span.desktop-payment__item-title:has-text("Boleto")',
                    'div:has-text("Boleto"):has-text("Confirmação em até 1 dia útil")',  # Mais específico
                ]
                
                print(f"[DEBUG PDF DOWNLOAD] 🔍 Tentando {len(seletores_boleto)} seletores para 'Boleto'...")
                logger.info(f"[PDF HUMANO] Tentando {len(seletores_boleto)} seletores para encontrar opção 'Boleto'...")
                
                for idx, seletor in enumerate(seletores_boleto, 1):
                    try:
                        print(f"[DEBUG PDF DOWNLOAD]   [{idx}/{len(seletores_boleto)}] Tentando: {seletor}")
                        btn = page.locator(seletor).first
                        count = btn.count()
                        print(f"[DEBUG PDF DOWNLOAD]     Encontrados: {count} elementos")
                        
                        if count > 0:
                            try:
                                btn.scroll_into_view_if_needed(timeout=2000)
                                page.wait_for_timeout(500)
                            except:
                                pass
                            
                            # Verificar se está visível, se não, usar force=True
                            try:
                                if btn.is_visible(timeout=2000):
                                    boleto_option = btn
                                    print(f"[DEBUG PDF DOWNLOAD] ✅ Opção 'Boleto' encontrada e visível com seletor: {seletor}")
                                    logger.info(f"[PDF HUMANO] Opção 'Boleto' encontrada e visível com seletor: {seletor}")
                                    break
                                else:
                                    # Elemento existe mas não está visível, vamos usar force=True
                                    boleto_option = btn
                                    print(f"[DEBUG PDF DOWNLOAD]     Elemento encontrado mas não visível, será usado com force=True")
                                    break
                            except:
                                # Se verificação falhar, usar mesmo assim com force=True
                                boleto_option = btn
                                print(f"[DEBUG PDF DOWNLOAD]     Elemento encontrado, será usado com force=True")
                                break
                        else:
                            print(f"[DEBUG PDF DOWNLOAD]     Nenhum elemento encontrado")
                    except Exception as e_sel:
                        print(f"[DEBUG PDF DOWNLOAD]     Erro: {e_sel}")
                        logger.debug(f"[PDF HUMANO] Seletor '{seletor}' falhou: {e_sel}")
                        continue
                
                if boleto_option and boleto_option.count() > 0:
                    try:
                        boleto_option.scroll_into_view_if_needed(timeout=3000)
                        page.wait_for_timeout(1000)
                    except:
                        pass
                    
                    print(f"[DEBUG PDF DOWNLOAD] 🖱️ Clicando na opção 'Boleto'...")
                    clicked = False
                    try:
                        # Tentar clicar normalmente primeiro
                        boleto_option.click(timeout=10000, force=False)
                        clicked = True
                    except Exception as e1:
                        print(f"[DEBUG PDF DOWNLOAD]     Clique normal falhou: {e1}")
                        try:
                            # Se falhar, tentar com force=True
                            print(f"[DEBUG PDF DOWNLOAD]     Tentando com force=True...")
                            boleto_option.click(timeout=10000, force=True)
                            clicked = True
                        except Exception as e2:
                            print(f"[DEBUG PDF DOWNLOAD]     Clique com force=True também falhou: {e2}")
                            # Último recurso: clicar via JavaScript
                            try:
                                print(f"[DEBUG PDF DOWNLOAD]     Tentando clicar via JavaScript...")
                                page.evaluate("""
                                    () => {
                                        const boleto = document.querySelector('div.desktop-payment__item-button-text:has-text("Boleto"), div:has-text("Boleto")');
                                        if (boleto) {
                                            boleto.click();
                                            return true;
                                        }
                                        return false;
                                    }
                                """)
                                clicked = True
                                print(f"[DEBUG PDF DOWNLOAD]     ✅ Clicado via JavaScript")
                            except Exception as e3:
                                print(f"[DEBUG PDF DOWNLOAD]     ❌ Clique via JavaScript também falhou: {e3}")
                                logger.error(f"[PDF HUMANO] Todos os métodos de clique falharam: {e1}, {e2}, {e3}")
                    
                    if clicked:
                        page.wait_for_timeout(2000)
                        page.wait_for_load_state("networkidle", timeout=10000)
                        print(f"[DEBUG PDF DOWNLOAD] ✅ PASSO 1: Clicou em 'Boleto'")
                        logger.info(f"[PDF HUMANO] ✅ Clicou em 'Boleto'")
                    else:
                        print(f"[DEBUG PDF DOWNLOAD] ⚠️ PASSO 1: Não conseguiu clicar em 'Boleto'")
                        logger.warning(f"[PDF HUMANO] ⚠️ Não conseguiu clicar em 'Boleto'")
                else:
                    print(f"[DEBUG PDF DOWNLOAD] ⚠️ PASSO 1: Opção 'Boleto' não encontrada")
                    logger.warning(f"[PDF HUMANO] ⚠️ Opção 'Boleto' não encontrada")
                    
                    # DIAGNÓSTICO: Capturar screenshot e HTML quando não encontra
                    try:
                        screenshot_path = os.path.join(downloads_dir, f"debug_{cpf}_boleto_nao_encontrado.png")
                        page.screenshot(path=screenshot_path, full_page=True)
                        print(f"[DEBUG PDF DOWNLOAD] 📸 Screenshot (Boleto não encontrado): {screenshot_path}")
                        logger.info(f"[PDF HUMANO] Screenshot (Boleto não encontrado): {screenshot_path}")
                    except Exception as e_debug:
                        logger.warning(f"[PDF HUMANO] Erro ao salvar screenshot: {e_debug}")
            except Exception as e:
                print(f"[DEBUG PDF DOWNLOAD] ⚠️ PASSO 1: Erro ao clicar em 'Boleto': {e}, continuando mesmo assim...")
                logger.warning(f"[PDF HUMANO] ⚠️ Erro ao clicar em 'Boleto': {e}, continuando mesmo assim...")
            
            # PASSO 2: Clicar em "Gerar boleto" - usando seletor correto: a#desktop-generate-boleto
            print(f"[DEBUG PDF DOWNLOAD] 📍 PASSO 2: Clicando em 'Gerar boleto'...")
            logger.info(f"[PDF HUMANO] Passo 2: Clicando em 'Gerar boleto'...")
            # Aguardar um pouco mais para garantir que a página carregou completamente
            page.wait_for_timeout(3000)  # Aumentado de 2000 para 3000
            page.wait_for_load_state("networkidle", timeout=15000)  # Aumentado de 10000 para 15000
            
            try:
                gerar_boleto = None
                seletores_gerar = [
                    'a#desktop-generate-boleto',  # Seletor exato fornecido pelo usuário
                    'a[id="desktop-generate-boleto"]',
                    'a.scheduled-payment__button.action-button#desktop-generate-boleto',
                    'a.scheduled-payment__button.action-button:has-text("Gerar boleto")',
                    'a.scheduled-payment__button:has-text("Gerar boleto")',
                    'a:has-text("Gerar boleto")',
                    'a:has-text("Gerar Boleto")',  # Com B maiúsculo
                    'button:has-text("Gerar boleto")',
                    'button:has-text("Gerar Boleto")',  # Com B maiúsculo
                    'div[data-context="btn_container_gerar-boleto"]',  # Seletor do test_nio_completo.py
                    'p:text-is("Gerar Boleto")',  # Seletor alternativo
                    'a[class*="scheduled-payment__button"]',
                    'a[href*="boleto"]',
                ]
                
                print(f"[DEBUG PDF DOWNLOAD] 🔍 Tentando {len(seletores_gerar)} seletores para 'Gerar boleto'...")
                logger.info(f"[PDF HUMANO] Tentando {len(seletores_gerar)} seletores para encontrar botão 'Gerar boleto'...")
                
                for idx, seletor in enumerate(seletores_gerar, 1):
                    try:
                        print(f"[DEBUG PDF DOWNLOAD]   [{idx}/{len(seletores_gerar)}] Tentando: {seletor}")
                        btn = page.locator(seletor).first
                        count = btn.count()
                        print(f"[DEBUG PDF DOWNLOAD]     Encontrados: {count} elementos")
                        
                        if count > 0:
                            # Tentar scroll para o elemento se necessário
                            try:
                                btn.scroll_into_view_if_needed(timeout=2000)
                                page.wait_for_timeout(500)
                            except:
                                pass
                            
                            # Verificar se está visível, se não, usar force=True
                            try:
                                if btn.is_visible(timeout=2000):
                                    gerar_boleto = btn
                                    print(f"[DEBUG PDF DOWNLOAD] ✅ Botão encontrado e visível com seletor: {seletor}")
                                    logger.info(f"[PDF HUMANO] Botão 'Gerar boleto' encontrado e visível com seletor: {seletor}")
                                    break
                                else:
                                    # Elemento existe mas não está visível, vamos usar force=True
                                    gerar_boleto = btn
                                    print(f"[DEBUG PDF DOWNLOAD]     Elemento encontrado mas não visível, será usado com force=True")
                                    break
                            except:
                                # Se verificação falhar, usar mesmo assim com force=True
                                gerar_boleto = btn
                                print(f"[DEBUG PDF DOWNLOAD]     Elemento encontrado, será usado com force=True")
                                break
                        else:
                            print(f"[DEBUG PDF DOWNLOAD]     Nenhum elemento encontrado")
                    except Exception as e_sel:
                        print(f"[DEBUG PDF DOWNLOAD]     Erro: {e_sel}")
                        logger.debug(f"[PDF HUMANO] Seletor '{seletor}' falhou: {e_sel}")
                        continue
                
                if not gerar_boleto or gerar_boleto.count() == 0:
                    print(f"[DEBUG PDF DOWNLOAD] ❌ PASSO 2: Botão 'Gerar boleto' não encontrado após tentar {len(seletores_gerar)} seletores!")
                    logger.error(f"[PDF HUMANO] ❌ Botão 'Gerar boleto' não encontrado após tentar {len(seletores_gerar)} seletores!")
                    
                    # Tentar buscar qualquer elemento com texto "gerar" ou "boleto" (case insensitive)
                    print(f"[DEBUG PDF DOWNLOAD] 🔍 Tentando busca alternativa por texto...")
                    try:
                        # Buscar por texto usando XPath (case insensitive)
                        elementos_texto = page.locator('xpath=//*[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "gerar") and contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "boleto")]').first
                        if elementos_texto.count() > 0:
                            print(f"[DEBUG PDF DOWNLOAD] ✅ Encontrado elemento por texto!")
                            gerar_boleto = elementos_texto
                            # Tentar encontrar o elemento clicável (pai com cursor pointer ou link)
                            try:
                                parent_clickable = elementos_texto.locator('xpath=ancestor::div[contains(@style, "cursor: pointer")] | ancestor::a | ancestor::button').first
                                if parent_clickable.count() > 0:
                                    gerar_boleto = parent_clickable
                                    print(f"[DEBUG PDF DOWNLOAD] ✅ Elemento clicável encontrado!")
                            except:
                                pass
                    except Exception as e_alt:
                        print(f"[DEBUG PDF DOWNLOAD]     Busca alternativa falhou: {e_alt}")
                        logger.debug(f"[PDF HUMANO] Busca alternativa falhou: {e_alt}")
                    
                    if not gerar_boleto or gerar_boleto.count() == 0:
                        # Salvar screenshot e HTML para debug
                        try:
                            screenshot_path = os.path.join(downloads_dir, f"debug_{cpf}_gerar_boleto_nao_encontrado.png")
                            page.screenshot(path=screenshot_path, full_page=True)
                            print(f"[DEBUG PDF DOWNLOAD] 💾 Screenshot salvo: {screenshot_path}")
                            logger.info(f"[PDF HUMANO] Screenshot salvo: {screenshot_path}")
                            html_path = os.path.join(downloads_dir, f"debug_{cpf}_gerar_boleto_html.html")
                            with open(html_path, 'w', encoding='utf-8') as f:
                                f.write(page.content())
                            print(f"[DEBUG PDF DOWNLOAD] 💾 HTML salvo: {html_path}")
                            logger.info(f"[PDF HUMANO] HTML salvo: {html_path}")
                        except Exception as e_debug:
                            logger.warning(f"[PDF HUMANO] Erro ao salvar debug: {e_debug}")
                        browser.close()
                        print(f"[DEBUG PDF DOWNLOAD] 🎉 RETORNANDO: None (botão não encontrado)")
                        return None
                
                # Scroll para o botão antes de clicar
                try:
                    gerar_boleto.scroll_into_view_if_needed(timeout=3000)
                    page.wait_for_timeout(1000)
                except:
                    pass
                
                print(f"[DEBUG PDF DOWNLOAD] 🖱️ Clicando no botão 'Gerar boleto'...")
                clicked = False
                try:
                    # Tentar clicar normalmente primeiro
                    gerar_boleto.click(timeout=10000, force=False)
                    clicked = True
                except Exception as e_click:
                    print(f"[DEBUG PDF DOWNLOAD]     Clique normal falhou: {e_click}")
                    try:
                        # Se falhar porque não está visível, tentar com force=True
                        print(f"[DEBUG PDF DOWNLOAD]     Tentando com force=True...")
                        logger.warning(f"[PDF HUMANO] Clique normal falhou, tentando com force=True: {e_click}")
                        gerar_boleto.click(timeout=10000, force=True)
                        clicked = True
                    except Exception as e2:
                        print(f"[DEBUG PDF DOWNLOAD]     Clique com force=True também falhou: {e2}")
                        # Último recurso: clicar via JavaScript
                        try:
                            print(f"[DEBUG PDF DOWNLOAD]     Tentando clicar via JavaScript...")
                            page.evaluate("""
                                () => {
                                    const btn = document.querySelector('a#desktop-generate-boleto, a#generate-boleto');
                                    if (btn) {
                                        btn.click();
                                        return true;
                                    }
                                    return false;
                                }
                            """)
                            clicked = True
                            print(f"[DEBUG PDF DOWNLOAD]     ✅ Clicado via JavaScript")
                        except Exception as e3:
                            print(f"[DEBUG PDF DOWNLOAD]     ❌ Clique via JavaScript também falhou: {e3}")
                            logger.error(f"[PDF HUMANO] Todos os métodos de clique falharam: {e_click}, {e2}, {e3}")
                
                if clicked:
                    page.wait_for_timeout(3000)  # Aumentado de 2000 para 3000
                    page.wait_for_load_state("networkidle", timeout=15000)  # Aumentado de 10000 para 15000
                    print(f"[DEBUG PDF DOWNLOAD] ✅ PASSO 2: Clicou em 'Gerar boleto'")
                    logger.info(f"[PDF HUMANO] ✅ Clicou em 'Gerar boleto'")
                else:
                    print(f"[DEBUG PDF DOWNLOAD] ⚠️ PASSO 2: Não conseguiu clicar em 'Gerar boleto'")
                    logger.error(f"[PDF HUMANO] ⚠️ Não conseguiu clicar em 'Gerar boleto'")
            except Exception as e:
                print(f"[DEBUG PDF DOWNLOAD] ❌ PASSO 2: Erro ao clicar em 'Gerar boleto': {e}")
                logger.error(f"[PDF HUMANO] ❌ Erro ao clicar em 'Gerar boleto': {e}")
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[PDF HUMANO] Traceback: {tb}")
                print(f"[DEBUG PDF DOWNLOAD] Traceback: {tb}")
                browser.close()
                print(f"[DEBUG PDF DOWNLOAD] 🎉 RETORNANDO: None (erro)")
                return None
            
            # PASSO 3: Clicar em "Download" - usando seletor correto: a#downloadInvoice
            print(f"[DEBUG PDF DOWNLOAD] 📍 PASSO 3: Clicando em 'Download'...")
            logger.info(f"[PDF HUMANO] Passo 3: Clicando em 'Download'...")
            # Aguardar um pouco mais para garantir que a página carregou completamente
            page.wait_for_timeout(3000)  # Aumentado de 2000 para 3000
            page.wait_for_load_state("networkidle", timeout=15000)  # Aumentado de 10000 para 15000
            
            try:
                download_btn = None
                seletores_download = [
                    'a#downloadInvoice',  # Seletor exato fornecido pelo usuário
                    'a[id="downloadInvoice"]',
                    'a.scheduled-payment__button--outline#downloadInvoice',
                    'a.scheduled-payment__button--outline:has-text("Download")',
                    'a:has-text("Download")',
                    'a:has-text("Baixar PDF")',  # Texto alternativo
                    'button:has-text("Download")',
                    'button:has-text("Baixar PDF")',  # Texto alternativo
                    'a[class*="scheduled-payment__button--outline"]',
                    'a[href*="download"]',
                    'text="Baixar PDF"',  # Seletor de texto
                ]
                
                print(f"[DEBUG PDF DOWNLOAD] 🔍 Tentando {len(seletores_download)} seletores para 'Download'...")
                logger.info(f"[PDF HUMANO] Tentando {len(seletores_download)} seletores para encontrar botão 'Download'...")
                
                for idx, seletor in enumerate(seletores_download, 1):
                    try:
                        print(f"[DEBUG PDF DOWNLOAD]   [{idx}/{len(seletores_download)}] Tentando: {seletor}")
                        btn = page.locator(seletor).first
                        count = btn.count()
                        print(f"[DEBUG PDF DOWNLOAD]     Encontrados: {count} elementos")
                        
                        if count > 0:
                            # Tentar scroll para o elemento se necessário
                            try:
                                btn.scroll_into_view_if_needed(timeout=2000)
                                page.wait_for_timeout(500)
                            except:
                                pass
                            
                            # Verificar se está visível, se não, usar force=True
                            try:
                                if btn.is_visible(timeout=2000):
                                    download_btn = btn
                                    print(f"[DEBUG PDF DOWNLOAD] ✅ Botão encontrado e visível com seletor: {seletor}")
                                    logger.info(f"[PDF HUMANO] Botão 'Download' encontrado e visível com seletor: {seletor}")
                                    break
                                else:
                                    # Elemento existe mas não está visível, vamos usar force=True
                                    download_btn = btn
                                    print(f"[DEBUG PDF DOWNLOAD]     Elemento encontrado mas não visível, será usado com force=True")
                                    break
                            except:
                                # Se verificação falhar, usar mesmo assim com force=True
                                download_btn = btn
                                print(f"[DEBUG PDF DOWNLOAD]     Elemento encontrado, será usado com force=True")
                                break
                        else:
                            print(f"[DEBUG PDF DOWNLOAD]     Nenhum elemento encontrado")
                    except Exception as e_sel:
                        print(f"[DEBUG PDF DOWNLOAD]     Erro: {e_sel}")
                        logger.debug(f"[PDF HUMANO] Seletor '{seletor}' falhou: {e_sel}")
                        continue
                
                if download_btn and download_btn.count() > 0:
                    print(f"[DEBUG PDF DOWNLOAD] ✅ Botão Download encontrado")
                    logger.info(f"[PDF HUMANO] ✅ Botão Download encontrado")
                    
                    # Scroll para o botão antes de clicar
                    try:
                        download_btn.scroll_into_view_if_needed(timeout=3000)
                        page.wait_for_timeout(1000)
                    except:
                        pass
                    
                    # O botão abre o modal de impressão do navegador
                    # Vamos usar a API de impressão do Playwright para salvar como PDF
                    print(f"[DEBUG PDF DOWNLOAD] 🖱️ Clicando no botão Download...")
                    logger.info(f"[PDF HUMANO] Clicando no botão Download (abrirá modal de impressão)...")
                    clicked = False
                    try:
                        # Tentar clicar normalmente primeiro
                        download_btn.click(timeout=10000, force=False)
                        clicked = True
                    except Exception as e_click:
                        print(f"[DEBUG PDF DOWNLOAD]     Clique normal falhou: {e_click}")
                        try:
                            # Se falhar porque não está visível, tentar com force=True
                            print(f"[DEBUG PDF DOWNLOAD]     Tentando com force=True...")
                            logger.warning(f"[PDF HUMANO] Clique normal falhou, tentando com force=True: {e_click}")
                            download_btn.click(timeout=10000, force=True)
                            clicked = True
                        except Exception as e2:
                            print(f"[DEBUG PDF DOWNLOAD]     Clique com force=True também falhou: {e2}")
                            # Último recurso: clicar via JavaScript
                            try:
                                print(f"[DEBUG PDF DOWNLOAD]     Tentando clicar via JavaScript...")
                                page.evaluate("""
                                    () => {
                                        const btn = document.querySelector('a#downloadInvoice, a[id="downloadInvoice"]');
                                        if (btn) {
                                            btn.click();
                                            return true;
                                        }
                                        return false;
                                    }
                                """)
                                clicked = True
                                print(f"[DEBUG PDF DOWNLOAD]     ✅ Clicado via JavaScript")
                            except Exception as e3:
                                print(f"[DEBUG PDF DOWNLOAD]     ❌ Clique via JavaScript também falhou: {e3}")
                                logger.error(f"[PDF HUMANO] Todos os métodos de clique falharam: {e_click}, {e2}, {e3}")
                    
                    if clicked:
                        page.wait_for_timeout(3000)  # Aguardar modal abrir (aumentado de 2000)
                    else:
                        print(f"[DEBUG PDF DOWNLOAD] ⚠️ Não conseguiu clicar em Download, tentando gerar PDF diretamente...")
                        logger.warning(f"[PDF HUMANO] ⚠️ Não conseguiu clicar em Download, tentando gerar PDF diretamente...")
                else:
                    print(f"[DEBUG PDF DOWNLOAD] ⚠️ Botão Download não encontrado, tentando gerar PDF diretamente da página...")
                    logger.warning(f"[PDF HUMANO] ⚠️ Botão 'Download' não encontrado, tentando gerar PDF diretamente da página atual...")
                    # Salvar screenshot e HTML para debug
                    try:
                        screenshot_path = os.path.join(downloads_dir, f"debug_{cpf}_download_nao_encontrado.png")
                        page.screenshot(path=screenshot_path, full_page=True)
                        print(f"[DEBUG PDF DOWNLOAD] 💾 Screenshot salvo: {screenshot_path}")
                        logger.info(f"[PDF HUMANO] Screenshot salvo: {screenshot_path}")
                        html_path = os.path.join(downloads_dir, f"debug_{cpf}_download_html.html")
                        with open(html_path, 'w', encoding='utf-8') as f:
                            f.write(page.content())
                        print(f"[DEBUG PDF DOWNLOAD] 💾 HTML salvo: {html_path}")
                        logger.info(f"[PDF HUMANO] HTML salvo: {html_path}")
                    except Exception as e_debug:
                        logger.warning(f"[PDF HUMANO] Erro ao salvar debug: {e_debug}")
                
                # Aguardar página estar completamente carregada E dados aparecerem antes de gerar PDF
                print(f"[DEBUG PDF DOWNLOAD] ⏳ Aguardando página estar completamente carregada...")
                logger.info(f"[PDF HUMANO] Aguardando página estar completamente carregada...")
                page.wait_for_load_state("networkidle", timeout=15000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                page.wait_for_timeout(5000)  # Aguardar 5 segundos para garantir renderização completa dos dados
                
                # Aguardar que elementos específicos apareçam (valor, código de barras)
                print(f"[DEBUG PDF DOWNLOAD] 🔍 Aguardando elementos da fatura aparecerem...")
                logger.info(f"[PDF HUMANO] Aguardando elementos da fatura aparecerem...")
                try:
                    # Tentar encontrar elementos que indicam que os dados carregaram
                    # Procurar por padrões de valor monetário ou código de barras no DOM
                    max_tentativas = 10
                    dados_encontrados = False
                    for tentativa in range(max_tentativas):
                        page_content = page.evaluate("() => document.body.innerText || ''")
                        # Verificar se tem valor monetário E código de barras
                        valores = re.findall(r'R\$\s*[\d.,]+', page_content)
                        codigos = re.findall(r'\d{40,50}', page_content)
                        if valores and codigos:
                            print(f"[DEBUG PDF DOWNLOAD] ✅ Dados encontrados na tentativa {tentativa + 1}: {len(valores)} valores, {len(codigos)} códigos")
                            logger.info(f"[PDF HUMANO] ✅ Dados encontrados na tentativa {tentativa + 1}")
                            dados_encontrados = True
                            break
                        else:
                            print(f"[DEBUG PDF DOWNLOAD] ⏳ Tentativa {tentativa + 1}/{max_tentativas}: aguardando dados... (valores={len(valores)}, codigos={len(codigos)})")
                            page.wait_for_timeout(1000)  # Aguardar 1 segundo entre tentativas
                    
                    if not dados_encontrados:
                        print(f"[DEBUG PDF DOWNLOAD] ❌ Dados não encontrados após {max_tentativas} tentativas - NÃO GERANDO PDF")
                        logger.error(f"[PDF HUMANO] ❌ Dados não encontrados após {max_tentativas} tentativas - NÃO GERANDO PDF")
                        # Capturar screenshot e HTML para debug
                        try:
                            screenshot_path = os.path.join(downloads_dir, f"debug_{cpf}_dados_nao_encontrados_apos_tentativas.png")
                            page.screenshot(path=screenshot_path, full_page=True)
                            print(f"[DEBUG PDF DOWNLOAD] 📸 Screenshot: {screenshot_path}")
                            logger.info(f"[PDF HUMANO] Screenshot: {screenshot_path}")
                            
                            html_path = os.path.join(downloads_dir, f"debug_{cpf}_dados_nao_encontrados.html")
                            with open(html_path, 'w', encoding='utf-8') as f:
                                f.write(page.content())
                            print(f"[DEBUG PDF DOWNLOAD] 📄 HTML: {html_path}")
                            logger.info(f"[PDF HUMANO] HTML: {html_path}")
                        except:
                            pass
                        browser.close()
                        return None
                except Exception as e_espera:
                    print(f"[DEBUG PDF DOWNLOAD] ⚠️ Erro ao aguardar dados: {e_espera}, continuando...")
                    logger.warning(f"[PDF HUMANO] ⚠️ Erro ao aguardar dados: {e_espera}")
                
                # Verificar se há conteúdo CORRETO na página antes de gerar PDF
                # Validar que a página tem os dados da fatura (valor, código de barras, etc)
                print(f"[DEBUG PDF DOWNLOAD] 🔍 Validando conteúdo da página antes de gerar PDF...")
                logger.info(f"[PDF HUMANO] Validando conteúdo da página antes de gerar PDF...")
                try:
                    page_content = page.evaluate("() => document.body.innerText")
                    if not page_content or len(page_content.strip()) < 50:
                        print(f"[DEBUG PDF DOWNLOAD] ❌ Página vazia ou com pouco conteúdo: {len(page_content) if page_content else 0} caracteres")
                        logger.error(f"[PDF HUMANO] ❌ Página vazia ou com pouco conteúdo")
                        browser.close()
                        return None
                    
                    # Verificar se a página contém dados da fatura correta
                    # Procurar por indicadores de que é a fatura correta:
                    # - Valor (R$ 130,00 ou similar)
                    # - Código de barras
                    # - Data de vencimento
                    valor_encontrado = False
                    codigo_barras_encontrado = False
                    
                    # Verificar se tem o valor esperado (R$ 130,00 ou similar)
                    # Procurar por padrões de valor monetário
                    valores = re.findall(r'R\$\s*[\d.,]+', page_content)
                    if valores:
                        print(f"[DEBUG PDF DOWNLOAD] ✅ Valores encontrados na página: {valores[:5]}")
                        logger.info(f"[PDF HUMANO] Valores encontrados na página: {valores[:5]}")
                        valor_encontrado = True
                    else:
                        print(f"[DEBUG PDF DOWNLOAD] ⚠️ Nenhum valor monetário encontrado na página")
                        logger.warning(f"[PDF HUMANO] ⚠️ Nenhum valor monetário encontrado na página")
                    
                    # Verificar se tem código de barras (padrão: números longos)
                    codigos_barras = re.findall(r'\d{40,50}', page_content)  # Códigos de barras têm 44-48 dígitos
                    if codigos_barras:
                        print(f"[DEBUG PDF DOWNLOAD] ✅ Códigos de barras encontrados: {len(codigos_barras)}")
                        logger.info(f"[PDF HUMANO] Códigos de barras encontrados: {len(codigos_barras)}")
                        codigo_barras_encontrado = True
                    else:
                        print(f"[DEBUG PDF DOWNLOAD] ⚠️ Nenhum código de barras encontrado na página")
                        logger.warning(f"[PDF HUMANO] ⚠️ Nenhum código de barras encontrado na página")
                    
                    # Se não encontrou dados essenciais, pode estar na página errada
                    if not valor_encontrado or not codigo_barras_encontrado:
                        print(f"[DEBUG PDF DOWNLOAD] ⚠️ Página pode não ter dados da fatura correta (valor={valor_encontrado}, codigo_barras={codigo_barras_encontrado})")
                        logger.warning(f"[PDF HUMANO] ⚠️ Página pode não ter dados da fatura correta")
                        # Capturar screenshot para debug
                        try:
                            screenshot_path = os.path.join(downloads_dir, f"debug_{cpf}_pagina_sem_dados_antes_pdf.png")
                            page.screenshot(path=screenshot_path, full_page=True)
                            print(f"[DEBUG PDF DOWNLOAD] 📸 Screenshot da página sem dados: {screenshot_path}")
                            logger.info(f"[PDF HUMANO] Screenshot da página sem dados: {screenshot_path}")
                            
                            html_path = os.path.join(downloads_dir, f"debug_{cpf}_pagina_sem_dados.html")
                            with open(html_path, 'w', encoding='utf-8') as f:
                                f.write(page.content())
                            print(f"[DEBUG PDF DOWNLOAD] 📄 HTML salvo: {html_path}")
                            logger.info(f"[PDF HUMANO] HTML salvo: {html_path}")
                        except:
                            pass
                        
                        # CRÍTICO: Não gerar PDF se não encontrou código de barras após todas as tentativas
                        # O código de barras é essencial para validar que é a fatura correta
                        if not codigo_barras_encontrado:
                            print(f"[DEBUG PDF DOWNLOAD] ❌ CÓDIGO DE BARRAS NÃO ENCONTRADO após validação - NÃO GERANDO PDF")
                            logger.error(f"[PDF HUMANO] ❌ CÓDIGO DE BARRAS NÃO ENCONTRADO - NÃO GERANDO PDF")
                            browser.close()
                            return None
                        else:
                            print(f"[DEBUG PDF DOWNLOAD] ⚠️ Valor não encontrado mas código de barras sim, continuando...")
                            logger.warning(f"[PDF HUMANO] ⚠️ Valor não encontrado mas código de barras sim, continuando...")
                    else:
                        print(f"[DEBUG PDF DOWNLOAD] ✅ Página contém dados da fatura (valor e código de barras encontrados)")
                        logger.info(f"[PDF HUMANO] ✅ Página contém dados da fatura")
                        
                except Exception as e_check:
                    print(f"[DEBUG PDF DOWNLOAD] ⚠️ Erro ao validar conteúdo da página: {e_check}")
                    logger.warning(f"[PDF HUMANO] Erro ao validar conteúdo da página: {e_check}")
                
                # VALIDAÇÃO FINAL: Verificar novamente se código de barras está presente antes de gerar PDF
                print(f"[DEBUG PDF DOWNLOAD] 🔍 VALIDAÇÃO FINAL: Verificando código de barras antes de gerar PDF...")
                logger.info(f"[PDF HUMANO] VALIDAÇÃO FINAL: Verificando código de barras antes de gerar PDF...")
                try:
                    page_content_final = page.evaluate("() => document.body.innerText || ''")
                    codigos_final = re.findall(r'\d{40,50}', page_content_final)
                    valores_final = re.findall(r'R\$\s*[\d.,]+', page_content_final)
                    
                    print(f"[DEBUG PDF DOWNLOAD] 📊 Validação final: valores={len(valores_final)}, codigos={len(codigos_final)}")
                    logger.info(f"[PDF HUMANO] Validação final: valores={len(valores_final)}, codigos={len(codigos_final)}")
                    
                    if not codigos_final:
                        print(f"[DEBUG PDF DOWNLOAD] ❌ CÓDIGO DE BARRAS NÃO ENCONTRADO na validação final - NÃO GERANDO PDF")
                        logger.error(f"[PDF HUMANO] ❌ CÓDIGO DE BARRAS NÃO ENCONTRADO na validação final - NÃO GERANDO PDF")
                        browser.close()
                        return None
                    
                    print(f"[DEBUG PDF DOWNLOAD] ✅ Código de barras confirmado na validação final: {len(codigos_final)} encontrado(s)")
                    logger.info(f"[PDF HUMANO] ✅ Código de barras confirmado na validação final")
                except Exception as e_val_final:
                    print(f"[DEBUG PDF DOWNLOAD] ⚠️ Erro na validação final: {e_val_final}, continuando...")
                    logger.warning(f"[PDF HUMANO] ⚠️ Erro na validação final: {e_val_final}")
                
                # Usar a API de impressão do Playwright para gerar PDF diretamente
                print(f"[DEBUG PDF DOWNLOAD] 📄 Gerando PDF via API de impressão do navegador...")
                logger.info(f"[PDF HUMANO] Gerando PDF via API de impressão do navegador...")
                pdf_bytes = page.pdf(
                    format='A4',
                    print_background=True,
                    margin={'top': '0.5cm', 'right': '0.5cm', 'bottom': '0.5cm', 'left': '0.5cm'}
                )
                
                # VALIDAÇÃO: Verificar se PDF não está vazio e tem estrutura válida
                if not pdf_bytes or len(pdf_bytes) < 100:
                    print(f"[DEBUG PDF DOWNLOAD] ❌ PDF gerado está vazio ou muito pequeno: {len(pdf_bytes) if pdf_bytes else 0} bytes")
                    logger.error(f"[PDF HUMANO] ❌ PDF gerado está vazio ou muito pequeno: {len(pdf_bytes) if pdf_bytes else 0} bytes")
                    browser.close()
                    return None
                
                # Verificar se começa com cabeçalho PDF válido
                if not pdf_bytes.startswith(b'%PDF'):
                    print(f"[DEBUG PDF DOWNLOAD] ❌ PDF não tem cabeçalho válido (não começa com %PDF)")
                    logger.error(f"[PDF HUMANO] ❌ PDF não tem cabeçalho válido")
                    browser.close()
                    return None
                
                print(f"[DEBUG PDF DOWNLOAD] ✅ PDF gerado e validado: {len(pdf_bytes)} bytes")
                logger.info(f"[PDF HUMANO] ✅ PDF gerado e validado: {len(pdf_bytes)} bytes")
                
                # Salvar PDF
                if os.path.exists(caminho_completo):
                    os.remove(caminho_completo)
                
                with open(caminho_completo, 'wb') as f:
                    f.write(pdf_bytes)
                
                # VALIDAÇÃO: Verificar se arquivo foi salvo corretamente
                if not os.path.exists(caminho_completo):
                    print(f"[DEBUG PDF DOWNLOAD] ❌ Erro: Arquivo não foi salvo em {caminho_completo}")
                    logger.error(f"[PDF HUMANO] ❌ Erro: Arquivo não foi salvo")
                    browser.close()
                    return None
                
                tamanho_salvo = os.path.getsize(caminho_completo)
                if tamanho_salvo != len(pdf_bytes):
                    print(f"[DEBUG PDF DOWNLOAD] ⚠️ Tamanho do arquivo salvo ({tamanho_salvo}) diferente do PDF gerado ({len(pdf_bytes)})")
                    logger.warning(f"[PDF HUMANO] ⚠️ Tamanho do arquivo salvo diferente do PDF gerado")
                
                print(f"[DEBUG PDF DOWNLOAD] ✅ PDF salvo e validado em: {caminho_completo} ({tamanho_salvo} bytes)")
                logger.info(f"[PDF HUMANO] ✅ PDF gerado e salvo: {caminho_completo} ({tamanho_salvo} bytes)")
                
            except Exception as e_download:
                print(f"[DEBUG PDF DOWNLOAD] ❌ PASSO 3: Erro ao processar download: {e_download}")
                logger.error(f"[PDF HUMANO] ❌ Erro ao processar download: {e_download}")
                import traceback
                tb = traceback.format_exc()
                logger.error(f"[PDF HUMANO] Traceback: {tb}")
                print(f"[DEBUG PDF DOWNLOAD] Traceback: {tb}")
                browser.close()
                print(f"[DEBUG PDF DOWNLOAD] 🎉 RETORNANDO: None (erro)")
                return None
            
            # 7. Verificar se arquivo foi salvo (já foi salvo no passo 6)
            logger.info(f"[PDF HUMANO] Passo 7: Verificando arquivo salvo...")
            
            browser.close()
            
            # Verificar se arquivo foi salvo corretamente
            print(f"[DEBUG PDF DOWNLOAD] 📍 PASSO 7: Verificando arquivo salvo...")
            print(f"[DEBUG PDF DOWNLOAD] Caminho: {caminho_completo}")
            print(f"[DEBUG PDF DOWNLOAD] Existe: {os.path.exists(caminho_completo)}")
            
            if os.path.exists(caminho_completo):
                tamanho = os.path.getsize(caminho_completo)
                print(f"[DEBUG PDF DOWNLOAD] Tamanho: {tamanho} bytes ({tamanho/1024:.2f} KB)")
            
            if os.path.exists(caminho_completo) and os.path.getsize(caminho_completo) > 0:
                tamanho_kb = os.path.getsize(caminho_completo) / 1024
                print(f"[DEBUG PDF DOWNLOAD] ✅ Arquivo salvo com sucesso: {caminho_completo} ({tamanho_kb:.2f} KB)")
                logger.info(f"[PDF HUMANO] ✅ Arquivo salvo com sucesso: {caminho_completo} ({tamanho_kb:.2f} KB)")
                
                # Tentar fazer upload para OneDrive
                print(f"[DEBUG PDF DOWNLOAD] ☁️ Tentando fazer upload para OneDrive...")
                try:
                    from crm_app.onedrive_service import OneDriveUploader
                    uploader = OneDriveUploader()
                    
                    # Criar pasta no OneDrive: Faturas_NIO/YYYY/MM
                    from datetime import datetime
                    if mes_referencia:
                        ano = mes_referencia[:4]
                        mes = mes_referencia[4:]
                    else:
                        ano = datetime.now().strftime('%Y')
                        mes = datetime.now().strftime('%m')
                    
                    folder_name = f"Faturas_NIO/{ano}/{mes}"
                    
                    print(f"[DEBUG PDF DOWNLOAD] 📁 Pasta OneDrive: {folder_name}/{nome_arquivo}")
                    logger.info(f"[PDF HUMANO] ☁️ Fazendo upload para OneDrive: {folder_name}/{nome_arquivo}")
                    
                    with open(caminho_completo, 'rb') as f:
                        link_onedrive = uploader.upload_file(f, folder_name, nome_arquivo)
                    
                    if link_onedrive:
                        print(f"[DEBUG PDF DOWNLOAD] ✅ Upload OneDrive concluído: {link_onedrive}")
                        logger.info(f"[PDF HUMANO] ✅ Upload OneDrive concluído: {link_onedrive}")
                        resultado = {
                            'local_path': caminho_completo,
                            'onedrive_url': link_onedrive,
                            'filename': nome_arquivo
                        }
                        print(f"[DEBUG PDF DOWNLOAD] 🎉 RETORNANDO: {resultado}")
                        return resultado
                    else:
                        print(f"[DEBUG PDF DOWNLOAD] ⚠️ Upload OneDrive falhou, mas arquivo local salvo")
                        logger.warning(f"[PDF HUMANO] ⚠️ Upload OneDrive falhou, mas arquivo local salvo")
                        resultado = {
                            'local_path': caminho_completo,
                            'onedrive_url': None,
                            'filename': nome_arquivo
                        }
                        print(f"[DEBUG PDF DOWNLOAD] 🎉 RETORNANDO (sem OneDrive): {resultado}")
                        return resultado
                except Exception as e_onedrive:
                    print(f"[DEBUG PDF DOWNLOAD] ❌ Erro ao fazer upload OneDrive: {e_onedrive}")
                    logger.warning(f"[PDF HUMANO] ⚠️ Erro ao fazer upload OneDrive: {e_onedrive}")
                    import traceback
                    tb = traceback.format_exc()
                    logger.warning(f"[PDF HUMANO] Traceback OneDrive: {tb}")
                    print(f"[DEBUG PDF DOWNLOAD] Traceback OneDrive: {tb}")
                    # Mesmo se OneDrive falhar, retornar o caminho local
                    resultado = {
                        'local_path': caminho_completo,
                        'onedrive_url': None,
                        'filename': nome_arquivo
                    }
                    print(f"[DEBUG PDF DOWNLOAD] 🎉 RETORNANDO (após erro OneDrive): {resultado}")
                    return resultado
            else:
                print(f"[DEBUG PDF DOWNLOAD] ❌ Arquivo salvo mas está vazio ou não existe")
                print(f"[DEBUG PDF DOWNLOAD] Existe: {os.path.exists(caminho_completo)}, Tamanho: {os.path.getsize(caminho_completo) if os.path.exists(caminho_completo) else 'N/A'}")
                logger.warning(f"[PDF HUMANO] ⚠️ Arquivo salvo mas está vazio ou não existe")
                logger.warning(f"[PDF HUMANO] Existe: {os.path.exists(caminho_completo)}, Tamanho: {os.path.getsize(caminho_completo) if os.path.exists(caminho_completo) else 'N/A'}")
                print(f"[DEBUG PDF DOWNLOAD] 🎉 RETORNANDO: None")
                return None
                
    except Exception as e:
        print(f"[DEBUG PDF DOWNLOAD] ❌ ERRO GERAL ao baixar PDF: {type(e).__name__}: {e}")
        logger.error(f"[PDF HUMANO] ❌ Erro ao baixar PDF: {e}")
        import traceback
        tb = traceback.format_exc()
        logger.error(f"[PDF HUMANO] Traceback completo: {tb}")
        print(f"[DEBUG PDF DOWNLOAD] Traceback completo: {tb}")
        
        # Salvar log de erro para debug
        try:
            from datetime import datetime
            error_log_path = os.path.join(downloads_dir, f"error_{cpf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            with open(error_log_path, 'w', encoding='utf-8') as f:
                f.write(f"Erro ao baixar PDF para CPF: {cpf}\n")
                f.write(f"Data: {datetime.now().isoformat()}\n")
                f.write(f"Erro: {str(e)}\n")
                f.write(f"\nTraceback:\n")
                traceback.print_exc(file=f)
            print(f"[DEBUG PDF DOWNLOAD] 📝 Log de erro salvo: {error_log_path}")
            logger.info(f"[PDF HUMANO] 📝 Log de erro salvo: {error_log_path}")
        except Exception as e_log:
            logger.warning(f"[PDF HUMANO] Erro ao salvar log de erro: {e_log}")
        
        print(f"[DEBUG PDF DOWNLOAD] 🎉 RETORNANDO: None (erro)")
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
            resultado = _buscar_todas_faturas_playwright(cpf_limpo)
            return resultado if resultado else []
        except Exception as e:
            print(f"[ERRO] Falha ao buscar faturas via Playwright: {e}")
            import traceback
            traceback.print_exc()
            return []
    return []


def _buscar_todas_faturas_playwright(cpf: str):
    """
    Busca TODAS as faturas (abertas e atrasadas) usando Playwright.
    Extrai todas as faturas da página HTML antes de clicar em qualquer uma.
    """
    if not HAS_PLAYWRIGHT:
        return []
    
    try:
        from playwright.sync_api import sync_playwright
        
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
            
            # Preenche CPF e consulta
            page.locator('input[type="text"]').first.fill(cpf)
            page.locator('button:has-text("Consultar")').first.click()
            page.wait_for_timeout(1500)
            page.wait_for_load_state("networkidle", timeout=20000)
            
            # Verifica se tem "ver detalhes" e expande
            ver_detalhes = page.locator('text=/ver detalhes/i')
            if ver_detalhes.count() > 0:
                ver_detalhes.first.click()
                page.wait_for_timeout(800)
            
            # Captura HTML completo da página de resultados
            html_resultado = page.content()
            
            # Extrai TODAS as faturas da tabela HTML
            faturas = _extrair_todas_faturas_html(html_resultado)
            
            if not faturas:
                print("[AVISO] Nenhuma fatura encontrada no HTML, tentando método alternativo...")
                # Fallback: busca a primeira fatura normalmente
                resultado = _buscar_fatura_playwright(cpf)
                return [resultado] if resultado else []
            
            browser.close()
            return faturas
            
    except Exception as e:
        print(f"[ERRO] Falha ao buscar todas faturas: {e}")
        import traceback
        traceback.print_exc()
        return []


def _extrair_todas_faturas_html(html: str):
    """
    Extrai todas as faturas do HTML da página de resultados da Nio.
    Procura por padrões de tabela/listagem com status, valores e vencimentos.
    """
    import re
    from bs4 import BeautifulSoup
    
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[AVISO] BeautifulSoup não instalado. Instale: pip install beautifulsoup4")
        return []
    
    faturas = []
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        
        # Procurar por linhas de tabela ou cards de faturas
        # Padrão comum: divs ou tr com classes relacionadas a "cobrança", "fatura", "invoice"
        
        # Tentar encontrar todas as linhas com status (Em aberto, Atrasado, etc)
        status_pattern = re.compile(r'(Em aberto|Atrasado|Atrasada|Vencida|Vencido)', re.IGNORECASE)
        
        # Buscar valores monetários (R$)
        valor_pattern = re.compile(r'R\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))', re.IGNORECASE)
        
        # Buscar datas de vencimento
        data_pattern = re.compile(r'(\d{2}/\d{2}/\d{4})')
        
        # Buscar elementos que podem conter faturas
        # Pode ser tabelas (tr), divs com classes específicas, etc
        elementos_fatura = soup.find_all(['tr', 'div'], class_=re.compile(r'(invoice|fatura|cobrança|bill)', re.IGNORECASE))
        
        # Se não encontrou por classe, tenta por texto que contenha "Cobrança"
        if not elementos_fatura:
            elementos_fatura = soup.find_all(string=re.compile(r'Cobrança|Fatura|Janeiro|Fevereiro|Março|Abril|Maio|Junho|Julho|Agosto|Setembro|Outubro|Novembro|Dezembro', re.IGNORECASE))
            elementos_fatura = [elem.parent for elem in elementos_fatura if elem.parent]
        
        # Se ainda não encontrou, tenta buscar todos os elementos que contenham valores monetários
        if not elementos_fatura:
            elementos_com_valor = soup.find_all(string=valor_pattern)
            elementos_fatura = [elem.parent for elem in elementos_com_valor if elem.parent]
        
        print(f"[DEBUG] Encontrados {len(elementos_fatura)} elementos candidatos a faturas")
        
        # Processar cada elemento encontrado
        for i, elemento in enumerate(elementos_fatura[:10]):  # Limitar a 10 faturas
            texto_elemento = elemento.get_text() if hasattr(elemento, 'get_text') else str(elemento)
            
            # Extrair dados
            valor_match = valor_pattern.search(texto_elemento)
            data_match = data_pattern.search(texto_elemento)
            status_match = status_pattern.search(texto_elemento)
            
            valor = None
            if valor_match:
                try:
                    valor_str = valor_match.group(1).replace('.', '').replace(',', '.')
                    valor = Decimal(valor_str)
                except:
                    pass
            
            data_vencimento = None
            if data_match:
                try:
                    data_vencimento = datetime.strptime(data_match.group(1), "%d/%m/%Y").date()
                except:
                    pass
            
            status = status_match.group(1) if status_match else None
            
            # Se encontrou pelo menos valor OU data, considera uma fatura
            if valor or data_vencimento:
                faturas.append({
                    'valor': float(valor) if valor else None,
                    'data_vencimento': data_vencimento.strftime('%Y-%m-%d') if data_vencimento else None,
                    'status': status,
                    'codigo_pix': None,  # Será preenchido ao clicar na fatura específica
                    'codigo_barras': None,
                    'pdf_url': None,
                    'indice': i + 1,
                })
        
        print(f"[DEBUG] Extraídas {len(faturas)} faturas do HTML")
        return faturas
        
    except Exception as e:
        print(f"[ERRO] Erro ao extrair faturas do HTML: {e}")
        import traceback
        traceback.print_exc()
        return []


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
        logger.info(f'[PLANO A] Navegando para {NIO_BASE_URL}')
        page.goto(NIO_BASE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        # Preencher CPF
        logger.info(f'[PLANO A] Preenchendo CPF: {cpf}')
        input_cpf = page.locator('input[type="text"]').first
        if input_cpf.count() == 0:
            logger.error('[PLANO A] ❌ Campo de CPF não encontrado!')
            # Capturar screenshot para debug
            try:
                screenshot_path = os.path.join(os.path.dirname(__file__), '..', '..', 'debug_plano_a_no_input.png')
                page.screenshot(path=screenshot_path, full_page=True)
                logger.error(f'[PLANO A] Screenshot salvo em: {screenshot_path}')
            except:
                pass
            browser.close()
            return {'valor': None, 'codigo_pix': None, 'codigo_barras': None, 'data_vencimento': None, 'pdf_url': None}
        
        input_cpf.fill(cpf)
        logger.info(f'[PLANO A] CPF preenchido com sucesso')
        page.wait_for_timeout(500)
        
        # Verificar se botão "Consultar" existe
        logger.info(f'[PLANO A] Procurando botão "Consultar"...')
        btn_consultar = page.locator('button:has-text("Consultar")').first
        btn_count = btn_consultar.count()
        
        if btn_count == 0:
            logger.error('[PLANO A] ❌ Botão "Consultar" não encontrado!')
            # Tentar outros seletores
            logger.info('[PLANO A] Tentando seletores alternativos...')
            alternativas = [
                'button:has-text("CONSULTAR")',
                'button[type="submit"]',
                'input[type="submit"]',
                'button.btn',
                'button',
            ]
            encontrado = False
            for sel in alternativas:
                alt_btn = page.locator(sel).first
                if alt_btn.count() > 0:
                    logger.info(f'[PLANO A] ✅ Botão encontrado com seletor alternativo: {sel}')
                    alt_btn.click(timeout=10000)
                    encontrado = True
                    break
            
            if not encontrado:
                # Capturar screenshot e HTML para debug
                try:
                    screenshot_path = os.path.join(os.path.dirname(__file__), '..', '..', 'debug_plano_a_no_button.png')
                    page.screenshot(path=screenshot_path, full_page=True)
                    logger.error(f'[PLANO A] Screenshot salvo em: {screenshot_path}')
                    
                    html_path = os.path.join(os.path.dirname(__file__), '..', '..', 'debug_plano_a_html.html')
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(page.content())
                    logger.error(f'[PLANO A] HTML salvo em: {html_path}')
                except Exception as e:
                    logger.error(f'[PLANO A] Erro ao salvar debug: {e}')
                
                browser.close()
                return {'valor': None, 'codigo_pix': None, 'codigo_barras': None, 'data_vencimento': None, 'pdf_url': None}
        else:
            logger.info(f'[PLANO A] ✅ Botão "Consultar" encontrado, clicando...')
            btn_consultar.click(timeout=10000)
        
        page.wait_for_timeout(1500)
        logger.info('[PLANO A] Aguardando carregamento da página após consulta...')
        page.wait_for_load_state("networkidle", timeout=20000)
        logger.info('[PLANO A] Página carregada após consulta')

        # Verificar se há resultados ou erro na página
        page_url = page.url
        logger.info(f'[PLANO A] URL após consulta: {page_url}')
        html_apos_consulta = page.content()
        
        # Verificar se há mensagem de erro ou "não encontrado"
        html_lower = html_apos_consulta.lower()
        mensagens_nao_encontrado = [
            'não encontrado',
            'sem faturas',
            'nenhuma fatura',
            'não há faturas',
            'não existem faturas',
            'sem débitos',
            'não possui'
        ]
        
        tem_mensagem_nao_encontrado = any(msg in html_lower for msg in mensagens_nao_encontrado)
        
        if tem_mensagem_nao_encontrado:
            logger.warning('[PLANO A] ⚠️ Mensagem de "não encontrado" detectada na página')
            browser.close()
            return {
                'valor': None,
                'codigo_pix': None,
                'codigo_barras': None,
                'data_vencimento': None,
                'pdf_url': None,
                'sem_dividas': True,
                'mensagem': 'Não foram encontradas faturas para este CPF'
            }
        
        ver_detalhes = page.locator('text=/ver detalhes/i').first
        ver_detalhes_count = ver_detalhes.count()
        logger.info(f'[PLANO A] Verificando "ver detalhes": encontrados {ver_detalhes_count} elementos')
        
        if ver_detalhes_count > 0:
            logger.info('[PLANO A] Clicando em "ver detalhes"...')
            ver_detalhes.click()
            page.wait_for_timeout(800)
            logger.info('[PLANO A] "Ver detalhes" expandido')
        else:
            logger.warning('[PLANO A] ⚠️ Link "ver detalhes" não encontrado - pode não haver faturas ou já estar expandido')

        html_expandido = page.content()
        vencimento = None
        m = re.search(r'(\d{2}/\d{2}/\d{4})', html_expandido)
        if m:
            try:
                vencimento = datetime.strptime(m.group(1), "%d/%m/%Y").date()
                logger.info(f'[PLANO A] Data de vencimento encontrada: {vencimento}')
            except Exception:
                pass
        else:
            logger.warning('[PLANO A] ⚠️ Data de vencimento não encontrada no HTML')

        logger.info('[PLANO A] Procurando botão "Pagar conta"...')
        pagar_btn = page.locator('button:has-text("Pagar conta")').first
        pagar_btn_count = pagar_btn.count()
        logger.info(f'[PLANO A] Botão "Pagar conta": encontrados {pagar_btn_count} elementos')
        
        if pagar_btn_count == 0:
            logger.error('[PLANO A] ❌ Botão "Pagar conta" não encontrado!')
            # Tentar seletores alternativos
            logger.info('[PLANO A] Tentando seletores alternativos para "Pagar conta"...')
            alternativas_pagar = [
                'button:has-text("Pagar")',
                'a:has-text("Pagar conta")',
                'button[type="button"]:has-text("Pagar")',
                '*[role="button"]:has-text("Pagar")',
            ]
            encontrado_pagar = False
            for sel in alternativas_pagar:
                alt_btn = page.locator(sel).first
                if alt_btn.count() > 0:
                    logger.info(f'[PLANO A] ✅ Botão "Pagar" encontrado com seletor alternativo: {sel}')
                    pagar_btn = alt_btn
                    encontrado_pagar = True
                    break
            
            if not encontrado_pagar:
                # Capturar screenshot e HTML para debug
                try:
                    downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
                    os.makedirs(downloads_dir, exist_ok=True)
                    
                    screenshot_path = os.path.join(downloads_dir, f'debug_plano_a_no_pagar_{cpf}.png')
                    page.screenshot(path=screenshot_path, full_page=True)
                    logger.error(f'[PLANO A] Screenshot salvo em: {screenshot_path}')
                    
                    html_path = os.path.join(downloads_dir, f'debug_plano_a_no_pagar_{cpf}.html')
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(page.content())
                    logger.error(f'[PLANO A] HTML salvo em: {html_path}')
                except Exception as e:
                    logger.error(f'[PLANO A] Erro ao salvar debug: {e}')
                
                # Se não encontrou "Pagar conta", provavelmente não há faturas
                logger.warning('[PLANO A] ⚠️ Parece que não há faturas para este CPF (botões não encontrados)')
                browser.close()
                return {
                    'valor': None,
                    'codigo_pix': None,
                    'codigo_barras': None,
                    'data_vencimento': vencimento,
                    'pdf_url': None,
                    'sem_dividas': True,  # Indica que não há faturas
                    'mensagem': 'Não foram encontradas faturas para este CPF'
                }
        else:
            logger.info('[PLANO A] ✅ Botão "Pagar conta" encontrado, clicando...')
        
        pagar_btn.click(timeout=15000)
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

        # PDF - Múltiplas estratégias para capturar o PDF
        pdf_url = None
        pdf_path = None
        
        # Estratégia 1: Procurar link direto na página HTML antes de clicar
        try:
            logger.info('[PDF] Estratégia 1: Procurando link direto na página...')
            html_boleto_check = page.content()
            pdf_links = re.findall(r'https?://[^\s<>"\']+\.pdf[^\s<>"\']*', html_boleto_check, re.IGNORECASE)
            if pdf_links:
                pdf_url = pdf_links[0]
                logger.info(f'[PDF] ✅ Link encontrado diretamente no HTML: {pdf_url[:100]}...')
        except Exception as e:
            logger.debug(f'[PDF] Estratégia 1 falhou: {e}')
        
        # Estratégia 2: Tentar capturar via download direto
        if not pdf_url and not pdf_path:
            try:
                logger.info('[PDF] Estratégia 2: Tentando capturar via download direto...')
                download_path = os.path.join(os.path.dirname(__file__), '..', '..', 'downloads')
                os.makedirs(download_path, exist_ok=True)
                
                # Aguardar download ao clicar
                with page.expect_download(timeout=10000) as download_info:
                    page.locator('text="Baixar PDF"').first.click()
                download = download_info.value
                
                # Salvar o arquivo
                filename = download.suggested_filename or f"fatura_{cpf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                filepath = os.path.join(download_path, filename)
                download.save_as(filepath)
                
                # Verificar se arquivo foi salvo corretamente
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    pdf_path = filepath
                    logger.info(f'[PDF] ✅ Arquivo baixado com sucesso: {filepath} ({os.path.getsize(filepath)} bytes)')
                    
                    # Tentar fazer upload para OneDrive para ter URL pública
                    try:
                        from crm_app.onedrive_service import OneDriveUploader
                        uploader = OneDriveUploader()
                        
                        # Criar pasta no OneDrive: Faturas_NIO/YYYY/MM
                        from datetime import datetime
                        ano = datetime.now().strftime('%Y')
                        mes = datetime.now().strftime('%m')
                        folder_name = f"Faturas_NIO/{ano}/{mes}"
                        
                        logger.info(f'[PDF] ☁️ Fazendo upload para OneDrive: {folder_name}/{filename}')
                        with open(filepath, 'rb') as f:
                            link_onedrive = uploader.upload_file(f, folder_name, filename)
                        
                        if link_onedrive:
                            pdf_url = link_onedrive
                            logger.info(f'[PDF] ✅ Upload OneDrive concluído: {link_onedrive}')
                        else:
                            logger.warning('[PDF] ⚠️ Upload OneDrive falhou, mas arquivo local salvo')
                    except Exception as e_onedrive:
                        logger.warning(f'[PDF] ⚠️ Erro ao fazer upload OneDrive: {e_onedrive}')
                        # Mesmo se OneDrive falhar, o arquivo local está disponível
                else:
                    logger.warning(f'[PDF] ⚠️ Arquivo baixado mas está vazio ou não existe: {filepath}')
                
            except Exception as e:
                logger.debug(f'[PDF] Estratégia 2 falhou: {e}')
        
        # Estratégia 3: Tentar capturar via popup/aba (método original)
        if not pdf_url and not pdf_path:
            try:
                logger.info('[PDF] Estratégia 3: Tentando capturar via popup...')
                with context.expect_page(timeout=10000) as popup_info:
                    page.locator('text="Baixar PDF"').first.click()
                pdf_page = popup_info.value
                pdf_page.wait_for_load_state('networkidle', timeout=5000)
                pdf_url = pdf_page.url
                
                # Verificar se a URL realmente é um PDF
                if pdf_url and (pdf_url.endswith('.pdf') or 'application/pdf' in pdf_page.url or '.pdf' in pdf_url.lower()):
                    logger.info(f'[PDF] ✅ Link capturado via popup: {pdf_url[:100]}...')
                else:
                    # Pode ser uma página intermediária, tentar encontrar o link do PDF
                    html_pdf_page = pdf_page.content()
                    pdf_links_page = re.findall(r'https?://[^\s<>"\']+\.pdf[^\s<>"\']*', html_pdf_page, re.IGNORECASE)
                    if pdf_links_page:
                        pdf_url = pdf_links_page[0]
                        logger.info(f'[PDF] ✅ Link encontrado na página do popup: {pdf_url[:100]}...')
                    else:
                        pdf_url = None  # Não encontrou PDF válido
                
                pdf_page.close()
            except Exception as e:
                logger.debug(f'[PDF] Estratégia 3 falhou: {e}')
                import traceback
                logger.debug(f'[PDF] Traceback Estratégia 3: {traceback.format_exc()}')
        
        # Estratégia 4: Tentar extrair de atributos href ou onclick
        if not pdf_url and not pdf_path:
            try:
                logger.info('[PDF] Estratégia 4: Procurando em atributos HTML...')
                btn_pdf = page.locator('text="Baixar PDF"').first
                if btn_pdf.count() > 0:
                    href = btn_pdf.get_attribute('href')
                    onclick = btn_pdf.get_attribute('onclick')
                    
                    if href and '.pdf' in href.lower():
                        pdf_url = href if href.startswith('http') else f"{page.url.rsplit('/', 1)[0]}/{href.lstrip('/')}"
                        logger.info(f'[PDF] ✅ Link encontrado em href: {pdf_url[:100]}...')
                    elif onclick:
                        # Extrair URL do onclick (pode conter JavaScript)
                        onclick_urls = re.findall(r'https?://[^\s\'"]+\.pdf[^\s\'"]*', onclick, re.IGNORECASE)
                        if onclick_urls:
                            pdf_url = onclick_urls[0]
                            logger.info(f'[PDF] ✅ Link encontrado em onclick: {pdf_url[:100]}...')
            except Exception as e:
                logger.debug(f'[PDF] Estratégia 4 falhou: {e}')
        
        if not pdf_url and not pdf_path:
            logger.warning('[PDF] ⚠️ Todas as estratégias falharam. PDF não capturado.')

        browser.close()

        resultado = {
            'valor': valor,
            'codigo_pix': codigo_pix,
            'codigo_barras': codigo_barras,
            'data_vencimento': vencimento,
            'pdf_url': pdf_url,
        }
        
        # Adicionar pdf_path e pdf_filename se foi baixado
        if pdf_path:
            resultado['pdf_path'] = pdf_path
            # Extrair nome do arquivo do caminho (os já está importado no topo do arquivo)
            resultado['pdf_filename'] = os.path.basename(pdf_path)
            logger.info(f'[PDF] ✅ PDF path adicionado ao resultado: {pdf_path}')
            logger.info(f'[PDF] ✅ PDF filename: {resultado["pdf_filename"]}')
        
        return resultado


def _validar_contrato_masked(masked_contrato: str, contrato_completo: str) -> bool:
    """
    Valida se o contrato mascarado (ex: "02****90") corresponde ao contrato completo.
    Compara os 2 primeiros e 2 últimos dígitos.
    """
    if not masked_contrato or not contrato_completo:
        return False
    
    masked_limpo = re.sub(r'[^0-9*]', '', masked_contrato)
    completo_limpo = re.sub(r'\D', '', str(contrato_completo))
    
    if '*' not in masked_limpo:
        return masked_limpo == completo_limpo
    
    partes = masked_limpo.split('*')
    if len(partes) < 2:
        return False
    
    inicio_masked = partes[0][:2] if len(partes[0]) >= 2 else partes[0]
    fim_masked = partes[-1][-2:] if len(partes[-1]) >= 2 else partes[-1]
    
    if len(completo_limpo) < 4:
        return False
    
    inicio_completo = completo_limpo[:2]
    fim_completo = completo_limpo[-2:]
    
    return inicio_masked == inicio_completo and fim_masked == fim_completo


def _buscar_fatura_nio_negocia(
    cpf: str, 
    numero_contrato=None,
    incluir_pdf=True,
    mes_referencia=None
):
    """
    Busca fatura via Nio Negocia (Plano B)
    Implementa os 12 passos descritos pelo usuário.
    
    Args:
        cpf: CPF do cliente
        numero_contrato: Número do contrato para validação (opcional)
        incluir_pdf: Se True, tenta baixar PDF
        mes_referencia: Mês de referência para nomear arquivo
        
    Returns:
        dict com: valor, codigo_pix, codigo_barras, data_vencimento, pdf_url
        ou None se falhou
    """
    if not HAS_PLAYWRIGHT:
        logger.warning("[NIO NEGOCIA] Playwright não disponível")
        return None
    
    try:
        from crm_app.recaptcha_solver import RecaptchaSolver
        
        cpf_limpo = re.sub(r'\D', '', cpf or '')
        if not cpf_limpo:
            return None
        
        logger.info(f"[NIO NEGOCIA] Iniciando busca para CPF: {cpf_limpo}")
        
        # Inicializar solver de captcha
        captcha_api_key = getattr(settings, 'CAPTCHA_API_KEY', None) or os.getenv('CAPTCHA_API_KEY')
        solver = RecaptchaSolver(api_key=captcha_api_key) if captcha_api_key else None
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            state_path = DEFAULT_STORAGE_STATE if os.path.exists(DEFAULT_STORAGE_STATE) else None
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                storage_state=state_path,
                accept_downloads=True,
            )
            
            page = context.new_page()
            
            # PASSO 1: Acessar site
            logger.info(f"[NIO NEGOCIA] Passo 1: Acessando {NIO_NEGOCIA_URL}")
            try:
                page.goto(NIO_NEGOCIA_URL, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
            except Exception as e:
                logger.error(f"[NIO NEGOCIA] Erro ao acessar site: {e}")
                browser.close()
                return None
            
            # PASSO 2: Informar CPF/CNPJ
            logger.info(f"[NIO NEGOCIA] Passo 2: Preenchendo CPF")
            campo_cpf = None
            seletores_cpf = [
                '#inputId',
                'input#inputId',
                'input.sc-kvZOFW.dXumbB',
                'input[type="text"]',
            ]
            
            for seletor in seletores_cpf:
                try:
                    locator = page.locator(seletor).first
                    if locator.count() > 0 and locator.is_visible(timeout=3000):
                        campo_cpf = locator
                        break
                except:
                    continue
            
            if not campo_cpf:
                logger.error("[NIO NEGOCIA] Campo CPF não encontrado")
                browser.close()
                return None
            
            try:
                campo_cpf.fill(cpf_limpo)
                page.wait_for_timeout(1000)
            except Exception as e:
                logger.error(f"[NIO NEGOCIA] Erro ao preencher CPF: {e}")
                browser.close()
                return None
            
            # PASSO 3: Resolver reCAPTCHA
            logger.info(f"[NIO NEGOCIA] Passo 3: Resolvendo reCAPTCHA")
            recaptcha_resolvido = False
            if solver:
                try:
                    # Tentar múltiplas formas de encontrar a site key do reCAPTCHA
                    site_key = page.evaluate("""
                        () => {
                            // Tentar vários seletores e atributos
                            const selectors = [
                                '[data-sitekey]',
                                '.g-recaptcha',
                                'div[data-sitekey]',
                                'iframe[src*="recaptcha"]',
                                '#recaptcha',
                                '.recaptcha'
                            ];
                            
                            for (const sel of selectors) {
                                const el = document.querySelector(sel);
                                if (el) {
                                    const key = el.getAttribute('data-sitekey') || 
                                               el.getAttribute('data-site-key') ||
                                               (el.querySelector('[data-sitekey]')?.getAttribute('data-sitekey'));
                                    if (key) return key;
                                }
                            }
                            
                            // Tentar encontrar no iframe do reCAPTCHA
                            const iframe = document.querySelector('iframe[src*="recaptcha"]');
                            if (iframe) {
                                const src = iframe.src;
                                const match = src.match(/[?&]k=([^&]+)/);
                                if (match) return match[1];
                            }
                            
                            // Tentar encontrar no script
                            const scripts = Array.from(document.querySelectorAll('script'));
                            for (const script of scripts) {
                                if (script.src && script.src.includes('recaptcha')) {
                                    const match = script.src.match(/[?&]render=([^&]+)/);
                                    if (match) return match[1];
                                }
                                if (script.innerHTML && script.innerHTML.includes('sitekey')) {
                                    const match = script.innerHTML.match(/sitekey['"]\\s*[:=]\\s*['"]([^'"]+)['"]/);
                                    if (match) return match[1];
                                }
                            }
                            
                            return null;
                        }
                    """)
                    if site_key:
                        logger.info(f"[NIO NEGOCIA] Site key encontrada: {site_key[:20]}...")
                        print(f"[DEBUG NIO NEGOCIA] Site key: {site_key}")
                        token = solver.solve_recaptcha_v2(site_key, NIO_NEGOCIA_URL)
                        if token:
                            print(f"[DEBUG NIO NEGOCIA] Token reCAPTCHA obtido: {token[:50]}...")
                            logger.info(f"[NIO NEGOCIA] Token reCAPTCHA obtido")
                            page.evaluate(f"""
                                (t) => {{
                                    const selectors = [
                                        'textarea[name="g-recaptcha-response"]',
                                        '#g-recaptcha-response',
                                        'input[name="g-recaptcha-response"]'
                                    ];
                                    for (const sel of selectors) {{
                                        const el = document.querySelector(sel);
                                        if (el) {{
                                            el.value = t;
                                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        }}
                                    }}
                                    // Tentar múltiplas formas de fazer o grecaptcha.getResponse() retornar o valor
                                    if (window.grecaptcha) {{
                                        try {{
                                            // Método 1: Sobrescrever getResponse
                                            if (window.grecaptcha.getResponse) {{
                                                window.grecaptcha.getResponse = function() {{
                                                    return t;
                                                }};
                                            }}
                                            
                                            // Método 2: Tentar definir diretamente
                                            if (window.grecaptcha.response !== undefined) {{
                                                window.grecaptcha.response = t;
                                            }}
                                            
                                            // Método 3: Disparar evento customizado
                                            window.dispatchEvent(new CustomEvent('recaptcha-success', {{ detail: {{ response: t }} }}));
                                            
                                            // Método 4: Tentar encontrar e disparar callbacks do reCAPTCHA
                                            // Verificar se há widgets renderizados e tentar disparar callbacks
                                            try {{
                                                const widgets = document.querySelectorAll('[data-sitekey]');
                                                widgets.forEach((widget) => {{
                                                    try {{
                                                        const widgetId = widget.getAttribute('data-widget-id');
                                                        if (widgetId && window.grecaptcha.getResponse) {{
                                                            // Tentar obter o callback do widget
                                                            const currentResponse = window.grecaptcha.getResponse(widgetId);
                                                            // Se não tiver resposta, tentar definir
                                                            if (!currentResponse) {{
                                                                // Tentar disparar o callback manualmente
                                                                if (window.grecaptcha.execute) {{
                                                                    // Não executar, apenas verificar se existe
                                                                }}
                                                            }}
                                                        }}
                                                    }} catch(e) {{
                                                        console.log('Erro ao processar widget:', e);
                                                    }}
                                                }});
                                            }} catch(e) {{
                                                console.log('Erro ao processar widgets:', e);
                                            }}
                                        }} catch (e) {{
                                            console.log('Erro ao configurar grecaptcha:', e);
                                        }}
                                    }}
                                    
                                    // Método 5: Tentar disparar eventos no textarea para simular interação
                                    const textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
                                    if (textarea) {{
                                        // Disparar eventos adicionais para simular interação
                                        textarea.dispatchEvent(new Event('focus', {{ bubbles: true }}));
                                        textarea.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                                        textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                        textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
                                        
                                        // Tentar disparar evento de sucesso
                                        const successEvent = new CustomEvent('recaptcha-verified', {{ 
                                            bubbles: true, 
                                            detail: {{ response: t }} 
                                        }});
                                        textarea.dispatchEvent(successEvent);
                                    }}
                                }}
                            """, token)
                            
                            # Aguardar e verificar se o grecaptcha.getResponse() agora retorna o valor
                            page.wait_for_timeout(2000)
                            
                            # Tentar disparar o callback do reCAPTCHA se existir
                            try:
                                callback_disparado = page.evaluate("""
                                    () => {
                                        // Tentar encontrar e disparar callbacks do reCAPTCHA
                                        const callbacks = [];
                                        
                                        // Verificar se há um callback registrado
                                        if (window.grecaptcha && window.grecaptcha.render) {
                                            // Tentar encontrar widgets renderizados
                                            const widgets = document.querySelectorAll('[data-sitekey]');
                                            widgets.forEach((widget) => {
                                                try {
                                                    const widgetId = widget.getAttribute('data-widget-id');
                                                    if (widgetId) {
                                                        // Tentar obter o callback do widget
                                                        const callback = window.grecaptcha.getResponse(widgetId);
                                                        if (callback) {
                                                            callbacks.push({ widgetId, hasResponse: !!callback });
                                                        }
                                                    }
                                                } catch(e) {
                                                    console.log('Erro ao verificar widget:', e);
                                                }
                                            });
                                        }
                                        
                                        // Tentar disparar evento de sucesso do reCAPTCHA
                                        try {
                                            // Verificar se há listeners para 'recaptcha-success'
                                            const textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
                                            if (textarea) {
                                                // Disparar eventos adicionais
                                                textarea.dispatchEvent(new Event('focus', { bubbles: true }));
                                                textarea.dispatchEvent(new Event('blur', { bubbles: true }));
                                                
                                                // Tentar disparar callback se houver
                                                if (window.grecaptcha && window.grecaptcha.execute) {
                                                    // Não executar, apenas verificar se existe
                                                }
                                            }
                                        } catch(e) {
                                            console.log('Erro ao disparar eventos:', e);
                                        }
                                        
                                        return { callbacks_encontrados: callbacks.length };
                                    }
                                """)
                                print(f"[DEBUG NIO NEGOCIA] Callbacks do reCAPTCHA: {callback_disparado}")
                                logger.info(f"[NIO NEGOCIA] Callbacks: {callback_disparado}")
                            except Exception as e_callback:
                                print(f"[DEBUG NIO NEGOCIA] Erro ao disparar callbacks: {e_callback}")
                                logger.warning(f"[NIO NEGOCIA] Erro ao disparar callbacks: {e_callback}")
                            
                            # Verificar se o grecaptcha.getResponse() está funcionando
                            grecaptcha_check = page.evaluate("""
                                () => {
                                    if (window.grecaptcha && window.grecaptcha.getResponse) {
                                        try {
                                            const response = window.grecaptcha.getResponse();
                                            return {
                                                has_response: !!response,
                                                response_length: response ? response.length : 0,
                                                response_preview: response ? response.substring(0, 50) + '...' : null
                                            };
                                        } catch(e) {
                                            return { error: e.message };
                                        }
                                    }
                                    return { error: 'grecaptcha.getResponse não existe' };
                                }
                            """)
                            print(f"[DEBUG NIO NEGOCIA] Verificação grecaptcha.getResponse() após injeção: {grecaptcha_check}")
                            logger.info(f"[NIO NEGOCIA] grecaptcha.getResponse() após injeção: {grecaptcha_check}")
                            
                            # Se ainda não funcionou, tentar mais uma vez com mais tempo
                            if not grecaptcha_check.get('has_response') or grecaptcha_check.get('response_length', 0) < 50:
                                print(f"[DEBUG NIO NEGOCIA] ⚠️ grecaptcha.getResponse() ainda não retorna valor, aguardando mais...")
                                logger.warning(f"[NIO NEGOCIA] grecaptcha.getResponse() ainda não retorna valor")
                                
                                # Tentar re-injetar o token e aguardar
                                page.evaluate("""
                                    (t) => {
                                        // Re-injetar no textarea
                                        const textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
                                        if (textarea) {
                                            textarea.value = t;
                                            textarea.dispatchEvent(new Event('input', { bubbles: true }));
                                            textarea.dispatchEvent(new Event('change', { bubbles: true }));
                                        }
                                        
                                        // Re-sobrescrever getResponse
                                        if (window.grecaptcha && window.grecaptcha.getResponse) {
                                            window.grecaptcha.getResponse = function() { return t; };
                                        }
                                    }
                                """, token)
                                
                                page.wait_for_timeout(3000)
                                
                                # Verificar novamente
                                grecaptcha_check2 = page.evaluate("""
                                    () => {
                                        if (window.grecaptcha && window.grecaptcha.getResponse) {
                                            try {
                                                const response = window.grecaptcha.getResponse();
                                                return {
                                                    has_response: !!response,
                                                    response_length: response ? response.length : 0
                                                };
                                            } catch(e) {
                                                return { error: e.message };
                                            }
                                        }
                                        return { error: 'grecaptcha.getResponse não existe' };
                                    }
                                """)
                                print(f"[DEBUG NIO NEGOCIA] Verificação grecaptcha.getResponse() após aguardar: {grecaptcha_check2}")
                                logger.info(f"[NIO NEGOCIA] grecaptcha.getResponse() após aguardar: {grecaptcha_check2}")
                            
                            # Verificar se o reCAPTCHA foi realmente resolvido
                            recaptcha_verificado = page.evaluate("""
                                () => {
                                    const textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
                                    const has_textarea_value = textarea && textarea.value && textarea.value.length > 50;
                                    
                                    let has_grecaptcha_response = false;
                                    let grecaptcha_response_length = 0;
                                    if (window.grecaptcha && window.grecaptcha.getResponse) {
                                        try {
                                            const response = window.grecaptcha.getResponse();
                                            has_grecaptcha_response = response && response.length > 50;
                                            grecaptcha_response_length = response ? response.length : 0;
                                        } catch(e) {
                                            console.log('Erro ao obter grecaptcha.getResponse():', e);
                                        }
                                    }
                                    
                                    // Verificar também se o botão está habilitado (indicador de que o reCAPTCHA foi aceito)
                                    const btn = document.querySelector('button:has-text("Consultar dívidas")');
                                    const btn_enabled = btn && !btn.hasAttribute('disabled');
                                    
                                    return {
                                        has_textarea_value: has_textarea_value,
                                        has_grecaptcha_response: has_grecaptcha_response,
                                        grecaptcha_response_length: grecaptcha_response_length,
                                        btn_enabled: btn_enabled,
                                        final: has_textarea_value || has_grecaptcha_response
                                    };
                                }
                            """)
                            
                            # Logar detalhes da verificação
                            print(f"[DEBUG NIO NEGOCIA] Verificação detalhada do reCAPTCHA: {recaptcha_verificado}")
                            logger.info(f"[NIO NEGOCIA] Verificação reCAPTCHA: {recaptcha_verificado}")
                            
                            # Usar o resultado final
                            recaptcha_verificado = recaptcha_verificado.get('final', False)
                            
                            if recaptcha_verificado:
                                logger.info("[NIO NEGOCIA] ✅ reCAPTCHA resolvido e verificado")
                                print(f"[DEBUG NIO NEGOCIA] ✅ reCAPTCHA resolvido e verificado")
                                recaptcha_resolvido = True
                            else:
                                logger.warning("[NIO NEGOCIA] ⚠️ reCAPTCHA token injetado mas não verificado")
                                print(f"[DEBUG NIO NEGOCIA] ⚠️ reCAPTCHA token injetado mas não verificado")
                        else:
                            logger.warning("[NIO NEGOCIA] ⚠️ Não foi possível obter token do reCAPTCHA")
                            print(f"[DEBUG NIO NEGOCIA] ⚠️ Não foi possível obter token do reCAPTCHA")
                    else:
                        logger.info("[NIO NEGOCIA] ℹ️ Site key não encontrada (pode não ter reCAPTCHA)")
                        print(f"[DEBUG NIO NEGOCIA] ℹ️ Site key não encontrada")
                except Exception as e:
                    logger.warning(f"[NIO NEGOCIA] Erro ao resolver reCAPTCHA: {e}")
                    print(f"[DEBUG NIO NEGOCIA] ❌ Erro ao resolver reCAPTCHA: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                logger.warning("[NIO NEGOCIA] ⚠️ Solver de reCAPTCHA não disponível (CAPTCHA_API_KEY não configurada)")
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Solver de reCAPTCHA não disponível")
            
            # PASSO 4: Clicar em "Consultar dívidas"
            logger.info(f"[NIO NEGOCIA] Passo 4: Clicando em Consultar dívidas")
            print(f"[DEBUG NIO NEGOCIA] Passo 4: Procurando botão 'Consultar dívidas'...")
            btn_consultar = None
            seletores_consultar = [
                'button:has-text("Consultar dívidas")',
                'span.sc-gqPbQI.faIpbA:has-text("Consultar dívidas")',
                'span:has-text("Consultar dívidas")',
                'button.sc-EHOje.btbnVF',
            ]
            
            for seletor in seletores_consultar:
                try:
                    locator = page.locator(seletor).first
                    if locator.count() > 0 and locator.is_visible(timeout=3000):
                        btn_consultar = locator
                        print(f"[DEBUG NIO NEGOCIA] ✅ Botão encontrado com seletor: {seletor}")
                        logger.info(f"[NIO NEGOCIA] Botão encontrado com seletor: {seletor}")
                        break
                except Exception as e_sel:
                    print(f"[DEBUG NIO NEGOCIA] Seletor {seletor} falhou: {e_sel}")
                    continue
            
            if not btn_consultar:
                logger.error("[NIO NEGOCIA] Botão Consultar dívidas não encontrado")
                print(f"[DEBUG NIO NEGOCIA] ❌ Botão não encontrado")
                # Capturar screenshot para debug
                try:
                    downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
                    os.makedirs(downloads_dir, exist_ok=True)
                    screenshot_path = os.path.join(downloads_dir, f"debug_nio_negocia_botao_nao_encontrado_{cpf_limpo}.png")
                    page.screenshot(path=screenshot_path, full_page=True)
                    print(f"[DEBUG NIO NEGOCIA] 📸 Screenshot salvo: {screenshot_path}")
                    logger.info(f"[NIO NEGOCIA] Screenshot salvo: {screenshot_path}")
                except:
                    pass
                browser.close()
                return None
            
            # Verificar estado do botão antes de clicar
            is_enabled = False
            is_visible = False
            try:
                is_enabled = btn_consultar.is_enabled(timeout=1000)
                is_visible = btn_consultar.is_visible(timeout=1000)
                print(f"[DEBUG NIO NEGOCIA] Estado do botão: enabled={is_enabled}, visible={is_visible}")
                logger.info(f"[NIO NEGOCIA] Estado do botão: enabled={is_enabled}, visible={is_visible}")
                
                # Se o botão está desabilitado, aguardar até ficar habilitado (pode ser que o reCAPTCHA ainda esteja validando)
                if not is_enabled:
                    print(f"[DEBUG NIO NEGOCIA] ⏳ Botão desabilitado, aguardando até ficar habilitado...")
                    logger.info(f"[NIO NEGOCIA] Botão desabilitado, aguardando até ficar habilitado...")
                    
                    # Verificar se o grecaptcha.getResponse() está funcionando enquanto aguarda
                    grecaptcha_status_inicial = page.evaluate("""
                        () => {
                            if (window.grecaptcha && window.grecaptcha.getResponse) {
                                try {
                                    const response = window.grecaptcha.getResponse();
                                    return {
                                        has_response: !!response,
                                        response_length: response ? response.length : 0
                                    };
                                } catch(e) {
                                    return { error: e.message };
                                }
                            }
                            return { error: 'grecaptcha.getResponse não existe' };
                        }
                    """)
                    print(f"[DEBUG NIO NEGOCIA] Estado inicial do grecaptcha.getResponse() enquanto aguarda: {grecaptcha_status_inicial}")
                    logger.info(f"[NIO NEGOCIA] grecaptcha.getResponse() inicial: {grecaptcha_status_inicial}")
                    
                    # Aguardar até 30 segundos para o botão ficar habilitado
                    max_espera = 30
                    for tentativa in range(max_espera):
                        try:
                            if btn_consultar.is_enabled(timeout=1000):
                                print(f"[DEBUG NIO NEGOCIA] ✅ Botão habilitado após {tentativa + 1} segundos")
                                logger.info(f"[NIO NEGOCIA] Botão habilitado após {tentativa + 1} segundos")
                                is_enabled = True
                                break
                        except:
                            pass
                        
                        # A cada 5 segundos, verificar o estado do grecaptcha.getResponse()
                        if tentativa > 0 and tentativa % 5 == 0:
                            grecaptcha_status = page.evaluate("""
                                () => {
                                    if (window.grecaptcha && window.grecaptcha.getResponse) {
                                        try {
                                            const response = window.grecaptcha.getResponse();
                                            return {
                                                has_response: !!response,
                                                response_length: response ? response.length : 0
                                            };
                                        } catch(e) {
                                            return { error: e.message };
                                        }
                                    }
                                    return { error: 'grecaptcha.getResponse não existe' };
                                }
                            """)
                            print(f"[DEBUG NIO NEGOCIA] grecaptcha.getResponse() após {tentativa + 1}s: {grecaptcha_status}")
                            logger.info(f"[NIO NEGOCIA] grecaptcha.getResponse() após {tentativa + 1}s: {grecaptcha_status}")
                        
                        page.wait_for_timeout(1000)
                    
                    if not is_enabled:
                        print(f"[DEBUG NIO NEGOCIA] ⚠️ Botão ainda desabilitado após {max_espera} segundos")
                        logger.warning(f"[NIO NEGOCIA] Botão ainda desabilitado após {max_espera} segundos")
                        
                        # Capturar screenshot para debug
                        try:
                            downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
                            os.makedirs(downloads_dir, exist_ok=True)
                            screenshot_path = os.path.join(downloads_dir, f"debug_nio_negocia_botao_desabilitado_{cpf_limpo}.png")
                            page.screenshot(path=screenshot_path, full_page=True)
                            print(f"[DEBUG NIO NEGOCIA] 📸 Screenshot do botão desabilitado: {screenshot_path}")
                            logger.info(f"[NIO NEGOCIA] Screenshot do botão desabilitado: {screenshot_path}")
                            
                            # Verificar estado do reCAPTCHA
                            recaptcha_status = page.evaluate("""
                                () => {
                                    const textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
                                    const has_value = textarea && textarea.value && textarea.value.length > 50;
                                    const grecaptcha_response = window.grecaptcha && window.grecaptcha.getResponse ? window.grecaptcha.getResponse() : null;
                                    return {
                                        has_textarea: !!textarea,
                                        has_value: has_value,
                                        value_length: textarea ? textarea.value.length : 0,
                                        grecaptcha_response: grecaptcha_response ? grecaptcha_response.substring(0, 50) + '...' : null
                                    };
                                }
                            """)
                            print(f"[DEBUG NIO NEGOCIA] Estado do reCAPTCHA: {recaptcha_status}")
                            logger.info(f"[NIO NEGOCIA] Estado do reCAPTCHA: {recaptcha_status}")
                        except Exception as e_debug:
                            print(f"[DEBUG NIO NEGOCIA] Erro ao capturar debug: {e_debug}")
                            logger.warning(f"[NIO NEGOCIA] Erro ao capturar debug: {e_debug}")
            except Exception as e_check:
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Erro ao verificar estado do botão: {e_check}")
                logger.warning(f"[NIO NEGOCIA] Erro ao verificar estado do botão: {e_check}")
            
            # Tentar clicar no botão (com force se necessário)
            try:
                if is_enabled:
                    print(f"[DEBUG NIO NEGOCIA] 🖱️ Clicando no botão (habilitado)...")
                    btn_consultar.click()
                else:
                    print(f"[DEBUG NIO NEGOCIA] 🖱️ Tentando clicar com force=True (botão desabilitado)...")
                    logger.warning(f"[NIO NEGOCIA] Tentando clicar com force=True")
                    
                    # Verificar reCAPTCHA antes de clicar com force
                    recaptcha_antes_clique = page.evaluate("""
                        () => {
                            const textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
                            let grecaptcha_response = null;
                            try {
                                if (window.grecaptcha && window.grecaptcha.getResponse) {
                                    grecaptcha_response = window.grecaptcha.getResponse();
                                }
                            } catch(e) {}
                            return {
                                textarea_value: textarea ? textarea.value.length : 0,
                                grecaptcha_response: grecaptcha_response ? grecaptcha_response.length : 0
                            };
                        }
                    """)
                    print(f"[DEBUG NIO NEGOCIA] Estado do reCAPTCHA antes do clique: {recaptcha_antes_clique}")
                    logger.info(f"[NIO NEGOCIA] reCAPTCHA antes do clique: {recaptcha_antes_clique}")
                    
                    btn_consultar.click(force=True)
                
                # Aguardar navegação ou mudança na página (SPA pode não mudar URL)
                print(f"[DEBUG NIO NEGOCIA] Aguardando conteúdo carregar após clique...")
                logger.info(f"[NIO NEGOCIA] Aguardando conteúdo após clique")
                
                # Aguardar um pouco para o clique ser processado
                page.wait_for_timeout(2000)
                
                # Verificar se houve mudança na URL primeiro
                url_antes = page.url
                print(f"[DEBUG NIO NEGOCIA] URL antes de aguardar: {url_antes}")
                logger.info(f"[NIO NEGOCIA] URL antes de aguardar: {url_antes}")
                
                # Aguardar mudança no DOM - verificar se novos elementos aparecem
                try:
                    # Aguardar até que apareça algum elemento indicativo da lista de dívidas
                    # Usar wait_for_function para verificar se o conteúdo mudou
                    print(f"[DEBUG NIO NEGOCIA] Iniciando wait_for_function para detectar conteúdo...")
                    logger.info(f"[NIO NEGOCIA] Iniciando wait_for_function")
                    
                    page.wait_for_function("""
                        () => {
                            // Verificar se há botões com data-context contendo "pagar"
                            const btnPagar = document.querySelector('button[data-context*="pagar"]');
                            if (btnPagar) {
                                console.log('[DEBUG] Botão pagar encontrado!');
                                return true;
                            }
                            
                            // Verificar se há elementos com valores monetários
                            const elementos = Array.from(document.querySelectorAll('*'));
                            for (let el of elementos) {
                                const texto = el.innerText || el.textContent || '';
                                if (texto.match(/R\\$\\s*\\d+[.,]\\d{2}/i) && texto.length < 200) {
                                    console.log('[DEBUG] Valor encontrado:', texto.substring(0, 50));
                                    return true;
                                }
                            }
                            
                            // Verificar se há datas
                            for (let el of elementos) {
                                const texto = el.innerText || el.textContent || '';
                                if (texto.match(/\\d{2}\\/\\d{2}\\/\\d{4}/) && texto.length < 200) {
                                    console.log('[DEBUG] Data encontrada:', texto.substring(0, 50));
                                    return true;
                                }
                            }
                            
                            // Verificar se a URL mudou
                            if (window.location.href.includes('debtslist')) {
                                console.log('[DEBUG] URL contém debtslist');
                                return true;
                            }
                            
                            return false;
                        }
                    """, timeout=30000)
                    print(f"[DEBUG NIO NEGOCIA] ✅ Conteúdo da lista detectado via JavaScript")
                    logger.info(f"[NIO NEGOCIA] Conteúdo da lista detectado")
                except Exception as e_wait:
                    print(f"[DEBUG NIO NEGOCIA] ⚠️ Timeout aguardando conteúdo: {e_wait}")
                    logger.warning(f"[NIO NEGOCIA] Timeout aguardando conteúdo: {e_wait}")
                    
                    # Verificar o estado atual da página após timeout
                    url_apos_timeout = page.url
                    print(f"[DEBUG NIO NEGOCIA] URL após timeout: {url_apos_timeout}")
                    logger.warning(f"[NIO NEGOCIA] URL após timeout: {url_apos_timeout}")
                    
                    # Tentar verificar se há algum erro na página
                    try:
                        erros = page.evaluate("""
                            () => {
                                const erros = [];
                                // Verificar se há mensagens de erro
                                const elementos = Array.from(document.querySelectorAll('*'));
                                for (let el of elementos) {
                                    const texto = el.innerText || el.textContent || '';
                                    const textoLower = texto.toLowerCase();
                                    if (textoLower.includes('erro') || 
                                        textoLower.includes('error') ||
                                        textoLower.includes('não encontrado') ||
                                        textoLower.includes('sem dívidas') ||
                                        textoLower.includes('cpf inválido') ||
                                        textoLower.includes('inválido') ||
                                        textoLower.includes('não encontramos') ||
                                        textoLower.includes('tente novamente')) {
                                        erros.push({
                                            texto: texto.substring(0, 200),
                                            tag: el.tagName,
                                            classes: el.className
                                        });
                                    }
                                }
                                
                                // Verificar também no console do navegador
                                const consoleErrors = [];
                                if (window.console && window.console.error) {
                                    // Não podemos acessar histórico do console, mas podemos verificar elementos de erro
                                }
                                
                                return erros;
                            }
                        """)
                        if erros:
                            print(f"[DEBUG NIO NEGOCIA] ⚠️ Possíveis erros encontrados na página: {len(erros)}")
                            logger.warning(f"[NIO NEGOCIA] Possíveis erros encontrados: {len(erros)}")
                            for idx, erro in enumerate(erros[:5], 1):  # Mostrar apenas os primeiros 5
                                print(f"[DEBUG NIO NEGOCIA]   Erro {idx}: {erro.get('texto', '')[:100]} (tag: {erro.get('tag', '')}, classes: {erro.get('classes', '')[:50]})")
                                logger.warning(f"[NIO NEGOCIA] Erro {idx}: {erro.get('texto', '')[:100]}")
                        else:
                            print(f"[DEBUG NIO NEGOCIA] ✅ Nenhuma mensagem de erro encontrada na página")
                            logger.info(f"[NIO NEGOCIA] Nenhuma mensagem de erro encontrada")
                    except Exception as e_erro:
                        print(f"[DEBUG NIO NEGOCIA] Erro ao verificar erros na página: {e_erro}")
                        logger.warning(f"[NIO NEGOCIA] Erro ao verificar erros: {e_erro}")
                
                # Aguardar mais tempo para garantir renderização completa
                page.wait_for_timeout(5000)  # Aguardar mais 5 segundos
                page.wait_for_load_state("networkidle", timeout=20000)
                page.wait_for_load_state("domcontentloaded", timeout=20000)
                
                # Verificar URL novamente
                url_apos_clique = page.url
                print(f"[DEBUG NIO NEGOCIA] URL após clique: {url_apos_clique}")
                logger.info(f"[NIO NEGOCIA] URL após clique: {url_apos_clique}")
                
                print(f"[DEBUG NIO NEGOCIA] ✅ Clique realizado e página aguardada")
                logger.info(f"[NIO NEGOCIA] Clique realizado e página aguardada")
            except Exception as e:
                logger.error(f"[NIO NEGOCIA] Erro ao clicar em Consultar dívidas: {e}")
                print(f"[DEBUG NIO NEGOCIA] ❌ Erro ao clicar: {e}")
                # Capturar screenshot antes de fechar
                try:
                    downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
                    os.makedirs(downloads_dir, exist_ok=True)
                    screenshot_path = os.path.join(downloads_dir, f"debug_nio_negocia_erro_clique_{cpf_limpo}.png")
                    page.screenshot(path=screenshot_path, full_page=True)
                    print(f"[DEBUG NIO NEGOCIA] 📸 Screenshot do erro: {screenshot_path}")
                    logger.info(f"[NIO NEGOCIA] Screenshot do erro: {screenshot_path}")
                except:
                    pass
                browser.close()
                return None
            
            # PASSO 5: Validar contrato e clicar em "Ver detalhes"
            logger.info(f"[NIO NEGOCIA] Passo 5: Verificando contrato e detalhes")
            
            # Verificar se há contrato mascarado e validar se necessário
            if numero_contrato:
                try:
                    html_content = page.content()
                    masked_pattern = re.search(r'(\d{2}\*{2,}\d{2})', html_content)
                    if masked_pattern:
                        contrato_masked = masked_pattern.group(1)
                        if not _validar_contrato_masked(contrato_masked, numero_contrato):
                            logger.warning(f"[NIO NEGOCIA] Contrato não corresponde: {contrato_masked} vs {numero_contrato}")
                            browser.close()
                            return None
                except Exception as e:
                    logger.warning(f"[NIO NEGOCIA] Erro ao validar contrato: {e}")
            
            # Clicar em "Ver detalhes"
            ver_detalhes = None
            seletores_detalhes = [
                'p.sc-htpNat.lpefcL:has-text("Ver detalhes")',
                'p:has-text("Ver detalhes")',
                'text=/ver detalhes/i',
            ]
            
            for seletor in seletores_detalhes:
                try:
                    locator = page.locator(seletor).first
                    if locator.count() > 0:
                        ver_detalhes = locator
                        break
                except:
                    continue
            
            if ver_detalhes:
                try:
                    ver_detalhes.click()
                    page.wait_for_timeout(2000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    logger.info("[NIO NEGOCIA] Detalhes expandidos")
                except Exception as e:
                    logger.warning(f"[NIO NEGOCIA] Erro ao clicar em Ver detalhes: {e}")
            
            # PASSO 6: Extrair dados da lista (Valor, Mês/Ano, Vencimento, Status)
            logger.info(f"[NIO NEGOCIA] Passo 6: Extraindo dados da lista")
            print(f"[DEBUG NIO NEGOCIA] Passo 6: Extraindo dados da lista...")
            
            # Verificar URL atual
            url_atual = page.url
            print(f"[DEBUG NIO NEGOCIA] URL atual: {url_atual}")
            logger.info(f"[NIO NEGOCIA] URL atual: {url_atual}")
            
            # DEBUG: Listar TODOS os elementos da página para identificar seletores corretos
            try:
                elementos_info = page.evaluate("""
                    () => {
                        const info = {
                            url: window.location.href,
                            titulo: document.title,
                            botoes: [],
                            elementos_com_texto: [],
                            elementos_com_data_context: [],
                            elementos_com_valor: [],
                            elementos_com_data: []
                        };
                        
                        // Listar todos os botões
                        document.querySelectorAll('button').forEach((btn, idx) => {
                            const rect = btn.getBoundingClientRect();
                            info.botoes.push({
                                index: idx,
                                texto: btn.innerText || btn.textContent || '',
                                dataContext: btn.getAttribute('data-context'),
                                classes: btn.className,
                                id: btn.id,
                                visivel: btn.offsetParent !== null,
                                posicao: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                            });
                        });
                        
                        // Listar elementos com data-context
                        document.querySelectorAll('[data-context]').forEach((el, idx) => {
                            info.elementos_com_data_context.push({
                                tag: el.tagName,
                                dataContext: el.getAttribute('data-context'),
                                texto: el.innerText || el.textContent || '',
                                classes: el.className
                            });
                        });
                        
                        // Listar elementos que contêm "R$" ou valores monetários
                        document.querySelectorAll('*').forEach((el) => {
                            const texto = el.innerText || el.textContent || '';
                            if (texto.match(/R\\$\\s*\\d+[.,]\\d{2}/i)) {
                                info.elementos_com_valor.push({
                                    tag: el.tagName,
                                    texto: texto.substring(0, 100),
                                    classes: el.className,
                                    id: el.id
                                });
                            }
                        });
                        
                        // Listar elementos que contêm datas
                        document.querySelectorAll('*').forEach((el) => {
                            const texto = el.innerText || el.textContent || '';
                            if (texto.match(/\\d{2}\\/\\d{2}\\/\\d{4}/)) {
                                info.elementos_com_data.push({
                                    tag: el.tagName,
                                    texto: texto.substring(0, 100),
                                    classes: el.className,
                                    id: el.id
                                });
                            }
                        });
                        
                        return info;
                    }
                """)
                
                # Log detalhado dos elementos encontrados
                logger.info(f"[NIO NEGOCIA] Debug elementos: {len(elementos_info.get('botoes', []))} botões, {len(elementos_info.get('elementos_com_data_context', []))} com data-context")
                
                # Print detalhado (pode não aparecer no log do Railway, mas útil para debug local)
                print(f"[DEBUG NIO NEGOCIA] ========== DEBUG: ELEMENTOS DA PÁGINA ==========")
                print(f"[DEBUG NIO NEGOCIA] URL: {elementos_info.get('url')}")
                print(f"[DEBUG NIO NEGOCIA] Título: {elementos_info.get('titulo')}")
                print(f"[DEBUG NIO NEGOCIA] Total de botões: {len(elementos_info.get('botoes', []))}")
                
                # Log detalhado de cada botão encontrado
                for btn in elementos_info.get('botoes', []):
                    btn_info = f"[{btn.get('index')}] Texto: '{btn.get('texto')}', data-context: {btn.get('dataContext')}, visível: {btn.get('visivel')}, classes: {btn.get('classes')}"
                    print(f"[DEBUG NIO NEGOCIA] Botão: {btn_info}")
                    logger.info(f"[NIO NEGOCIA] Botão: {btn_info}")
                
                print(f"[DEBUG NIO NEGOCIA] Elementos com data-context: {len(elementos_info.get('elementos_com_data_context', []))}")
                for el in elementos_info.get('elementos_com_data_context', []):
                    el_info = f"{el.get('tag')}: data-context='{el.get('dataContext')}', texto='{el.get('texto')[:50]}'"
                    print(f"[DEBUG NIO NEGOCIA]   - {el_info}")
                    logger.info(f"[NIO NEGOCIA] Elemento data-context: {el_info}")
                
                print(f"[DEBUG NIO NEGOCIA] Elementos com valores (R$): {len(elementos_info.get('elementos_com_valor', []))}")
                for el in elementos_info.get('elementos_com_valor', [])[:5]:
                    el_info = f"{el.get('tag')}: '{el.get('texto')[:80]}'"
                    print(f"[DEBUG NIO NEGOCIA]   - {el_info}")
                    logger.info(f"[NIO NEGOCIA] Elemento com valor: {el_info}")
                
                print(f"[DEBUG NIO NEGOCIA] Elementos com datas: {len(elementos_info.get('elementos_com_data', []))}")
                for el in elementos_info.get('elementos_com_data', [])[:5]:
                    el_info = f"{el.get('tag')}: '{el.get('texto')[:80]}'"
                    print(f"[DEBUG NIO NEGOCIA]   - {el_info}")
                    logger.info(f"[NIO NEGOCIA] Elemento com data: {el_info}")
                
                print(f"[DEBUG NIO NEGOCIA] =================================================")
            except Exception as e_debug:
                print(f"[DEBUG NIO NEGOCIA] Erro ao listar elementos: {e_debug}")
                logger.warning(f"[NIO NEGOCIA] Erro ao listar elementos: {e_debug}")
            
            # Aguardar mais tempo para página carregar completamente (dados podem vir via JS)
            try:
                # Aguardar elementos específicos da lista de dívidas aparecerem
                print(f"[DEBUG NIO NEGOCIA] Aguardando elementos da lista de dívidas...")
                try:
                    # Tentar aguardar por qualquer elemento que indique que a lista carregou
                    page.wait_for_selector('button[data-context*="pagar"], button:has-text("Pagar"), div:has-text("Valor"), div:has-text("Vencimento"), div:has-text("R$")', timeout=20000, state="visible")
                    print(f"[DEBUG NIO NEGOCIA] ✅ Elementos da lista detectados")
                    logger.info(f"[NIO NEGOCIA] Elementos da lista detectados")
                except Exception as e_sel:
                    print(f"[DEBUG NIO NEGOCIA] ⚠️ Não encontrou elementos específicos: {e_sel}")
                    logger.warning(f"[NIO NEGOCIA] Não encontrou elementos específicos: {e_sel}")
                
                page.wait_for_timeout(5000)  # Aguardar 5 segundos adicionais
                page.wait_for_load_state("networkidle", timeout=20000)
                page.wait_for_load_state("domcontentloaded", timeout=20000)
                print(f"[DEBUG NIO NEGOCIA] Página aguardada para carregar dados")
            except Exception as e_wait:
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Timeout ao aguardar página carregar: {e_wait}")
                logger.warning(f"[NIO NEGOCIA] Timeout ao aguardar página carregar: {e_wait}")
            
            # Obter tanto HTML quanto texto visível (innerText via JS)
            html_lista = page.content()
            texto_visivel = page.evaluate("() => document.body.innerText")
            
            # Verificar se o texto visível contém dados esperados
            if texto_visivel and len(texto_visivel) < 200:
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Texto visível muito curto ({len(texto_visivel)} chars), pode estar na página errada")
                logger.warning(f"[NIO NEGOCIA] Texto visível muito curto ({len(texto_visivel)} chars)")
                # Tentar aguardar mais um pouco
                page.wait_for_timeout(5000)
                texto_visivel = page.evaluate("() => document.body.innerText")
                html_lista = page.content()
            
            # Log detalhado do texto visível para debug
            if texto_visivel:
                print(f"[DEBUG NIO NEGOCIA] Texto visível completo (primeiros 1000 chars): {texto_visivel[:1000]}")
                logger.info(f"[NIO NEGOCIA] Texto visível (primeiros 500 chars): {texto_visivel[:500]}")
            else:
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Texto visível está vazio!")
                logger.warning(f"[NIO NEGOCIA] Texto visível está vazio!")
            
            # Verificar se há mensagens de erro na página
            mensagens_erro = []
            if texto_visivel:
                texto_lower = texto_visivel.lower()
                if 'não encontrado' in texto_lower or 'não encontrada' in texto_lower:
                    mensagens_erro.append("Mensagem 'não encontrado' na página")
                if 'erro' in texto_lower:
                    mensagens_erro.append("Palavra 'erro' encontrada na página")
                if 'sem dívidas' in texto_lower or 'sem dividas' in texto_lower:
                    mensagens_erro.append("Mensagem 'sem dívidas' na página")
            
            if mensagens_erro:
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Mensagens de erro detectadas: {mensagens_erro}")
                logger.warning(f"[NIO NEGOCIA] Mensagens de erro detectadas: {mensagens_erro}")
            
            # Capturar screenshot para debug
            try:
                downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
                os.makedirs(downloads_dir, exist_ok=True)
                screenshot_path = os.path.join(downloads_dir, f"debug_nio_negocia_extraindo_dados_{cpf_limpo}.png")
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"[DEBUG NIO NEGOCIA] 📸 Screenshot para extração de dados: {screenshot_path}")
                logger.info(f"[NIO NEGOCIA] Screenshot para extração de dados: {screenshot_path}")
            except:
                pass
            
            # Extrair valores - tentar múltiplos padrões
            valor = None
            valor_matches = []
            
            # Normalizar HTML: substituir &nbsp; e outras entidades por espaços
            html_normalizado = html_lista.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            
            # Padrão 1: R$ seguido de espaços/&nbsp; e valor (ex: R$  &nbsp;130,00 ou R$ 130,00)
            # Aceita valores com ou sem separador de milhares
            valor_matches.extend(re.findall(r'R\$\s+(?:&nbsp;)?\s*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})', html_normalizado, re.IGNORECASE))
            valor_matches.extend(re.findall(r'R\$\s+(?:&nbsp;)?\s*(\d+[.,]\d{2})', html_normalizado, re.IGNORECASE))
            
            # Padrão 2: Buscar diretamente no texto visível (já normalizado pelo innerText)
            if texto_visivel:
                # Padrão para valores com R$ no texto visível
                valor_matches.extend(re.findall(r'R\$\s*(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})', texto_visivel, re.IGNORECASE))
                valor_matches.extend(re.findall(r'R\$\s*(\d+[.,]\d{2})', texto_visivel, re.IGNORECASE))
                # Padrão para "Valor da dívida: R$ 130,00"
                valor_matches.extend(re.findall(r'[Vv]alor[^:]*:\s*R\$\s*(\d+[.,]\d{2})', texto_visivel, re.IGNORECASE))
            
            # Padrão 3: Tentar extrair via JavaScript dos elementos específicos
            try:
                valor_js = page.evaluate("""
                    () => {
                        // Buscar diretamente no texto que contém "Valor da dívida"
                        const elementos = Array.from(document.querySelectorAll('p, span, div'));
                        for (let el of elementos) {
                            const texto = el.innerText || el.textContent || '';
                            // Procurar por "Valor da dívida: R$ 130,00" ou similar
                            if (texto.includes('Valor') && texto.includes('dívida')) {
                                const match = texto.match(/R\\$\\s*[&nbsp;\\s]*(\\d+[.,]\\d{2})/i);
                                if (match) {
                                    return match[1].replace(/&nbsp;/g, '').trim();
                                }
                            }
                            // Procurar por qualquer R$ seguido de número
                            const match = texto.match(/R\\$\\s*[&nbsp;\\s]*(\\d+[.,]\\d{2})/i);
                            if (match && texto.length < 200) { // Evitar pegar valores muito longos
                                return match[1].replace(/&nbsp;/g, '').trim();
                            }
                        }
                        return null;
                    }
                """)
                if valor_js:
                    valor_matches.append(valor_js)
                    print(f"[DEBUG NIO NEGOCIA] ✅ Valor encontrado via JavaScript: {valor_js}")
                    logger.info(f"[NIO NEGOCIA] Valor encontrado via JavaScript: {valor_js}")
            except Exception as e_js:
                print(f"[DEBUG NIO NEGOCIA] Erro ao extrair valor via JS: {e_js}")
                logger.warning(f"[NIO NEGOCIA] Erro ao extrair valor via JS: {e_js}")
            
            # Remover duplicatas mantendo ordem
            valor_matches = list(dict.fromkeys(valor_matches))
            
            print(f"[DEBUG NIO NEGOCIA] Valores encontrados na página: {valor_matches}")
            print(f"[DEBUG NIO NEGOCIA] Texto visível (primeiros 500 chars): {texto_visivel[:500] if texto_visivel else 'N/A'}")
            logger.info(f"[NIO NEGOCIA] Valores encontrados: {valor_matches}")
            
            if valor_matches:
                try:
                    valor_str = valor_matches[0].replace('.', '').replace(',', '.')
                    valor = Decimal(valor_str)
                    print(f"[DEBUG NIO NEGOCIA] ✅ Valor extraído: R$ {valor}")
                    logger.info(f"[NIO NEGOCIA] Valor extraído: R$ {valor}")
                except Exception as e_val:
                    print(f"[DEBUG NIO NEGOCIA] ⚠️ Erro ao converter valor: {e_val}")
                    logger.warning(f"[NIO NEGOCIA] Erro ao converter valor: {e_val}")
            else:
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Nenhum valor encontrado na página")
                logger.warning(f"[NIO NEGOCIA] Nenhum valor encontrado na página")
            
            # Extrair data de vencimento - tentar múltiplos padrões
            data_vencimento = None
            data_matches = []
            
            # Normalizar HTML para busca
            html_normalizado = html_lista.replace('&nbsp;', ' ').replace('&amp;', '&')
            
            # Padrão 1: DD/MM/YYYY no HTML normalizado
            data_matches.extend(re.findall(r'(\d{2}/\d{2}/\d{4})', html_normalizado))
            
            # Padrão 2: Buscar em texto visível também
            if texto_visivel:
                data_matches.extend(re.findall(r'(\d{2}/\d{2}/\d{4})', texto_visivel))
                # Padrão específico para "Vencimento: 27/01/2026"
                data_matches.extend(re.findall(r'[Vv]encimento[^:]*:\s*(\d{2}/\d{2}/\d{4})', texto_visivel, re.IGNORECASE))
            
            # Padrão 3: Tentar extrair via JavaScript dos elementos específicos
            try:
                data_js = page.evaluate("""
                    () => {
                        // Buscar diretamente no texto que contém "Vencimento"
                        const elementos = Array.from(document.querySelectorAll('p, span, div'));
                        for (let el of elementos) {
                            const texto = el.innerText || el.textContent || '';
                            // Procurar por "Vencimento: 27/01/2026" ou similar
                            if (texto.includes('Vencimento') || texto.includes('vencimento')) {
                                const match = texto.match(/(\\d{2}\\/\\d{2}\\/\\d{4})/);
                                if (match) return match[1];
                            }
                        }
                        // Se não encontrou com "Vencimento", procurar qualquer data no formato DD/MM/YYYY
                        const elementos2 = Array.from(document.querySelectorAll('p, span, div'));
                        for (let el of elementos2) {
                            const texto = el.innerText || el.textContent || '';
                            const match = texto.match(/(\\d{2}\\/\\d{2}\\/\\d{4})/);
                            if (match && texto.length < 200) { // Evitar pegar datas muito longas
                                return match[1];
                            }
                        }
                        return null;
                    }
                """)
                if data_js:
                    data_matches.append(data_js)
                    print(f"[DEBUG NIO NEGOCIA] ✅ Data encontrada via JavaScript: {data_js}")
                    logger.info(f"[NIO NEGOCIA] Data encontrada via JavaScript: {data_js}")
            except Exception as e_js:
                print(f"[DEBUG NIO NEGOCIA] Erro ao extrair data via JS: {e_js}")
                logger.warning(f"[NIO NEGOCIA] Erro ao extrair data via JS: {e_js}")
            
            # Remover duplicatas mantendo ordem
            data_matches = list(dict.fromkeys(data_matches))
            
            print(f"[DEBUG NIO NEGOCIA] Datas encontradas na página: {data_matches}")
            logger.info(f"[NIO NEGOCIA] Datas encontradas: {data_matches}")
            
            if data_matches:
                try:
                    data_vencimento = datetime.strptime(data_matches[0], "%d/%m/%Y").date()
                    print(f"[DEBUG NIO NEGOCIA] ✅ Data extraída: {data_vencimento}")
                    logger.info(f"[NIO NEGOCIA] Data extraída: {data_vencimento}")
                except Exception as e_data:
                    print(f"[DEBUG NIO NEGOCIA] ⚠️ Erro ao converter data: {e_data}")
                    logger.warning(f"[NIO NEGOCIA] Erro ao converter data: {e_data}")
            else:
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Nenhuma data encontrada na página")
                logger.warning(f"[NIO NEGOCIA] Nenhuma data encontrada na página")
            
            # PASSO 7: Clicar em "Pagar conta" (SINGULAR - não "Pagar contas")
            # O botão real tem: data-context="btn_lista-dividas_pagar-conta" e texto "Pagar conta"
            logger.info(f"[NIO NEGOCIA] Passo 7: Clicando em Pagar conta")
            print(f"[DEBUG NIO NEGOCIA] Passo 7: Procurando botão 'Pagar conta' (SINGULAR)...")
            
            # Aguardar página carregar completamente após clicar em "Consultar dívidas"
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
                page.wait_for_timeout(2000)
                print(f"[DEBUG NIO NEGOCIA] Página aguardada após 'Consultar dívidas'")
            except:
                print(f"[DEBUG NIO NEGOCIA] ⚠️ Timeout ao aguardar página carregar")
            
            # Capturar screenshot para debug antes de procurar botão
            try:
                downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
                os.makedirs(downloads_dir, exist_ok=True)
                screenshot_path = os.path.join(downloads_dir, f"debug_nio_negocia_antes_pagar_conta_{cpf_limpo}.png")
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"[DEBUG NIO NEGOCIA] 📸 Screenshot antes de procurar 'Pagar conta': {screenshot_path}")
                logger.info(f"[NIO NEGOCIA] Screenshot antes de procurar 'Pagar conta': {screenshot_path}")
            except:
                pass
            
            # Verificar se há elementos colapsáveis e expandir se necessário
            try:
                # Procurar por elementos com "Ocultar detalhes" ou "Ver detalhes" e clicar para expandir
                btn_expandir = page.locator('p:has-text("Ocultar detalhes"), p:has-text("Ver detalhes")').first
                if btn_expandir.is_visible(timeout=2000):
                    btn_expandir.click()
                    page.wait_for_timeout(1000)
                    print(f"[DEBUG NIO NEGOCIA] Elemento colapsável expandido")
            except:
                pass
            
            btn_pagar = None
            # Priorizar seletores mais específicos primeiro
            seletores_pagar = [
                # Seletor mais específico: data-context exato
                'button[data-context="btn_lista-dividas_pagar-conta"]',
                # Seletor por data-context parcial
                'button[data-context*="pagar-conta"]',
                'button[data-context*="pagar"]',
                # Seletor por classe e texto (SINGULAR)
                'button.sc-EHOje.btbnVF:has-text("Pagar conta")',
                'button.sc-EHOje.btbnVF',
                # Seletores por texto (SINGULAR primeiro, depois plural como fallback)
                'button:has-text("Pagar conta")',
                'button:has-text("Pagar contas")',  # Fallback para plural
                'button:has-text("Pagar")',
                # Outros seletores genéricos
                'span:has-text("Pagar conta")',
                'a:has-text("Pagar conta")',
                'div:has-text("Pagar conta")',
            ]
            
            # Tentar também buscar via JavaScript e clicar diretamente se encontrar
            try:
                btn_info = page.evaluate("""
                    () => {
                        // Buscar botão por data-context
                        const btn = document.querySelector('button[data-context="btn_lista-dividas_pagar-conta"]');
                        if (btn) {
                            const rect = btn.getBoundingClientRect();
                            return {
                                encontrado: true,
                                visivel: btn.offsetParent !== null,
                                texto: btn.innerText || btn.textContent || '',
                                dataContext: btn.getAttribute('data-context'),
                                classes: btn.className,
                                posicao: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                            };
                        }
                        
                        // Buscar por texto "Pagar conta"
                        const botoes = Array.from(document.querySelectorAll('button'));
                        for (let b of botoes) {
                            const texto = b.innerText || b.textContent || '';
                            if (texto.includes('Pagar conta') || texto.includes('Pagar contas')) {
                                const rect = b.getBoundingClientRect();
                                return {
                                    encontrado: true,
                                    visivel: b.offsetParent !== null,
                                    texto: texto,
                                    dataContext: b.getAttribute('data-context'),
                                    classes: b.className,
                                    posicao: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                                };
                            }
                        }
                        return { encontrado: false };
                    }
                """)
                if btn_info and btn_info.get('encontrado'):
                    print(f"[DEBUG NIO NEGOCIA] Botão encontrado via JavaScript:")
                    print(f"  - Visível: {btn_info.get('visivel')}")
                    print(f"  - Texto: '{btn_info.get('texto')}'")
                    print(f"  - data-context: {btn_info.get('dataContext')}")
                    print(f"  - Classes: {btn_info.get('classes')}")
                    logger.info(f"[NIO NEGOCIA] Botão encontrado via JS: visível={btn_info.get('visivel')}, texto='{btn_info.get('texto')}'")
            except Exception as e_js:
                print(f"[DEBUG NIO NEGOCIA] Erro ao buscar botão via JS: {e_js}")
                logger.warning(f"[NIO NEGOCIA] Erro ao buscar botão via JS: {e_js}")
            
            for seletor in seletores_pagar:
                try:
                    locator = page.locator(seletor).first
                    count = locator.count()
                    print(f"[DEBUG NIO NEGOCIA] Seletor '{seletor}': {count} elemento(s) encontrado(s)")
                    logger.info(f"[NIO NEGOCIA] Seletor '{seletor}': {count} elemento(s)")
                    if count > 0:
                        try:
                            is_visible = locator.is_visible(timeout=2000)
                            print(f"[DEBUG NIO NEGOCIA] Seletor '{seletor}': visível={is_visible}")
                            if is_visible:
                                btn_pagar = locator
                                texto_botao = locator.inner_text() if locator else "N/A"
                                print(f"[DEBUG NIO NEGOCIA] ✅ Botão 'Pagar conta' encontrado com seletor: {seletor}")
                                print(f"[DEBUG NIO NEGOCIA] Texto do botão encontrado: '{texto_botao}'")
                                logger.info(f"[NIO NEGOCIA] Botão 'Pagar conta' encontrado com seletor: {seletor}, texto: '{texto_botao}'")
                                break
                        except Exception as e_vis:
                            print(f"[DEBUG NIO NEGOCIA] Erro ao verificar visibilidade do seletor '{seletor}': {e_vis}")
                            # Tentar mesmo assim se encontrou o elemento
                            if count > 0:
                                try:
                                    btn_pagar = locator
                                    texto_botao = locator.inner_text() if locator else "N/A"
                                    print(f"[DEBUG NIO NEGOCIA] ✅ Botão 'Pagar conta' encontrado (sem verificar visibilidade) com seletor: {seletor}")
                                    logger.info(f"[NIO NEGOCIA] Botão encontrado (sem verificar visibilidade) com seletor: {seletor}")
                                    break
                                except:
                                    pass
                except Exception as e_sel:
                    print(f"[DEBUG NIO NEGOCIA] Seletor '{seletor}' falhou: {e_sel}")
                    logger.debug(f"[NIO NEGOCIA] Seletor '{seletor}' falhou: {e_sel}")
                    continue
            
            if not btn_pagar:
                logger.error("[NIO NEGOCIA] Botão Pagar conta não encontrado")
                print(f"[DEBUG NIO NEGOCIA] ❌ Botão 'Pagar conta' não encontrado")
                # Capturar HTML para debug
                try:
                    downloads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'downloads')
                    os.makedirs(downloads_dir, exist_ok=True)
                    html_path = os.path.join(downloads_dir, f"debug_nio_negocia_sem_pagar_conta_{cpf_limpo}.html")
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(page.content())
                    print(f"[DEBUG NIO NEGOCIA] 📄 HTML salvo: {html_path}")
                    logger.info(f"[NIO NEGOCIA] HTML salvo: {html_path}")
                except:
                    pass
                browser.close()
                return None
            
            try:
                btn_pagar.click()
                page.wait_for_timeout(2000)
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as e:
                logger.error(f"[NIO NEGOCIA] Erro ao clicar em Pagar conta: {e}")
                browser.close()
                return None
            
            # PASSO 8: Obter PIX primeiro
            logger.info(f"[NIO NEGOCIA] Passo 8: Obtendo código PIX")
            codigo_pix = None
            
            # Clicar em "Pagar com Pix"
            btn_pix = None
            seletores_pix = [
                'p.sc-htpNat.leGWMc:has-text("Pagar com Pix")',
                'p:has-text("Pagar com Pix")',
                'text=/pagar com pix/i',
            ]
            
            for seletor in seletores_pix:
                try:
                    locator = page.locator(seletor).first
                    if locator.count() > 0:
                        btn_pix = locator
                        break
                except:
                    continue
            
            if btn_pix:
                try:
                    btn_pix.click()
                    page.wait_for_timeout(2000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    
                    html_pix = page.content()
                    # Buscar código PIX
                    pix_matches = re.findall(r'00020126[0-9a-zA-Z]{100,}', html_pix)
                    if not pix_matches:
                        pix_matches = re.findall(r'[a-zA-Z0-9]{80,150}', html_pix)
                    
                    if pix_matches:
                        codigo_pix = pix_matches[0]
                        logger.info("[NIO NEGOCIA] Código PIX obtido")
                    
                    # Voltar para página de pagamento
                    btn_voltar = page.locator('text=/voltar ao início/i').first
                    if btn_voltar.count() > 0:
                        btn_voltar.click()
                        page.wait_for_timeout(2000)
                        page.wait_for_load_state("networkidle", timeout=10000)
                    
                    # Clicar novamente em "Pagar conta"
                    btn_pagar.click()
                    page.wait_for_timeout(2000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception as e:
                    logger.warning(f"[NIO NEGOCIA] Erro ao obter PIX: {e}")
            
            # PASSO 9: Obter código de barras e PDF
            logger.info(f"[NIO NEGOCIA] Passo 9: Obtendo código de barras e PDF")
            codigo_barras = None
            pdf_url = None
            
            # Clicar em "Gerar boleto"
            btn_boleto = None
            seletores_boleto = [
                'p.sc-htpNat.leGWMc:has-text("Gerar Boleto")',
                'p:has-text("Gerar Boleto")',
                'p:has-text("Gerar boleto")',
                'text=/gerar boleto/i',
            ]
            
            for seletor in seletores_boleto:
                try:
                    locator = page.locator(seletor).first
                    if locator.count() > 0:
                        btn_boleto = locator
                        break
                except:
                    continue
            
            if btn_boleto:
                try:
                    btn_boleto.click()
                    page.wait_for_timeout(2000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    
                    html_boleto = page.content()
                    
                    # Extrair código de barras
                    codigos = re.findall(r'\b(\d{44,50})\b', html_boleto)
                    if codigos:
                        preferidos = [c for c in codigos if c.startswith('0339')]
                        codigo_barras = preferidos[0] if preferidos else codigos[0]
                        logger.info("[NIO NEGOCIA] Código de barras obtido")
                    
                    # PASSO 10-12: Baixar PDF
                    if incluir_pdf:
                        logger.info(f"[NIO NEGOCIA] Passo 10-12: Baixar PDF")
                        try:
                            # Múltiplas estratégias para capturar PDF
                            pdf_url = None
                            
                            # Estratégia 1: Procurar link direto no HTML
                            pdf_links = re.findall(r'https?://[^\s<>"\']+\.pdf[^\s<>"\']*', html_boleto, re.IGNORECASE)
                            if pdf_links:
                                pdf_url = pdf_links[0]
                                logger.info(f"[NIO NEGOCIA] PDF URL encontrada no HTML: {pdf_url[:100]}...")
                            
                            # Estratégia 2: Esperar download direto
                            if not pdf_url:
                                try:
                                    downloads_dir = os.path.join(
                                        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
                                        'downloads'
                                    )
                                    os.makedirs(downloads_dir, exist_ok=True)
                                    
                                    nome_arquivo = f"{cpf_limpo}_{mes_referencia or datetime.now().strftime('%Y%m')}.pdf"
                                    caminho_pdf = os.path.join(downloads_dir, nome_arquivo)
                                    
                                    with page.expect_download(timeout=10000) as download_info:
                                        btn_baixar_pdf = page.locator('p.sc-htpNat.kOdFoh:has-text("Baixar PDF")').first
                                        if btn_baixar_pdf.count() > 0:
                                            btn_baixar_pdf.click()
                                    download = download_info.value
                                    download.save_as(caminho_pdf)
                                    logger.info(f"[NIO NEGOCIA] PDF baixado: {caminho_pdf}")
                                    pdf_url = caminho_pdf
                                except Exception as e:
                                    logger.debug(f"[NIO NEGOCIA] Estratégia download direto falhou: {e}")
                                    
                                    # Estratégia 3: Capturar via popup/aba
                                    try:
                                        with context.expect_page(timeout=10000) as popup_info:
                                            btn_baixar_pdf = page.locator('p.sc-htpNat.kOdFoh:has-text("Baixar PDF")').first
                                            if btn_baixar_pdf.count() > 0:
                                                btn_baixar_pdf.click()
                                        pdf_page = popup_info.value
                                        pdf_page.wait_for_load_state('networkidle', timeout=5000)
                                        pdf_url = pdf_page.url
                                        pdf_page.close()
                                        logger.info(f"[NIO NEGOCIA] PDF URL capturada via popup: {pdf_url[:100]}...")
                                    except Exception as e2:
                                        logger.warning(f"[NIO NEGOCIA] Erro ao baixar PDF: {e2}")
                        except Exception as e:
                            logger.warning(f"[NIO NEGOCIA] Erro ao processar PDF: {e}")
                except Exception as e:
                    logger.warning(f"[NIO NEGOCIA] Erro ao gerar boleto: {e}")
            
            browser.close()
            
            # Retornar resultado
            resultado = {
                'valor': float(valor) if valor else None,
                'codigo_pix': codigo_pix,
                'codigo_barras': codigo_barras,
                'data_vencimento': data_vencimento,
                'pdf_url': pdf_url,
            }
            
            if resultado.get('valor') or resultado.get('codigo_pix') or resultado.get('codigo_barras'):
                logger.info(f"[NIO NEGOCIA] Busca concluída com sucesso")
                return resultado
            else:
                logger.warning(f"[NIO NEGOCIA] Busca concluída mas sem dados válidos")
                return None
            
    except Exception as e:
        logger.error(f"[NIO NEGOCIA] Erro: {e}")
        import traceback
        logger.error(f"[NIO NEGOCIA] Traceback: {traceback.format_exc()}")
        return None
