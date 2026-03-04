# scripts/testar_lead_login.py
"""
Teste local do login e fluxo de criação de Lead no site Comercial Blink (automação Lead).
Abre o navegador VISÍVEL e executa os cliques passo a passo para você acompanhar.

=== DESENHO DOS CLIQUES (passo a passo) ===
  --- LOGIN ---
  0. Abrir URL: https://blinktelecom.my.site.com/comercial/login
  1. Preencher usuário (input#username): recordpap@gmail.com
  2. Preencher senha (input#password): Alpap123
  3. Clicar botão "Fazer login" (input#Login)
  4. Aguardar redirecionamento

  --- PÓS-LOGIN (criar lead) ---
  5. Clicar em "Leads" (span com texto Leads)
  6. Clicar em "Criar" (a.forceActionLink title="Criar")
  7. Modal: manter "Blink Fibra" selecionado; clicar "Avançar" (span.label.bBody)
  8. Formulário (dados virão do usuário via WhatsApp no futuro):
     - Primeiro Nome (input[name="firstName"] / #input-110)
     - Sobrenome (input[name="lastName"] / #input-112)
     - Tratamento: manter "nenhum" (não pedir ao usuário)
     - Telefone celular com DDD (input[name="MobilePhone"] / #input-150)
     - CPF (input[name="CPF__c"] / #input-209)
     - Canal de atendimento: selecionar "Externo" (combobox, sempre fixo)
     - CEP (input combobox "Pesquisar endereço" / #combobox-input-347) -> escolher da lista
     - Número da fachada (input[name="Numero__c"] / #input-306)
  9. Clicar "Salvar e criar" (button[name="SaveAndNew"])

Tratamento de erros:
  - Se o endereço (CEP) não for selecionado: mensagem "O endereço não foi selecionado."
  - Se aparecer "Encontramos um obstáculo." na página: extrair mensagem, fechar diálogo e informar que o lead não foi criado.

Uso:
    cd c:\\site-record
    python scripts/testar_lead_login.py

Requisito: playwright instalado (pip install playwright && playwright install chromium)
"""
import time
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Instale o Playwright: pip install playwright && playwright install chromium")
    sys.exit(1)

# Configuração do login (altere se quiser testar com outros dados)
URL_LOGIN = "https://blinktelecom.my.site.com/comercial/login"
USUARIO = "recordpap@gmail.com"
SENHA = "Alpap123"

# Dados de teste para o formulário do lead (em produção vêm do usuário via WhatsApp)
PRIMEIRO_NOME = "João"
SOBRENOME = "Silva Santos"
TELEFONE_DDD = "11987654321"
CPF_CLIENTE = "12345678909"  # 11 dígitos
CEP = "01310100"  # Exemplo SP
NUMERO_FACHADA = "100"

# Seletores - Login
SELETOR_USUARIO = "input#username"
SELETOR_USUARIO_FALLBACK = "input[name='username'], input[type='email'], input[placeholder*='sername'], input[placeholder*='mail']"
SELETOR_SENHA = "input#password"
SELETOR_SENHA_FALLBACK = "input[name='pw'], input[type='password']"
SELETOR_BOTAO_LOGIN = "input#Login"
SELETOR_BOTAO_FALLBACK = "input[type='submit'][value='Fazer login'], button[type='submit']"

# Seletores - Pós-login (Leads, Criar, Modal, Formulário)
SELETOR_LEADS = "span:has-text('Leads')"
SELETOR_CRIAR = "a.forceActionLink[title='Criar'], a[title='Criar']"
SELETOR_AVANCAR_MODAL = "span.label.bBody:has-text('Avançar'), span:has-text('Avançar')"
SELETOR_PRIMEIRO_NOME = "input[name='firstName']"
SELETOR_PRIMEIRO_NOME_FB = "input#input-110, input[placeholder='Primeiro Nome']"
SELETOR_SOBRENOME = "input[name='lastName']"
SELETOR_SOBRENOME_FB = "input#input-112, input[placeholder='Sobrenome']"
SELETOR_TELEFONE = "input[name='MobilePhone']"
SELETOR_TELEFONE_FB = "input#input-150"
SELETOR_CPF = "input[name='CPF__c']"
SELETOR_CPF_FB = "input#input-209"
SELETOR_CANAL_ATENDIMENTO = "button[aria-label='Canal de atendimento'], button#combobox-button-235"
SELETOR_OPCAO_EXTERNO = "[role='listbox'] [role='option']:has-text('Externo'), li:has-text('Externo'), [data-value='Externo']"
# CEP: combobox de endereço (LWC id dinâmico, ex: combobox-input-362)
# Usar APENAS seletores que identifiquem o campo de endereço (evitar outro combobox com "Search...")
SELETOR_CEP = "input[placeholder='Pesquisar endereço'], input[aria-label='Pesquisa de endereço']"
SELETOR_CEP_FB = "input[id^='combobox-input-'][placeholder='Pesquisar endereço']"
SELETOR_CEP_COMBO = "input[id^='combobox-input-'][aria-label='Pesquisa de endereço']"
# Não usar input[role='combobox'] sozinho: pega o primeiro combobox da página (ex: Search)
SELETOR_OPCAO_ENDERECO = "[role='listbox'] [role='option'], [id^='dropdown-element-'] li, ul[role='listbox'] li"
SELETOR_NUMERO_FACHADA = "input[name='Numero__c']"
SELETOR_NUMERO_FACHADA_FB = "input#input-306"
SELETOR_SALVAR_CRIAR = "button[name='SaveAndNew']"
SELETOR_SALVAR_CRIAR_FB = "button:has-text('Salvar e criar')"

# Campos de endereço (preenchidos ao selecionar CEP) - para verificar se endereço foi selecionado
SELETOR_RUA = "textarea[name='street'], input[name='street']"
SELETOR_CEP_PREENCHIDO = "input[name='postalCode']"
SELETOR_CIDADE = "input[name='city']"


def verificar_endereco_preenchido(page, timeout_espera: float = 1.5) -> bool:
    """
    Verifica se, após digitar CEP e tentar selecionar, os campos de endereço foram preenchidos.
    Retorna True se pelo menos um deles (Rua, Cidade ou CEP) tiver valor.
    """
    time.sleep(timeout_espera)
    try:
        el_cep = page.query_selector(SELETOR_CEP_PREENCHIDO)
        if el_cep:
            v = el_cep.input_value() or ""
            if v.strip():
                return True
        el_rua = page.query_selector(SELETOR_RUA)
        if el_rua:
            v = el_rua.input_value() if hasattr(el_rua, "input_value") else ""
            if v and str(v).strip():
                return True
        el_cidade = page.query_selector(SELETOR_CIDADE)
        if el_cidade:
            v = el_cidade.input_value() or ""
            if v.strip():
                return True
    except Exception:
        pass
    return False


def verificar_erro_obstaculo(page) -> tuple:
    """
    Verifica se na página aparece o diálogo 'Encontramos um obstáculo.' (Salesforce).
    Retorna (True, mensagem_erro) se encontrar; (False, None) caso contrário.
    """
    try:
        dialog = page.get_by_role("dialog", name="Encontramos um obstáculo.")
        if dialog.count() > 0 and dialog.first.is_visible():
            msg = "Encontramos um obstáculo."
            try:
                listas = page.locator("ul.errorsList.slds-list_dotted li, .pageLevelErrors ul li")
                if listas.count() > 0:
                    msg = listas.first.inner_text().strip() or msg
            except Exception:
                pass
            return (True, msg)
        if page.get_by_text("Encontramos um obstáculo.", exact=False).first.is_visible():
            return (True, "Encontramos um obstáculo.")
    except Exception:
        pass
    return (False, None)


def fechar_dialogo_erro(page) -> None:
    """Tenta fechar o diálogo de erro (botão Fechar ou X)."""
    try:
        btn = page.get_by_role("button", name="Fechar caixa de diálogo de erro")
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            time.sleep(0.5)
            return
        close = page.locator("button[title*='Fechar'], .slds-popover__close button").first
        if close.is_visible():
            close.click()
            time.sleep(0.5)
    except Exception:
        pass


def log(msg: str) -> None:
    print(f"  [LEAD] {msg}")


def passo_clique(page, seletor: str, descricao: str, fallback: str = None, timeout: int = 10000) -> bool:
    """Aguarda elemento, clica e registra. Retorna True se ok."""
    try:
        el = page.wait_for_selector(seletor, timeout=timeout)
        if el:
            log(f"Clique: {descricao} (seletor: {seletor})")
            el.click()
            time.sleep(0.5)
            return True
    except Exception as e:
        log(f"Seletor principal falhou: {seletor} -> {e}")
    if fallback:
        try:
            el = page.wait_for_selector(fallback, timeout=3000)
            if el:
                log(f"Clique (fallback): {descricao} (seletor: {fallback})")
                el.click()
                time.sleep(0.5)
                return True
        except Exception as e2:
            log(f"Fallback falhou: {fallback} -> {e2}")
    return False


def passo_preencher(page, seletor: str, valor: str, descricao: str, fallback: str = None, timeout: int = 10000) -> bool:
    """Preenche campo e registra. Retorna True se ok."""
    try:
        el = page.wait_for_selector(seletor, timeout=timeout)
        if el:
            log(f"Preencher: {descricao} -> '{valor}' (seletor: {seletor})")
            el.click()
            time.sleep(0.2)
            el.fill("")
            el.fill(valor)
            time.sleep(0.3)
            return True
    except Exception as e:
        log(f"Seletor principal falhou: {seletor} -> {e}")
    if fallback:
        try:
            el = page.wait_for_selector(fallback, timeout=3000)
            if el:
                log(f"Preencher (fallback): {descricao} (seletor: {fallback})")
                el.click()
                time.sleep(0.2)
                el.fill("")
                el.fill(valor)
                time.sleep(0.3)
                return True
        except Exception as e2:
            log(f"Fallback falhou: {fallback} -> {e2}")
    return False


def passo_clique_por_texto(page, texto: str, descricao: str, timeout: int = 10000) -> bool:
    """Clica em elemento que contém o texto (ex.: 'Leads', 'Avançar')."""
    try:
        el = page.get_by_text(texto, exact=False).first
        el.wait_for(state="visible", timeout=timeout)
        log(f"Clique (por texto): {descricao} -> '{texto}'")
        el.click()
        time.sleep(0.5)
        return True
    except Exception as e:
        log(f"Clique por texto '{texto}' falhou: {e}")
    return False


def main():
    print("\n=== Teste de login LEAD (Comercial Blink - criação de Lead) ===\n")
    print(f"URL: {URL_LOGIN}")
    print(f"Usuário: {USUARIO}")
    print("Senha: ******")
    print("\nNavegador abrindo em modo VISÍVEL. Acompanhe os cliques.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )
        page = context.new_page()

        try:
            log("Abrindo página de login...")
            page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            log("Passo 1: Preencher usuário (email)")
            ok_user = passo_preencher(
                page,
                SELETOR_USUARIO,
                USUARIO,
                "Campo Username / Email",
                fallback=SELETOR_USUARIO_FALLBACK,
            )
            if not ok_user:
                print("\n[ERRO] Não foi possível encontrar o campo de usuário.")
                time.sleep(30)
                return

            time.sleep(0.8)

            log("Passo 2: Preencher senha")
            ok_pw = passo_preencher(
                page,
                SELETOR_SENHA,
                SENHA,
                "Campo Senha",
                fallback=SELETOR_SENHA_FALLBACK,
            )
            if not ok_pw:
                print("\n[ERRO] Não foi possível encontrar o campo de senha.")
                time.sleep(30)
                return

            time.sleep(0.8)

            log("Passo 3: Clicar em 'Fazer login'")
            ok_btn = passo_clique(
                page,
                SELETOR_BOTAO_LOGIN,
                "Botão Fazer login",
                fallback=SELETOR_BOTAO_FALLBACK,
            )
            if not ok_btn:
                print("\n[ERRO] Não foi possível encontrar o botão de login.")
                time.sleep(30)
                return

            log("Aguardando redirecionamento após login...")
            time.sleep(3)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            log(f"URL atual: {page.url}")

            log("Passo 5: Clicar em 'Leads'")
            if not passo_clique(page, SELETOR_LEADS, "Menu Leads") and not passo_clique_por_texto(page, "Leads", "Menu Leads"):
                if not passo_clique_por_texto(page, "Leads", "Menu Leads"):
                    print("[ERRO] Não foi possível clicar em Leads.")
                    time.sleep(30)
                    return
            time.sleep(2)

            log("Passo 6: Clicar em 'Criar'")
            if not passo_clique(page, SELETOR_CRIAR, "Botão Criar") and not passo_clique_por_texto(page, "Criar", "Botão Criar"):
                print("[ERRO] Não encontrou 'Criar'.")
                time.sleep(30)
                return
            time.sleep(2)

            log("Passo 7: Modal - clicar 'Avançar' (manter Blink Fibra)")
            if not passo_clique(page, SELETOR_AVANCAR_MODAL, "Botão Avançar") and not passo_clique_por_texto(page, "Avançar", "Botão Avançar"):
                print("[ERRO] Não encontrou 'Avançar'.")
                time.sleep(30)
                return
            time.sleep(2)

            log("Passo 8: Preencher formulário do lead (dados de teste)")

            if not passo_preencher(page, SELETOR_PRIMEIRO_NOME, PRIMEIRO_NOME, "Primeiro Nome", fallback=SELETOR_PRIMEIRO_NOME_FB):
                print("[ERRO] Campo Primeiro Nome não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.5)

            if not passo_preencher(page, SELETOR_SOBRENOME, SOBRENOME, "Sobrenome", fallback=SELETOR_SOBRENOME_FB):
                print("[ERRO] Campo Sobrenome não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.5)

            if not passo_preencher(page, SELETOR_TELEFONE, TELEFONE_DDD, "Telefone (DDD + celular)", fallback=SELETOR_TELEFONE_FB):
                print("[ERRO] Campo Telefone não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.5)

            if not passo_preencher(page, SELETOR_CPF, CPF_CLIENTE, "CPF", fallback=SELETOR_CPF_FB):
                print("[ERRO] Campo CPF não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.5)

            log("Passo 8b: Canal de atendimento -> Externo")
            try:
                btn_canal = page.wait_for_selector(SELETOR_CANAL_ATENDIMENTO, timeout=5000)
                if btn_canal:
                    btn_canal.click()
                    time.sleep(1)
                    opt = page.locator(SELETOR_OPCAO_EXTERNO).first
                    if opt.count() > 0:
                        opt.click()
                        log("Selecionado 'Externo' no canal de atendimento")
                    else:
                        page.keyboard.press("Escape")
            except Exception as ex:
                log(f"Canal (Externo) não encontrado ou já selecionado: {ex}")
            time.sleep(0.5)

            log("Passo 8c: CEP - preencher e selecionar sugestão de endereço")
            page.keyboard.press("Escape")
            time.sleep(0.5)
            # Dar tempo para o bloco de endereço do formulário renderizar (LWC pode carregar depois)
            time.sleep(1.5)
            cep_locator = None
            timeout_cep = 10000
            # 1) get_by_placeholder perfura Shadow DOM (LWC); tentar na página inteira primeiro
            try:
                loc = page.get_by_placeholder("Pesquisar endereço", exact=True)
                loc.first.wait_for(state="visible", timeout=timeout_cep)
                if loc.first.is_visible():
                    cep_locator = loc.first
                    log("Campo CEP encontrado via: get_by_placeholder('Pesquisar endereço')")
            except Exception:
                pass
            if not cep_locator:
                try:
                    loc = page.get_by_placeholder("Pesquisar endereço", exact=False)
                    if loc.count() > 0:
                        loc.first.wait_for(state="visible", timeout=timeout_cep)
                        if loc.first.is_visible():
                            cep_locator = loc.first
                            log("Campo CEP encontrado via: get_by_placeholder (partial)")
                except Exception:
                    pass
            if not cep_locator:
                try:
                    loc = page.get_by_label("Pesquisa de endereço", exact=False)
                    if loc.count() > 0:
                        loc.first.wait_for(state="visible", timeout=timeout_cep)
                        if loc.first.is_visible():
                            cep_locator = loc.first
                            log("Campo CEP encontrado via: get_by_label('Pesquisa de endereço')")
                except Exception:
                    pass
            if not cep_locator:
                for desc, seletor in [
                    ("placeholder/aria-label", "input[placeholder='Pesquisar endereço'], input[aria-label='Pesquisa de endereço']"),
                    ("combobox+placeholder", "input[id^='combobox-input-'][placeholder='Pesquisar endereço']"),
                    ("placeholder contains", "input[placeholder*='endereço']"),
                ]:
                    try:
                        loc = page.locator(seletor).first
                        loc.wait_for(state="visible", timeout=5000)
                        if loc.is_visible():
                            cep_locator = loc
                            log(f"Campo CEP encontrado via: {desc}")
                            break
                    except Exception:
                        pass
            if not cep_locator:
                try:
                    modal = page.locator(".slds-modal__container, .modal-container").first
                    loc = modal.locator("input[placeholder='Pesquisar endereço'], input[aria-label='Pesquisa de endereço'], input[placeholder*='endereço']").first
                    loc.wait_for(state="visible", timeout=5000)
                    if loc.is_visible():
                        cep_locator = loc
                        log("Campo CEP encontrado via: dentro do modal")
                except Exception:
                    pass
            if cep_locator:
                try:
                    cep_locator.scroll_into_view_if_needed()
                except Exception:
                    pass
                time.sleep(0.3)
                try:
                    cep_locator.fill(CEP)
                except Exception:
                    try:
                        cep_locator.click(force=True)
                        time.sleep(0.2)
                        cep_locator.fill(CEP)
                    except Exception as e:
                        log(f"Falha ao preencher CEP: {e}")
                        cep_locator = None
                if cep_locator:
                    log(f"CEP digitado: {CEP}; aguardando sugestão...")
                    time.sleep(2)
                    page.keyboard.press("ArrowDown")
                    time.sleep(0.4)
                    page.keyboard.press("Enter")
                    log("Sugestão selecionada (ArrowDown + Enter)")
                    time.sleep(0.6)
                    cep_formatado = f"{CEP[:5]}-{CEP[5:]}" if len(CEP) >= 8 else CEP
                    try:
                        sug = page.get_by_text(cep_formatado, exact=False).first
                        if sug.is_visible():
                            sug.click()
                            log("Sugestão selecionada (clique no CEP)")
                    except Exception:
                        pass
            else:
                log("[AVISO] Campo CEP não encontrado.")
            time.sleep(1)

            if not cep_locator:
                print("\n[ERRO] Campo CEP não encontrado. O lead NÃO será salvo sem endereço.")
                time.sleep(30)
                browser.close()
                return

            # Tratamento de erro 1: endereço não selecionado
            if not verificar_endereco_preenchido(page):
                print("\n[ERRO] O endereço não foi selecionado. Selecione uma sugestão da lista após digitar o CEP.")
                time.sleep(30)
                browser.close()
                return

            if not passo_preencher(page, SELETOR_NUMERO_FACHADA, NUMERO_FACHADA, "Número da fachada", fallback=SELETOR_NUMERO_FACHADA_FB):
                print("[ERRO] Campo Número fachada não encontrado.")
                time.sleep(30)
                return
            time.sleep(0.8)

            log("Passo 9: Clicar 'Salvar e criar'")
            if not passo_clique(page, SELETOR_SALVAR_CRIAR, "Salvar e criar", fallback=SELETOR_SALVAR_CRIAR_FB) and not passo_clique_por_texto(page, "Salvar e criar", "Salvar e criar"):
                print("[ERRO] Botão 'Salvar e criar' não encontrado.")
                time.sleep(30)
                return

            time.sleep(2)

            # Tratamento de erro 2: "Encontramos um obstáculo."
            tem_obstaculo, msg_erro = verificar_erro_obstaculo(page)
            if tem_obstaculo:
                print("\n[ERRO] Encontramos um obstáculo. O lead NÃO foi criado.")
                print(f"Detalhe: {msg_erro}")
                fechar_dialogo_erro(page)
                print("\nNavegador permanecerá aberto por 30 segundos.")
                time.sleep(30)
                browser.close()
                print("\nFim do teste (lead não criado).")
                return

            log(f"URL final: {page.url}")

            print("\n--- Fluxo concluído. Verifique se o lead foi criado. ---")
            print("Navegador permanecerá aberto por 60 segundos para você inspecionar.")
            time.sleep(60)

        except Exception as e:
            print(f"\n[ERRO] {e}")
            import traceback
            traceback.print_exc()
            time.sleep(30)
        finally:
            browser.close()

    print("\nFim do teste.")


if __name__ == "__main__":
    main()
