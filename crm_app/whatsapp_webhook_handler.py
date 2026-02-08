# crm_app/whatsapp_webhook_handler.py
"""
Handler para processar mensagens do WhatsApp e executar comandos:
- Fachada
- Viabilidade  
- Status
- Fatura
"""
import re
import os
import logging
import threading
from datetime import datetime
from django.utils import timezone

logger = logging.getLogger(__name__)

# Pendências etapa 6: aguardando confirmação do cliente ("sim") ou "bio ok" do vendedor
_pending_client_confirm = {}  # telefone_cliente_normalizado -> {event, vendedor_telefone, ...}
_pending_bio_ok = {}  # vendedor_telefone_normalizado -> {event, ...}
_pending_lock = threading.Lock()

# Automações PAP em andamento (agendamento - usuário seleciona dia/período via mensagem)
_automacoes_pap_ativas = {}  # sessao_id -> {automacao, dados, vendedor_id, bo_usuario_id, telefone}
_automacoes_lock = threading.Lock()


def _registrar_estatistica(telefone, comando):
    """
    Registra uma estatística de mensagem enviada pelo bot
    Tenta identificar o vendedor pelo telefone
    """
    try:
        from crm_app.models import EstatisticaBotWhatsApp
        from usuarios.models import Usuario
        
        # Tentar encontrar vendedor pelo telefone
        vendedor = None
        telefone_limpo = formatar_telefone(telefone)
        
        # Buscar vendedor pelo tel_whatsapp (formato pode variar)
        # Tentar com e sem prefixo 55
        telefones_variantes = [telefone_limpo]
        if not telefone_limpo.startswith('55') and len(telefone_limpo) >= 10:
            telefones_variantes.append('55' + telefone_limpo)
        if telefone_limpo.startswith('55'):
            telefones_variantes.append(telefone_limpo[2:])
        
        for tel_var in telefones_variantes:
            try:
                vendedor = Usuario.objects.filter(tel_whatsapp__icontains=tel_var).first()
                if vendedor:
                    break
            except:
                pass
        
        # Criar registro de estatística
        EstatisticaBotWhatsApp.objects.create(
            telefone=telefone,
            vendedor=vendedor,
            comando=comando
        )
        
        if vendedor:
            logger.debug(f"[Estatística] Registrado {comando} para vendedor {vendedor.username}")
        else:
            logger.debug(f"[Estatística] Registrado {comando} para telefone {telefone} (vendedor não identificado)")
            
    except Exception as e:
        logger.error(f"[Estatística] Erro ao registrar estatística: {e}", exc_info=True)


def formatar_telefone(telefone):
    """Normaliza telefone removendo caracteres não numéricos"""
    if not telefone:
        return ""
    telefone_limpo = "".join(filter(str.isdigit, str(telefone)))
    # Remove prefixo 55 se tiver
    if telefone_limpo.startswith('55') and len(telefone_limpo) > 12:
        telefone_limpo = telefone_limpo[2:]
    return telefone_limpo


def _chave_telefone(telefone):
    """Chave única para dicionários de pendência (dígitos normalizados)."""
    return formatar_telefone(telefone) or ""


def _chaves_telefone_variantes(telefone):
    """Retorna variantes da chave para matching robusto (ex: 31986791000 e 5531986791000)."""
    base = formatar_telefone(telefone) or ""
    if not base:
        return []
    chaves = [base]
    if base.startswith('55') and len(base) > 11:
        chaves.append(base[2:])  # sem 55
    elif len(base) >= 10 and not base.startswith('55'):
        chaves.append('55' + base)  # com 55
    return chaves


def limpar_texto_cep_cpf(texto):
    """Remove pontos, traços e espaços (para CEP e CPF)"""
    if not texto:
        return ""
    return re.sub(r'[\s.\-/]', '', str(texto))


def _formatar_status_portugues(status):
    """Traduz status para português"""
    status_upper = str(status).upper()
    traducoes = {
        'OVERDUE': 'Atrasado',
        'PENDING': 'Pendente',
        'EM ABERTO': 'Em Aberto',
        'ABERTO': 'Em Aberto',
        'OPEN': 'Em Aberto',
        'VENCIDA': 'Vencida',
        'VENCIDO': 'Vencido',
        'LATE': 'Atrasado',
        'PAID': 'Pago',
        'PAGO': 'Pago',
    }
    return traducoes.get(status_upper, status)


def _formatar_data_brasileira(data_str):
    """Converte data de formato YYYYMMDD ou YYYY-MM-DD para dd/mm/aaaa"""
    if not data_str:
        return None
    
    try:
        # Formato YYYYMMDD (ex: 20251230)
        if isinstance(data_str, str) and len(data_str) == 8 and data_str.isdigit():
            from datetime import datetime
            data = datetime.strptime(data_str, '%Y%m%d')
            return data.strftime('%d/%m/%Y')
        
        # Formato YYYY-MM-DD (ex: 2025-12-30)
        elif isinstance(data_str, str) and '-' in data_str:
            from datetime import datetime
            data = datetime.strptime(data_str, '%Y-%m-%d')
            return data.strftime('%d/%m/%Y')
        
        # Já está formatado ou é objeto date
        elif hasattr(data_str, 'strftime'):
            return data_str.strftime('%d/%m/%Y')
        
        # Tentar parsear outros formatos
        else:
            from datetime import datetime
            # Tenta vários formatos comuns
            for fmt in ['%Y-%m-%d', '%Y%m%d', '%d/%m/%Y', '%d-%m-%Y']:
                try:
                    data = datetime.strptime(str(data_str), fmt)
                    return data.strftime('%d/%m/%Y')
                except:
                    continue
            
            return str(data_str)  # Retorna original se não conseguir converter
    except Exception as e:
        logger.warning(f"[Webhook] Erro ao formatar data {data_str}: {e}")
        return str(data_str)


def _enviar_pdf_whatsapp(whatsapp_service, telefone, invoice, caption=None):
    """
    Envia o PDF da fatura via WhatsApp se estiver disponível (localmente ou via URL).
    Retorna True se enviou com sucesso, False caso contrário.
    
    Args:
        whatsapp_service: Instância do WhatsAppService
        telefone: Número do destinatário
        invoice: Dicionário com informações da fatura (incluindo pdf_path, pdf_url, etc)
        caption: Mensagem de legenda para o PDF (opcional)
    """
    pdf_path = invoice.get('pdf_path', '')
    pdf_url = invoice.get('pdf_url', '') or invoice.get('pdf_onedrive_url', '')
    pdf_filename = invoice.get('pdf_filename', 'fatura.pdf')
    
    logger.info(f"[Webhook] 📄 _enviar_pdf_whatsapp chamado")
    logger.info(f"[Webhook] PDF path: {pdf_path}")
    logger.info(f"[Webhook] PDF URL: {pdf_url}")
    logger.info(f"[Webhook] PDF filename: {pdf_filename}")
    logger.info(f"[Webhook] Telefone: {telefone}")
    print(f"[Webhook] Iniciando _enviar_pdf_whatsapp: path={pdf_path}, url={pdf_url}, filename={pdf_filename}")
    
    # Prioridade 1: Tentar enviar via URL (mais rápido e eficiente)
    if pdf_url:
        logger.info(f"[Webhook] 📎 Tentando enviar PDF via URL: {pdf_url}")
        print(f"[Webhook] Enviando PDF via URL: {pdf_url}")
        try:
            sucesso = whatsapp_service.enviar_pdf_url(telefone, pdf_url, pdf_filename, caption=caption)
            if sucesso:
                logger.info(f"[Webhook] ✅ PDF enviado com sucesso via URL: {pdf_filename}")
                print(f"[Webhook] ✅ PDF enviado com sucesso via URL")
                return True
            else:
                logger.warning(f"[Webhook] ⚠️ Falha ao enviar PDF via URL, tentando método local...")
                print(f"[Webhook] ⚠️ Falha via URL, tentando local...")
        except Exception as e:
            logger.error(f"[Webhook] ❌ Erro ao enviar PDF via URL: {type(e).__name__}: {e}")
            print(f"[Webhook] ❌ Erro via URL: {e}")
            # Continuar para tentar método local
    
    # Prioridade 2: Tentar enviar via arquivo local (base64)
    if not pdf_path:
        logger.warning(f"[Webhook] ⚠️ PDF path vazio e URL não disponível, não é possível enviar")
        print(f"[Webhook] ⚠️ PDF path vazio e URL não disponível")
        return False
    
    try:
        import base64
        
        # Verificar se o arquivo existe
        if not os.path.exists(pdf_path):
            logger.warning(f"[Webhook] ❌ PDF não encontrado no caminho: {pdf_path}")
            print(f"[Webhook] ❌ Arquivo não existe: {pdf_path}")
            return False
        
        logger.info(f"[Webhook] ✅ Arquivo PDF encontrado, lendo...")
        print(f"[Webhook] Arquivo encontrado, tamanho: {os.path.getsize(pdf_path)} bytes")
        
        # Ler arquivo e converter para base64
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
            pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        logger.info(f"[Webhook] PDF lido e convertido para base64")
        logger.info(f"[Webhook] Tamanho original: {len(pdf_bytes)} bytes")
        logger.info(f"[Webhook] Tamanho base64: {len(pdf_base64)} chars")
        print(f"[Webhook] PDF convertido: {len(pdf_bytes)} bytes -> {len(pdf_base64)} chars base64")
        
        # Enviar via WhatsApp
        logger.info(f"[Webhook] Enviando PDF via WhatsApp (base64): {pdf_filename} ({len(pdf_bytes)} bytes)")
        if caption:
            logger.info(f"[Webhook] Com caption: {caption[:100]}...")
        print(f"[Webhook] Chamando enviar_pdf_b64...")
        sucesso = whatsapp_service.enviar_pdf_b64(telefone, pdf_base64, pdf_filename, caption=caption)
        
        if sucesso:
            logger.info(f"[Webhook] ✅ PDF enviado com sucesso via WhatsApp: {pdf_filename}")
            print(f"[Webhook] ✅ PDF enviado com sucesso")
        else:
            logger.warning(f"[Webhook] ⚠️ Falha ao enviar PDF via WhatsApp: {pdf_filename}")
            print(f"[Webhook] ⚠️ Falha ao enviar PDF")
        
        return sucesso
    except FileNotFoundError as fnfe:
        logger.error(f"[Webhook] ❌ Arquivo não encontrado: {fnfe}")
        print(f"[Webhook] ❌ FILE NOT FOUND: {fnfe}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        logger.error(f"[Webhook] ❌ Erro ao enviar PDF via WhatsApp: {type(e).__name__}: {e}")
        print(f"[Webhook] ❌ EXCEÇÃO: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def _formatar_detalhes_fatura(invoice, cpf, incluir_pdf=False):
    """
    Formata os detalhes de uma fatura para envio via WhatsApp.
    """
    resposta_parts = [f"✅ *FATURA ENCONTRADA*\n"]
    
    # Valor
    valor = invoice.get('amount', 0)
    if valor:
        try:
            valor_formatado = float(valor) if valor else 0
            resposta_parts.append(f"💰 *Valor:* R$ {valor_formatado:.2f}")
        except:
            resposta_parts.append(f"💰 *Valor:* {valor}")
    
    # Data de vencimento (formatada em dd/mm/aaaa)
    data_vencimento = invoice.get('due_date_raw') or invoice.get('data_vencimento')
    if data_vencimento:
        data_formatada = _formatar_data_brasileira(data_vencimento)
        resposta_parts.append(f"📅 *Vencimento:* {data_formatada}")
    
    # Status (traduzido para português)
    status = invoice.get('status', '')
    if status:
        status_pt = _formatar_status_portugues(status)
        emoji_status = "🔴" if status.upper() in ['ATRASADO', 'ATRASADA', 'VENCIDA', 'VENCIDO', 'OVERDUE', 'LATE'] else "🟡"
        resposta_parts.append(f"{emoji_status} *Status:* {status_pt}")
    
    # Mês de referência
    mes_ref = invoice.get('reference_month', '')
    if mes_ref:
        resposta_parts.append(f"📆 *Referência:* {mes_ref}")
    
    # Código PIX
    codigo_pix = invoice.get('pix', '') or invoice.get('codigo_pix', '')
    if codigo_pix:
        # Remover backticks do início e fim do código PIX se existirem
        codigo_pix_limpo = codigo_pix.strip('`').strip()
        resposta_parts.append(f"\n💳 *PIX:*\n{codigo_pix_limpo}")
    
    # Código de barras
    codigo_barras = invoice.get('barcode', '') or invoice.get('codigo_barras', '')
    if codigo_barras:
        # Remover backticks do início e fim do código de barras se existirem
        codigo_barras_limpo = codigo_barras.strip('`').strip()
        resposta_parts.append(f"\n📄 *Código de Barras:*\n{codigo_barras_limpo}")
    
    # PDF (não incluir link na mensagem - será enviado como anexo)
    # O PDF será enviado separadamente como anexo, então não precisamos incluir o link na mensagem
    # if incluir_pdf:
    #     # Removido: não incluir link do PDF na mensagem
    #     pass
    
    return "\n".join(resposta_parts)


# =============================================================================
# FUNÇÕES PARA FLUXO DE VENDA VIA WHATSAPP
# =============================================================================

def _iniciar_fluxo_venda(telefone: str, sessao) -> str:
    """
    Inicia o fluxo de venda via WhatsApp.
    Verifica se o usuário está autorizado (qualquer perfil com autorização).
    
    Args:
        telefone: Número do telefone do usuário
        sessao: Sessão do WhatsApp
        
    Returns:
        Mensagem de resposta
    """
    from usuarios.models import Usuario
    from django.db.models import Q
    
    # Limpar telefone - remover tudo que não for número
    telefone_limpo = re.sub(r'\D', '', telefone)
    logger.info(f"[VENDA] Buscando usuário para telefone: {telefone} -> limpo: {telefone_limpo}")
    
    usuario = None
    
    # Criar variantes do telefone para busca
    telefones_variantes = set()
    telefones_variantes.add(telefone_limpo)
    
    # Sem DDI (55)
    if telefone_limpo.startswith('55') and len(telefone_limpo) > 11:
        telefones_variantes.add(telefone_limpo[2:])  # Remove 55
    
    # Com DDI (55)
    if not telefone_limpo.startswith('55') and len(telefone_limpo) >= 10:
        telefones_variantes.add('55' + telefone_limpo)
    
    # Últimos 8 e 9 dígitos (número local)
    if len(telefone_limpo) >= 8:
        telefones_variantes.add(telefone_limpo[-8:])
    if len(telefone_limpo) >= 9:
        telefones_variantes.add(telefone_limpo[-9:])
    
    logger.info(f"[VENDA] Variantes de telefone para busca: {telefones_variantes}")
    
    # Buscar usuário ativo com qualquer uma das variantes
    for tel_var in telefones_variantes:
        # Buscar onde o campo tel_whatsapp contenha os dígitos
        usuarios_encontrados = Usuario.objects.filter(
            is_active=True
        ).extra(
            where=["REPLACE(REPLACE(REPLACE(REPLACE(tel_whatsapp, '-', ''), ' ', ''), '(', ''), ')', '') LIKE %s"],
            params=[f'%{tel_var}%']
        )
        
        if usuarios_encontrados.exists():
            usuario = usuarios_encontrados.first()
            logger.info(f"[VENDA] Usuário encontrado: {usuario.username} (ID: {usuario.id})")
            break
    
    # Fallback: busca simples por contains
    if not usuario:
        for tel_var in telefones_variantes:
            usuario = Usuario.objects.filter(
                tel_whatsapp__icontains=tel_var, 
                is_active=True
            ).first()
            if usuario:
                logger.info(f"[VENDA] Usuário encontrado (fallback): {usuario.username}")
                break
    
    if not usuario:
        logger.warning(f"[VENDA] Nenhum usuário encontrado para telefone: {telefone_limpo}")
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Seu número não está cadastrado no sistema.\n"
            "Verifique se o campo WhatsApp está preenchido no seu cadastro."
        )
    
    # Verificar se está autorizado para venda sem auditoria
    if not getattr(usuario, 'autorizar_venda_sem_auditoria', False):
        logger.warning(f"[VENDA] Usuário {usuario.username} não está autorizado (autorizar_venda_sem_auditoria=False)")
        return (
            "❌ *ACESSO NEGADO*\n\n"
            "Você não está autorizado a realizar vendas pelo WhatsApp.\n"
            "Solicite que marquem a opção 'Autorizar venda sem auditoria' no seu cadastro."
        )
    
    # Vendedor só precisa de matrícula (para ser selecionado no PAP como vendedor da venda).
    # O login no PAP usa credenciais de perfil BackOffice (pool).
    if not usuario.matricula_pap:
        logger.warning(f"[VENDA] Usuário {usuario.username} sem matrícula PAP")
        return (
            "⚠️ *CONFIGURAÇÃO INCOMPLETA*\n\n"
            "Sua matrícula PAP não está configurada.\n"
            "Preencha o campo 'Matrícula PAP' no seu cadastro para poder ser identificado como vendedor."
        )
    
    # Iniciar fluxo de venda
    sessao.etapa = 'venda_confirmar_matricula'
    sessao.dados_temp = {
        'vendedor_id': usuario.id,
        'vendedor_nome': usuario.get_full_name() or usuario.username,
        'matricula_pap': usuario.matricula_pap,
    }
    sessao.save()
    
    logger.info(f"[VENDA] Iniciando fluxo para usuário {usuario.username} (perfil: {usuario.perfil})")
    
    return (
        f"🛒 *NOVA VENDA - PAP NIO*\n\n"
        f"Olá, {usuario.first_name or usuario.username}!\n\n"
        f"Sua matrícula PAP (vendedor): *{usuario.matricula_pap}*\n\n"
        f"O acesso ao PAP será feito com credenciais de backoffice.\n\n"
        f"Confirma que deseja iniciar uma nova venda?\n\n"
        f"Digite *SIM* para continuar ou *CANCELAR* para sair."
    )


def _processar_correcao_credito(telefone: str, sessao, dados: dict, mensagem_limpa: str, campo: str) -> str:
    """Processa correção de celular/email/cpf quando análise de crédito falha (como no terminal)."""
    from crm_app.whatsapp_service import WhatsAppService
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Cancelado. Digite *VENDER* para iniciar novamente."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    automacao = ctx['automacao']
    celular_sec = dados.get('celular_sec', '') or None
    
    if campo == 'celular':
        celular_limpo = limpar_texto_cep_cpf(mensagem_limpa)
        if not celular_limpo or len(celular_limpo) < 10:
            return "❌ Celular inválido. Digite o celular com DDD (10 ou 11 dígitos):"
        dados['celular'] = celular_limpo
        celular, email = celular_limpo, dados.get('email', '')
    elif campo == 'email':
        email_raw = mensagem_limpa
        if '@' not in email_raw or '.' not in email_raw:
            return "❌ E-mail inválido. Digite um e-mail válido:"
        dados['email'] = email_raw.lower()
        celular, email = dados.get('celular', ''), dados['email']
    else:
        cpf_limpo = limpar_texto_cep_cpf(mensagem_limpa)
        if not cpf_limpo or len(cpf_limpo) != 11:
            return "❌ CPF inválido. Digite o CPF completo (11 dígitos):"
        dados['cpf_cliente'] = cpf_limpo
        sessao.dados_temp = dados
        sessao.save()
        sucesso, msg, _ = automacao.etapa3_cadastro_cliente(cpf_limpo)
        if not sucesso:
            return f"❌ Cadastro: {msg}\n\nDigite outro CPF ou *CANCELAR*."
        celular, email = dados.get('celular', ''), dados.get('email', '')
        sucesso, msg, _ = automacao.etapa4_contato(celular, email, celular_secundario=celular_sec)
        if not sucesso:
            if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                sessao.etapa = 'venda_corrigir_celular'
                sessao.save()
                return "⚠️ O número excede repetições ou é inválido. Digite outro celular com DDD:"
            if msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                sessao.etapa = 'venda_corrigir_email'
                sessao.save()
                return "⚠️ E-mail já usado ou inválido. Digite outro e-mail:"
            if msg == "CREDITO_NEGADO":
                return "❌ Crédito negado para este CPF.\n\nDigite outro CPF para tentar, ou *CANCELAR*:"
            return f"❌ {msg}\n\nDigite *CANCELAR* para sair."
        threading.Thread(target=_continuar_apos_correcao_credito, args=(telefone, sessao.id, dict(dados)), daemon=True).start()
        return "✅ Crédito aprovado!\n\n⏳ Continuando o processamento... Aguarde."
    
    sucesso, msg, _ = automacao.etapa4_contato(celular, email, celular_secundario=celular_sec)
    if not sucesso:
        if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
            return "⚠️ O número excede repetições ou é inválido. Digite outro celular com DDD:"
        if msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
            return "⚠️ E-mail já usado ou inválido. Digite outro e-mail:"
        if msg == "CREDITO_NEGADO":
            sessao.etapa = 'venda_corrigir_cpf'
            sessao.dados_temp = dados
            sessao.save()
            return "❌ Crédito negado para este CPF.\n\nDigite outro CPF para tentar, ou *CANCELAR*:"
        return f"❌ {msg}\n\nDigite *CANCELAR* para sair."
    
    sessao.dados_temp = dados
    sessao.save()
    threading.Thread(target=_continuar_apos_correcao_credito, args=(telefone, sessao.id, dict(dados)), daemon=True).start()
    return "✅ Crédito aprovado!\n\n⏳ Continuando o processamento... Aguarde."


def _continuar_apos_correcao_credito(telefone: str, sessao_id: int, dados: dict):
    """Continua o fluxo após correção de crédito (etapa5 em diante)."""
    import django
    django.setup()
    from crm_app.models import SessaoWhatsapp
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.pool_bo_pap import liberar_bo
    
    whatsapp = WhatsAppService()
    def enviar(m):
        try:
            whatsapp.enviar_mensagem_texto(telefone, m)
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao enviar: {e}")
    
    def resetar():
        try:
            s = SessaoWhatsapp.objects.get(id=sessao_id)
            s.etapa = 'inicial'
            s.dados_temp = {}
            s.save()
        except Exception:
            pass
        liberar_bo(dados.get('bo_usuario_id'), telefone)
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao_id)
    if not ctx:
        return
    automacao = ctx['automacao']
    vendedor_matricula = dados.get('matricula_pap') or ctx.get('vendedor_matricula')
    
    try:
        sucesso, msg = automacao.etapa5_selecionar_forma_pagamento(dados.get('forma_pagamento', 'boleto'))
        if not sucesso:
            automacao._fechar_sessao()
            with _automacoes_lock:
                _automacoes_pap_ativas.pop(sessao_id, None)
            resetar()
            enviar(f"❌ Erro na forma de pagamento: {msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        if dados.get('forma_pagamento') == 'debito':
            sucesso, msg = automacao.etapa5_preencher_debito(
                dados.get('banco', ''), dados.get('agencia', ''), dados.get('conta', ''), dados.get('digito', ''))
            if not sucesso:
                automacao._fechar_sessao()
                with _automacoes_lock:
                    _automacoes_pap_ativas.pop(sessao_id, None)
                resetar()
                enviar(f"❌ Erro no débito: {msg}\n\nDigite *VENDER* para tentar novamente.")
                return
        for step_name, step_fn in [
            ('plano', lambda: automacao.etapa5_selecionar_plano(dados.get('plano', '500mega'))),
            ('fixo', lambda: automacao.etapa5_selecionar_fixo(dados.get('tem_fixo', False))),
            ('streaming', lambda: automacao.etapa5_selecionar_streaming(
                bool(dados.get('tem_streaming', False)), dados.get('streaming_opcoes') or '', dados.get('plano', '500mega'))),
            ('avançar', lambda: automacao.etapa5_clicar_avancar()),
        ]:
            sucesso, msg = step_fn()
            if not sucesso:
                automacao._fechar_sessao()
                with _automacoes_lock:
                    _automacoes_pap_ativas.pop(sessao_id, None)
                resetar()
                enviar(f"❌ Erro: {msg}\n\nDigite *VENDER* para tentar novamente.")
                return
        _executar_venda_pap_etapa6_em_diante(
            telefone=telefone, sessao_id=sessao_id, dados=dados, automacao=automacao,
            vendedor_matricula=vendedor_matricula, vendedor_id=ctx.get('vendedor_id'),
            vendedor_nome=ctx.get('vendedor_nome'), bo_usuario_id=ctx.get('bo_usuario_id'),
            enviar_resultado=enviar, resetar_sessao_e_liberar_bo=resetar
        )
    except Exception as e:
        logger.exception(f"[VENDA PAP] Erro ao continuar após correção: {e}")
        try:
            automacao._fechar_sessao()
        except Exception:
            pass
        with _automacoes_lock:
            _automacoes_pap_ativas.pop(sessao_id, None)
        resetar()
        enviar(f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente.")


def _processar_viabilidade_selecionar_endereco(telefone: str, sessao, dados: dict, mensagem_limpa: str, mensagem: str) -> str:
    """Processa seleção de endereço quando há múltiplos (como no terminal etapa 24)."""
    from crm_app.whatsapp_service import WhatsAppService
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Cancelado. Digite *VENDER* para iniciar novamente."
    
    if not mensagem.isdigit():
        lista = dados.get('viabilidade_lista_enderecos', [])
        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
        return f"❌ Digite o número do endereço (ex: 1, 2)\n\n{linha}"
    
    idx = int(mensagem)
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    automacao = ctx['automacao']
    cep, numero, ref = dados.get('cep', ''), dados.get('numero', ''), dados.get('referencia', '')
    sucesso, msg = automacao.etapa2_selecionar_endereco_instalacao(idx)
    if not sucesso:
        return f"❌ {msg}\n\nDigite outro número ou *CANCELAR*."
    
    sucesso2, msg2, extra2 = automacao.etapa2_preencher_referencia_e_continuar(cep, numero, ref)
    if not sucesso2:
        if extra2 == "POSSE_ENCONTRADA":
            sessao.etapa = 'venda_posse_consultar_outro'
            sessao.save()
            return msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."
        if extra2 == "INDISPONIVEL_TECNICO":
            sessao.etapa = 'venda_indisponivel_voltar'
            sessao.save()
            return msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return f"❌ {msg2}\n\nDigite *VENDER* para tentar novamente."
    
    if isinstance(extra2, dict) and extra2.get('_codigo') == 'COMPLEMENTOS':
        with _automacoes_lock:
            _automacoes_pap_ativas[sessao.id]['phase'] = 'viabilidade_complemento'
        lista = extra2.get('lista', [])
        sessao.etapa = 'venda_selecionar_complemento'
        sessao.dados_temp = {**dados, 'viabilidade_lista_complementos': lista}
        sessao.save()
        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
        return f"📋 *Complementos encontrados:*\n\n{linha}\n\nDigite *0* ou *SEM COMPLEMENTO* se não tiver, ou o *número* do complemento (ex: 1, 2, 3):"
    
    with _automacoes_lock:
        _automacoes_pap_ativas.pop(sessao.id, None)
    automacao._fechar_sessao()
    from crm_app.pool_bo_pap import liberar_bo
    liberar_bo(dados.get('bo_usuario_id'), telefone)
    sessao.etapa = 'venda_cpf'
    sessao.dados_temp = dados
    sessao.save()
    protocolo = automacao.dados_pedido.get('protocolo', '')
    msg_ok = "✅ Endereço disponível!"
    if protocolo:
        msg_ok += f"\n📋 Protocolo: {protocolo}"
    return msg_ok + "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:"


def _processar_viabilidade_selecionar_complemento(telefone: str, sessao, dados: dict, mensagem_limpa: str, mensagem: str) -> str:
    """Processa seleção de complemento (como no terminal etapa 25)."""
    from crm_app.pool_bo_pap import liberar_bo
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Cancelado. Digite *VENDER* para iniciar novamente."
    
    escolha = mensagem.strip().upper()
    if escolha in ("0", "SEM", "SEM COMPLEMENTO", "NAO", "NÃO", "N"):
        sucesso, msg = None, None
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if ctx:
            sucesso, msg = ctx['automacao'].etapa2_selecionar_sem_complemento()
    elif escolha.isdigit():
        idx = int(escolha)
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if ctx:
            sucesso, msg = ctx['automacao'].etapa2_selecionar_complemento(idx)
        else:
            sucesso, msg = False, "Sessão expirada"
    else:
        lista = dados.get('viabilidade_lista_complementos', [])
        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
        return f"❌ Digite *0* ou *SEM COMPLEMENTO*, ou o número do complemento (ex: 1)\n\n{linha}"
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    automacao = ctx['automacao']
    if not sucesso:
        return f"❌ {msg}\n\nDigite *0* ou *SEM COMPLEMENTO*, ou o número do complemento (ex: 1):"
    
    cep, numero = dados.get('cep', ''), dados.get('numero', '')
    sucesso2, msg2, extra2 = automacao.etapa2_clicar_avancar_apos_complemento(cep, numero)
    if not sucesso2:
        if extra2 == "POSSE_ENCONTRADA":
            sessao.etapa = 'venda_posse_consultar_outro'
            sessao.save()
            return msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."
        if extra2 == "INDISPONIVEL_TECNICO":
            sessao.etapa = 'venda_indisponivel_voltar'
            sessao.save()
            return msg2 + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair."
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return f"❌ {msg2}\n\nDigite *VENDER* para tentar novamente."
    
    with _automacoes_lock:
        _automacoes_pap_ativas.pop(sessao.id, None)
    automacao._fechar_sessao()
    liberar_bo(dados.get('bo_usuario_id'), telefone)
    sessao.etapa = 'venda_cpf'
    sessao.dados_temp = dados
    sessao.save()
    protocolo = automacao.dados_pedido.get('protocolo', '')
    msg_ok = "✅ Endereço disponível!"
    if protocolo:
        msg_ok += f"\n📋 Protocolo: {protocolo}"
    return msg_ok + "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:"


def _processar_viabilidade_posse(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa posse encontrada - outro CEP ou CONCLUIR (como no terminal etapa 30)."""
    from crm_app.pool_bo_pap import liberar_bo
    
    if mensagem_limpa == 'CONCLUIR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão encerrada. Digite *VENDER* para iniciar novamente."
    
    cep_novo = limpar_texto_cep_cpf(mensagem_limpa)
    if len(cep_novo) < 8:
        return "❌ CEP inválido. Digite 8 dígitos para consultar outro endereço ou *CONCLUIR* para sair."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    ok, _ = ctx['automacao'].etapa2_modal_posse_clicar_consultar_outro()
    if not ok:
        return f"⚠️ Erro ao voltar à consulta.\n\nDigite outro CEP ou *CONCLUIR*."
    
    dados['cep'] = cep_novo
    sessao.dados_temp = dados
    sessao.etapa = 'venda_numero'
    sessao.save()
    return f"✅ CEP: *{cep_novo}*\n\nDigite o *número* do endereço:\n(ou digite *SN* se não houver número)"


def _processar_viabilidade_indisponivel(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa indisponível técnico - outro CEP ou CONCLUIR (como no terminal etapa 31)."""
    if mensagem_limpa == 'CONCLUIR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão encerrada. Digite *VENDER* para iniciar novamente."
    
    cep_novo = limpar_texto_cep_cpf(mensagem_limpa)
    if len(cep_novo) < 8:
        return "❌ CEP inválido. Digite 8 dígitos para consultar outro endereço ou *CONCLUIR* para sair."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    ok, _ = ctx['automacao'].etapa2_modal_indisponivel_clicar_voltar()
    if not ok:
        return f"⚠️ Erro ao voltar à consulta.\n\nDigite outro CEP ou *CONCLUIR*."
    
    dados['cep'] = cep_novo
    sessao.dados_temp = dados
    sessao.etapa = 'venda_numero'
    sessao.save()
    return f"✅ CEP: *{cep_novo}*\n\nDigite o *número* do endereço:\n(ou digite *SN* se não houver número)"


def _processar_agendamento_dia(telefone: str, sessao, dados: dict, mensagem_limpa: str, mensagem: str) -> str:
    """Processa seleção do dia no agendamento."""
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.pool_bo_pap import liberar_bo
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if not mensagem.isdigit():
        datas = dados.get('agendamento_datas', [])
        return f"❌ Digite o número do dia (ex: 10)\n\nDatas disponíveis: {', '.join(str(d) for d in datas)}\n\nOu *CANCELAR* para sair."
    
    dia = int(mensagem)
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    automacao = ctx['automacao']
    sucesso, msg, periodos = automacao.etapa7_selecionar_data_e_obter_periodos(dia)
    if not sucesso:
        return f"❌ {msg}\n\nDigite outro dia ou *CANCELAR*."
    
    dados['agendamento_dia'] = dia
    dados['agendamento_periodos'] = periodos
    sessao.dados_temp = dados
    sessao.etapa = 'venda_agendamento_confirmar_data'
    sessao.save()
    
    if not periodos:
        return "⚠️ Nenhum período disponível para este dia.\n\nDigite outro dia ou *CANCELAR*."
    
    return f"✅ Dia *{dia}* selecionado.\n\nDeseja *CONFIRMAR* a data ou *ALTERAR*?"


def _processar_agendamento_confirmar_data(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa CONFIRMAR ou ALTERAR data (como no terminal etapa 121)."""
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if mensagem_limpa == 'ALTERAR':
        sessao.etapa = 'venda_agendamento_dia'
        sessao.save()
        datas = dados.get('agendamento_datas', [])
        return f"📅 Datas disponíveis: {', '.join(str(d) for d in datas)}\n\nDigite o *número do dia* (ex: 10) ou *CANCELAR*:"
    
    if mensagem_limpa in ('CONFIRMAR', 'SIM', 'S'):
        periodos = dados.get('agendamento_periodos', [])
        sessao.etapa = 'venda_agendamento_periodo'
        sessao.save()
        linha = "\n".join(f"  {p['idx']} - {p['label']}" for p in periodos)
        return f"✅ Data confirmada!\n\n*Períodos disponíveis:*\n{linha}\n\nDigite o *número do período* (ex: 1) ou *CANCELAR*:"
    
    return "Digite *CONFIRMAR* para a data ou *ALTERAR* para escolher outra."


def _processar_agendamento_periodo(telefone: str, sessao, dados: dict, mensagem_limpa: str, mensagem: str) -> str:
    """Processa seleção do período no agendamento."""
    from crm_app.whatsapp_service import WhatsAppService
    
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if not mensagem.isdigit():
        periodos = dados.get('agendamento_periodos', [])
        linha = "\n".join(f"  {p['idx']} - {p['label']}" for p in periodos)
        return f"❌ Digite o número do período\n\n{linha}\n\nOu *CANCELAR* para sair."
    
    idx = int(mensagem)
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    automacao = ctx['automacao']
    sucesso, msg = automacao.etapa7_selecionar_periodo(idx)
    if not sucesso:
        return f"❌ {msg}\n\nDigite outro período ou *CANCELAR*."
    
    periodos = dados.get('agendamento_periodos', [])
    label = periodos[idx - 1]['label'] if idx <= len(periodos) else f"Período {idx}"
    dados['agendamento_turno_label'] = label
    sessao.dados_temp = dados
    sessao.etapa = 'venda_agendamento_confirmar_turno'
    sessao.save()
    
    return f"✅ Turno *{label}* selecionado.\n\nDeseja *CONFIRMAR* o turno ou *ALTERAR*?"


def _processar_agendamento_confirmar_turno(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa CONFIRMAR ou ALTERAR turno (como no terminal etapa 131)."""
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if mensagem_limpa == 'ALTERAR':
        periodos = dados.get('agendamento_periodos', [])
        linha = "\n".join(f"  {p['idx']} - {p['label']}" for p in periodos)
        return f"*Períodos disponíveis:*\n{linha}\n\nDigite o *número do período* (ex: 1) ou *CANCELAR*:"
    
    if mensagem_limpa in ('CONFIRMAR', 'SIM', 'S'):
        dia = dados.get('agendamento_dia', '?')
        label = dados.get('agendamento_turno_label', '?')
        sessao.etapa = 'venda_agendamento_sim_agendar'
        sessao.save()
        return f"✅ Turno confirmado!\n\nPodemos agendar para o dia *{dia}* e turno *{label}*?\n\nDigite *SIM* para confirmar e agendar, ou *CANCELAR* para sair."
    
    return "Digite *CONFIRMAR* para o turno ou *ALTERAR* para escolher outro."


def _processar_agendamento_sim_agendar(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa SIM para agendar - clica em Agendar (como no terminal etapa 14)."""
    if mensagem_limpa == 'CANCELAR':
        _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Agendamento cancelado. Digite *VENDER* para iniciar novamente."
    
    if mensagem_limpa not in ('SIM', 'S'):
        dia = dados.get('agendamento_dia', '?')
        label = dados.get('agendamento_turno_label', '?')
        return f"Digite *SIM* para agendar (dia {dia}, turno {label}) ou *CANCELAR* para sair."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.get(sessao.id)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    automacao = ctx['automacao']
    sucesso, msg = automacao.etapa7_clicar_agendar()
    if not sucesso:
        return f"❌ {msg}\n\nDigite *SIM* para tentar novamente ou *CANCELAR*."
    
    sessao.etapa = 'venda_agendamento_final'
    sessao.save()
    
    dia = dados.get('agendamento_dia', '?')
    label = dados.get('agendamento_turno_label', '?')
    return f"📅 *Agendado para* dia *{dia}* e turno *{label}*\n\nDigite *SIM* ou *CONFIRMAR* para concluir (clicar Continuar) ou *ALTERAR* para escolher outra data/turno."


def _processar_agendamento_final(telefone: str, sessao, dados: dict, mensagem_limpa: str) -> str:
    """Processa confirmação final - clica em Continuar no modal (como no terminal etapa 15)."""
    from crm_app.whatsapp_service import WhatsAppService
    from usuarios.models import Usuario
    from crm_app.cadastro_venda_pap import cadastrar_venda_pap_no_crm
    
    if mensagem_limpa == 'CANCELAR':
        with _automacoes_lock:
            ctx = _automacoes_pap_ativas.get(sessao.id)
        if ctx:
            try:
                ctx['automacao'].etapa7_modal_fechar()
            except Exception:
                pass
            _encerrar_automacao_pap(sessao.id, dados.get('bo_usuario_id'), telefone)
        sessao.etapa = 'venda_agendamento_dia'
        sessao.dados_temp = {**dados, 'agendamento_datas': dados.get('agendamento_datas', [])}
        sessao.save()
        return f"📅 Para escolher outra data:\n\nDatas disponíveis: {', '.join(str(d) for d in dados.get('agendamento_datas', []))}\n\nDigite o número do dia ou *CANCELAR* para sair."
    
    if mensagem_limpa not in ('SIM', 'S', 'CONFIRMAR'):
        return "Digite *SIM* ou *CONFIRMAR* para concluir, ou *CANCELAR* para escolher outra data."
    
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.pop(sessao.id, None)
    if not ctx:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    from crm_app.pool_bo_pap import liberar_bo
    automacao = ctx['automacao']
    
    try:
        sucesso, msg, numero_os = automacao.etapa7_modal_clicar_continuar()
        automacao._fechar_sessao()
    except Exception as e:
        automacao._fechar_sessao()
        liberar_bo(ctx['bo_usuario_id'], telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return f"❌ Erro: {e}\n\nDigite *VENDER* para iniciar novamente."
    
    liberar_bo(ctx['bo_usuario_id'], telefone)
    sessao.etapa = 'inicial'
    sessao.dados_temp = {}
    sessao.save()
    
    if not sucesso:
        return f"❌ {msg}\n\nDigite *VENDER* para iniciar novamente."
    
    try:
        vendedor = Usuario.objects.get(id=ctx['vendedor_id'])
        dados_crm = {**dados, **automacao.dados_pedido}
        cadastrar_venda_pap_no_crm(dados_crm, numero_os or "", vendedor=vendedor)
    except Exception as e:
        logger.error(f"[VENDA PAP] Erro ao cadastrar no CRM: {e}")
    
    return (
        f"🎉 *VENDA CONCLUÍDA COM SUCESSO!*\n\n"
        f"📋 Número do Pedido: *{numero_os or 'N/A'}*\n\n"
        f"A venda foi registrada no CRM.\n\n"
        f"Digite *VENDER* para iniciar uma nova venda."
    )


def _encerrar_automacao_pap(sessao_id: int, bo_usuario_id, telefone: str):
    """Encerra automação PAP (agendamento, viabilidade ou crédito) e libera o BO."""
    from crm_app.pool_bo_pap import liberar_bo
    with _automacoes_lock:
        ctx = _automacoes_pap_ativas.pop(sessao_id, None)
    if ctx:
        try:
            ctx['automacao']._fechar_sessao()
        except Exception:
            pass
        if bo_usuario_id:
            liberar_bo(bo_usuario_id, telefone)


def _montar_resumo_venda_e_pedir_confirmar(dados: dict) -> str:
    """Monta o resumo da venda e pede confirmação (fluxo unificado com terminal)."""
    cpf = dados.get('cpf_cliente', '')
    celular = dados.get('celular', '')
    plano_nome = {
        '1giga': 'Nio Fibra Ultra 1 Giga - R$ 160,00/mês',
        '700mega': 'Nio Fibra Super 700 Mega - R$ 130,00/mês',
        '500mega': 'Nio Fibra Essencial 500 Mega - R$ 100,00/mês'
    }
    forma_nome = {'boleto': 'Boleto', 'cartao': 'Cartão de Crédito', 'debito': 'Débito em Conta'}
    cpf_fmt = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf
    cel_fmt = f"({celular[:2]}) {celular[2:7]}-{celular[7:]}" if len(celular) >= 10 else celular
    return (
        f"📋 *RESUMO DA VENDA*\n\n"
        f"📍 *Endereço:*\n"
        f"CEP: {dados.get('cep', '')}\n"
        f"Número: {dados.get('numero', '')}\n"
        f"Referência: {dados.get('referencia', '')}\n\n"
        f"👤 *Cliente:*\n"
        f"CPF: {cpf_fmt}\n"
        f"Celular: {cel_fmt}\n"
        f"E-mail: {dados.get('email', '')}\n\n"
        f"💳 *Pagamento:* {forma_nome.get(dados.get('forma_pagamento', ''), '')}\n"
        f"📦 *Plano:* {plano_nome.get(dados.get('plano', ''), '')}\n"
        f"📞 *Fixo:* {'Sim' if dados.get('tem_fixo') else 'Não'}\n"
        f"📺 *Streaming:* {'Sim' if dados.get('tem_streaming') else 'Não'}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Confirma a venda?\n\n"
        f"Digite *CONFIRMAR* para enviar ao PAP\n"
        f"Digite *CANCELAR* para desistir"
    )


def _processar_etapa_venda(telefone: str, mensagem: str, sessao, etapa: str) -> str:
    """
    Processa as etapas do fluxo de venda.
    
    Args:
        telefone: Número do telefone
        mensagem: Mensagem recebida
        sessao: Sessão do WhatsApp
        etapa: Etapa atual
        
    Returns:
        Mensagem de resposta
    """
    from usuarios.models import Usuario
    from crm_app.services_pap_nio import (
        PAPNioAutomation, 
        obter_sessao_venda, 
        criar_sessao_venda,
        atualizar_sessao_venda,
        encerrar_sessao_venda
    )
    import threading
    
    dados = sessao.dados_temp or {}
    mensagem_limpa = mensagem.strip().upper()
    
    # Comando para cancelar em qualquer etapa
    if mensagem_limpa in ['CANCELAR', 'SAIR', 'PARAR']:
        from crm_app.pool_bo_pap import liberar_bo
        # Se está em agendamento ou viabilidade com automação armazenada
        etapas_com_automacao = (
            'venda_agendamento_', 'venda_selecionar_endereco', 'venda_selecionar_complemento',
            'venda_posse_consultar_outro', 'venda_indisponivel_voltar',
            'venda_corrigir_celular', 'venda_corrigir_email', 'venda_corrigir_cpf'
        )
        if etapa and (etapa.startswith('venda_agendamento_') or etapa in etapas_com_automacao):
            _encerrar_automacao_pap(sessao.id, (dados or {}).get('bo_usuario_id'), telefone)
        else:
            bo_id = (dados or {}).get('bo_usuario_id')
            if bo_id:
                liberar_bo(bo_id, telefone)
        encerrar_sessao_venda(telefone)
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Venda cancelada. Digite *VENDER* para iniciar novamente."
    
    # --- ETAPA: Confirmar matrícula ---
    if etapa == 'venda_confirmar_matricula':
        if mensagem_limpa == 'SIM':
            # Obter login BackOffice do pool (seleção randômica entre disponíveis)
            from crm_app.pool_bo_pap import obter_login_bo
            bo_usuario, erro = obter_login_bo(
                vendedor_telefone=telefone,
                sessao_whatsapp_id=sessao.id,
            )
            if erro:
                return erro
            # Guardar bo_usuario_id para usar no PAP e liberar ao final
            dados['bo_usuario_id'] = bo_usuario.id
            sessao.dados_temp = dados
            sessao.etapa = 'venda_cep'
            sessao.save()
            return (
                "✅ Acesso reservado!\n\n"
                "📍 *ETAPA 1: ENDEREÇO*\n\n"
                "Digite o *CEP* do endereço de instalação:"
            )
        else:
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return "❌ Venda cancelada. Digite *VENDER* para iniciar novamente."
    
    # --- ETAPA: CEP ---
    elif etapa == 'venda_cep':
        cep_limpo = limpar_texto_cep_cpf(mensagem)
        if not cep_limpo or len(cep_limpo) < 8:
            return "❌ CEP inválido. Digite o CEP completo (8 dígitos):"
        
        dados['cep'] = cep_limpo
        sessao.dados_temp = dados
        sessao.etapa = 'venda_numero'
        sessao.save()
        
        return (
            f"✅ CEP: *{cep_limpo}*\n\n"
            f"Agora digite o *número* do endereço:\n"
            f"(ou digite *SN* se não houver número)"
        )
    
    # --- ETAPA: Número ---
    elif etapa == 'venda_numero':
        numero = mensagem.strip()
        if mensagem_limpa == 'SN':
            numero = 'S/N'
        
        dados['numero'] = numero
        sessao.dados_temp = dados
        sessao.etapa = 'venda_referencia'
        sessao.save()
        
        return (
            f"✅ Número: *{numero}*\n\n"
            f"Digite uma *referência* do endereço:\n"
            f"(ex: Próximo ao mercado, casa azul, etc.)"
        )
    
    # --- ETAPA: Referência ---
    elif etapa == 'venda_referencia':
        referencia = mensagem.strip()
        if len(referencia) < 3:
            return "❌ Referência muito curta. Digite uma referência mais detalhada:"

        dados['referencia'] = referencia
        sessao.dados_temp = dados
        sessao.save()

        # Consultar viabilidade no PAP Nio (usa credenciais BO do pool)
        from usuarios.models import Usuario
        from crm_app.services_pap_nio import PAPNioAutomation
        from crm_app.whatsapp_service import WhatsAppService
        from crm_app.pool_bo_pap import liberar_bo
        import threading

        def consultar_viabilidade_thread():
            import django
            django.db.close_old_connections()
            bo_id = dados.get('bo_usuario_id')
            if not bo_id:
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                WhatsAppService().enviar_mensagem_texto(
                    telefone,
                    "❌ Sessão inválida. Digite *VENDER* para iniciar novamente."
                )
                return
            try:
                bo = Usuario.objects.get(id=bo_id)
                vendedor_matricula = dados.get('matricula_pap')
                automacao = PAPNioAutomation(
                    matricula_pap=bo.matricula_pap,
                    senha_pap=bo.senha_pap,
                    vendedor_nome=dados.get('vendedor_nome', ''),
                )
                sucesso_login, _ = automacao.iniciar_sessao()
                if not sucesso_login:
                    automacao._fechar_sessao()
                    liberar_bo(bo_id, telefone)
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    WhatsAppService().enviar_mensagem_texto(
                        telefone,
                        "❌ Erro ao acessar PAP. Digite *VENDER* para tentar novamente."
                    )
                    return
                sucesso_novo, _ = automacao.iniciar_novo_pedido(vendedor_matricula)
                if not sucesso_novo:
                    automacao._fechar_sessao()
                    liberar_bo(bo_id, telefone)
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    WhatsAppService().enviar_mensagem_texto(
                        telefone,
                        "❌ Erro ao iniciar pedido. Digite *VENDER* para tentar novamente."
                    )
                    return
                sucesso, msg, extra = automacao.etapa2_viabilidade(
                    dados.get('cep', ''),
                    dados.get('numero', ''),
                    referencia,
                )
                if sucesso:
                    automacao._fechar_sessao()
                    sessao.etapa = 'venda_cpf'
                    sessao.save()
                    protocolo = automacao.dados_pedido.get('protocolo', '')
                    msg_viab = "✅ Endereço disponível para instalação!"
                    if protocolo:
                        msg_viab += f"\n📋 Protocolo: {protocolo}"
                    msg_viab += "\n\n📋 *ETAPA 2: CLIENTE*\n\nDigite o *CPF* do cliente:"
                    WhatsAppService().enviar_mensagem_texto(telefone, msg_viab)
                elif isinstance(extra, dict) and extra.get('_codigo') == 'MULTIPLOS_ENDERECOS':
                    lista = extra.get('lista', [])
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {'automacao': automacao, 'phase': 'viabilidade_endereco', 'bo_usuario_id': bo_id, 'telefone': telefone}
                    sessao.etapa = 'venda_selecionar_endereco'
                    sessao.dados_temp = {**dados, 'viabilidade_lista_enderecos': lista}
                    sessao.save()
                    linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                    WhatsAppService().enviar_mensagem_texto(telefone, f"📋 *Múltiplos endereços encontrados:*\n\n{linha}\n\nDigite o *número* do endereço desejado (ex: 1, 2):")
                elif isinstance(extra, dict) and extra.get('_codigo') == 'COMPLEMENTOS':
                    lista = extra.get('lista', [])
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {'automacao': automacao, 'phase': 'viabilidade_complemento', 'bo_usuario_id': bo_id, 'telefone': telefone}
                    sessao.etapa = 'venda_selecionar_complemento'
                    sessao.dados_temp = {**dados, 'viabilidade_lista_complementos': lista}
                    sessao.save()
                    linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                    WhatsAppService().enviar_mensagem_texto(telefone, f"📋 *Complementos encontrados:*\n\n{linha}\n\nDigite *0* ou *SEM COMPLEMENTO* se não tiver complemento, ou o *número* do complemento (ex: 1, 2, 3):")
                elif extra == "POSSE_ENCONTRADA":
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {'automacao': automacao, 'phase': 'viabilidade_posse', 'bo_usuario_id': bo_id, 'telefone': telefone}
                    sessao.etapa = 'venda_posse_consultar_outro'
                    sessao.dados_temp = dados
                    sessao.save()
                    WhatsAppService().enviar_mensagem_texto(telefone, msg + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                elif extra == "INDISPONIVEL_TECNICO":
                    with _automacoes_lock:
                        _automacoes_pap_ativas[sessao.id] = {'automacao': automacao, 'phase': 'viabilidade_indisponivel', 'bo_usuario_id': bo_id, 'telefone': telefone}
                    sessao.etapa = 'venda_indisponivel_voltar'
                    sessao.dados_temp = dados
                    sessao.save()
                    WhatsAppService().enviar_mensagem_texto(telefone, msg + "\n\nDigite outro *CEP* (8 dígitos) ou *CONCLUIR* para sair.")
                else:
                    automacao._fechar_sessao()
                    liberar_bo(bo_id, telefone)
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
                    texto = f"❌ Endereço indisponível. Motivo: {msg}\n\nDigite *VENDER* para tentar novamente."
                    WhatsAppService().enviar_mensagem_texto(telefone, texto)
            except Exception as e:
                liberar_bo(bo_id, telefone)
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                WhatsAppService().enviar_mensagem_texto(
                    telefone,
                    f"❌ Erro ao consultar viabilidade: {e}\n\nDigite *VENDER* para tentar novamente."
                )

        resposta = "⏳ Consultando viabilidade do endereço... Aguarde alguns instantes. Você receberá a resposta em seguida."
        thread = threading.Thread(target=consultar_viabilidade_thread)
        thread.start()
        return resposta
    
    # --- ETAPAS: Viabilidade (múltiplos endereços, complementos, posse, indisponível) ---
    elif etapa == 'venda_selecionar_endereco':
        return _processar_viabilidade_selecionar_endereco(telefone, sessao, dados, mensagem_limpa, mensagem.strip())
    elif etapa == 'venda_selecionar_complemento':
        return _processar_viabilidade_selecionar_complemento(telefone, sessao, dados, mensagem_limpa, mensagem.strip())
    elif etapa == 'venda_posse_consultar_outro':
        return _processar_viabilidade_posse(telefone, sessao, dados, mensagem_limpa)
    elif etapa == 'venda_indisponivel_voltar':
        return _processar_viabilidade_indisponivel(telefone, sessao, dados, mensagem_limpa)
    
    # --- ETAPAS: Correção de crédito (como no terminal) ---
    elif etapa == 'venda_corrigir_celular':
        return _processar_correcao_credito(telefone, sessao, dados, mensagem_limpa, 'celular')
    elif etapa == 'venda_corrigir_email':
        return _processar_correcao_credito(telefone, sessao, dados, mensagem_limpa, 'email')
    elif etapa == 'venda_corrigir_cpf':
        return _processar_correcao_credito(telefone, sessao, dados, mensagem_limpa, 'cpf')
    
    # --- ETAPA: CPF ---
    elif etapa == 'venda_cpf':
        cpf_limpo = limpar_texto_cep_cpf(mensagem)
        if not cpf_limpo or len(cpf_limpo) != 11:
            return "❌ CPF inválido. Digite o CPF completo (11 dígitos):"
        
        dados['cpf_cliente'] = cpf_limpo
        sessao.dados_temp = dados
        sessao.etapa = 'venda_celular'
        sessao.save()
        
        return (
            f"✅ CPF: *{cpf_limpo[:3]}.{cpf_limpo[3:6]}.{cpf_limpo[6:9]}-{cpf_limpo[9:]}*\n\n"
            f"📱 *ETAPA 3: CONTATO*\n\n"
            f"Digite o *celular principal* do cliente (com DDD):"
        )
    
    # --- ETAPA: Celular ---
    elif etapa == 'venda_celular':
        celular_limpo = limpar_texto_cep_cpf(mensagem)
        if not celular_limpo or len(celular_limpo) < 10:
            return "❌ Celular inválido. Digite o celular com DDD (10 ou 11 dígitos):"
        
        dados['celular'] = celular_limpo
        sessao.dados_temp = dados
        sessao.etapa = 'venda_celular_sec'
        sessao.save()
        
        return (
            f"✅ Celular: *({celular_limpo[:2]}) {celular_limpo[2:7]}-{celular_limpo[7:]}*\n\n"
            f"📱 Celular secundário (opcional - digite *PULAR* para pular):"
        )
    
    # --- ETAPA: Celular secundário ---
    elif etapa == 'venda_celular_sec':
        celular_sec = ""
        if mensagem_limpa not in ("PULAR", "P"):
            celular_sec = limpar_texto_cep_cpf(mensagem)
            if celular_sec and len(celular_sec) < 10:
                return "❌ Celular inválido. Digite um número válido ou *PULAR*:"
        dados['celular_sec'] = celular_sec
        sessao.dados_temp = dados
        sessao.etapa = 'venda_email'
        sessao.save()
        
        return (
            f"✅ {'Celular sec. registrado' if celular_sec else 'Pulado'}\n\n"
            f"📧 Digite o *e-mail* do cliente:"
        )
    
    # --- ETAPA: Email ---
    elif etapa == 'venda_email':
        email = mensagem.strip().lower()
        if '@' not in email or '.' not in email:
            return "❌ E-mail inválido. Digite um e-mail válido:"
        
        dados['email'] = email
        sessao.dados_temp = dados
        sessao.etapa = 'venda_forma_pagamento'
        sessao.save()
        
        return (
            f"✅ E-mail: *{email}*\n\n"
            f"💳 *ETAPA 4: PAGAMENTO*\n\n"
            f"Escolha a forma de pagamento:\n\n"
            f"1️⃣ Boleto\n"
            f"2️⃣ Cartão de Crédito\n"
            f"3️⃣ Débito em Conta\n\n"
            f"Digite o número da opção:"
        )
    
    # --- ETAPA: Forma de Pagamento ---
    elif etapa == 'venda_forma_pagamento':
        formas = {'1': 'boleto', '2': 'cartao', '3': 'debito'}
        if mensagem_limpa not in formas:
            return "❌ Opção inválida. Digite 1, 2 ou 3:"
        
        dados['forma_pagamento'] = formas[mensagem_limpa]
        sessao.dados_temp = dados
        if formas[mensagem_limpa] == 'debito':
            sessao.etapa = 'venda_debito_banco'
        else:
            sessao.etapa = 'venda_plano'
        sessao.save()
        
        forma_nome = {'boleto': 'Boleto', 'cartao': 'Cartão de Crédito', 'debito': 'Débito em Conta'}
        
        if formas[mensagem_limpa] == 'debito':
            return (
                f"✅ Pagamento: *Débito em Conta*\n\n"
                f"🏦 Banco: 1=Itaú 2=Banrisul 3=Santander 4=BB 5=Bradesco 6=Nubank\n\n"
                f"Digite o número do banco:"
            )
        return (
            f"✅ Pagamento: *{forma_nome[formas[mensagem_limpa]]}*\n\n"
            f"📦 *ETAPA 5: PLANO*\n\n"
            f"Escolha o plano:\n\n"
            f"1️⃣ Nio Fibra Ultra 1 Giga - R$ 160,00/mês\n"
            f"2️⃣ Nio Fibra Super 700 Mega - R$ 130,00/mês\n"
            f"3️⃣ Nio Fibra Essencial 500 Mega - R$ 100,00/mês\n\n"
            f"Digite o número da opção:"
        )
    
    # --- ETAPA: Débito - Banco ---
    elif etapa == 'venda_debito_banco':
        banco_map = {'1': 'Banco Itau S/A', '2': 'Banrisul', '3': 'Banco Santander', '4': 'Banco do Brasil', '5': 'Banco Bradesco', '6': 'Nubank'}
        banco = banco_map.get(mensagem_limpa, '')
        if not banco:
            return "❌ Opção inválida. Digite 1, 2, 3, 4, 5 ou 6:"
        dados['banco'] = banco
        sessao.dados_temp = dados
        sessao.etapa = 'venda_debito_agencia'
        sessao.save()
        return f"✅ Banco: *{banco}*\n\n🏦 Digite a *agência*:"
    
    # --- ETAPA: Débito - Agência ---
    elif etapa == 'venda_debito_agencia':
        dados['agencia'] = mensagem.strip()
        sessao.dados_temp = dados
        sessao.etapa = 'venda_debito_conta'
        sessao.save()
        return "📋 Digite a *conta*:"
    
    # --- ETAPA: Débito - Conta ---
    elif etapa == 'venda_debito_conta':
        dados['conta'] = mensagem.strip()
        sessao.dados_temp = dados
        sessao.etapa = 'venda_debito_digito'
        sessao.save()
        return "🔢 Digite o *dígito*:"
    
    # --- ETAPA: Débito - Dígito ---
    elif etapa == 'venda_debito_digito':
        dados['digito'] = mensagem.strip()
        sessao.dados_temp = dados
        sessao.etapa = 'venda_plano'
        sessao.save()
        return (
            f"✅ Débito preenchido!\n\n"
            f"📦 *ETAPA 5: PLANO*\n\n"
            f"Escolha o plano:\n\n"
            f"1️⃣ Nio Fibra Ultra 1 Giga - R$ 160,00/mês\n"
            f"2️⃣ Nio Fibra Super 700 Mega - R$ 130,00/mês\n"
            f"3️⃣ Nio Fibra Essencial 500 Mega - R$ 100,00/mês\n\n"
            f"Digite o número da opção:"
        )
    
    # --- ETAPA: Plano ---
    elif etapa == 'venda_plano':
        planos = {'1': '1giga', '2': '700mega', '3': '500mega'}
        if mensagem_limpa not in planos:
            return "❌ Opção inválida. Digite 1, 2 ou 3:"
        
        dados['plano'] = planos[mensagem_limpa]
        sessao.dados_temp = dados
        sessao.etapa = 'venda_fixo'
        sessao.save()
        
        plano_nome = {
            '1giga': 'Nio Fibra Ultra 1 Giga - R$ 160,00/mês',
            '700mega': 'Nio Fibra Super 700 Mega - R$ 130,00/mês',
            '500mega': 'Nio Fibra Essencial 500 Mega - R$ 100,00/mês'
        }
        
        return (
            f"✅ Plano: *{plano_nome[planos[mensagem_limpa]]}*\n\n"
            f"📞 Tem *Fixo* (R$ 30/mês)?\n\n"
            f"1️⃣ Sim\n"
            f"2️⃣ Não\n\n"
            f"Digite o número da opção:"
        )
    
    # --- ETAPA: Fixo ---
    elif etapa == 'venda_fixo':
        if mensagem_limpa not in ('1', '2'):
            return "❌ Opção inválida. Digite 1 (Sim) ou 2 (Não):"
        dados['tem_fixo'] = mensagem_limpa == '1'
        sessao.dados_temp = dados
        sessao.etapa = 'venda_streaming'
        sessao.save()
        
        return (
            f"✅ Fixo: {'Sim' if dados['tem_fixo'] else 'Não'}\n\n"
            f"📺 Tem *Streaming*?\n\n"
            f"1️⃣ Sim\n"
            f"2️⃣ Não\n\n"
            f"Digite o número da opção:"
        )
    
    # --- ETAPA: Streaming ---
    elif etapa == 'venda_streaming':
        if mensagem_limpa not in ('1', '2'):
            return "❌ Opção inválida. Digite 1 (Sim) ou 2 (Não):"
        tem_stream = mensagem_limpa == '1'
        dados['tem_streaming'] = tem_stream
        sessao.dados_temp = dados
        if tem_stream:
            sessao.etapa = 'venda_streaming_opcoes'
        else:
            sessao.etapa = 'venda_confirmar'
            sessao.save()
            return _montar_resumo_venda_e_pedir_confirmar(dados)
        sessao.save()
        
        return (
            "✅ Streaming: Sim\n\n"
            "Escolha a opção de Streaming:\n\n"
            "1️⃣ HBO+Premium\n"
            "2️⃣ HBO+Basico\n"
            "3️⃣ Basico\n"
            "4️⃣ Premium\n"
            "5️⃣ HBO\n\n"
            "Digite o número da opção:"
        )
    
    # --- ETAPA: Streaming opções ---
    elif etapa == 'venda_streaming_opcoes':
        st_map = {'1': 'hbomax,globoplay_premium', '2': 'hbomax,globoplay_basico', '3': 'globoplay_basico', '4': 'globoplay_premium', '5': 'hbomax'}
        streaming_opcoes = st_map.get(mensagem_limpa, '')
        if not streaming_opcoes:
            return "❌ Opção inválida. Digite 1, 2, 3, 4 ou 5:"
        dados['streaming_opcoes'] = streaming_opcoes
        sessao.dados_temp = dados
        sessao.etapa = 'venda_confirmar'
        sessao.save()
        return _montar_resumo_venda_e_pedir_confirmar(dados)
    
    # --- ETAPA: Confirmar Venda ---
    elif etapa == 'venda_confirmar':
        if mensagem_limpa != 'CONFIRMAR':
            if mensagem_limpa == 'CANCELAR':
                from crm_app.pool_bo_pap import liberar_bo
                bo_id = dados.get('bo_usuario_id')
                if bo_id:
                    liberar_bo(bo_id, telefone)
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
                return "❌ Venda cancelada. Digite *VENDER* para iniciar novamente."
            return "Digite *CONFIRMAR* para enviar a venda ou *CANCELAR* para desistir:"
        
        # Iniciar automação PAP
        sessao.etapa = 'venda_processando'
        sessao.save()
        
        return _executar_venda_pap(telefone, sessao, dados)
    
    # --- ETAPA: Processando (aguardando biometria) ---
    elif etapa == 'venda_aguardando_biometria':
        if mensagem_limpa in ['VERIFICAR', 'STATUS']:
            return _verificar_biometria_venda(telefone, sessao, dados)
        return (
            "⏳ *AGUARDANDO BIOMETRIA*\n\n"
            "O cliente precisa completar a biometria via WhatsApp.\n\n"
            "Quando o cliente completar, digite *VERIFICAR* para continuar.\n"
            "Ou digite *CANCELAR* para desistir."
        )
    
    # --- ETAPAS: Agendamento (fluxo passo a passo como no terminal) ---
    elif etapa == 'venda_agendamento_dia':
        return _processar_agendamento_dia(telefone, sessao, dados, mensagem_limpa, mensagem.strip())
    elif etapa == 'venda_agendamento_confirmar_data':
        return _processar_agendamento_confirmar_data(telefone, sessao, dados, mensagem_limpa)
    elif etapa == 'venda_agendamento_periodo':
        return _processar_agendamento_periodo(telefone, sessao, dados, mensagem_limpa, mensagem.strip())
    elif etapa == 'venda_agendamento_confirmar_turno':
        return _processar_agendamento_confirmar_turno(telefone, sessao, dados, mensagem_limpa)
    elif etapa == 'venda_agendamento_sim_agendar':
        return _processar_agendamento_sim_agendar(telefone, sessao, dados, mensagem_limpa)
    elif etapa == 'venda_agendamento_final':
        return _processar_agendamento_final(telefone, sessao, dados, mensagem_limpa)
    
    return "❓ Etapa não reconhecida. Digite *VENDER* para iniciar novamente."


def _executar_venda_pap(telefone: str, sessao, dados: dict) -> str:
    """
    Executa a venda no sistema PAP via automação em background.
    Usa credenciais de BackOffice (pool) para login; matrícula do vendedor
    para atribuição da venda.
    """
    import threading
    from usuarios.models import Usuario
    
    sessao.etapa = 'venda_processando'
    sessao.save()
    
    vendedor_id = dados.get('vendedor_id')
    bo_usuario_id = dados.get('bo_usuario_id')
    if not bo_usuario_id:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ *ERRO*\n\nSessão inválida. Digite *VENDER* para iniciar novamente."
    try:
        vendedor = Usuario.objects.get(id=vendedor_id)
        vendedor_matricula = vendedor.matricula_pap
        vendedor_nome = vendedor.get_full_name() or vendedor.username
        bo_usuario = Usuario.objects.get(id=bo_usuario_id)
        bo_matricula = bo_usuario.matricula_pap
        bo_senha = bo_usuario.senha_pap
    except Usuario.DoesNotExist:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ *ERRO*\n\nUsuário não encontrado."
    
    def executar_em_background():
        _executar_venda_pap_background(
            telefone,
            sessao.id,
            dados,
            vendedor_id,
            vendedor_matricula,
            vendedor_nome,
            bo_usuario_id,
            bo_matricula,
            bo_senha,
        )
    
    thread = threading.Thread(target=executar_em_background, daemon=True)
    thread.start()
    
    return (
        "⏳ *PROCESSANDO VENDA...*\n\n"
        "Estou acessando o sistema PAP Nio para registrar sua venda.\n"
        "Isso pode levar alguns segundos.\n\n"
        "Aguarde a confirmação..."
    )


def _executar_venda_pap_etapa6_em_diante(
    telefone: str, sessao_id: int, dados: dict, automacao,
    vendedor_matricula: str, vendedor_id, vendedor_nome: str, bo_usuario_id: int,
    enviar_resultado, resetar_sessao_e_liberar_bo,
):
    """Executa etapa 6 (resumo, sim, biometria) e 7 (agendamento) - usado após etapa5 ou após correção de crédito."""
    from crm_app.models import SessaoWhatsapp
    from crm_app.whatsapp_service import WhatsAppService
    
    try:
        resumo_txt = automacao.obter_resumo_pedido_para_cliente()
        celular_cliente = dados.get('celular', '') or automacao.dados_pedido.get('celular', '')
        msg_cliente = f"{resumo_txt}\n\nPara confirmar, responda *SIM*."
        try:
            WhatsAppService().enviar_mensagem_texto(celular_cliente, msg_cliente)
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao enviar resumo ao cliente: {e}")
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado("❌ Erro ao enviar resumo ao cliente.\n\nDigite *VENDER* para tentar novamente.")
            return
        try:
            from crm_app.models import PapConfirmacaoCliente
            cel_norm = _chave_telefone(celular_cliente)
            cel_sec = _chave_telefone(dados.get('celular_sec', '') or '')
            celulares_reg = [c for c in [cel_norm, cel_sec] if c]
            for c in celulares_reg:
                PapConfirmacaoCliente.objects.filter(celular_cliente=c, confirmado=False).delete()
                PapConfirmacaoCliente.objects.create(celular_cliente=c, confirmado=False)
        except Exception as e:
            logger.warning(f"[VENDA PAP] Falha ao registrar PapConfirmacaoCliente: {e}")
        celular_mask = celular_cliente
        if len(celular_mask) >= 6:
            celular_mask = f"({celular_mask[-11:-9]}) {celular_mask[-9:-4]}-{celular_mask[-4:]}" if len(celular_mask) >= 11 else celular_mask[:4] + "****"
        enviar_resultado("✅ *Resumo enviado ao cliente* " + f"(cel: {celular_mask}).\n\nAguardando confirmação (*SIM*) do cliente.")
        evt_cliente = threading.Event()
        chave_cliente = _chave_telefone(celular_cliente)
        with _pending_lock:
            _pending_client_confirm[chave_cliente] = {'event': evt_cliente, 'vendedor_telefone': telefone, 'automacao': automacao, 'dados': dados, 'sessao_id': sessao_id}
        evt_cliente.wait(timeout=600)
        with _pending_lock:
            _pending_client_confirm.pop(chave_cliente, None)
        if not evt_cliente.is_set():
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado("⏳ *Timeout*: Cliente não confirmou em 10 minutos.\n\nDigite *VENDER* para iniciar novamente.")
            return
        while True:
            sucesso, msg, biometria_ok = automacao.etapa6_verificar_biometria()
            if biometria_ok:
                break
            enviar_resultado(f"⏳ *BIOMETRIA PENDENTE*\n\n{msg}\n\nPeça ao cliente para realizar a biometria.\nQuando concluir, digite *BIO OK* para consultar.")
            evt_bio = threading.Event()
            chave_vendedor = _chave_telefone(telefone)
            with _pending_lock:
                _pending_bio_ok[chave_vendedor] = {'event': evt_bio, 'automacao': automacao, 'dados': dados}
            evt_bio.wait(timeout=600)
            with _pending_lock:
                _pending_bio_ok.pop(chave_vendedor, None)
            if not evt_bio.is_set():
                automacao._fechar_sessao()
                resetar_sessao_e_liberar_bo()
                enviar_resultado("⏳ *Timeout*: Biometria.\n\nDigite *VENDER* para iniciar novamente.")
                return
            automacao.etapa6_consultar_biometria()
            automacao.page.wait_for_timeout(2000)
        sucesso, msg = automacao.etapa7_ir_para_agendamento()
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NO AGENDAMENTO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        ok, _, datas = automacao.etapa7_obter_datas_disponiveis()
        if not ok or not datas:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado("❌ Não foi possível obter datas.\n\nDigite *VENDER* para tentar novamente.")
            return
        with _automacoes_lock:
            _automacoes_pap_ativas[sessao_id] = {'automacao': automacao, 'dados': dados, 'vendedor_id': vendedor_id, 'bo_usuario_id': bo_usuario_id, 'telefone': telefone}
        try:
            s = SessaoWhatsapp.objects.get(id=sessao_id)
            s.etapa = 'venda_agendamento_dia'
            s.dados_temp = {**(s.dados_temp or {}), **dados, 'agendamento_datas': datas}
            s.save()
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao atualizar sessão: {e}")
            automacao._fechar_sessao()
            with _automacoes_lock:
                _automacoes_pap_ativas.pop(sessao_id, None)
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente.")
            return
        enviar_resultado(f"📅 *AGENDAMENTO - Selecione o dia*\n\nDatas disponíveis: {', '.join(str(d) for d in datas)}\n\nDigite o *número do dia* (ex: 10) ou *CANCELAR*.")
    except Exception as e:
        logger.exception(f"[VENDA PAP] Erro etapa6+: {e}")
        try:
            automacao._fechar_sessao()
        except Exception:
            pass
        with _automacoes_lock:
            _automacoes_pap_ativas.pop(sessao_id, None)
        resetar_sessao_e_liberar_bo()
        enviar_resultado(f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente.")


def _executar_venda_pap_background(
    telefone: str,
    sessao_id: int,
    dados: dict,
    vendedor_id: int,
    vendedor_matricula: str,
    vendedor_nome: str,
    bo_usuario_id: int,
    bo_matricula: str,
    bo_senha: str,
):
    """
    Executa a automação PAP em background (thread separada).
    Login com credenciais BO; matrícula do vendedor para atribuição da venda.
    Libera o BO ao final (sucesso, erro ou biometria pendente).
    """
    import django
    django.setup()

    from crm_app.models import SessaoWhatsapp
    from usuarios.models import Usuario
    from crm_app.services_pap_nio import PAPNioAutomation
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.pool_bo_pap import liberar_bo

    whatsapp = WhatsAppService()

    def enviar_resultado(mensagem: str):
        try:
            whatsapp.enviar_mensagem_texto(telefone, mensagem)
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao enviar resultado: {e}")

    def resetar_sessao_e_liberar_bo():
        """Reseta sessão e libera o BO para o pool"""
        try:
            sessao = SessaoWhatsapp.objects.get(id=sessao_id)
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
        except Exception as e:
            logger.error(f"[VENDA PAP] Erro ao resetar sessão: {e}")
        liberar_bo(bo_usuario_id, telefone)

    try:
        logger.info(f"[VENDA PAP] Iniciando automação em background para {vendedor_nome} (BO id={bo_usuario_id})")

        automacao = PAPNioAutomation(
            matricula_pap=bo_matricula,
            senha_pap=bo_senha,
            vendedor_nome=vendedor_nome,
        )
        
        # Etapa 0: Iniciar sessão
        sucesso, msg = automacao.iniciar_sessao()
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NO LOGIN PAP*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 1: Iniciar novo pedido
        sucesso, msg = automacao.iniciar_novo_pedido(vendedor_matricula)
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NA ETAPA 1*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 2: Viabilidade
        sucesso, msg, enderecos = automacao.etapa2_viabilidade(
            dados.get('cep', ''),
            dados.get('numero', ''),
            dados.get('referencia', '')
        )
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NA VIABILIDADE*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 3: Cadastro do cliente
        sucesso, msg, cliente = automacao.etapa3_cadastro_cliente(dados.get('cpf_cliente', ''))
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NO CADASTRO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 4: Contato (com celular secundário como no terminal)
        celular_sec = dados.get('celular_sec', '') or None
        sucesso, msg, credito = automacao.etapa4_contato(
            dados.get('celular', ''),
            dados.get('email', ''),
            celular_secundario=celular_sec
        )
        if not sucesso:
            # Manter sessão e permitir correção (como no terminal)
            etapa_correcao = None
            txt = ""
            if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                etapa_correcao = 'venda_corrigir_celular'
                txt = ("⚠️ O número excede repetições. Digite outro celular:" if msg == "TELEFONE_REJEITADO"
                       else "⚠️ Celular inválido. Digite um número válido com DDD:")
            elif msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                etapa_correcao = 'venda_corrigir_email'
                txt = ("⚠️ E-mail já usado em pedido anterior. Digite outro e-mail:" if msg == "EMAIL_REJEITADO"
                       else "⚠️ E-mail inválido. Digite um e-mail válido:")
            elif msg == "CREDITO_NEGADO":
                etapa_correcao = 'venda_corrigir_cpf'
                txt = "❌ Crédito negado para este CPF.\n\nDigite outro CPF para tentar, ou CANCELAR para sair:"
            if etapa_correcao:
                with _automacoes_lock:
                    _automacoes_pap_ativas[sessao_id] = {
                        'automacao': automacao, 'phase': 'corrigir_credito',
                        'dados': dados, 'vendedor_id': vendedor_id, 'vendedor_matricula': vendedor_matricula,
                        'vendedor_nome': vendedor_nome, 'bo_usuario_id': bo_usuario_id,
                        'telefone': telefone,
                    }
                try:
                    s = SessaoWhatsapp.objects.get(id=sessao_id)
                    s.etapa = etapa_correcao
                    s.dados_temp = dados
                    s.save()
                except Exception as e:
                    logger.error(f"[VENDA PAP] Erro ao atualizar sessão: {e}")
                    automacao._fechar_sessao()
                    resetar_sessao_e_liberar_bo()
                    enviar_resultado(f"❌ Erro: {e}\n\nDigite *VENDER* para tentar novamente.")
                    return
                enviar_resultado(txt)
            else:
                automacao._fechar_sessao()
                resetar_sessao_e_liberar_bo()
                enviar_resultado(f"❌ *ERRO NA ANÁLISE DE CRÉDITO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        # Etapa 5: Pagamento e Plano (passo a passo como no terminal)
        sucesso, msg = automacao.etapa5_selecionar_forma_pagamento(dados.get('forma_pagamento', 'boleto'))
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NA FORMA DE PAGAMENTO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        if dados.get('forma_pagamento') == 'debito':
            sucesso, msg = automacao.etapa5_preencher_debito(
                dados.get('banco', ''),
                dados.get('agencia', ''),
                dados.get('conta', ''),
                dados.get('digito', ''),
            )
            if not sucesso:
                automacao._fechar_sessao()
                resetar_sessao_e_liberar_bo()
                enviar_resultado(f"❌ *ERRO NO DÉBITO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
                return
        sucesso, msg = automacao.etapa5_selecionar_plano(dados.get('plano', '500mega'))
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NO PLANO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        sucesso, msg = automacao.etapa5_selecionar_fixo(dados.get('tem_fixo', False))
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NO FIXO*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        plano = dados.get('plano', '500mega')
        streaming_opcoes = dados.get('streaming_opcoes') or ''
        sucesso, msg = automacao.etapa5_selecionar_streaming(
            bool(dados.get('tem_streaming', False)),
            streaming_opcoes,
            plano
        )
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO NO STREAMING*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        sucesso, msg = automacao.etapa5_clicar_avancar()
        if not sucesso:
            automacao._fechar_sessao()
            resetar_sessao_e_liberar_bo()
            enviar_resultado(f"❌ *ERRO AO AVANÇAR*\n\n{msg}\n\nDigite *VENDER* para tentar novamente.")
            return
        
        _executar_venda_pap_etapa6_em_diante(
            telefone=telefone, sessao_id=sessao_id, dados=dados, automacao=automacao,
            vendedor_matricula=vendedor_matricula, vendedor_id=vendedor_id, vendedor_nome=vendedor_nome,
            bo_usuario_id=bo_usuario_id, enviar_resultado=enviar_resultado,
            resetar_sessao_e_liberar_bo=resetar_sessao_e_liberar_bo
        )
        
    except Exception as e:
        logger.exception(f"[VENDA PAP] Erro na execução em background: {e}")
        resetar_sessao_e_liberar_bo()
        enviar_resultado(f"❌ *ERRO INESPERADO*\n\n{str(e)}\n\nDigite *VENDER* para tentar novamente.")


def _verificar_biometria_venda(telefone: str, sessao, dados: dict) -> str:
    """
    Verifica o status da biometria e continua a venda se aprovada.
    """
    automacao = dados.get('automacao_instancia')
    
    if not automacao:
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return "❌ Sessão expirada. Digite *VENDER* para iniciar novamente."
    
    try:
        # Verificar biometria
        sucesso, msg, biometria_ok = automacao.etapa6_verificar_biometria()
        
        if not biometria_ok:
            return (
                f"⏳ *BIOMETRIA AINDA PENDENTE*\n\n"
                f"{msg}\n\n"
                f"Aguarde o cliente completar e digite *VERIFICAR* novamente.\n"
                f"Ou digite *CANCELAR* para desistir."
            )
        
        # Biometria OK - Abrir OS
        sucesso, msg, numero_os = automacao.etapa7_abrir_os(
            turno=dados.get('turno', 'manha')
        )
        
        automacao._fechar_sessao()
        
        if not sucesso:
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            return f"❌ *ERRO AO ABRIR O.S.*\n\n{msg}"
        
        # SUCESSO! Mesclar dados da automação e cadastrar no CRM
        from usuarios.models import Usuario
        from crm_app.cadastro_venda_pap import cadastrar_venda_pap_no_crm
        vendedor = Usuario.objects.get(id=dados.get('vendedor_id'))
        dados_crm = {**dados, **automacao.dados_pedido}
        cadastrar_venda_pap_no_crm(dados_crm, numero_os or "", vendedor=vendedor)
        
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        
        return (
            f"🎉 *VENDA CONCLUÍDA COM SUCESSO!*\n\n"
            f"📋 Número do Pedido: *{numero_os or 'N/A'}*\n\n"
            f"A venda foi registrada no CRM.\n\n"
            f"Digite *VENDER* para iniciar uma nova venda."
        )
        
    except Exception as e:
        logger.exception(f"[VENDA PAP] Erro ao verificar biometria: {e}")
        sessao.etapa = 'inicial'
        sessao.dados_temp = {}
        sessao.save()
        return f"❌ *ERRO*\n\n{str(e)}\n\nDigite *VENDER* para iniciar novamente."


def processar_webhook_whatsapp(data):
    """
    Processa mensagens recebidas do WhatsApp via webhook.
    
    Formato esperado do data (Z-API):
    {
        "phone": "5511999999999",
        "message": {
            "text": "Fachada"
        }
    }
    
    Ou formato alternativo:
    {
        "from": "5511999999999",
        "body": "Fachada"
    }
    """
    from crm_app.models import SessaoWhatsapp
    from crm_app.whatsapp_service import WhatsAppService
    from crm_app.utils import (
        listar_fachadas_dfv,
        consultar_viabilidade_kmz,
        consultar_status_venda,
        consultar_andamento_agendamentos
    )
    from crm_app.nio_api import consultar_dividas_nio
    
    # Log completo do payload recebido para debug
    logger.info(f"[Webhook] Payload completo recebido: {data}")
    logger.info(f"[Webhook] Tipo do payload: {type(data)}")
    logger.info(f"[Webhook] Chaves disponíveis: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
    
    # Ignorar mensagens enviadas pelo próprio bot (evita eco e resposta duplicada)
    from_me = data.get('fromMe') or data.get('isFromMe') or data.get('from_me')
    if not from_me and isinstance(data.get('message'), dict):
        from_me = data['message'].get('fromMe') or data['message'].get('isFromMe') or data['message'].get('from_me')
    if from_me:
        logger.info("[Webhook] Ignorando mensagem do próprio bot (fromMe=True)")
        return {'status': 'ok', 'mensagem': 'Ignorando mensagem do próprio bot'}
    
    # Extrair telefone e mensagem do payload (Z-API pode usar phone, from, text.participant, etc.)
    telefone = data.get('phone') or data.get('from') or data.get('phoneNumber') or data.get('phone_number')
    if not telefone and isinstance(data.get('text'), dict):
        telefone = data['text'].get('participant')
    if not telefone and isinstance(data.get('message'), dict):
        telefone = (data.get('message') or {}).get('participant')
    mensagem_texto = ""
    
    # Formato Z-API: text é um dict com 'message' dentro
    if 'text' in data and isinstance(data['text'], dict):
        mensagem_texto = data['text'].get('message') or data['text'].get('text') or data['text'].get('body') or ""
    
    # Tentar múltiplos formatos de mensagem (outros provedores)
    if not mensagem_texto:
        if 'message' in data:
            if isinstance(data['message'], dict):
                mensagem_texto = data['message'].get('text') or data['message'].get('body') or data['message'].get('message') or ""
            else:
                mensagem_texto = str(data['message'])
        else:
            mensagem_texto = data.get('text') or data.get('body') or data.get('message') or data.get('content') or ""
    
    # Se ainda não encontrou, tentar em nested structures comuns
    if not mensagem_texto:
        if 'data' in data and isinstance(data['data'], dict):
            mensagem_texto = data['data'].get('text') or data['data'].get('body') or data['data'].get('message') or ""
        if 'payload' in data and isinstance(data['payload'], dict):
            mensagem_texto = data['payload'].get('text') or data['payload'].get('body') or data['payload'].get('message') or ""
    
    # Garantir que mensagem_texto é string
    if isinstance(mensagem_texto, dict):
        # Se ainda for dict, tentar extrair valores
        mensagem_texto = mensagem_texto.get('message') or mensagem_texto.get('text') or mensagem_texto.get('body') or str(mensagem_texto)
    elif not isinstance(mensagem_texto, str):
        mensagem_texto = str(mensagem_texto) if mensagem_texto else ""
    
    # Normalizar: ignorar mensagens vazias ou só espaços (evita processar eventos sem texto)
    mensagem_texto = (mensagem_texto or "").strip()
    
    logger.info(f"[Webhook] Telefone extraído: {telefone}")
    logger.info(f"[Webhook] Mensagem extraída: {mensagem_texto}")
    logger.info(f"[Webhook] Tipo da mensagem: {type(mensagem_texto)}")
    
    if not telefone or not mensagem_texto:
        logger.warning(f"[Webhook] Dados incompletos: telefone={telefone}, mensagem={mensagem_texto}")
        logger.warning(f"[Webhook] Payload completo para análise: {data}")
        return {'status': 'erro', 'mensagem': f'Dados incompletos: telefone={telefone}, mensagem={mensagem_texto}'}
    
    telefone_formatado = formatar_telefone(telefone)
    mensagem_limpa = mensagem_texto.strip().upper()
    
    logger.info(f"[Webhook] Mensagem recebida de {telefone_formatado}: {mensagem_texto}")
    logger.info(f"[Webhook] Mensagem limpa (uppercase): {mensagem_limpa}")
    
    # === ETAPA 6: Confirmação do cliente (SIM) ou BIO OK do vendedor ===
    chave = _chave_telefone(telefone_formatado)
    chaves_tentar = _chaves_telefone_variantes(telefone_formatado) or [chave]
    with _pending_lock:
        pend_cliente = next((_pending_client_confirm.get(k) for k in chaves_tentar if _pending_client_confirm.get(k)), None)
        pend_bio = next((_pending_bio_ok.get(k) for k in chaves_tentar if _pending_bio_ok.get(k)), None)
    
    if pend_cliente and mensagem_limpa in ['SIM', 'S']:
        pend_cliente['event'].set()
        try:
            WhatsAppService().enviar_mensagem_texto(telefone_formatado, "✅ *Confirmado!* O vendedor receberá a confirmação.")
        except Exception:
            pass
        return {'status': 'ok', 'mensagem': 'Confirmado pelo cliente'}

    # Terminal (testar_pap_terminal): confirmação via BD - cliente respondeu Sim
    if mensagem_limpa in ['SIM', 'S']:
        try:
            from crm_app.models import PapConfirmacaoCliente
            chaves = chaves_tentar or [chave]
            logger.info(f"[Webhook] [DEBUG] Cliente respondeu SIM. Telefone: {telefone_formatado}, chaves a tentar: {chaves}")
            for k in chaves:
                pend = PapConfirmacaoCliente.objects.filter(
                    celular_cliente=k, confirmado=False
                ).order_by('-criado_em').first()
                logger.info(f"[Webhook] [DEBUG] Chave '{k}': pendente encontrado={pend is not None}")
                if pend:
                    pend.confirmado = True
                    pend.save()
                    logger.info(f"[Webhook] PapConfirmacaoCliente marcado confirmado=True (celular={k})")
                    try:
                        WhatsAppService().enviar_mensagem_texto(telefone_formatado, "✅ *Confirmado!* O vendedor receberá a confirmação.")
                    except Exception:
                        pass
                    return {'status': 'ok', 'mensagem': 'Confirmado pelo cliente (BD)'}
            logger.info(f"[Webhook] [DEBUG] Nenhum PapConfirmacaoCliente pendente encontrado para chaves {chaves}")
        except Exception as e:
            logger.warning(f"[Webhook] Erro ao marcar PapConfirmacaoCliente: {e}", exc_info=True)
    
    if pend_bio and mensagem_limpa in ['BIO OK', 'BIOOK', 'CONSULTAR']:
        pend_bio['event'].set()
        try:
            WhatsAppService().enviar_mensagem_texto(telefone_formatado, "⏳ Consultando biometria...")
        except Exception:
            pass
        return {'status': 'ok', 'mensagem': 'BIO OK recebido'}
    
    # Inicializar serviço WhatsApp
    whatsapp_service = WhatsAppService()
    
    # Buscar ou criar sessão
    sessao, created = SessaoWhatsapp.objects.get_or_create(
        telefone=telefone_formatado,
        defaults={'etapa': 'inicial', 'dados_temp': {}}
    )
    
    # Resetar sessão antiga (mais de 30 minutos sem interação)
    if not created:
        tempo_decorrido = timezone.now() - sessao.updated_at
        if tempo_decorrido.total_seconds() > 1800:  # 30 minutos
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
    
    etapa_atual = sessao.etapa
    dados_temp = sessao.dados_temp or {}
    
    def _enviar_resposta_e_retornar(resposta_texto):
        """Envia a mensagem ao usuário via Z-API e retorna o resultado para a API."""
        if resposta_texto and str(resposta_texto).strip():
            try:
                whatsapp_service.enviar_mensagem_texto(telefone_formatado, resposta_texto)
            except Exception as e:
                logger.exception(f"[Webhook] Erro ao enviar mensagem ao usuário: {e}")
        return {'status': 'ok', 'mensagem': resposta_texto or 'Processado com sucesso'}

    try:
        # Identificar comando ou processar resposta
        resposta = None
        
        # === COMANDOS INICIAIS ===
        logger.info(f"[Webhook] Verificando comando. Mensagem limpa: '{mensagem_limpa}'")
        logger.info(f"[Webhook] Mensagem original: '{mensagem_texto}'")
        logger.info(f"[Webhook] Etapa atual: {etapa_atual}")
        
        # Verificação mais flexível - aceita comandos com ou sem acentuação, maiúsculas/minúsculas
        mensagem_sem_acentos = mensagem_limpa.replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U')
        
        # Comando FATURA
        if mensagem_limpa in ['FATURA', 'FATURAS']:
            logger.info(f"[Webhook] Comando FATURA reconhecido!")
            sessao.etapa = 'fatura_cpf'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "Por favor, digite o CPF do titular da fatura (apenas números):"
            return _enviar_resposta_e_retornar(resposta)

        # Comando VIABILIDADE
        if mensagem_limpa in ['VIABILIDADE', 'VIABILIDADES']:
            logger.info(f"[Webhook] Comando VIABILIDADE reconhecido!")
            sessao.etapa = 'viabilidade_cep'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "Por favor, digite o CEP do endereço para consulta de viabilidade (apenas números):"
            return _enviar_resposta_e_retornar(resposta)

        # Comando STATUS
        if mensagem_limpa in ['STATUS', 'SITUACAO', 'SITUAÇÃO']:
            logger.info(f"[Webhook] Comando STATUS reconhecido!")
            sessao.etapa = 'status_tipo'
            sessao.dados_temp = {}
            sessao.save()
            resposta = ("Para consultar o status do pedido, escolha uma opção:\n"
                        "1️⃣ CPF\n2️⃣ OS (Ordem de Serviço)\n\nDigite 1 para CPF ou 2 para O.S:")
            return _enviar_resposta_e_retornar(resposta)
        if 'FACHADA' in mensagem_limpa or 'FACADA' in mensagem_limpa:
            logger.info(f"[Webhook] Comando FACHADA reconhecido!")
            sessao.etapa = 'fachada_cep'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "Por favor, digite o CEP para consultar fachadas (apenas números):"
            return _enviar_resposta_e_retornar(resposta)

        # Comando MATERIAL
        if mensagem_limpa in ['MATERIAL', 'MATERIAIS']:
            logger.info(f"[Webhook] Comando MATERIAL reconhecido!")
            sessao.etapa = 'material_buscar'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "Digite a palavra-chave para buscar materiais ou documentos (ex: boleto, contrato, instalacao):"
            return _enviar_resposta_e_retornar(resposta)
        
        elif mensagem_limpa in ['ANDAMENTO', 'ANDAMENTOS']:
            logger.info(f"[Webhook] Comando ANDAMENTO reconhecido!")
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            resposta = consultar_andamento_agendamentos(telefone_formatado)
            _registrar_estatistica(telefone_formatado, 'ANDAMENTO')
            if resposta is None:
                resposta = "Nenhum agendamento encontrado para hoje."
            return _enviar_resposta_e_retornar(resposta)
        
        elif mensagem_limpa in ['VENDER', 'VENDA', 'NOVA VENDA']:
            logger.info(f"[Webhook] Comando VENDER reconhecido!")
            resposta = _iniciar_fluxo_venda(telefone_formatado, sessao)
            _registrar_estatistica(telefone_formatado, 'VENDER')
            if not resposta:
                resposta = "Não foi possível iniciar o fluxo de venda. Tente novamente."
            return _enviar_resposta_e_retornar(resposta)
        
        elif mensagem_limpa in ['MENU', 'AJUDA', 'HELP', 'OPCOES', 'OPÇÕES', 'OPCOES', 'OPÇOES']:
            logger.info(f"[Webhook] Comando MENU/AJUDA reconhecido!")
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
            resposta = (
                "📋 *MENU*\n\n"
                "Escolha uma opção:\n"
                "• *Fachada* - Consultar fachadas por CEP\n"
                "• *Viabilidade* - Consultar viabilidade por CEP e número\n"
                "• *Status* - Consultar status de pedido\n"
                "• *Fatura* - Consultar fatura por CPF\n"
                "• *Material* - Buscar materiais/documentos\n"
                "• *Andamento* - Ver agendamentos do dia\n"
                "• *Vender* - Realizar venda pelo WhatsApp 🆕"
            )
            return _enviar_resposta_e_retornar(resposta)
        
        # === PROCESSAMENTO POR ETAPA ===
        elif etapa_atual == 'fachada_cep':
            cep_limpo = limpar_texto_cep_cpf(mensagem_texto)
            if not cep_limpo or len(cep_limpo) < 8:
                resposta = "❌ CEP inválido. Por favor, digite o CEP completo (somente números):"
            else:
                logger.info(f"[Webhook] Buscando fachadas para CEP: {cep_limpo}")
                resposta_lista = listar_fachadas_dfv(cep_limpo)
                if isinstance(resposta_lista, list):
                    resposta = "🔎 Buscando todas as fachadas no DFV...\n\n" + "\n".join(resposta_lista)
                else:
                    resposta = f"🔎 Buscando todas as fachadas no DFV...\n\n{resposta_lista}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
            return _enviar_resposta_e_retornar(resposta)
        
        elif etapa_atual == 'viabilidade_cep':
            cep_limpo = limpar_texto_cep_cpf(mensagem_texto)
            if not cep_limpo or len(cep_limpo) < 8:
                resposta = "❌ CEP inválido. Por favor, digite o CEP completo:"
            else:
                sessao.etapa = 'viabilidade_numero'
                sessao.dados_temp = {'cep': cep_limpo}
                sessao.save()
                resposta = "Ok (Modo Mapa)! Agora digite o NÚMERO da fachada para localizarmos no mapa:"
        
        elif etapa_atual == 'viabilidade_numero':
            numero = mensagem_texto.strip()
            cep = dados_temp.get('cep', '')
            if not numero:
                resposta = "❌ Número inválido. Por favor, digite o número da fachada:"
            else:
                logger.info(f"[Webhook] Consultando viabilidade: CEP={cep}, Num={numero}")
                resultado_viabilidade = consultar_viabilidade_kmz(cep, numero)
                resposta = f"🛰️ Geolocalizando e analisando mancha (KMZ)...\n\n{resultado_viabilidade}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        elif etapa_atual == 'status_tipo':
            if mensagem_limpa in ['1', 'CPF']:
                sessao.etapa = 'status_cpf'
                sessao.dados_temp = {'tipo': 'CPF'}
                sessao.save()
                resposta = "Ok, digite o CPF do cliente (apenas números):"
            elif mensagem_limpa in ['2', 'OS', 'O.S']:
                sessao.etapa = 'status_os'
                sessao.dados_temp = {'tipo': 'OS'}
                sessao.save()
                resposta = "Ok, digite o número da O.S (Ordem de Serviço):"
            else:
                resposta = "❌ Opção inválida. Por favor, digite 1 para CPF ou 2 para O.S:"
        
        elif etapa_atual == 'status_cpf':
            cpf_limpo = limpar_texto_cep_cpf(mensagem_texto)
            if not cpf_limpo or len(cpf_limpo) < 11:
                resposta = "❌ CPF inválido. Por favor, digite o CPF completo (apenas números):"
            else:
                logger.info(f"[Webhook] Consultando status por CPF: {cpf_limpo}")
                resultado_status = consultar_status_venda('CPF', cpf_limpo)
                resposta = f"🔎 Buscando pedido por CPF...\n\n{resultado_status}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        elif etapa_atual == 'status_os':
            os_limpo = mensagem_texto.strip()
            if not os_limpo:
                resposta = "❌ O.S inválida. Por favor, digite o número da O.S:"
            else:
                logger.info(f"[Webhook] Consultando status por OS: {os_limpo}")
                resultado_status = consultar_status_venda('OS', os_limpo)
                resposta = f"🔎 Buscando pedido por O.S...\n\n{resultado_status}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        elif etapa_atual == 'fatura_cpf':
            cpf_limpo = limpar_texto_cep_cpf(mensagem_texto)
            
            # Validar apenas formato básico (11 dígitos)
            # A API da Nio é quem valida se o CPF existe na base deles
            # Não validamos dígito verificador aqui porque o site da Nio aceita CPFs
            # que podem não passar na validação rigorosa mas existem na base deles
            cpf_valido = cpf_limpo and len(cpf_limpo) == 11 and cpf_limpo.isdigit()
            
            if not cpf_valido:
                resposta = "❌ CPF inválido. Por favor, digite o CPF completo (11 dígitos, apenas números):"
            else:
                logger.info(f"[Webhook] Buscando TODAS as faturas para CPF: {cpf_limpo}")
                try:
                    # Buscar TODAS as faturas - fazer múltiplas requisições se necessário
                    todas_invoices = []
                    offset = 0
                    limit = 50  # Aumentar limite por requisição
                    max_tentativas = 5  # Evitar loop infinito
                    
                    for tentativa in range(max_tentativas):
                        resultado = consultar_dividas_nio(cpf_limpo, offset=offset, limit=limit, headless=True)
                        invoices_lote = resultado.get('invoices', [])
                        
                        if not invoices_lote:
                            break  # Não há mais faturas
                        
                        todas_invoices.extend(invoices_lote)
                        
                        # Se retornou menos que o limite, já pegou todas
                        if len(invoices_lote) < limit:
                            break
                        
                        offset += limit
                        logger.info(f"[Webhook] Buscando mais faturas: offset={offset}, já encontradas={len(todas_invoices)}")
                    
                    invoices = todas_invoices
                    logger.info(f"[Webhook] Total de faturas encontradas: {len(invoices)}")
                    
                    if not invoices:
                        # Quando a API retorna 200 mas sem faturas (caso do site que mostra "0 contas pra pagar")
                        # Formatar CPF para exibição (XXX.XXX.XXX-XX)
                        cpf_formatado = f"{cpf_limpo[:3]}.XXX.XXX-{cpf_limpo[-2:]}"
                        resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n✅ *CPF: {cpf_formatado}*\n\nOlá Cliente, você tem *0 contas* pra pagar.\n\nEste CPF não possui faturas em aberto no momento."
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                    else:
                        # Separar faturas por status (aceitar tanto uppercase quanto lowercase)
                        # Status pode vir como "overdue", "OVERDUE", "em aberto", "EM ABERTO", etc
                        todas_faturas = []
                        faturas_atrasadas = []
                        faturas_aberto = []
                        outras = []
                        
                        for inv in invoices:
                            status = str(inv.get('status', '')).upper()
                            if status in ['ATRASADO', 'ATRASADA', 'VENCIDA', 'VENCIDO', 'OVERDUE', 'LATE']:
                                faturas_atrasadas.append(inv)
                            elif status in ['EM ABERTO', 'ABERTO', 'OPEN', 'PENDENTE']:
                                faturas_aberto.append(inv)
                            else:
                                outras.append(inv)  # Incluir outras também
                        
                        # Ordenar: atrasadas primeiro, depois abertas, depois outras
                        todas_faturas = faturas_atrasadas + faturas_aberto + outras
                        
                        logger.info(f"[Webhook] Faturas encontradas: {len(invoices)} total | {len(faturas_atrasadas)} atrasadas | {len(faturas_aberto)} em aberto | {len(outras)} outras")
                        
                        if len(todas_faturas) == 1:
                            # Se só tem uma, mostra direto mas busca PDF também
                            invoice = todas_faturas[0]
                            
                            # Tentar buscar PDF via API primeiro (mais rápido)
                            print(f"[DEBUG PDF] 🔍 ETAPA 1: Tentando buscar PDF via API...")
                            logger.info(f"[DEBUG PDF] 🔍 ETAPA 1: Tentando buscar PDF via API para fatura única")
                            logger.info(f"[DEBUG PDF] Parâmetros: debt_id={invoice.get('debt_id')}, invoice_id={invoice.get('invoice_id')}, cpf={cpf_limpo}, ref={invoice.get('reference_month')}")
                            print(f"[DEBUG PDF] debt_id={invoice.get('debt_id')}, invoice_id={invoice.get('invoice_id')}, cpf={cpf_limpo}")
                            
                            try:
                                from crm_app.nio_api import get_invoice_pdf_url
                                import requests
                                session = requests.Session()
                                
                                api_base = resultado.get('api_base', '')
                                token = resultado.get('token', '')
                                session_id = resultado.get('session_id', '')
                                
                                print(f"[DEBUG PDF] api_base={api_base}, token={'SIM' if token else 'NÃO'}, session_id={'SIM' if session_id else 'NÃO'}")
                                logger.info(f"[DEBUG PDF] api_base={api_base}, token presente={bool(token)}, session_id presente={bool(session_id)}")
                                
                                pdf_url = get_invoice_pdf_url(
                                    api_base,
                                    token,
                                    session_id,
                                    invoice.get('debt_id', ''),
                                    invoice.get('invoice_id', ''),
                                    cpf_limpo,
                                    invoice.get('reference_month', ''),
                                    session
                                )
                                
                                print(f"[DEBUG PDF] Resultado get_invoice_pdf_url: {pdf_url}")
                                logger.info(f"[DEBUG PDF] Resultado get_invoice_pdf_url: {pdf_url}")
                                
                                if pdf_url:
                                    invoice['pdf_url'] = pdf_url
                                    print(f"[DEBUG PDF] ✅ PDF encontrado via API: {pdf_url[:100]}...")
                                    logger.info(f"[DEBUG PDF] ✅ PDF encontrado via API para fatura única: {pdf_url[:100]}...")
                                else:
                                    print(f"[DEBUG PDF] ❌ PDF não encontrado via API (retornou None)")
                                    logger.warning(f"[DEBUG PDF] ❌ PDF não encontrado via API (retornou None)")
                            except Exception as e:
                                print(f"[DEBUG PDF] ❌ ERRO ao buscar PDF via API: {type(e).__name__}: {e}")
                                logger.warning(f"[DEBUG PDF] ❌ Erro ao buscar PDF via API para fatura única: {e}")
                                import traceback
                                logger.error(f"[DEBUG PDF] Traceback: {traceback.format_exc()}")
                                print(f"[DEBUG PDF] Traceback: {traceback.format_exc()}")
                            
                            # Se não encontrou via API, tenta baixar como humano (Playwright)
                            print(f"[DEBUG PDF] 🔍 ETAPA 2: Verificando se precisa baixar via Playwright...")
                            print(f"[DEBUG PDF] invoice.get('pdf_url')={invoice.get('pdf_url')}")
                            print(f"[DEBUG PDF] invoice.get('pdf_path')={invoice.get('pdf_path')}")
                            logger.info(f"[DEBUG PDF] Verificando necessidade de download via Playwright: pdf_url={bool(invoice.get('pdf_url'))}, pdf_path={bool(invoice.get('pdf_path'))}")
                            
                            if not invoice.get('pdf_url') and not invoice.get('pdf_path'):
                                print(f"[DEBUG PDF] 🔍 ETAPA 3: Iniciando download via Playwright...")
                                logger.info(f"[DEBUG PDF] 🔍 ETAPA 3: Tentando baixar PDF como humano para fatura única...")
                                
                                try:
                                    # Importar função diretamente do módulo (função privada)
                                    import crm_app.services_nio as nio_services
                                    mes_ref = invoice.get('reference_month', '')
                                    data_venc = invoice.get('due_date_raw') or invoice.get('data_vencimento', '')
                                    
                                    print(f"[DEBUG PDF] Parâmetros Playwright: CPF={cpf_limpo}, mes_ref={mes_ref}, data_venc={data_venc}")
                                    logger.info(f"[DEBUG PDF] Parâmetros: CPF={cpf_limpo}, mes_ref={mes_ref}, data_venc={data_venc}")
                                    
                                    # Marcar que está processando PDF para evitar webhooks duplicados
                                    if sessao:
                                        sessao.dados_temp['processando_pdf'] = True
                                        sessao.save(update_fields=['dados_temp', 'updated_at'])
                                        print(f"[DEBUG PDF] 🔒 Marcado processando_pdf=True para evitar duplicação")
                                        logger.info(f"[DEBUG PDF] 🔒 Marcado processando_pdf=True")
                                    
                                    pdf_result = nio_services._baixar_pdf_como_humano(cpf_limpo, mes_ref, data_venc)
                                    
                                    # Remover flag de processamento após concluir
                                    if sessao:
                                        sessao.dados_temp.pop('processando_pdf', None)
                                        sessao.save(update_fields=['dados_temp', 'updated_at'])
                                        print(f"[DEBUG PDF] 🔓 Removido processando_pdf após download")
                                        logger.info(f"[DEBUG PDF] 🔓 Removido processando_pdf após download")
                                    
                                    print(f"[DEBUG PDF] Resultado _baixar_pdf_como_humano: {pdf_result}")
                                    print(f"[DEBUG PDF] Tipo do resultado: {type(pdf_result)}")
                                    logger.info(f"[DEBUG PDF] Resultado _baixar_pdf_como_humano: {pdf_result}, tipo: {type(pdf_result)}")
                                    
                                    if pdf_result:
                                        # pdf_result pode ser dict (com local_path e onedrive_url) ou string (caminho antigo)
                                        if isinstance(pdf_result, dict):
                                            invoice['pdf_path'] = pdf_result.get('local_path')
                                            invoice['pdf_onedrive_url'] = pdf_result.get('onedrive_url')
                                            invoice['pdf_filename'] = pdf_result.get('filename')
                                            
                                            print(f"[DEBUG PDF] ✅ PDF baixado (dict): local_path={pdf_result.get('local_path')}, onedrive_url={pdf_result.get('onedrive_url')}")
                                            logger.info(f"[DEBUG PDF] ✅ PDF baixado (dict): local_path={pdf_result.get('local_path')}, onedrive_url={pdf_result.get('onedrive_url')}")
                                            
                                            if pdf_result.get('onedrive_url'):
                                                print(f"[DEBUG PDF] ✅ PDF enviado para OneDrive: {pdf_result['onedrive_url']}")
                                                logger.info(f"[DEBUG PDF] ✅ PDF baixado e enviado para OneDrive (fatura única): {pdf_result['onedrive_url']}")
                                            else:
                                                print(f"[DEBUG PDF] ✅ PDF baixado localmente: {pdf_result['local_path']}")
                                                logger.info(f"[DEBUG PDF] ✅ PDF baixado localmente (fatura única): {pdf_result['local_path']}")
                                        else:
                                            # Compatibilidade com formato antigo (string)
                                            invoice['pdf_path'] = pdf_result
                                            print(f"[DEBUG PDF] ✅ PDF baixado (string): {pdf_result}")
                                            logger.info(f"[DEBUG PDF] ✅ PDF baixado com sucesso para fatura única: {pdf_result}")
                                    else:
                                        print(f"[DEBUG PDF] ❌ Falha ao baixar PDF - retornou None")
                                        logger.warning(f"[DEBUG PDF] ❌ Falha ao baixar PDF como humano para fatura única - retornou None")
                                except Exception as e:
                                    print(f"[DEBUG PDF] ❌ ERRO ao baixar PDF: {type(e).__name__}: {e}")
                                    logger.error(f"[DEBUG PDF] ❌ Erro ao baixar PDF como humano para fatura única: {e}")
                                    import traceback
                                    tb = traceback.format_exc()
                                    logger.error(f"[DEBUG PDF] Traceback completo:\n{tb}")
                                    print(f"[DEBUG PDF] Traceback completo:\n{tb}")
                            else:
                                print(f"[DEBUG PDF] ⏭️ Pulando download via Playwright - PDF já disponível")
                                logger.info(f"[DEBUG PDF] ⏭️ Pulando download via Playwright - PDF já disponível")
                            
                            resposta = _formatar_detalhes_fatura(invoice, cpf_limpo, incluir_pdf=True)
                            
                            # Armazenar invoice para envio do PDF após a mensagem (só se houver PDF disponível)
                            print(f"[DEBUG PDF] 🔍 ETAPA 4: Verificando se PDF está disponível para envio...")
                            print(f"[DEBUG PDF] invoice.get('pdf_path')={invoice.get('pdf_path')}")
                            print(f"[DEBUG PDF] invoice.get('pdf_url')={invoice.get('pdf_url')}")
                            print(f"[DEBUG PDF] invoice.get('pdf_onedrive_url')={invoice.get('pdf_onedrive_url')}")
                            logger.info(f"[DEBUG PDF] Verificando disponibilidade de PDF: pdf_path={bool(invoice.get('pdf_path'))}, pdf_url={bool(invoice.get('pdf_url'))}, pdf_onedrive_url={bool(invoice.get('pdf_onedrive_url'))}")
                            
                            if invoice.get('pdf_path') or invoice.get('pdf_url') or invoice.get('pdf_onedrive_url'):
                                # Se tem pdf_onedrive_url, usar como pdf_url
                                if invoice.get('pdf_onedrive_url') and not invoice.get('pdf_url'):
                                    invoice['pdf_url'] = invoice.get('pdf_onedrive_url')
                                    print(f"[DEBUG PDF] ✅ Usando pdf_onedrive_url como pdf_url: {invoice['pdf_url']}")
                                    logger.info(f"[DEBUG PDF] ✅ Usando pdf_onedrive_url como pdf_url")
                                
                                sessao.dados_temp = {'invoice_para_pdf': invoice}
                                print(f"[DEBUG PDF] ✅ PDF disponível - salvo na sessão para envio")
                                logger.info(f"[DEBUG PDF] ✅ PDF disponível - salvo na sessão para envio")
                            else:
                                sessao.dados_temp = {}
                                print(f"[DEBUG PDF] ❌ PDF NÃO disponível - sessão limpa")
                                logger.warning(f"[DEBUG PDF] ❌ PDF NÃO disponível - sessão limpa")
                            
                            sessao.etapa = 'inicial'
                            sessao.save()
                        else:
                            # Lista todas e pede para escolher
                            resposta_parts = [
                                f"🔎 *FATURAS ENCONTRADAS* para CPF {cpf_limpo}:\n"
                            ]
                            
                            for idx, inv in enumerate(todas_faturas, 1):
                                valor = inv.get('amount', 0)
                                status = inv.get('status', '')
                                data_venc = inv.get('due_date_raw') or inv.get('data_vencimento', '')
                                mes_ref = inv.get('reference_month', '')
                                
                                # Formatar valor
                                valor_str = f"R$ {valor:.2f}" if isinstance(valor, (int, float)) else str(valor)
                                
                                # Ícone de status (aceitar lowercase também)
                                status_upper = str(status).upper()
                                if status_upper in ['ATRASADO', 'ATRASADA', 'VENCIDA', 'VENCIDO', 'OVERDUE', 'LATE']:
                                    emoji = "🔴"
                                elif status_upper in ['EM ABERTO', 'ABERTO', 'OPEN', 'PENDENTE']:
                                    emoji = "🟡"
                                else:
                                    emoji = "⚪"
                                
                                # Formatar data e status
                                data_venc_formatada = _formatar_data_brasileira(data_venc) or data_venc
                                status_pt = _formatar_status_portugues(status)
                                
                                resposta_parts.append(
                                    f"{emoji} *{idx}.* {valor_str} | Venc: {data_venc_formatada} | {status_pt}"
                                )
                                if mes_ref:
                                    resposta_parts.append(f"   📅 Ref: {mes_ref}")
                            
                            resposta_parts.append(
                                f"\n📋 Digite o *NÚMERO* da fatura que deseja ver os detalhes (1 a {len(todas_faturas)}):"
                            )
                            
                            resposta = "\n".join(resposta_parts)
                            
                            # Salvar faturas na sessão para recuperar depois
                            sessao.etapa = 'fatura_selecionar'
                            sessao.dados_temp = {
                                'cpf': cpf_limpo,
                                'faturas': todas_faturas,
                                'token': resultado.get('token'),
                                'api_base': resultado.get('api_base'),
                                'session_id': resultado.get('session_id'),
                            }
                            sessao.save()
                            
                except Exception as e:
                    logger.error(f"[Webhook] Erro ao buscar faturas: {e}")
                    import traceback
                    traceback.print_exc()
                    # Tratamento de erros mais específico
                    erro_msg = str(e)
                    
                    # Verificar apenas formato básico (11 dígitos)
                    # A API da Nio é quem valida se o CPF existe na base deles
                    cpf_formato_valido = cpf_limpo and len(cpf_limpo) == 11 and cpf_limpo.isdigit()
                    
                    # Formatar CPF para exibição (XXX.XXX.XXX-XX)
                    cpf_formatado = f"{cpf_limpo[:3]}.XXX.XXX-{cpf_limpo[-2:]}" if cpf_formato_valido else cpf_limpo
                    
                    if "400" in erro_msg or "Bad Request" in erro_msg:
                        # Erro 400: Pode ser CPF não encontrado na base OU formato inválido
                        # Se o formato está correto, provavelmente existe mas não tem faturas
                        if cpf_formato_valido:
                            # CPF com formato válido mas API retornou 400 - provavelmente não tem faturas
                            resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n✅ *CPF: {cpf_formatado}*\n\nOlá Cliente, você tem *0 contas* pra pagar.\n\nEste CPF não possui faturas em aberto no momento."
                        else:
                            # Formato inválido
                            resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nCPF não encontrado na base da Nio ou dados inválidos.\n\nVerifique se o CPF está correto e tente novamente."
                    elif "401" in erro_msg or "Unauthorized" in erro_msg:
                        resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nErro de autenticação com a API da Nio.\n\nTente novamente em alguns instantes."
                    elif "404" in erro_msg or "Not Found" in erro_msg:
                        # Erro 404: Recurso não encontrado
                        # Se o formato está correto, pode ser que não tenha faturas
                        if cpf_formato_valido:
                            resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n✅ *CPF: {cpf_formatado}*\n\nOlá Cliente, você tem *0 contas* pra pagar.\n\nEste CPF não possui faturas em aberto no momento."
                        else:
                            resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *FATURAS NÃO ENCONTRADAS*\n\nNão encontrei nenhuma fatura para este CPF."
                    else:
                        resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nErro ao buscar faturas: {erro_msg}\n\nTente novamente em alguns instantes."
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
        
        elif etapa_atual == 'fatura_negocia_cpf':
            cpf_limpo = limpar_texto_cep_cpf(mensagem_texto)
            
            # Validar apenas formato básico (11 dígitos)
            cpf_valido = cpf_limpo and len(cpf_limpo) == 11 and cpf_limpo.isdigit()
            
            if not cpf_valido:
                resposta = "❌ CPF inválido. Por favor, digite o CPF completo (11 dígitos, apenas números):"
            else:
                logger.info(f"[Webhook] Buscando fatura via PLANO B (Nio Negocia) para CPF: {cpf_limpo}")
                try:
                    # Importar função do Plano B diretamente
                    import crm_app.services_nio as nio_services
                    
                    # Chamar diretamente o Plano B (sem tentar Plano A)
                    resultado_plano_b = nio_services._buscar_fatura_nio_negocia(
                        cpf_limpo,
                        numero_contrato=None,  # Pode ser passado depois se necessário
                        incluir_pdf=True,
                        mes_referencia=None
                    )
                    
                    if resultado_plano_b and (resultado_plano_b.get('valor') or resultado_plano_b.get('codigo_pix') or resultado_plano_b.get('codigo_barras')):
                        # Formatar como invoice para usar a função de formatação existente
                        # Converter data_vencimento para string se for date object
                        data_venc = resultado_plano_b.get('data_vencimento')
                        if data_venc and hasattr(data_venc, 'strftime'):
                            # Se for date object, converter para string YYYYMMDD
                            data_venc_str = data_venc.strftime('%Y%m%d')
                        else:
                            data_venc_str = data_venc
                        
                        invoice = {
                            'amount': resultado_plano_b.get('valor'),  # Campo esperado pela função de formatação
                            'valor': resultado_plano_b.get('valor'),  # Backup
                            'pix': resultado_plano_b.get('codigo_pix'),  # Campo esperado pela função de formatação
                            'codigo_pix': resultado_plano_b.get('codigo_pix'),  # Backup
                            'barcode': resultado_plano_b.get('codigo_barras'),  # Campo esperado pela função de formatação
                            'codigo_barras': resultado_plano_b.get('codigo_barras'),  # Backup
                            'data_vencimento': data_venc_str,  # String formatada
                            'due_date_raw': data_venc_str,  # Campo esperado pela função de formatação
                            'pdf_url': resultado_plano_b.get('pdf_url'),
                            'pdf_path': resultado_plano_b.get('pdf_path'),
                            'status': 'Pendente',
                            'reference_month': None,
                            'metodo_usado': 'nio_negocia'
                        }
                        
                        # Formatar resposta
                        resposta = _formatar_detalhes_fatura(invoice, cpf_limpo, incluir_pdf=True)
                        
                        # Adicionar informação sobre o método usado
                        resposta += f"\n\n🔧 *Método:* Plano B (Nio Negocia)"
                        
                        # Armazenar invoice para envio do PDF após a mensagem (só se houver PDF disponível)
                        if invoice.get('pdf_path') or invoice.get('pdf_url'):
                            sessao.dados_temp = {'invoice_para_pdf': invoice}
                        else:
                            sessao.dados_temp = {}
                        sessao.etapa = 'inicial'
                        sessao.save()
                        
                        logger.info(f"[Webhook] ✅ Plano B (Nio Negocia) retornou dados válidos")
                    else:
                        # Formatar CPF para exibição
                        cpf_formatado = f"{cpf_limpo[:3]}.XXX.XXX-{cpf_limpo[-2:]}"
                        resposta = f"🔎 Buscando faturas via Plano B (Nio Negocia) para o cliente {cpf_limpo}...\n\n❌ *CPF: {cpf_formatado}*\n\nNão foi possível encontrar faturas usando o método Nio Negocia.\n\nTente usar o comando *Fatura* para buscar pelo método padrão."
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                        logger.warning(f"[Webhook] ⚠️ Plano B (Nio Negocia) não retornou dados válidos")
                        
                except Exception as e:
                    logger.error(f"[Webhook] ❌ Erro ao buscar fatura via Plano B (Nio Negocia): {e}")
                    import traceback
                    traceback.print_exc()
                    resposta = f"❌ Erro ao buscar fatura via Plano B (Nio Negocia): {str(e)}\n\nTente novamente ou use o comando *Fatura* para buscar pelo método padrão."
                    sessao.etapa = 'inicial'
                    sessao.dados_temp = {}
                    sessao.save()
        
        elif etapa_atual == 'material_buscar':
            try:
                busca_texto = mensagem_texto.strip()
                if not busca_texto or len(busca_texto) < 2:
                    resposta = "❌ Por favor, digite pelo menos 2 caracteres para buscar:"
                else:
                    logger.info(f"[Webhook] Buscando materiais com tag: {busca_texto}")
                    from crm_app.models import RecordApoia
                    from django.db.models import Q
                    import base64
                    
                    # Buscar arquivos que contenham a tag na busca (case-insensitive, busca parcial)
                    arquivos = RecordApoia.objects.filter(
                        ativo=True
                    ).filter(
                        Q(tags__icontains=busca_texto) |
                        Q(titulo__icontains=busca_texto) |
                        Q(descricao__icontains=busca_texto) |
                        Q(categoria__icontains=busca_texto)
                    ).order_by('-data_upload')[:5]  # Limitar a 5 resultados
                    
                    if not arquivos.exists():
                        resposta = f"❌ *MATERIAL NÃO ENCONTRADO*\n\nNão encontrei materiais com a tag \"{busca_texto}\".\n\nTente buscar com outras palavras-chave."
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                    else:
                        # Se encontrou apenas 1, enviar direto
                        if arquivos.count() == 1:
                            arquivo = arquivos.first()
                            arquivo.downloads_count += 1
                            arquivo.save(update_fields=['downloads_count'])
                            
                            try:
                                # Ler arquivo do FileField
                                arquivo_field = arquivo.arquivo
                                if not arquivo_field or not arquivo_field.name:
                                    resposta = f"❌ Arquivo \"{arquivo.titulo}\" não encontrado."
                                    sessao.etapa = 'inicial'
                                    sessao.dados_temp = {}
                                    sessao.save()
                                else:
                                    arquivo_bytes = None
                                    arquivo_b64 = None
                                    try:
                                        # Usar storage para ler o arquivo (mais seguro)
                                        from django.core.files.storage import default_storage
                                        
                                        if default_storage.exists(arquivo_field.name):
                                            with default_storage.open(arquivo_field.name, 'rb') as f:
                                                arquivo_bytes = f.read()
                                            arquivo_b64 = base64.b64encode(arquivo_bytes).decode('utf-8')
                                        else:
                                            # Fallback: tentar abrir diretamente
                                            arquivo_field.open('rb')
                                            arquivo_bytes = arquivo_field.read()
                                            arquivo_field.close()
                                            arquivo_b64 = base64.b64encode(arquivo_bytes).decode('utf-8')
                                    except (FileNotFoundError, IOError, OSError) as e:
                                        logger.error(f"[Webhook] Erro ao ler arquivo {arquivo_field.name}: {e}")
                                        resposta = f"❌ Erro ao acessar arquivo \"{arquivo.titulo}\": {str(e)}"
                                        sessao.etapa = 'inicial'
                                        sessao.dados_temp = {}
                                        sessao.save()
                                        arquivo_b64 = None
                                    
                                    if arquivo_b64:
                                        nome_arquivo = arquivo.nome_original
                                        
                                        # Preparar mensagem de resposta
                                        if arquivo.tipo_arquivo == 'IMAGEM':
                                            resposta = f"✅ *MATERIAL ENCONTRADO*\n\n📷 {arquivo.titulo}\n\nEnviando imagem..."
                                            # Armazenar dados do arquivo para envio após a mensagem
                                            sessao.dados_temp = {
                                                'material_para_envio': {
                                                    'tipo': 'IMAGEM',
                                                    'base64': arquivo_b64,
                                                    'nome': nome_arquivo,
                                                    'titulo': arquivo.titulo,
                                                    'descricao': arquivo.descricao
                                                }
                                            }
                                        else:
                                            # DOCUMENTO: Verificar se é grande e fazer upload para OneDrive se necessário
                                            tamanho_bytes = len(arquivo_bytes) if arquivo_bytes else (len(arquivo_b64) * 3 // 4)
                                            tamanho_mb = tamanho_bytes / (1024 * 1024)
                                            
                                            pdf_url = None
                                            usar_url = tamanho_mb > 5  # Usar URL se arquivo > 5MB
                                            
                                            if usar_url:
                                                logger.info(f"[Webhook] Arquivo grande ({tamanho_mb:.2f} MB), fazendo upload para OneDrive...")
                                                try:
                                                    from crm_app.onedrive_service import OneDriveUploader
                                                    from io import BytesIO
                                                    
                                                    # Criar objeto file-like do arquivo_bytes
                                                    file_obj = BytesIO(arquivo_bytes) if arquivo_bytes else BytesIO(base64.b64decode(arquivo_b64))
                                                    
                                                    # Fazer upload para OneDrive
                                                    onedrive = OneDriveUploader()
                                                    pdf_url = onedrive.upload_file_and_get_download_url(
                                                        file_obj, 
                                                        folder_name='WhatsApp_Materiais',
                                                        filename=nome_arquivo
                                                    )
                                                    
                                                    logger.info(f"[Webhook] ✅ Upload para OneDrive concluído: {pdf_url}")
                                                    print(f"[Webhook] ✅ Upload OneDrive: {pdf_url}")
                                                except Exception as e:
                                                    logger.error(f"[Webhook] ❌ Erro ao fazer upload para OneDrive: {e}")
                                                    logger.warning(f"[Webhook] ⚠️ Continuando com base64 como fallback")
                                                    print(f"[Webhook] ❌ Erro OneDrive: {e}, usando base64")
                                                    pdf_url = None
                                            
                                            resposta = f"✅ *MATERIAL ENCONTRADO*\n\n📄 {arquivo.titulo}\nTipo: {arquivo.get_tipo_arquivo_display()}\n\nEnviando arquivo..."
                                            # Armazenar dados do arquivo para envio após a mensagem
                                            material_data = {
                                                'tipo': 'DOCUMENTO',
                                                'nome': nome_arquivo,
                                                'titulo': arquivo.titulo,
                                                'tipo_display': arquivo.get_tipo_arquivo_display()
                                            }
                                            
                                            # Adicionar URL se disponível (preferível), senão base64
                                            if pdf_url:
                                                material_data['url'] = pdf_url
                                                logger.info(f"[Webhook] Material preparado com URL (OneDrive)")
                                            else:
                                                material_data['base64'] = arquivo_b64
                                                logger.info(f"[Webhook] Material preparado com base64")
                                            
                                            sessao.dados_temp = {
                                                'material_para_envio': material_data
                                            }
                                        
                                        sessao.etapa = 'inicial'
                                        sessao.save()
                                        
                                        # Incrementar contador de downloads
                                        arquivo.downloads_count += 1
                                        arquivo.save(update_fields=['downloads_count'])
                            except Exception as e:
                                logger.error(f"[Webhook] Erro ao enviar arquivo: {e}")
                                resposta = f"❌ Erro ao processar arquivo: {str(e)}"
                                sessao.etapa = 'inicial'
                                sessao.dados_temp = {}
                                sessao.save()
                        else:
                            # Múltiplos resultados - listar para escolher
                            # Converter QuerySet para lista ANTES de usar
                            arquivos_lista = list(arquivos)
                            arquivos_ids_lista = [arq.id for arq in arquivos_lista]
                            
                            resposta_parts = [f"📚 *MATERIAIS ENCONTRADOS* para \"{busca_texto}\":\n"]
                            for idx, arq in enumerate(arquivos_lista, 1):
                                resposta_parts.append(f"{idx}. {arq.titulo} ({arq.get_tipo_arquivo_display()})")
                                if arq.descricao:
                                    desc_curta = arq.descricao[:50] + "..." if len(arq.descricao) > 50 else arq.descricao
                                    resposta_parts.append(f"   {desc_curta}")
                            
                            resposta_parts.append(f"\n📋 Digite o *NÚMERO* do material desejado (1 a {len(arquivos_lista)}):")
                            resposta = "\n".join(resposta_parts)
                            
                            # Salvar arquivos na sessão usando save() com update_fields
                            sessao.etapa = 'material_selecionar'
                            sessao.dados_temp = {
                                'busca': busca_texto,
                                'arquivos_ids': arquivos_ids_lista
                            }
                            sessao.save(update_fields=['etapa', 'dados_temp'])
                            logger.info(f"[Webhook] Salvos {len(arquivos_ids_lista)} IDs de arquivos na sessão: {arquivos_ids_lista}")
                            logger.info(f"[Webhook] Sessão salva - etapa: {sessao.etapa}, dados_temp: {sessao.dados_temp}")
            except Exception as e:
                logger.error(f"[Webhook] Erro ao buscar material: {e}")
                import traceback
                traceback.print_exc()
                resposta = f"❌ Erro ao buscar material: {str(e)}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        elif etapa_atual == 'material_selecionar':
            try:
                numero_escolhido = mensagem_texto.strip()
                if not numero_escolhido:
                    resposta = None  # Mensagem vazia: não enviar erro
                elif not numero_escolhido.isdigit():
                    resposta = "❌ Por favor, digite apenas o NÚMERO do material (ex: 1, 2, 3...):"
                else:
                    from crm_app.models import RecordApoia
                    import base64
                    
                    # Buscar sessão diretamente do banco para garantir dados mais recentes
                    from crm_app.models import SessaoWhatsapp
                    sessao_atualizada = SessaoWhatsapp.objects.get(id=sessao.id)
                    dados_temp_atualizado = sessao_atualizada.dados_temp or {}
                    
                    logger.info(f"[Webhook] DEBUG material_selecionar - sessao.id: {sessao_atualizada.id}, etapa: {sessao_atualizada.etapa}")
                    logger.info(f"[Webhook] DEBUG material_selecionar - dados_temp do banco: {dados_temp_atualizado}")
                    logger.info(f"[Webhook] DEBUG material_selecionar - tipo de dados_temp: {type(dados_temp_atualizado)}")
                    
                    idx = int(numero_escolhido) - 1
                    arquivos_ids = dados_temp_atualizado.get('arquivos_ids', [])
                    
                    if not arquivos_ids or len(arquivos_ids) == 0:
                        logger.error(f"[Webhook] arquivos_ids está vazio na sessão! dados_temp: {dados_temp_atualizado}, sessao.id: {sessao_atualizada.id}")
                        logger.error(f"[Webhook] DEBUG - Tentando buscar sessão completa do banco novamente...")
                        # Última tentativa: buscar sessão completa novamente
                        try:
                            sessao_db = SessaoWhatsapp.objects.values('dados_temp', 'etapa').get(id=sessao_atualizada.id)
                            logger.error(f"[Webhook] DEBUG - dados_temp do values(): {sessao_db.get('dados_temp')}, etapa: {sessao_db.get('etapa')}")
                        except Exception as db_error:
                            logger.error(f"[Webhook] DEBUG - Erro ao buscar do banco: {db_error}")
                        
                        resposta = "❌ Erro: Lista de materiais não encontrada. Por favor, busque novamente."
                        sessao_atualizada.etapa = 'inicial'
                        sessao_atualizada.dados_temp = {}
                        sessao_atualizada.save()
                    elif idx < 0 or idx >= len(arquivos_ids):
                        # Não responder: evita mensagem fantasma (webhook duplicado)
                        logger.info(f"[Webhook] material_selecionar: número fora do intervalo ({numero_escolhido}), ignorando sem resposta.")
                        resposta = None
                    else:
                        arquivo_id = arquivos_ids[idx]
                        arquivo = RecordApoia.objects.get(id=arquivo_id, ativo=True)
                        arquivo.downloads_count += 1
                        arquivo.save(update_fields=['downloads_count'])
                        
                        try:
                            # Ler arquivo do FileField
                            arquivo_field = arquivo.arquivo
                            if not arquivo_field or not arquivo_field.name:
                                resposta = f"❌ Arquivo \"{arquivo.titulo}\" não encontrado."
                                sessao.etapa = 'inicial'
                                sessao.dados_temp = {}
                                sessao.save()
                            else:
                                try:
                                    # Tentar ler o arquivo usando o método do FileField
                                    try:
                                        arquivo_field.open('rb')
                                        arquivo_bytes = arquivo_field.read()
                                        arquivo_field.close()
                                    except (FileNotFoundError, IOError, OSError) as e:
                                        logger.error(f"[Webhook] Erro ao ler arquivo (método 1) {arquivo_field.name}: {e}")
                                        # Tentar usar storage como fallback
                                        from django.core.files.storage import default_storage
                                        if default_storage.exists(arquivo_field.name):
                                            with default_storage.open(arquivo_field.name, 'rb') as f:
                                                arquivo_bytes = f.read()
                                        else:
                                            raise e
                                    
                                    arquivo_b64 = base64.b64encode(arquivo_bytes).decode('utf-8')
                                    nome_arquivo = arquivo.nome_original
                                    
                                    # Preparar mensagem de resposta
                                    if arquivo.tipo_arquivo == 'IMAGEM':
                                        resposta = f"✅ *MATERIAL SELECIONADO*\n\n📷 {arquivo.titulo}\n\nEnviando imagem..."
                                        # Armazenar dados do arquivo para envio após a mensagem
                                        sessao.dados_temp = {
                                            'material_para_envio': {
                                                'tipo': 'IMAGEM',
                                                'base64': arquivo_b64,
                                                'nome': nome_arquivo,
                                                'titulo': arquivo.titulo,
                                                'descricao': arquivo.descricao
                                            }
                                        }
                                    else:
                                        # DOCUMENTO: Verificar se é grande e fazer upload para OneDrive se necessário
                                        tamanho_bytes = len(arquivo_bytes) if arquivo_bytes else (len(arquivo_b64) * 3 // 4)
                                        tamanho_mb = tamanho_bytes / (1024 * 1024)
                                        
                                        pdf_url = None
                                        usar_url = tamanho_mb > 5  # Usar URL se arquivo > 5MB
                                        
                                        if usar_url:
                                            logger.info(f"[Webhook] Arquivo grande ({tamanho_mb:.2f} MB), fazendo upload para OneDrive...")
                                            try:
                                                from crm_app.onedrive_service import OneDriveUploader
                                                from io import BytesIO
                                                
                                                # Criar objeto file-like do arquivo_bytes
                                                file_obj = BytesIO(arquivo_bytes) if arquivo_bytes else BytesIO(base64.b64decode(arquivo_b64))
                                                
                                                # Fazer upload para OneDrive
                                                onedrive = OneDriveUploader()
                                                pdf_url = onedrive.upload_file_and_get_download_url(
                                                    file_obj, 
                                                    folder_name='WhatsApp_Materiais',
                                                    filename=nome_arquivo
                                                )
                                                
                                                logger.info(f"[Webhook] ✅ Upload para OneDrive concluído: {pdf_url}")
                                                print(f"[Webhook] ✅ Upload OneDrive: {pdf_url}")
                                            except Exception as e:
                                                logger.error(f"[Webhook] ❌ Erro ao fazer upload para OneDrive: {e}")
                                                logger.warning(f"[Webhook] ⚠️ Continuando com base64 como fallback")
                                                print(f"[Webhook] ❌ Erro OneDrive: {e}, usando base64")
                                                pdf_url = None
                                        
                                        resposta = f"✅ *MATERIAL SELECIONADO*\n\n📄 {arquivo.titulo}\nTipo: {arquivo.get_tipo_arquivo_display()}\n\nEnviando arquivo..."
                                        # Armazenar dados do arquivo para envio após a mensagem
                                        material_data = {
                                            'tipo': 'DOCUMENTO',
                                            'nome': nome_arquivo,
                                            'titulo': arquivo.titulo,
                                            'tipo_display': arquivo.get_tipo_arquivo_display()
                                        }
                                        
                                        # Adicionar URL se disponível (preferível), senão base64
                                        if pdf_url:
                                            material_data['url'] = pdf_url
                                            logger.info(f"[Webhook] Material preparado com URL (OneDrive)")
                                        else:
                                            material_data['base64'] = arquivo_b64
                                            logger.info(f"[Webhook] Material preparado com base64")
                                        
                                        sessao.dados_temp = {
                                            'material_para_envio': material_data
                                        }
                                    
                                    sessao.etapa = 'inicial'
                                    sessao.save()
                                    
                                    # Incrementar contador de downloads
                                    arquivo.downloads_count += 1
                                    arquivo.save(update_fields=['downloads_count'])
                                except (FileNotFoundError, IOError, OSError) as e:
                                    logger.error(f"[Webhook] Erro ao acessar arquivo {arquivo_field.name if arquivo_field else 'N/A'}: {e}")
                                    resposta = f"❌ Arquivo \"{arquivo.titulo}\" não encontrado no servidor. O arquivo pode ter sido removido ou há um problema no armazenamento."
                                    sessao.etapa = 'inicial'
                                    sessao.dados_temp = {}
                                    sessao.save()
                        except Exception as e:
                            logger.error(f"[Webhook] Erro ao enviar arquivo selecionado: {e}")
                            import traceback
                            traceback.print_exc()
                            resposta = f"❌ Erro ao processar arquivo: {str(e)}"
                            sessao.etapa = 'inicial'
                            sessao.dados_temp = {}
                            sessao.save()
            except Exception as e:
                logger.error(f"[Webhook] Erro ao processar seleção de material: {e}")
                resposta = f"❌ Erro ao processar seleção: {str(e)}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        elif etapa_atual == 'fatura_selecionar':
            try:
                numero_escolhido = mensagem_texto.strip()
                if not numero_escolhido:
                    resposta = None  # Mensagem vazia: não enviar erro para não duplicar
                elif not numero_escolhido.isdigit():
                    resposta = "❌ Por favor, digite apenas o NÚMERO da fatura (ex: 1, 2, 3...):"
                else:
                    idx = int(numero_escolhido) - 1
                    faturas = dados_temp.get('faturas', [])
                    
                    if idx < 0 or idx >= len(faturas):
                        # Não responder: evita mensagem fantasma (webhook duplicado com 0, 3, etc.)
                        logger.info(f"[Webhook] fatura_selecionar: número fora do intervalo ({numero_escolhido}), ignorando sem resposta.")
                        resposta = None
                    else:
                        invoice = faturas[idx]
                        cpf = dados_temp.get('cpf', '')
                        
                        # Tentar buscar PDF via API primeiro (mais rápido)
                        try:
                            from crm_app.nio_api import get_invoice_pdf_url
                            token = dados_temp.get('token')
                            api_base = dados_temp.get('api_base')
                            session_id = dados_temp.get('session_id')
                            
                            if token and api_base and session_id:
                                import requests
                                session = requests.Session()
                                pdf_url = get_invoice_pdf_url(
                                    api_base, token, session_id,
                                    invoice.get('debt_id', ''),
                                    invoice.get('invoice_id', ''),
                                    cpf,
                                    invoice.get('reference_month', ''),
                                    session
                                )
                                if pdf_url:
                                    invoice['pdf_url'] = pdf_url
                                    logger.info(f"[Webhook] PDF encontrado via API: {pdf_url[:100]}...")
                        except Exception as e:
                            logger.warning(f"[Webhook] Erro ao buscar PDF via API: {e}")
                        
                        # Se não encontrou via API, tenta baixar como humano (Playwright)
                        if not invoice.get('pdf_url') and not invoice.get('pdf_path'):
                            try:
                                # Importar função diretamente do módulo (função privada)
                                import crm_app.services_nio as nio_services
                                mes_ref = invoice.get('reference_month', '')
                                data_venc = invoice.get('due_date_raw') or invoice.get('data_vencimento', '')
                                
                                logger.info(f"[Webhook] Tentando baixar PDF como humano...")
                                logger.info(f"[Webhook] Parâmetros: CPF={cpf}, mes_ref={mes_ref}, data_venc={data_venc}")
                                
                                # Marcar que está processando PDF para evitar webhooks duplicados
                                if sessao:
                                    sessao.dados_temp['processando_pdf'] = True
                                    sessao.save(update_fields=['dados_temp', 'updated_at'])
                                    print(f"[DEBUG PDF] 🔒 Marcado processando_pdf=True para evitar duplicação")
                                    logger.info(f"[DEBUG PDF] 🔒 Marcado processando_pdf=True")
                                
                                pdf_result = nio_services._baixar_pdf_como_humano(cpf, mes_ref, data_venc)
                                
                                # Remover flag de processamento após concluir
                                if sessao:
                                    sessao.dados_temp.pop('processando_pdf', None)
                                    sessao.save(update_fields=['dados_temp', 'updated_at'])
                                    print(f"[DEBUG PDF] 🔓 Removido processando_pdf após download")
                                    logger.info(f"[DEBUG PDF] 🔓 Removido processando_pdf após download")
                                
                                if pdf_result:
                                    # pdf_result pode ser dict (com local_path e onedrive_url) ou string (caminho antigo)
                                    if isinstance(pdf_result, dict):
                                        invoice['pdf_path'] = pdf_result.get('local_path')
                                        invoice['pdf_onedrive_url'] = pdf_result.get('onedrive_url')
                                        invoice['pdf_filename'] = pdf_result.get('filename')
                                        
                                        if pdf_result.get('onedrive_url'):
                                            logger.info(f"[Webhook] ✅ PDF baixado e enviado para OneDrive: {pdf_result['onedrive_url']}")
                                        else:
                                            logger.info(f"[Webhook] ✅ PDF baixado localmente: {pdf_result['local_path']}")
                                    else:
                                        # Compatibilidade com formato antigo (string)
                                        invoice['pdf_path'] = pdf_result
                                        logger.info(f"[Webhook] ✅ PDF baixado com sucesso: {pdf_result}")
                                else:
                                    logger.warning(f"[Webhook] ⚠️ Falha ao baixar PDF como humano - retornou None")
                            except Exception as e:
                                logger.error(f"[Webhook] ❌ Erro ao baixar PDF como humano: {e}")
                                import traceback
                                traceback.print_exc()
                        
                        # Formatar resposta com detalhes completos
                        resposta = _formatar_detalhes_fatura(invoice, cpf, incluir_pdf=True)
                        
                        # Armazenar invoice para envio do PDF após a mensagem (só se houver PDF disponível)
                        if invoice.get('pdf_path') or invoice.get('pdf_url'):
                            sessao.dados_temp = {'invoice_para_pdf': invoice}
                        else:
                            sessao.dados_temp = {}
                        sessao.etapa = 'inicial'
                        sessao.save()
            except Exception as e:
                logger.error(f"[Webhook] Erro ao processar seleção de fatura: {e}")
                resposta = f"❌ Erro ao processar seleção: {str(e)}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        # === PROCESSAMENTO DE ETAPAS DE VENDA ===
        elif etapa_atual.startswith('venda_'):
            logger.info(f"[Webhook] Processando etapa de venda: {etapa_atual}")
            resposta = _processar_etapa_venda(telefone_formatado, mensagem_texto, sessao, etapa_atual)
        
        else:
            # Menu só aparece quando o usuário pede (MENU/AJUDA). Mensagem não reconhecida não gera resposta.
            resposta = None
            sessao.etapa = 'inicial'
            sessao.dados_temp = {}
            sessao.save()
        
        # PRIMEIRO: Verificar se já há um processamento em andamento para evitar duplicação
        if sessao and sessao.dados_temp.get('processando_pdf'):
            tempo_processamento = timezone.now() - sessao.updated_at
            if tempo_processamento.total_seconds() < 300:  # Menos de 5 minutos
                print(f"[DEBUG] ⚠️ Processamento de PDF já em andamento para {telefone_formatado} (há {tempo_processamento.total_seconds():.1f}s), ignorando webhook duplicado")
                logger.warning(f"[Webhook] Processamento de PDF já em andamento para {telefone_formatado} (há {tempo_processamento.total_seconds():.1f}s), ignorando webhook duplicado")
                return {'status': 'ok', 'mensagem': 'Processamento em andamento'}
            else:
                # Se passou mais de 5 minutos, limpar a flag (pode ter travado)
                print(f"[DEBUG] ⚠️ Flag processando_pdf antiga (há {tempo_processamento.total_seconds():.1f}s), limpando...")
                logger.warning(f"[Webhook] Flag processando_pdf antiga (há {tempo_processamento.total_seconds():.1f}s), limpando...")
                sessao.dados_temp.pop('processando_pdf', None)
                sessao.save(update_fields=['dados_temp', 'updated_at'])
        
        # PRIMEIRO: Verificar se há PDF para enviar e preparar caption com a resposta
        arquivo_enviado = False
        pdf_enviado_com_caption = False
        
        if sessao:
            invoice_para_pdf = sessao.dados_temp.get('invoice_para_pdf')
            material_para_envio = sessao.dados_temp.get('material_para_envio')
            
            if invoice_para_pdf and resposta:
                print(f"[DEBUG PDF] 🔍 ETAPA 5: PDF detectado na sessão, preparando envio com caption...")
                print(f"[DEBUG PDF] invoice_para_pdf keys: {list(invoice_para_pdf.keys())}")
                print(f"[DEBUG PDF] pdf_path={invoice_para_pdf.get('pdf_path')}")
                print(f"[DEBUG PDF] pdf_url={invoice_para_pdf.get('pdf_url')}")
                print(f"[DEBUG PDF] pdf_onedrive_url={invoice_para_pdf.get('pdf_onedrive_url')}")
                logger.info(f"[DEBUG PDF] 🔍 ETAPA 5: PDF detectado, preparando envio com caption...")
                logger.info(f"[DEBUG PDF] invoice_para_pdf keys: {list(invoice_para_pdf.keys())}")
                logger.info(f"[DEBUG PDF] pdf_path={invoice_para_pdf.get('pdf_path')}, pdf_url={invoice_para_pdf.get('pdf_url')}, pdf_onedrive_url={invoice_para_pdf.get('pdf_onedrive_url')}")
                
                # VALIDAÇÃO: Verificar se PDF existe e não está vazio antes de enviar
                pdf_path = invoice_para_pdf.get('pdf_path')
                pdf_valido = False
                
                if pdf_path and os.path.exists(pdf_path):
                    tamanho = os.path.getsize(pdf_path)
                    print(f"[DEBUG PDF] 📊 Validando PDF antes de enviar: {pdf_path}, tamanho: {tamanho} bytes")
                    logger.info(f"[DEBUG PDF] 📊 Validando PDF antes de enviar: {pdf_path}, tamanho: {tamanho} bytes")
                    
                    if tamanho < 100:
                        print(f"[DEBUG PDF] ❌ PDF muito pequeno ({tamanho} bytes), provavelmente vazio")
                        logger.error(f"[DEBUG PDF] ❌ PDF muito pequeno ({tamanho} bytes), provavelmente vazio")
                        # Remover PDF inválido da sessão
                        invoice_para_pdf.pop('pdf_path', None)
                    else:
                        # Verificar cabeçalho PDF
                        try:
                            with open(pdf_path, 'rb') as f:
                                header = f.read(4)
                                if not header.startswith(b'%PDF'):
                                    print(f"[DEBUG PDF] ❌ PDF não tem cabeçalho válido")
                                    logger.error(f"[DEBUG PDF] ❌ PDF não tem cabeçalho válido")
                                    invoice_para_pdf.pop('pdf_path', None)
                                else:
                                    pdf_valido = True
                                    print(f"[DEBUG PDF] ✅ PDF válido: {tamanho} bytes")
                                    logger.info(f"[DEBUG PDF] ✅ PDF válido: {tamanho} bytes")
                        except Exception as e_val:
                            print(f"[DEBUG PDF] ❌ Erro ao validar PDF: {e_val}")
                            logger.error(f"[DEBUG PDF] ❌ Erro ao validar PDF: {e_val}")
                            invoice_para_pdf.pop('pdf_path', None)
                
                # Se PDF é válido, enviar com a resposta como caption
                if pdf_valido or invoice_para_pdf.get('pdf_url') or invoice_para_pdf.get('pdf_onedrive_url'):
                    # Usar a resposta formatada como caption
                    caption_para_pdf = resposta
                    print(f"[DEBUG PDF] 📝 Enviando PDF com caption (primeiros 100 chars): {caption_para_pdf[:100]}...")
                    logger.info(f"[DEBUG PDF] 📝 Enviando PDF com caption")
                    
                    resultado_envio = _enviar_pdf_whatsapp(whatsapp_service, telefone_formatado, invoice_para_pdf, caption=caption_para_pdf)
                    print(f"[DEBUG PDF] Resultado do envio: {resultado_envio}")
                    logger.info(f"[DEBUG PDF] Resultado do envio: {resultado_envio}")
                    if resultado_envio:
                        arquivo_enviado = True
                        pdf_enviado_com_caption = True
                        # Enviar mensagem imediatamente após o PDF para aparecer junto
                        # (Z-API pode não suportar caption diretamente, então enviamos como mensagem separada)
                        print(f"[DEBUG PDF] 📨 Enviando mensagem imediatamente após PDF para aparecer junto...")
                        logger.info(f"[DEBUG PDF] 📨 Enviando mensagem imediatamente após PDF")
                        try:
                            sucesso_msg, resultado_msg = whatsapp_service.enviar_mensagem_texto(telefone_formatado, resposta)
                            if sucesso_msg:
                                print(f"[DEBUG PDF] ✅ Mensagem enviada após PDF")
                                logger.info(f"[DEBUG PDF] ✅ Mensagem enviada após PDF")
                            else:
                                print(f"[DEBUG PDF] ⚠️ Erro ao enviar mensagem após PDF: {resultado_msg}")
                                logger.warning(f"[DEBUG PDF] ⚠️ Erro ao enviar mensagem após PDF: {resultado_msg}")
                        except Exception as e_msg:
                            print(f"[DEBUG PDF] ❌ Exceção ao enviar mensagem após PDF: {e_msg}")
                            logger.error(f"[DEBUG PDF] ❌ Exceção ao enviar mensagem após PDF: {e_msg}")
                        
                        # IMPORTANTE: Limpar resposta para não enviar mensagem duplicada
                        resposta = None
                        pdf_enviado_com_caption = True  # Garantir que está marcado
                        print(f"[DEBUG PDF] ✅ PDF e mensagem enviados, resposta limpa (None), pdf_enviado_com_caption={pdf_enviado_com_caption}")
                        logger.info(f"[DEBUG PDF] ✅ PDF e mensagem enviados, resposta limpa (None), pdf_enviado_com_caption={pdf_enviado_com_caption}")
                    else:
                        # Se PDF não foi enviado, manter resposta para enviar normalmente
                        print(f"[DEBUG PDF] ⚠️ PDF não foi enviado, resposta será enviada normalmente")
                        logger.warning(f"[DEBUG PDF] ⚠️ PDF não foi enviado, resposta será enviada normalmente")
                    
            elif material_para_envio:
                logger.info(f"[Webhook] Material detectado, enviando ANTES da mensagem...")
                try:
                    import base64
                    if material_para_envio['tipo'] == 'IMAGEM':
                        caption = f"📷 {material_para_envio['titulo']}"
                        if material_para_envio.get('descricao'):
                            caption += f"\n{material_para_envio['descricao'][:100]}"
                        resultado_img = whatsapp_service.enviar_imagem_b64(telefone_formatado, material_para_envio['base64'], caption)
                        if resultado_img:
                            logger.info(f"[Webhook] ✅ Imagem enviada com sucesso: {material_para_envio['nome']}")
                            arquivo_enviado = True
                        else:
                            logger.error(f"[Webhook] ❌ Falha ao enviar imagem: {material_para_envio['nome']}")
                    else:  # DOCUMENTO
                        logger.info(f"[Webhook] 📄 Preparando envio de DOCUMENTO")
                        pdf_url = material_para_envio.get('url')
                        base64_data = material_para_envio.get('base64', '')
                        
                        if pdf_url:
                            logger.info(f"[Webhook] Enviando documento via URL")
                            sucesso = whatsapp_service.enviar_pdf_url(telefone_formatado, pdf_url, material_para_envio['nome'])
                        elif base64_data:
                            logger.info(f"[Webhook] Enviando documento via base64")
                            sucesso = whatsapp_service.enviar_pdf_b64(telefone_formatado, base64_data, material_para_envio['nome'])
                        else:
                            logger.error(f"[Webhook] ❌ Nenhum dado disponível")
                            sucesso = False
                        
                        if sucesso:
                            logger.info(f"[Webhook] ✅ Documento enviado com sucesso: {material_para_envio['nome']}")
                            arquivo_enviado = True
                        else:
                            logger.error(f"[Webhook] ❌ Falha ao enviar documento: {material_para_envio['nome']}")
                except Exception as e:
                    logger.error(f"[Webhook] ❌ Erro ao enviar material: {e}")
                    import traceback
                    traceback.print_exc()
        
        # DEPOIS: Enviar resposta via WhatsApp (só se houver resposta para enviar E PDF não foi enviado com caption)
        # IMPORTANTE: Verificar se resposta não é None, não está vazia e se PDF não foi enviado com caption
        if resposta and resposta.strip() and not pdf_enviado_com_caption:
            print(f"[DEBUG] Enviando resposta final: resposta não é None={resposta is not None}, pdf_enviado_com_caption={pdf_enviado_com_caption}")
            logger.info(f"[Webhook] Enviando resposta final: pdf_enviado_com_caption={pdf_enviado_com_caption}")
            try:
                logger.info(f"[Webhook] Preparando para enviar resposta para {telefone_formatado}")
                logger.info(f"[Webhook] Resposta a ser enviada: {resposta[:100]}...")
                
                # Dividir mensagem se muito longa (limite WhatsApp ~4096 caracteres)
                mensagens = [resposta[i:i+4000] for i in range(0, len(resposta), 4000)]
                logger.info(f"[Webhook] Dividindo em {len(mensagens)} mensagem(ns)")
                
                for idx, msg in enumerate(mensagens):
                    logger.info(f"[Webhook] Enviando mensagem {idx+1}/{len(mensagens)} para {telefone_formatado}")
                    sucesso, resultado = whatsapp_service.enviar_mensagem_texto(telefone_formatado, msg)
                    if sucesso:
                        logger.info(f"[Webhook] Mensagem {idx+1} enviada com sucesso: {resultado}")
                    else:
                        logger.error(f"[Webhook] Erro ao enviar mensagem {idx+1}: {resultado}")
                
                logger.info(f"[Webhook] Resposta enviada para {telefone_formatado}")
                
                # Limpar dados temporários APENAS se arquivo foi enviado E não estamos na etapa material_selecionar
                # (precisamos manter arquivos_ids na etapa material_selecionar para o usuário escolher)
                if arquivo_enviado and sessao and sessao.etapa != 'material_selecionar':
                    sessao.dados_temp = {}
                    sessao.save(update_fields=['dados_temp'])
                    logger.info(f"[Webhook] Dados temporários limpos após envio de arquivo")
            except Exception as e:
                logger.error(f"[Webhook] Erro ao enviar resposta: {e}")
                import traceback
                traceback.print_exc()
                return {'status': 'erro', 'mensagem': f'Erro ao enviar resposta: {str(e)}'}
        
        return {'status': 'ok', 'mensagem': 'Processado com sucesso'}
    
    except Exception as e:
        logger.exception(f"[Webhook] Erro ao processar mensagem: {e}")
        return {'status': 'erro', 'mensagem': str(e)}
