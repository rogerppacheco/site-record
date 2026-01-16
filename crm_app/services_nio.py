# crm_app/services_nio.py
"""
Serviço para automação de consulta de faturas no site da Nio Internet
"""

import re
import os
import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

# Tentar importar Playwright
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    print("[AVISO] Playwright não instalado. Busca automática desabilitada.")

# Configurações
NIO_BASE_URL = "https://www.niointernet.com.br/ajuda/servicos/segunda-via/"
DEFAULT_STORAGE_STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".playwright_state.json")


def buscar_fatura_nio_por_cpf(cpf, incluir_pdf=True, mes_referencia=None):
    """
    Busca fatura no site da Nio Internet por CPF
    
    Args:
        cpf: CPF do cliente
        incluir_pdf: Se True, busca também o PDF (mais lento)
        mes_referencia: Mês de referência da fatura (YYYYMM) para nomear o arquivo
    
    Returns:
        dict com: valor, codigo_pix, codigo_barras, data_vencimento, pdf_url, pdf_path
        ou None se não encontrou
    """
    if not HAS_PLAYWRIGHT:
        return None
    
    try:
        cpf_limpo = re.sub(r'\D', '', cpf or '')
        if not cpf_limpo:
            return None
        
        resultado = _buscar_fatura_playwright(cpf_limpo)
        
        # Se precisa do PDF e ainda não tem, tenta baixar
        if incluir_pdf and resultado and not resultado.get('pdf_url') and not resultado.get('pdf_path'):
            pdf_path = _baixar_pdf_como_humano(cpf_limpo, mes_referencia, resultado.get('data_vencimento'))
            if pdf_path:
                resultado['pdf_path'] = pdf_path
                print(f"✅ [PDF] Arquivo salvo em: {pdf_path}")
        
        return resultado
    except Exception as e:
        print(f"[ERRO] Falha ao buscar fatura: {e}")
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
        
        logger.info(f"[PDF HUMANO] Iniciando download como humano para CPF: {cpf}")
        logger.info(f"[PDF HUMANO] Arquivo será salvo em: {caminho_completo}")
        logger.info(f"[PDF HUMANO] Parâmetros: mes_ref={mes_referencia}, data_venc={data_vencimento}")
        
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
            logger.info(f"[PDF HUMANO] Passo 1: Navegando para {NIO_BASE_URL}")
            try:
                page.goto(NIO_BASE_URL, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                logger.info(f"[PDF HUMANO] Página carregada com sucesso")
            except Exception as e:
                logger.error(f"[PDF HUMANO] Erro ao carregar página inicial: {e}")
                import traceback
                logger.error(f"[PDF HUMANO] Traceback: {traceback.format_exc()}")
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
            logger.info(f"[PDF HUMANO] Passo 2: Preenchendo CPF e consultando...")
            
            # Aguardar um pouco mais para garantir que a página carregou completamente
            page.wait_for_timeout(2000)
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            logger.info(f"[PDF HUMANO] Tentando encontrar campo de CPF...")
            
            # Tentar vários seletores possíveis para o campo CPF
            campo_cpf = None
            seletores_cpf = [
                'input[placeholder*="CPF" i]',  # case insensitive
                'input[placeholder*="cpf" i]',
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
                logger.error(f"[PDF HUMANO] ❌ Nenhum campo de CPF encontrado após tentar {len(seletores_cpf)} seletores!")
                # Salvar HTML para debug
                try:
                    html_path = os.path.join(downloads_dir, f"debug_{cpf}_html.html")
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(page.content())
                    logger.info(f"[PDF HUMANO] HTML salvo para debug: {html_path}")
                except Exception as e_html:
                    logger.warning(f"[PDF HUMANO] Erro ao salvar HTML: {e_html}")
                browser.close()
                return None
            
            # Preencher CPF
            try:
                logger.info(f"[PDF HUMANO] Preenchendo campo CPF com: {cpf}")
                campo_cpf.fill(cpf, timeout=10000)
                logger.info(f"[PDF HUMANO] ✅ CPF preenchido com sucesso")
            except Exception as e:
                logger.error(f"[PDF HUMANO] ❌ Erro ao preencher CPF: {e}")
                import traceback
                logger.error(f"[PDF HUMANO] Traceback: {traceback.format_exc()}")
                browser.close()
                return None
            
            # Clicar em Consultar - usando seletor correto: button.segunda-via__button
            try:
                logger.info(f"[PDF HUMANO] Procurando botão Consultar (button.segunda-via__button)...")
                btn_consultar = page.locator('button.segunda-via__button[type="submit"]').first
                count = btn_consultar.count()
                logger.debug(f"[PDF HUMANO] Botão 'segunda-via__button' encontrado: {count} elementos")
                
                if count == 0:
                    # Tentar seletor alternativo
                    logger.info(f"[PDF HUMANO] Tentando seletor alternativo: button[type='submit']")
                    btn_consultar = page.locator('button[type="submit"]').first
                    count = btn_consultar.count()
                    logger.debug(f"[PDF HUMANO] Botão submit encontrado: {count} elementos")
                
                if count > 0:
                    btn_consultar.click(timeout=10000)
                    logger.info(f"[PDF HUMANO] ✅ Botão Consultar clicado")
                else:
                    logger.error(f"[PDF HUMANO] ❌ Nenhum botão Consultar encontrado!")
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
                    page.wait_for_timeout(800)
                    logger.info(f"[PDF HUMANO] ✅ Detalhes expandidos")
                else:
                    logger.debug(f"[PDF HUMANO] Não foi necessário expandir detalhes (não encontrado)")
            except Exception as e:
                logger.debug(f"[PDF HUMANO] Não foi necessário expandir detalhes ou erro: {e}")
            
            # 4. Clicar em "Pagar conta"
            logger.info(f"[PDF HUMANO] Passo 4: Clicando em 'Pagar conta'...")
            try:
                # Tentar vários seletores para "Pagar conta"
                pagar_btn = None
                seletores_pagar = [
                    'button:has-text("Pagar conta")',
                    'a:has-text("Pagar conta")',
                    'button[class*="pagar"]',
                    'a[class*="pagar"]',
                ]
                
                for seletor in seletores_pagar:
                    try:
                        btn = page.locator(seletor).first
                        if btn.count() > 0:
                            pagar_btn = btn
                            logger.info(f"[PDF HUMANO] Botão 'Pagar conta' encontrado com seletor: {seletor}")
                            break
                    except:
                        continue
                
                if not pagar_btn or pagar_btn.count() == 0:
                    logger.error(f"[PDF HUMANO] ❌ Botão 'Pagar conta' não encontrado!")
                    browser.close()
                    return None
                
                pagar_btn.click()
                page.wait_for_timeout(2000)  # Aguardar navegação
                logger.info(f"[PDF HUMANO] ✅ Clicou em 'Pagar conta'")
            except Exception as e:
                logger.error(f"[PDF HUMANO] ❌ Erro ao clicar em 'Pagar conta': {e}")
                import traceback
                logger.error(f"[PDF HUMANO] Traceback: {traceback.format_exc()}")
                browser.close()
                return None
            
            # 5. Clicar em "Gerar boleto" - usando seletor correto: a#generate-boleto
            logger.info(f"[PDF HUMANO] Passo 5: Clicando em 'Gerar boleto'...")
            try:
                # Usar seletor correto: a#generate-boleto ou a.scheduled-payment__button
                gerar_boleto = page.locator('a#generate-boleto').first
                count = gerar_boleto.count()
                
                if count == 0:
                    # Tentar seletor alternativo
                    logger.info(f"[PDF HUMANO] Tentando seletor alternativo: a.scheduled-payment__button")
                    gerar_boleto = page.locator('a.scheduled-payment__button:has-text("Gerar boleto")').first
                    count = gerar_boleto.count()
                
                if count == 0:
                    logger.error(f"[PDF HUMANO] ❌ Botão 'Gerar boleto' não encontrado!")
                    browser.close()
                    return None
                
                gerar_boleto.click()
                page.wait_for_timeout(2000)  # Aguardar carregamento
                logger.info(f"[PDF HUMANO] ✅ Clicou em 'Gerar boleto'")
            except Exception as e:
                logger.error(f"[PDF HUMANO] ❌ Erro ao clicar em 'Gerar boleto': {e}")
                import traceback
                logger.error(f"[PDF HUMANO] Traceback: {traceback.format_exc()}")
                browser.close()
                return None
            
            # 6. Clicar em "Download" - usando seletor correto: a#downloadInvoice
            # NOTA: Este botão abre o modal de impressão do navegador, não um download direto
            logger.info(f"[PDF HUMANO] Passo 6: Clicando em 'Download' (abre modal de impressão)...")
            
            try:
                # Usar seletor correto: a#downloadInvoice
                download_btn = page.locator('a#downloadInvoice').first
                count = download_btn.count()
                
                if count == 0:
                    # Tentar seletor alternativo
                    logger.info(f"[PDF HUMANO] Tentando seletor alternativo: a.scheduled-payment__button--outline")
                    download_btn = page.locator('a.scheduled-payment__button--outline:has-text("Download")').first
                    count = download_btn.count()
                
                if count == 0:
                    logger.error(f"[PDF HUMANO] ❌ Botão 'Download' não encontrado!")
                    browser.close()
                    return None
                
                logger.info(f"[PDF HUMANO] ✅ Botão Download encontrado")
                
                # O botão abre o modal de impressão do navegador
                # Vamos usar a API de impressão do Playwright para salvar como PDF
                logger.info(f"[PDF HUMANO] Clicando no botão Download (abrirá modal de impressão)...")
                download_btn.click()
                page.wait_for_timeout(1000)  # Aguardar modal abrir
                
                # Usar a API de impressão do Playwright para gerar PDF diretamente
                logger.info(f"[PDF HUMANO] Gerando PDF via API de impressão do navegador...")
                pdf_bytes = page.pdf(
                    format='A4',
                    print_background=True,
                    margin={'top': '0.5cm', 'right': '0.5cm', 'bottom': '0.5cm', 'left': '0.5cm'}
                )
                
                # Salvar PDF
                if os.path.exists(caminho_completo):
                    os.remove(caminho_completo)
                
                with open(caminho_completo, 'wb') as f:
                    f.write(pdf_bytes)
                
                logger.info(f"[PDF HUMANO] ✅ PDF gerado e salvo: {caminho_completo}")
                
            except Exception as e_download:
                logger.error(f"[PDF HUMANO] ❌ Erro ao processar download: {e_download}")
                import traceback
                logger.error(f"[PDF HUMANO] Traceback: {traceback.format_exc()}")
                browser.close()
                return None
            
            # 7. Verificar se arquivo foi salvo (já foi salvo no passo 6)
            logger.info(f"[PDF HUMANO] Passo 7: Verificando arquivo salvo...")
            
            browser.close()
            
            # Verificar se arquivo foi salvo corretamente
            if os.path.exists(caminho_completo) and os.path.getsize(caminho_completo) > 0:
                tamanho_kb = os.path.getsize(caminho_completo) / 1024
                logger.info(f"[PDF HUMANO] ✅ Arquivo salvo com sucesso: {caminho_completo} ({tamanho_kb:.2f} KB)")
                
                # Tentar fazer upload para OneDrive
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
                    
                    logger.info(f"[PDF HUMANO] ☁️ Fazendo upload para OneDrive: {folder_name}/{nome_arquivo}")
                    
                    with open(caminho_completo, 'rb') as f:
                        link_onedrive = uploader.upload_file(f, folder_name, nome_arquivo)
                    
                    if link_onedrive:
                        logger.info(f"[PDF HUMANO] ✅ Upload OneDrive concluído: {link_onedrive}")
                        # Retornar tanto o caminho local quanto o link do OneDrive
                        return {
                            'local_path': caminho_completo,
                            'onedrive_url': link_onedrive,
                            'filename': nome_arquivo
                        }
                    else:
                        logger.warning(f"[PDF HUMANO] ⚠️ Upload OneDrive falhou, mas arquivo local salvo")
                        return {
                            'local_path': caminho_completo,
                            'onedrive_url': None,
                            'filename': nome_arquivo
                        }
                except Exception as e_onedrive:
                    logger.warning(f"[PDF HUMANO] ⚠️ Erro ao fazer upload OneDrive: {e_onedrive}")
                    import traceback
                    logger.warning(f"[PDF HUMANO] Traceback OneDrive: {traceback.format_exc()}")
                    # Mesmo se OneDrive falhar, retornar o caminho local
                    return {
                        'local_path': caminho_completo,
                        'onedrive_url': None,
                        'filename': nome_arquivo
                    }
            else:
                logger.warning(f"[PDF HUMANO] ⚠️ Arquivo salvo mas está vazio ou não existe")
                logger.warning(f"[PDF HUMANO] Existe: {os.path.exists(caminho_completo)}, Tamanho: {os.path.getsize(caminho_completo) if os.path.exists(caminho_completo) else 'N/A'}")
                return None
                
    except Exception as e:
        logger.error(f"[PDF HUMANO] ❌ Erro ao baixar PDF: {e}")
        import traceback
        logger.error(f"[PDF HUMANO] Traceback completo: {traceback.format_exc()}")
        
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
            logger.info(f"[PDF HUMANO] 📝 Log de erro salvo: {error_log_path}")
        except Exception as e_log:
            logger.warning(f"[PDF HUMANO] Erro ao salvar log de erro: {e_log}")
        
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

        # PDF - Múltiplas estratégias para capturar o PDF
        pdf_url = None
        
        # Estratégia 1: Procurar link direto na página HTML antes de clicar
        try:
            print('🔍 [PDF] Estratégia 1: Procurando link direto na página...')
            html_boleto_check = page.content()
            pdf_links = re.findall(r'https?://[^\s<>"\']+\.pdf', html_boleto_check, re.IGNORECASE)
            if pdf_links:
                pdf_url = pdf_links[0]
                print(f'✅ [PDF] Link encontrado diretamente no HTML: {pdf_url[:100]}...')
        except Exception as e:
            print(f'⚠️ [PDF] Estratégia 1 falhou: {e}')
        
        # Estratégia 2: Tentar capturar via download
        if not pdf_url:
            try:
                print('🔍 [PDF] Estratégia 2: Tentando capturar via download...')
                download_path = os.path.join(os.path.dirname(__file__), '..', '..', 'downloads')
                os.makedirs(download_path, exist_ok=True)
                
                # Aguardar download ao clicar
                with page.expect_download(timeout=10000) as download_info:
                    page.locator('text="Baixar PDF"').first.click()
                download = download_info.value
                
                # Salvar o arquivo
                filename = download.suggested_filename or f"fatura_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                filepath = os.path.join(download_path, filename)
                download.save_as(filepath)
                
                # Se o arquivo foi baixado, podemos retornar o caminho ou fazer upload
                # Por enquanto, vamos tentar extrair a URL do download se possível
                print(f'✅ [PDF] Arquivo baixado: {filepath}')
                # Nota: Neste caso, seria necessário fazer upload para um storage público
                # Para agora, vamos continuar tentando outras estratégias
                
            except Exception as e:
                print(f'⚠️ [PDF] Estratégia 2 falhou: {e}')
        
        # Estratégia 3: Tentar capturar via popup/aba (método original)
        if not pdf_url:
            try:
                print('🔍 [PDF] Estratégia 3: Tentando capturar via popup...')
                with context.expect_page(timeout=10000) as popup_info:
                    page.locator('text="Baixar PDF"').first.click()
                pdf_page = popup_info.value
                pdf_page.wait_for_load_state('networkidle', timeout=5000)
                pdf_url = pdf_page.url
                
                # Verificar se a URL realmente é um PDF
                if pdf_url and (pdf_url.endswith('.pdf') or 'application/pdf' in pdf_page.url):
                    print(f'✅ [PDF] Link capturado via popup: {pdf_url[:100]}...')
                else:
                    # Pode ser uma página intermediária, tentar encontrar o link do PDF
                    html_pdf_page = pdf_page.content()
                    pdf_links_page = re.findall(r'https?://[^\s<>"\']+\.pdf', html_pdf_page, re.IGNORECASE)
                    if pdf_links_page:
                        pdf_url = pdf_links_page[0]
                        print(f'✅ [PDF] Link encontrado na página do popup: {pdf_url[:100]}...')
                    else:
                        pdf_url = None  # Não encontrou PDF válido
                
                pdf_page.close()
            except Exception as e:
                print(f'⚠️ [PDF] Estratégia 3 falhou: {e}')
                import traceback
                traceback.print_exc()
        
        # Estratégia 4: Tentar extrair de atributos href ou onclick
        if not pdf_url:
            try:
                print('🔍 [PDF] Estratégia 4: Procurando em atributos HTML...')
                btn_pdf = page.locator('text="Baixar PDF"').first
                if btn_pdf.count() > 0:
                    href = btn_pdf.get_attribute('href')
                    onclick = btn_pdf.get_attribute('onclick')
                    
                    if href and '.pdf' in href.lower():
                        pdf_url = href if href.startswith('http') else f"{page.url.rsplit('/', 1)[0]}/{href.lstrip('/')}"
                        print(f'✅ [PDF] Link encontrado em href: {pdf_url[:100]}...')
                    elif onclick:
                        # Extrair URL do onclick (pode conter JavaScript)
                        onclick_urls = re.findall(r'https?://[^\s\'"]+\.pdf', onclick, re.IGNORECASE)
                        if onclick_urls:
                            pdf_url = onclick_urls[0]
                            print(f'✅ [PDF] Link encontrado em onclick: {pdf_url[:100]}...')
            except Exception as e:
                print(f'⚠️ [PDF] Estratégia 4 falhou: {e}')
        
        if not pdf_url:
            print('⚠️ [PDF] Todas as estratégias falharam. PDF não capturado.')

        browser.close()

        return {
            'valor': valor,
            'codigo_pix': codigo_pix,
            'codigo_barras': codigo_barras,
            'data_vencimento': vencimento,
            'pdf_url': pdf_url,
        }
