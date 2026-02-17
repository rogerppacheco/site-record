# crm_app/services_inclusao_viabilidade.py
"""
Serviço para automação de solicitação de viabilidade (Inclusão) via Google Forms.
- Consulta ViaCEP para endereço
- Nominatim para coordenadas
- Street View Static API para foto automática
- Playwright para preencher o formulário
"""
import logging
import os
import re
import tempfile
from typing import Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    sync_playwright = None

# Constantes
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLScnXtSMB3EMutB88IfAg3ihGxUj60nAM6BZqmt4m24TsyPoAw/viewform"

# Valores fixos do formulário
CODIGO_SAP = "1068561"
EXECUTIVO = "ROGERIO PEREIRA PACHECO"
TIPO_CANAL = "PAP"
# Email do campo formulário - lido de GOOGLE_FORM_EMAIL (fallback: comunicacao@recordpap.com.br)
EMAIL = os.environ.get("GOOGLE_FORM_EMAIL", "comunicacao@recordpap.com.br")
EMPRESA_VENDAS = "RECORD"

# Mapeamento UF (sigla ViaCEP) -> nome completo (Google Forms)
UF_SIGLA_PARA_NOME = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santos", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}

# Mapeamento tipo logradouro (primeira palavra) -> opção do formulário
TIPO_LOGRADOURO_MAP = {
    "ALAMEDA": "Alameda",
    "AVENIDA": "Avenida",
    "AV": "Avenida",
    "BECO": "Beco",
    "TRAVESSA": "Travessa",
    "TRAV": "Travessa",
    "RUA": "Rua",
    "RODOVIA": "Rodovia",
    "BR": "Rodovia",
    "SERVIDAO": "Servidão",
    "SERVIDÃO": "Servidão",
}


def _limpar_cep(cep: str) -> str:
    """Retorna apenas dígitos do CEP."""
    return re.sub(r'\D', '', str(cep or ''))[:8]


def consultar_viacep(cep: str) -> Optional[dict]:
    """
    Consulta ViaCEP e retorna dados do endereço.
    Retorna None se CEP inválido.
    """
    cep_limpo = _limpar_cep(cep)
    if len(cep_limpo) != 8:
        return None
    try:
        resp = requests.get(f"https://viacep.com.br/ws/{cep_limpo}/json/", timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get('erro'):
            return None
        return {
            'cep': data.get('cep', cep_limpo),
            'logradouro': data.get('logradouro') or '',
            'bairro': data.get('bairro') or '',
            'localidade': data.get('localidade') or '',
            'uf': data.get('uf') or '',
        }
    except Exception as e:
        logger.warning(f"[Inclusão] ViaCEP erro: {e}")
        return None


def obter_tipo_logradouro(logradouro: str) -> str:
    """
    Extrai o tipo de logradouro da primeira palavra.
    Retorna 'Outros' se não encontrar mapeamento.
    """
    if not logradouro or not isinstance(logradouro, str):
        return "Outros"
    partes = logradouro.strip().upper().split()
    if not partes:
        return "Outros"
    primeira = partes[0].replace(".", "")
    return TIPO_LOGRADOURO_MAP.get(primeira, "Outros")


def buscar_coordenadas(endereco_completo: str) -> Optional[dict]:
    """
    Busca coordenadas (lat, lng) via Nominatim.
    endereco_completo: ex "Rua X, 123, Cidade - UF, Brasil"
    """
    try:
        headers = {'User-Agent': 'RecordPAP_Inclusao/1.0'}
        params = {'q': endereco_completo, 'format': 'json', 'limit': 1}
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers=headers,
            timeout=5
        )
        if resp.status_code == 200 and resp.json():
            r = resp.json()[0]
            return {
                'lat': float(r['lat']),
                'lng': float(r['lon']),
                'lat_str': r['lat'],
                'lng_str': r['lon'],
            }
    except Exception as e:
        logger.warning(f"[Inclusão] Nominatim erro: {e}")
    return None


def baixar_street_view(lat: float, lng: float, tamanho: str = "640x640") -> Optional[str]:
    """
    Baixa imagem do Street View Static API.
    Retorna o caminho do arquivo salvo ou None se falhar.
    """
    api_key = os.environ.get('GOOGLE_STREETVIEW_API_KEY') or getattr(
        settings, 'GOOGLE_STREETVIEW_API_KEY', None
    )
    if not api_key:
        logger.warning("[Inclusão] GOOGLE_STREETVIEW_API_KEY não configurada")
        return None
    try:
        location = f"{lat},{lng}"
        url = (
            "https://maps.googleapis.com/maps/api/streetview"
            f"?size={tamanho}&location={location}&key={api_key}"
        )
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"[Inclusão] Street View API status {resp.status_code}")
            return None
        # Verificar se retornou imagem válida (API retorna imagem ou HTML de erro)
        ct = resp.headers.get('Content-Type', '')
        if 'image' not in ct:
            logger.warning(f"[Inclusão] Street View não retornou imagem: {ct}")
            return None
        fd, path = tempfile.mkstemp(suffix='.jpg', prefix='streetview_')
        os.close(fd)
        with open(path, 'wb') as f:
            f.write(resp.content)
        return path
    except Exception as e:
        logger.warning(f"[Inclusão] Street View erro: {e}")
    return None


def formatar_cep(cep: str) -> str:
    """Formato: xxxxx-xxx"""
    c = _limpar_cep(cep)
    if len(c) == 8:
        return f"{c[:5]}-{c[5:]}"
    return c


# Debug: DEBUG_INCLUSAO_FORM=1 no .env para log detalhado por etapa
DEBUG_FORM = os.environ.get('DEBUG_INCLUSAO_FORM', '').lower() in ('1', 'true', 'yes')


def _log_step(step: str, msg: str = '', ok: bool = True):
    """Log de etapa para debug do preenchimento do formulário."""
    if DEBUG_FORM or not ok:
        level = logger.info if ok else logger.warning
        level(f"[Inclusão] {step} {'✓' if ok else '✗'} {msg}".strip())


def _fill_safe(page, locator, valor: str, step_name: str, timeout: int = 8000) -> bool:
    """Preenche campo com timeout reduzido e log. Retorna True se OK."""
    try:
        el = page.locator(locator)
        n = el.count()
        _log_step(step_name, f"elementos={n}")
        if n > 0:
            el.first.fill(str(valor), timeout=timeout)
            _log_step(step_name, "preenchido", ok=True)
            return True
    except Exception as e:
        _log_step(step_name, str(e), ok=False)
    return False


def _preencher_campo(page, locator, valor: str) -> bool:
    """Preenche campo e retorna True se OK."""
    try:
        el = page.locator(locator).first
        if el.count() > 0:
            el.fill(str(valor), timeout=8000)
            return True
    except Exception:
        pass
    return False


def _clicar_opcao(page, texto: str) -> bool:
    """Clica em opção (radio) que contém o texto exato."""
    try:
        el = page.get_by_text(texto, exact=True).first
        if el.count() > 0:
            el.click()
            return True
    except Exception:
        pass
    try:
        el = page.locator(f'span.aDTYNe:has-text("{texto}")').first
        if el.count() > 0:
            el.click()
            return True
    except Exception:
        pass
    return False


def _fazer_login_google(page) -> bool:
    """
    Se a página redirecionou para login do Google, faz login com GOOGLE_FORM_EMAIL e GOOGLE_FORM_PASSWORD.
    Retorna True se fez login (ou não precisava), False se falhou.
    """
    url = page.url
    if "accounts.google.com" not in url:
        return True  # Já está no formulário
    email = os.environ.get("GOOGLE_FORM_EMAIL", "comunicacao@recordpap.com.br")
    password = os.environ.get("GOOGLE_FORM_PASSWORD", "")
    if not password:
        logger.warning("[Inclusão] GOOGLE_FORM_PASSWORD não configurada - não é possível fazer login")
        return False
    try:
        def _clicar_avancar():
            for selector in [
                'button:has-text("Avançar")',
                'button:has-text("Next")',
                'span:has-text("Avançar")',
                'span:has-text("Next")',
                '[role="button"]:has-text("Avançar")',
                '[role="button"]:has-text("Next")',
            ]:
                btn = page.locator(selector).first
                if btn.count() > 0:
                    btn.click()
                    return True
            return False

        def _pular_passkey():
            """Clica em 'Agora não' ou 'Not now' para pular passkey/login mais rápido."""
            for texto in ['Agora não', 'Not now', 'Agora nao']:
                try:
                    btn = page.get_by_role('button', name=texto)
                    if btn.count() > 0:
                        btn.first.click(force=True, timeout=3000)
                        logger.info(f"[Inclusão] Clicou em '{texto}' (passkey)")
                        return True
                except Exception:
                    pass
            for texto in ['Agora não', 'Not now']:
                try:
                    btn = page.get_by_text(texto, exact=False)
                    if btn.count() > 0:
                        btn.first.click(force=True, timeout=3000)
                        logger.info(f"[Inclusão] Clicou em '{texto}' (get_by_text)")
                        return True
                except Exception:
                    pass
            for sel in [
                'button:has-text("Agora não")',
                'button:has-text("Not now")',
                'span:has-text("Agora não")',
                'span:has-text("Not now")',
                '[role="button"]:has-text("Agora não")',
                '[role="button"]:has-text("Not now")',
                'div[role="button"]:has-text("Agora não")',
                'div[role="button"]:has-text("Not now")',
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0:
                        btn.click(force=True, timeout=3000)
                        logger.info(f"[Inclusão] Clicou em passkey via seletor {sel[:40]}")
                        return True
                except Exception:
                    pass
            return False

        # Campo de email (identifierId)
        email_input = page.locator('#identifierId').first
        if email_input.count() > 0:
            email_input.click()
            page.wait_for_timeout(300)
            email_input.fill(email)
            page.wait_for_timeout(500)
            _clicar_avancar()
            page.wait_for_timeout(3000)

        # Tela "Login mais rápido" (passkey) - ANTES da senha
        if 'passkeyenrollment' in page.url or page.locator('text=Login mais rápido').count() > 0:
            if _pular_passkey():
                page.wait_for_timeout(2000)

        # Campo de senha
        password_input = page.locator('input[type="password"]').first
        if password_input.count() > 0:
            password_input.click()
            page.wait_for_timeout(300)
            password_input.fill(password)
            page.wait_for_timeout(500)
            _clicar_avancar()
            page.wait_for_timeout(5000)
            page.wait_for_load_state('networkidle', timeout=10000)

        # "Agora não" pode aparecer DEPOIS da senha (Google oferece passkey após login)
        for tentativa in range(5):
            page.wait_for_timeout(2000)
            if "accounts.google.com" not in page.url:
                logger.info(f"[Inclusão] Saiu do login (tentativa {tentativa + 1})")
                break
            # Aguardar botão "Agora não" aparecer (até 3s)
            try:
                page.get_by_text("Agora não", exact=False).first.wait_for(state='visible', timeout=3000)
            except Exception:
                try:
                    page.get_by_text("Not now", exact=False).first.wait_for(state='visible', timeout=1000)
                except Exception:
                    pass
            if _pular_passkey():
                page.wait_for_timeout(3000)
        if "accounts.google.com" in page.url:
            logger.warning("[Inclusão] Ainda em accounts.google.com após tentativas de pular passkey")
    except Exception as e:
        logger.warning(f"[Inclusão] Erro no login Google: {e}")
        return False
    return True


# Seletor para inputs de texto do formulário - EXCLUI o campo do reCAPTCHA (name="ca", aria-label com "ouve")
INPUTS_TEXT_FORM = 'input[type="text"]:not([name="ca"]):not([aria-label*="ouve"])'
# Campos de texto longo (Cidade, Logradouro, etc): Google Forms usa textarea OU div contenteditable
TEXTAREAS_FORM = 'textarea:not([name="g-recaptcha-response"])'
# Fallback: Google Forms Material Design usa div[contenteditable] e [role="textbox"]
CONTENTEDITABLE_FORM = 'div[contenteditable="true"], [role="textbox"]'


def _selecionar_dropdown(page, valor: str, nth_escolher: int = 0) -> bool:
    """Abre o dropdown (Escolher ou Selecione) e seleciona valor. Retorna True se OK."""
    try:
        # Fechar qualquer overlay/dropdown aberto que possa interceptar cliques
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        # Opção direta: se o dropdown já estiver aberto, clicar na opção
        for sel in [
            f'div[role="option"][data-value="{valor}"]',
            f'div[role="option"][data-value="{valor.upper()}"]',
            f'div[role="option"][data-value="{valor.lower()}"]',
            f'span.vRMGwf.oJeWuf:has-text("{valor}")',
            f'div[role="option"]:has(span:has-text("{valor}"))',
        ]:
            opt = page.locator(sel).first
            if opt.count() > 0:
                try:
                    opt.click(force=True, timeout=2000)
                    _log_step("Dropdown", f"{valor} (já aberto)", ok=True)
                    return True
                except Exception:
                    pass
        # Abrir dropdown: clicar no trigger (Escolher OU Selecione - Google Forms pt-BR)
        dd = page.locator('span.vRMGwf.oJeWuf').filter(has_text='Escolher')
        if dd.count() == 0:
            dd = page.get_by_text('Escolher', exact=True)
        if dd.count() == 0:
            # Form pode usar "Selecione" em vez de "Escolher"
            dd = page.locator('span.vRMGwf.oJeWuf').filter(has_text=re.compile(r'Selecione|Escolher', re.I))
        if dd.count() == 0:
            dd = page.locator('span').filter(has_text=re.compile(r'Selecione', re.I))
        if dd.count() > nth_escolher:
            dd = dd.nth(nth_escolher)
            dd.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            dd.click(force=True, timeout=5000)
            page.wait_for_timeout(1200)
        # Selecionar a opção - múltiplos seletores (Google Forms pode usar data-value ou span interno)
        for sel in [
            f'div[role="option"][data-value="{valor}"]',
            f'div[role="option"][data-value="{valor.upper()}"]',
            f'div[role="option"][data-value="{valor.lower()}"]',
            f'div[role="option"]:has(span:has-text("{valor}"))',
            f'span.vRMGwf.oJeWuf:has-text("{valor}")',
        ]:
            opt = page.locator(sel).first
            if opt.count() > 0:
                opt.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                opt.click(force=True, timeout=5000)
                return True
        # Fallback: clique por texto exato
        opt = page.get_by_text(valor, exact=True).first
        if opt.count() > 0:
            opt.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            opt.click(force=True, timeout=5000)
            return True
    except Exception as e:
        logger.warning(f"[Inclusão] Dropdown '{valor}' erro: {e}")
    return False


def _fechar_picker_modal(page) -> None:
    """
    Fecha o modal do Google Picker (Inserir arquivo) que bloqueia cliques.
    Quando o upload falha, o modal fica aberto e intercepta o botão Enviar.
    """
    try:
        # 1) Clicar em Cancelar/Fechar no picker (dentro do iframe)
        try:
            picker = page.frame_locator('iframe[src*="docs.google.com/picker"]')
            for texto in ['Cancelar', 'Cancel', 'Fechar', 'Close']:
                btn = picker.locator(f'button:has-text("{texto}"), span:has-text("{texto}")').first
                if btn.count() > 0:
                    btn.click(force=True, timeout=2000)
                    page.wait_for_timeout(500)
                    logger.info(f"[Inclusão] Fechou picker via '{texto}'")
                    return
        except Exception:
            pass
        # 2) Tecla Escape (fecha modais)
        for _ in range(3):
            page.keyboard.press('Escape')
            page.wait_for_timeout(400)
        # 3) Clicar fora do modal (se houver overlay)
        try:
            page.locator('.picker-dialog, [role="dialog"]').first.click(position={'x': 0, 'y': 0})
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"[Inclusão] _fechar_picker_modal: {e}")


def _upload_arquivos_viabilidade(page, arquivos_paths: list) -> bool:
    """
    Faz upload de um ou mais arquivos no formulário Google Forms.
    Aceita lista de caminhos (foto + comprovantes). O botão do form aceita múltiplos arquivos.
    Tenta: input direto com lista, depois Adicionar arquivo com filechooser.
    """
    if not arquivos_paths:
        return False
    paths_abs = []
    for p in arquivos_paths:
        pa = os.path.abspath(str(p))
        if os.path.isfile(pa):
            paths_abs.append(pa)
    if not paths_abs:
        _log_step("16-Foto", "Nenhum arquivo válido encontrado", ok=False)
        return False
    # 1) Tentar input[type="file"] direto (aceita múltiplos)
    try:
        fi = page.locator('input[type="file"]').first
        if fi.count() > 0:
            fi.set_input_files(paths_abs, timeout=8000)
            _log_step("16-Foto", f"OK (input direto, {len(paths_abs)} arquivo(s))")
            page.wait_for_timeout(2000)
            return True
    except Exception as e:
        _log_step("16-Foto", f"input direto: {e}", ok=False)
    # 2) "Adicionar arquivo" abre modal com iframe picker
    try:
        btn_add = page.locator('span.NPEfkd.RveJvd.snByac:has-text("Adicionar arquivo")').first
        if btn_add.count() == 0:
            btn_add = page.get_by_text('Adicionar arquivo').first
        if btn_add.count() == 0:
            _log_step("16-Foto", "Botão Adicionar arquivo não encontrado", ok=False)
            return False
        try:
            with page.expect_file_chooser(timeout=3000) as fc_info:
                btn_add.click()
            fc = fc_info.value
            fc.set_files(paths_abs)
            _log_step("16-Foto", f"OK (Adicionar arquivo direto, {len(paths_abs)} arquivo(s))")
            page.wait_for_timeout(2000)
            return True
        except Exception:
            pass
        page.wait_for_timeout(2500)
        picker_frame = page.frame_locator('iframe[src*="docs.google.com/picker"]')
        btn_procurar = picker_frame.locator('[jsname="V67aGc"], span:has-text("Procurar"), button:has-text("Procurar")').first
        btn_procurar.wait_for(state='visible', timeout=8000)
        with page.expect_file_chooser(timeout=12000) as fc_info:
            btn_procurar.click(force=True)
        fc = fc_info.value
        fc.set_files(paths_abs)
        _log_step("16-Foto", f"OK (FileChooser via Procurar, {len(paths_abs)} arquivo(s))")
        page.wait_for_timeout(2000)
        return True
    except Exception as e2:
        _log_step("16-Foto", f"Procurar (iframe): {e2}", ok=False)
    return False


def _upload_inclusao_onedrive(dados: dict, arquivos_paths: list) -> tuple:
    """
    Salva os arquivos da inclusão em pasta do OneDrive (uma pasta por solicitação).
    Pasta: Inclusao_Viabilidade/YYYY-MM-DD_HHmm_CEP_localidade/
    Retorna (sucesso: bool, pasta_path: str, links: list)
    """
    from datetime import datetime
    from crm_app.onedrive_service import OneDriveUploader

    viacep = dados.get('viacep') or {}
    cep = re.sub(r'\D', '', str(dados.get('cep', '') or ''))[:8]
    localidade = (viacep.get('localidade') or '').strip() or 'local'
    localidade_safe = re.sub(r'[^\w\s-]', '', localidade).strip()[:40] or 'local'
    dt = datetime.now().strftime('%Y-%m-%d_%H%M')
    pasta = f"{dt}_{cep}_{localidade_safe}".replace(' ', '_')
    base_folder = getattr(settings, 'INCLUSAO_ONEDRIVE_FOLDER', 'Inclusao_Viabilidade')
    folder_path = f"{base_folder}/{pasta}"

    uploader = OneDriveUploader()
    links = []
    for i, path in enumerate(arquivos_paths):
        if not path or not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1] or '.jpg'
        nome = f"foto_{i+1}{ext}" if i == 0 else f"comprovante_{i}{ext}"
        try:
            with open(path, 'rb') as f:
                url = uploader.upload_file(f, folder_path, nome)
                if url:
                    links.append(url)
                    logger.info(f"[Inclusão] OneDrive: {folder_path}/{nome} -> {url[:80]}...")
        except Exception as e:
            logger.warning(f"[Inclusão] Erro ao subir {nome} para OneDrive: {e}")
    return len(links) > 0, folder_path, links


def preencher_formulario_inclusao(
    dados: dict,
    foto_path: Optional[str] = None,
    arquivos_paths: Optional[list] = None,
) -> Tuple[bool, str]:
    """
    Preenche o formulário Google Forms de solicitação de viabilidade via Playwright.
    dados: dict com viacep, numero_fachada, complementos, fachadas_vizinhos, coordenadas, observacoes
    foto_path: (legado) caminho da foto principal
    arquivos_paths: lista de caminhos [foto, comprovante1, comprovante2, ...] - foto primeiro, depois comprovantes

    Retorna (sucesso, mensagem)
    """
    if not HAS_PLAYWRIGHT:
        return False, "Playwright não disponível"

    viacep = dados.get('viacep') or {}
    uf = viacep.get('uf', '')
    cidade = viacep.get('localidade', '')
    logradouro = viacep.get('logradouro', '')
    bairro = viacep.get('bairro', '')
    cep = dados.get('cep', '')
    numero = str(dados.get('numero_fachada', '') or '0')
    complementos = dados.get('complementos', '') or 'sem complementos'
    fachadas_vizinhos = dados.get('fachadas_vizinhos', '')
    coordenadas = dados.get('coordenadas', '')
    observacoes = dados.get('observacoes', '') or ''

    tipo_logradouro = obter_tipo_logradouro(logradouro)
    cep_formatado = formatar_cep(cep)

    headless = getattr(settings, 'PAP_HEADLESS', True)

    od_pasta_used = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.set_default_timeout(20000)

            page.goto(FORM_URL, wait_until='domcontentloaded')
            page.wait_for_load_state('networkidle', timeout=15000)
            page.wait_for_timeout(1500)

            # Login no Google (se redirecionou para accounts.google.com)
            if not _fazer_login_google(page):
                browser.close()
                return False, "Não foi possível fazer login no Google. Verifique GOOGLE_FORM_EMAIL e GOOGLE_FORM_PASSWORD no .env"
            page.wait_for_timeout(2000)
            # Se ainda estiver no login, tentar voltar ao formulário
            if "accounts.google.com" in page.url:
                page.goto(FORM_URL, wait_until='domcontentloaded')
                page.wait_for_load_state('networkidle', timeout=15000)
                page.wait_for_timeout(1500)

            # Limpar overlays/dropdowns abertos antes de preencher
            page.keyboard.press('Escape')
            page.wait_for_timeout(300)

            # Inputs de texto do formulário (exclui reCAPTCHA - name="ca")
            inputs_text = page.locator(INPUTS_TEXT_FORM)
            textareas = page.locator(TEXTAREAS_FORM)
            contenteditables = page.locator(CONTENTEDITABLE_FORM)
            n_inputs = inputs_text.count()
            n_textareas = textareas.count()
            n_ce = contenteditables.count()
            _log_step("INIT", f"URL={page.url[:80]}... inputs={n_inputs} textareas={n_textareas} contenteditable={n_ce}")

            # Ordem do formulário (manter alinhado):
            #  1) Código SAP   2) Executivo   3) Tipo canal   4) E-mail   5) Empresa
            #  6) UF/Estado   7) CEP         8) Cidade       9) Tipo logradouro
            # 10) Nome logradouro  11) Nº fachada  12) Bairro  13) Complementos
            # 14) Fachadas vizinhos  15) Coordenadas  16) Foto/vídeo  17) Observações

            def _fill_textlike(idx: int, valor: str, step_name: str) -> bool:
                """Preenche campo de texto longo (textarea OU div contenteditable). Google Forms pode usar ambos."""
                val = str(valor)
                # 1) Tentar textarea
                if textareas.count() > idx:
                    try:
                        textareas.nth(idx).fill(val, timeout=8000)
                        _log_step(step_name, "OK (textarea)")
                        return True
                    except Exception as e:
                        _log_step(step_name, f"textarea: {e}", ok=False)
                # 2) Fallback: div contenteditable / role=textbox
                if contenteditables.count() > idx:
                    try:
                        el = contenteditables.nth(idx)
                        el.click()
                        page.wait_for_timeout(200)
                        el.fill(val, timeout=8000)
                        _log_step(step_name, "OK (contenteditable)")
                        return True
                    except Exception as e:
                        _log_step(step_name, f"contenteditable: {e}", ok=False)
                _log_step(step_name, f"textareas={n_textareas}, contenteditable={n_ce}, idx={idx}", ok=False)
                return False

            # 1. Código SAP
            _log_step("1-CodigoSAP", f"inputs={n_inputs}")
            if n_inputs >= 1:
                try:
                    inputs_text.first.fill(CODIGO_SAP, timeout=8000)
                except Exception as e:
                    _log_step("1-CodigoSAP", str(e), ok=False)
                    raise
            page.wait_for_timeout(200)

            # 2. Executivo - dropdown
            _log_step("2-Executivo", "")
            ok_dd = _selecionar_dropdown(page, EXECUTIVO)
            _log_step("2-Executivo", "OK" if ok_dd else "FALHOU", ok=ok_dd)
            page.wait_for_timeout(500)

            # 3. Tipo canal - radio PAP
            _log_step("3-TipoCanal", "")
            _clicar_opcao(page, TIPO_CANAL)
            page.wait_for_timeout(200)

            # 4. E-mail
            _log_step("4-Email", "")
            try:
                page.locator('input[type="email"]').first.fill(EMAIL, timeout=8000)
            except Exception as e:
                _log_step("4-Email", str(e), ok=False)
                raise
            page.wait_for_timeout(200)

            # 5. Empresa - dropdown (1º Selecione restante após Executivo)
            _log_step("5-Empresa", "")
            _selecionar_dropdown(page, EMPRESA_VENDAS, nth_escolher=0)
            page.wait_for_timeout(500)

            # 6. UF - dropdown (ViaCEP retorna sigla "MG", form usa "Minas Gerais")
            if uf:
                uf_form = UF_SIGLA_PARA_NOME.get(uf.upper(), uf)
                _log_step("6-UF", f"{uf} -> {uf_form}")
                _selecionar_dropdown(page, uf_form, nth_escolher=1)
                page.wait_for_timeout(500)

            # 7. CEP
            _log_step("7-CEP", "")
            if n_inputs >= 2:
                try:
                    inputs_text.nth(1).fill(cep_formatado, timeout=8000)
                except Exception as e:
                    _log_step("7-CEP", str(e), ok=False)
            page.wait_for_timeout(200)

            # 8. Cidade
            _log_step("8-Cidade", "")
            _fill_textlike(0, cidade, "8-Cidade")
            page.wait_for_timeout(200)

            # 9. Tipo logradouro - radio
            _log_step("9-TipoLogradouro", tipo_logradouro)
            _clicar_opcao(page, tipo_logradouro)
            page.wait_for_timeout(200)

            # 10. Nome logradouro
            _fill_textlike(1, logradouro, "10-Logradouro")
            page.wait_for_timeout(200)

            # 11. Número fachada
            _log_step("11-Numero", "")
            if n_inputs >= 3:
                try:
                    inputs_text.nth(2).fill(numero, timeout=8000)
                except Exception as e:
                    _log_step("11-Numero", str(e), ok=False)
            page.wait_for_timeout(200)

            # 12. Bairro
            _fill_textlike(2, bairro, "12-Bairro")
            page.wait_for_timeout(200)

            # 13. Complementos
            _fill_textlike(3, complementos, "13-Complementos")
            page.wait_for_timeout(200)

            # 14. Fachadas vizinhas
            _fill_textlike(4, fachadas_vizinhos, "14-FachadasVizinhos")
            page.wait_for_timeout(200)

            # 15. Coordenadas
            _log_step("15-Coordenadas", "")
            if n_inputs >= 4:
                try:
                    inputs_text.nth(3).fill(coordenadas, timeout=8000)
                except Exception as e:
                    _log_step("15-Coordenadas", str(e), ok=False)
            page.wait_for_timeout(200)

            # 16. Upload de arquivos (foto + comprovantes). Primeiro salva no OneDrive, depois tenta no formulário
            paths = arquivos_paths if arquivos_paths else ([foto_path] if foto_path else [])
            paths = [p for p in paths if p and os.path.isfile(p)]
            ok_upload = False
            if paths:
                try:
                    ok_od, od_pasta_used, _ = _upload_inclusao_onedrive(dados, paths)
                    if ok_od:
                        logger.info(f"[Inclusão] Arquivos salvos no OneDrive: {od_pasta_used}")
                except Exception as e:
                    logger.warning(f"[Inclusão] OneDrive upload falhou (continuando): {e}")
                ok_upload = _upload_arquivos_viabilidade(page, paths)
                # Se o upload falhou, o modal do Google Picker pode ter ficado aberto e bloqueia Enviar
                _fechar_picker_modal(page)
                page.wait_for_timeout(500)

            # 17. Observações - textarea ou contenteditable (opcional)
            if observacoes:
                _fill_textlike(5, observacoes, "17-Observacoes")

            # Submit
            _log_step("SUBMIT", "Procurando botão Enviar...")
            submit = page.get_by_role('button', name='Enviar')
            if submit.count() == 0:
                submit = page.locator('span.NPEfkd:has-text("Enviar")').first
            if submit.count() == 0:
                submit = page.locator('span:has-text("Enviar")').first
            if submit.count() > 0:
                _log_step("SUBMIT", "Clicando Enviar...")
                _fechar_picker_modal(page)  # Garantir que modal não bloqueie
                page.wait_for_timeout(300)
                try:
                    submit.click(timeout=15000)
                except Exception as submit_err:
                    # Modal pode estar bloqueando; tentar fechar e force click
                    _fechar_picker_modal(page)
                    page.wait_for_timeout(500)
                    submit.click(force=True, timeout=10000)
                page.wait_for_timeout(5000)
                # Verificar confirmação - apenas frases específicas da página de sucesso
                # (evitar falso positivo: "registrada"/"sua resposta" podem aparecer em labels do form)
                confirm_sel = [
                    'text="Obrigado"', 'text="Respostas enviadas"',
                    'text=Your response has been recorded', 'text=Thank you',
                    '[data-params*="confirmationMessage"]'
                ]
                still_has_form = page.locator('span:has-text("Enviar")').count() > 0
                confirmed = (not still_has_form) and any(
                    page.locator(s).count() > 0 for s in confirm_sel
                )
                if confirmed:
                    _log_step("SUBMIT", "Confirmado (Obrigado/Respostas enviadas)")
                    browser.close()
                    msg = "✅ Solicitação de viabilidade enviada com sucesso!"
                    if od_pasta_used:
                        msg += f"\n\n📁 Arquivos salvos no OneDrive: {od_pasta_used}"
                    return True, msg
            else:
                _log_step("SUBMIT", "Botão Enviar não encontrado", ok=False)
            browser.close()
            # Formulário NÃO foi enviado - avisar o usuário
            if "accounts.google.com" in page.url:
                msg = "O formulário não foi preenchido: ainda na tela de login. Tente novamente ou clique em 'Agora não' se o Google oferecer login mais rápido."
            elif ok_upload is False and od_pasta_used:
                msg = "O formulário não foi enviado. O upload automático da foto falhou (o Google Forms pode bloquear em ambiente automatizado). "
            else:
                msg = "O formulário não foi enviado (campos ou botão não encontrados). "
            if od_pasta_used:
                msg += f"\n\n📁 Arquivos salvos no OneDrive: {od_pasta_used}\nVocê pode anexá-los manualmente no formulário."
            return False, msg

    except Exception as e:
        logger.exception(f"[Inclusão] Erro ao preencher formulário: {e}")
        err_text = str(e).split('\n')[0].strip()
        if len(err_text) > 150:
            err_text = err_text[:147] + "..."
        msg = f"Erro ao preencher formulário: {err_text}"
        if od_pasta_used:
            msg += f"\n\n📁 Arquivos salvos no OneDrive: {od_pasta_used}\nVocê pode anexá-los manualmente."
        return False, msg
