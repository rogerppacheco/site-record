# crm_app/whatsapp_webhook_handler.py
"""
Handler para processar mensagens do WhatsApp e executar comandos:
- Fachada
- Viabilidade  
- Status
- Fatura
"""
import re
import logging
from datetime import datetime
from django.utils import timezone

logger = logging.getLogger(__name__)


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


def _enviar_pdf_whatsapp(whatsapp_service, telefone, invoice):
    """
    Envia o PDF da fatura via WhatsApp se estiver disponível localmente.
    Retorna True se enviou com sucesso, False caso contrário.
    """
    pdf_path = invoice.get('pdf_path', '')
    pdf_filename = invoice.get('pdf_filename', 'fatura.pdf')
    
    if not pdf_path:
        return False
    
    try:
        import os
        import base64
        
        # Verificar se o arquivo existe
        if not os.path.exists(pdf_path):
            logger.warning(f"[Webhook] PDF não encontrado no caminho: {pdf_path}")
            return False
        
        # Ler arquivo e converter para base64
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
            pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        # Enviar via WhatsApp
        logger.info(f"[Webhook] Enviando PDF via WhatsApp: {pdf_filename} ({len(pdf_bytes)} bytes)")
        sucesso = whatsapp_service.enviar_pdf_b64(telefone, pdf_base64, pdf_filename)
        
        if sucesso:
            logger.info(f"[Webhook] ✅ PDF enviado com sucesso via WhatsApp: {pdf_filename}")
        else:
            logger.warning(f"[Webhook] ⚠️ Falha ao enviar PDF via WhatsApp: {pdf_filename}")
        
        return sucesso
    except Exception as e:
        logger.error(f"[Webhook] ❌ Erro ao enviar PDF via WhatsApp: {e}")
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
        resposta_parts.append(f"\n💳 *PIX:*\n`{codigo_pix}`")
    
    # Código de barras
    codigo_barras = invoice.get('barcode', '') or invoice.get('codigo_barras', '')
    if codigo_barras:
        resposta_parts.append(f"\n📄 *Código de Barras:*\n`{codigo_barras}`")
    
    # PDF (se solicitado e disponível)
    if incluir_pdf:
        pdf_url = invoice.get('pdf_url', '')
        pdf_onedrive_url = invoice.get('pdf_onedrive_url', '')
        pdf_path = invoice.get('pdf_path', '')
        pdf_filename = invoice.get('pdf_filename', '')
        
        if pdf_onedrive_url:
            resposta_parts.append(f"\n📎 *PDF:* {pdf_onedrive_url}")
            resposta_parts.append(f"   💾 Arquivo: {pdf_filename}")
        elif pdf_url:
            resposta_parts.append(f"\n📎 *PDF:* {pdf_url}")
        elif pdf_path:
            resposta_parts.append(f"\n📎 *PDF:* Salvo localmente em {pdf_path}")
            if pdf_filename:
                resposta_parts.append(f"   📄 Arquivo: {pdf_filename}")
        else:
            resposta_parts.append(f"\n⚠️ *PDF:* Não disponível no momento")
    
    return "\n".join(resposta_parts)


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
        consultar_status_venda
    )
    from crm_app.nio_api import consultar_dividas_nio
    
    # Log completo do payload recebido para debug
    logger.info(f"[Webhook] Payload completo recebido: {data}")
    logger.info(f"[Webhook] Tipo do payload: {type(data)}")
    logger.info(f"[Webhook] Chaves disponíveis: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")
    
    # Extrair telefone e mensagem do payload
    telefone = data.get('phone') or data.get('from') or data.get('phoneNumber') or data.get('phone_number')
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
    
    etapa_atual = sessao.etapa
    dados_temp = sessao.dados_temp or {}
    
    try:
        # Identificar comando ou processar resposta
        resposta = None
        
        # === COMANDOS INICIAIS ===
        logger.info(f"[Webhook] Verificando comando. Mensagem limpa: '{mensagem_limpa}'")
        logger.info(f"[Webhook] Mensagem original: '{mensagem_texto}'")
        logger.info(f"[Webhook] Etapa atual: {etapa_atual}")
        
        # Verificação mais flexível - aceita comandos com ou sem acentuação, maiúsculas/minúsculas
        mensagem_sem_acentos = mensagem_limpa.replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U')
        
        if 'FACHADA' in mensagem_limpa or 'FACADA' in mensagem_limpa:
            logger.info(f"[Webhook] Comando FACHADA reconhecido!")
            sessao.etapa = 'fachada_cep'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "🏢 *CONSULTA MASSIVA (DFV)*\n\nEu vou listar todos os números viáveis de uma rua.\nPor favor, digite o CEP (somente números):"
            logger.info(f"[Webhook] Resposta preparada para FACHADA: {resposta[:50]}...")
            _registrar_estatistica(telefone_formatado, 'FACHADA')
        
        elif 'VIABILIDADE' in mensagem_limpa or 'VIABIL' in mensagem_limpa:
            logger.info(f"[Webhook] Comando VIABILIDADE reconhecido!")
            sessao.etapa = 'viabilidade_cep'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "🗺️ *CONSULTA VIABILIDADE (KMZ)*\n\nIdentifiquei que você quer consultar a mancha.\nPor favor, digite o CEP:"
            logger.info(f"[Webhook] Resposta preparada para VIABILIDADE: {resposta[:50]}...")
            _registrar_estatistica(telefone_formatado, 'VIABILIDADE')
        
        elif mensagem_limpa in ['STATUS', 'STAT']:
            sessao.etapa = 'status_tipo'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "📋 *CONSULTA DE STATUS*\n\nComo deseja pesquisar o pedido?\n\n1️⃣ Por CPF\n2️⃣ Por O.S (Ordem de Serviço)\n\nDigite o número da opção (1 ou 2):"
            _registrar_estatistica(telefone_formatado, 'STATUS')
        
        elif mensagem_limpa in ['FATURA', 'FAT']:
            sessao.etapa = 'fatura_cpf'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "💳 *CONSULTA DE FATURA NIO*\n\nPor favor, digite o CPF ou ID do cliente para buscar a fatura:"
            _registrar_estatistica(telefone_formatado, 'FATURA')
        
        elif mensagem_limpa in ['MATERIAL', 'MATERIAIS']:
            logger.info(f"[Webhook] Comando MATERIAL reconhecido!")
            sessao.etapa = 'material_buscar'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "📚 *MATERIAIS*\n\nQual material você precisa?\n\nDigite uma palavra-chave ou tag para buscar (ex: manual, treinamento, tutorial):"
            logger.info(f"[Webhook] Resposta preparada para MATERIAL")
            _registrar_estatistica(telefone_formatado, 'MATERIAL')
        
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
                "• *Material* - Buscar materiais/documentos"
            )
            logger.info(f"[Webhook] Resposta preparada para MENU/AJUDA")
        
        # === PROCESSAMENTO POR ETAPA ===
        elif etapa_atual == 'fachada_cep':
            cep_limpo = limpar_texto_cep_cpf(mensagem_texto)
            if not cep_limpo or len(cep_limpo) < 8:
                resposta = "❌ CEP inválido. Por favor, digite o CEP completo (somente números):"
            else:
                logger.info(f"[Webhook] Buscando fachadas para CEP: {cep_limpo}")
                resposta_lista = listar_fachadas_dfv(cep_limpo)
                if isinstance(resposta_lista, list):
                    # listar_fachadas_dfv retorna lista de strings (mensagens divididas)
                    resposta = "🔎 Buscando todas as fachadas no DFV...\n\n" + "\n".join(resposta_lista)
                else:
                    resposta = f"🔎 Buscando todas as fachadas no DFV...\n\n{resposta_lista}"
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
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
            if not cpf_limpo or len(cpf_limpo) < 11:
                resposta = "❌ CPF inválido. Por favor, digite o CPF completo (apenas números):"
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
                        resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *FATURAS NÃO ENCONTRADAS*\n\nNão encontrei nenhuma fatura para este CPF."
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
                            try:
                                from crm_app.nio_api import get_invoice_pdf_url
                                import requests
                                session = requests.Session()
                                pdf_url = get_invoice_pdf_url(
                                    resultado.get('api_base', ''),
                                    resultado.get('token', ''),
                                    resultado.get('session_id', ''),
                                    invoice.get('debt_id', ''),
                                    invoice.get('invoice_id', ''),
                                    cpf_limpo,
                                    invoice.get('reference_month', ''),
                                    session
                                )
                                if pdf_url:
                                    invoice['pdf_url'] = pdf_url
                                    logger.info(f"[Webhook] PDF encontrado via API para fatura única: {pdf_url[:100]}...")
                            except Exception as e:
                                logger.warning(f"[Webhook] Erro ao buscar PDF via API para fatura única: {e}")
                            
                            # Se não encontrou via API, tenta baixar como humano (Playwright)
                            if not invoice.get('pdf_url') and not invoice.get('pdf_path'):
                                try:
                                    # Importar função diretamente do módulo (função privada)
                                    import crm_app.services_nio as nio_services
                                    mes_ref = invoice.get('reference_month', '')
                                    data_venc = invoice.get('due_date_raw') or invoice.get('data_vencimento', '')
                                    
                                    logger.info(f"[Webhook] Tentando baixar PDF como humano para fatura única...")
                                    logger.info(f"[Webhook] Parâmetros: CPF={cpf_limpo}, mes_ref={mes_ref}, data_venc={data_venc}")
                                    
                                    pdf_result = nio_services._baixar_pdf_como_humano(cpf_limpo, mes_ref, data_venc)
                                    
                                    if pdf_result:
                                        # pdf_result pode ser dict (com local_path e onedrive_url) ou string (caminho antigo)
                                        if isinstance(pdf_result, dict):
                                            invoice['pdf_path'] = pdf_result.get('local_path')
                                            invoice['pdf_onedrive_url'] = pdf_result.get('onedrive_url')
                                            invoice['pdf_filename'] = pdf_result.get('filename')
                                            
                                            if pdf_result.get('onedrive_url'):
                                                logger.info(f"[Webhook] ✅ PDF baixado e enviado para OneDrive (fatura única): {pdf_result['onedrive_url']}")
                                            else:
                                                logger.info(f"[Webhook] ✅ PDF baixado localmente (fatura única): {pdf_result['local_path']}")
                                        else:
                                            # Compatibilidade com formato antigo (string)
                                            invoice['pdf_path'] = pdf_result
                                            logger.info(f"[Webhook] ✅ PDF baixado com sucesso para fatura única: {pdf_result}")
                                    else:
                                        logger.warning(f"[Webhook] ⚠️ Falha ao baixar PDF como humano para fatura única - retornou None")
                                except Exception as e:
                                    logger.error(f"[Webhook] ❌ Erro ao baixar PDF como humano para fatura única: {e}")
                                    import traceback
                                    traceback.print_exc()
                            
                            resposta = _formatar_detalhes_fatura(invoice, cpf_limpo, incluir_pdf=True)
                            
                            # Armazenar invoice para envio do PDF após a mensagem (só se houver PDF disponível)
                            if invoice.get('pdf_path') or invoice.get('pdf_url'):
                                sessao.dados_temp = {'invoice_para_pdf': invoice}
                            else:
                                sessao.dados_temp = {}
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
                    if "400" in erro_msg or "Bad Request" in erro_msg:
                        resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nCPF não encontrado na base da Nio ou dados inválidos.\n\nVerifique se o CPF está correto e tente novamente."
                    elif "401" in erro_msg or "Unauthorized" in erro_msg:
                        resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nErro de autenticação com a API da Nio.\n\nTente novamente em alguns instantes."
                    elif "404" in erro_msg or "Not Found" in erro_msg:
                        resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *FATURAS NÃO ENCONTRADAS*\n\nNão encontrei nenhuma fatura para este CPF."
                    else:
                        resposta = f"🔎 Buscando faturas para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nErro ao buscar faturas: {erro_msg}\n\nTente novamente em alguns instantes."
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
                    import os
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
                                            resposta = f"✅ *MATERIAL ENCONTRADO*\n\n📄 {arquivo.titulo}\nTipo: {arquivo.get_tipo_arquivo_display()}\n\nEnviando arquivo..."
                                            # Armazenar dados do arquivo para envio após a mensagem
                                            sessao.dados_temp = {
                                                'material_para_envio': {
                                                    'tipo': 'DOCUMENTO',
                                                    'base64': arquivo_b64,
                                                    'nome': nome_arquivo,
                                                    'titulo': arquivo.titulo,
                                                    'tipo_display': arquivo.get_tipo_arquivo_display()
                                                }
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
                            
                            # Salvar arquivos na sessão
                            sessao.etapa = 'material_selecionar'
                            sessao.dados_temp = {
                                'busca': busca_texto,
                                'arquivos_ids': arquivos_ids_lista
                            }
                            sessao.save()
                            logger.info(f"[Webhook] Salvos {len(arquivos_ids_lista)} IDs de arquivos na sessão")
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
                if not numero_escolhido.isdigit():
                    resposta = "❌ Por favor, digite apenas o NÚMERO do material (ex: 1, 2, 3...):"
                else:
                    from crm_app.models import RecordApoia
                    import os
                    import base64
                    
                    idx = int(numero_escolhido) - 1
                    arquivos_ids = dados_temp.get('arquivos_ids', [])
                    
                    if not arquivos_ids or len(arquivos_ids) == 0:
                        logger.error(f"[Webhook] arquivos_ids está vazio na sessão! dados_temp: {dados_temp}")
                        resposta = "❌ Erro: Lista de materiais não encontrada. Por favor, busque novamente."
                        sessao.etapa = 'inicial'
                        sessao.dados_temp = {}
                        sessao.save()
                    elif idx < 0 or idx >= len(arquivos_ids):
                        resposta = f"❌ Número inválido. Por favor, digite um número entre 1 e {len(arquivos_ids)}:"
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
                                        resposta = f"✅ *MATERIAL SELECIONADO*\n\n📄 {arquivo.titulo}\nTipo: {arquivo.get_tipo_arquivo_display()}\n\nEnviando arquivo..."
                                        # Armazenar dados do arquivo para envio após a mensagem
                                        sessao.dados_temp = {
                                            'material_para_envio': {
                                                'tipo': 'DOCUMENTO',
                                                'base64': arquivo_b64,
                                                'nome': nome_arquivo,
                                                'titulo': arquivo.titulo,
                                                'tipo_display': arquivo.get_tipo_arquivo_display()
                                            }
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
                if not numero_escolhido.isdigit():
                    resposta = "❌ Por favor, digite apenas o NÚMERO da fatura (ex: 1, 2, 3...):"
                else:
                    idx = int(numero_escolhido) - 1
                    faturas = dados_temp.get('faturas', [])
                    
                    if idx < 0 or idx >= len(faturas):
                        resposta = f"❌ Número inválido. Por favor, digite um número entre 1 e {len(faturas)}:"
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
                                
                                pdf_result = nio_services._baixar_pdf_como_humano(cpf, mes_ref, data_venc)
                                
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
        
        else:
            # Mensagem não reconhecida - mas só mostrar se realmente for um comando novo
            # Se a sessão acabou de mostrar uma fatura ou outro resultado, não mostrar erro imediatamente
            # (pode ser uma resposta automática ou confirmação do usuário)
            
            # Ignorar mensagens muito curtas ou que parecem ser confirmações
            if len(mensagem_texto.strip()) <= 2 and mensagem_texto.strip().isdigit():
                # Pode ser um número de confirmação que não foi processado corretamente
                resposta = None  # Não enviar resposta de erro
            elif etapa_atual == 'inicial' and mensagem_limpa not in ['FATURA', 'FACHADA', 'VIABILIDADE', 'STATUS', 'STAT', 'VIABIL', 'FACADA', 'FAT', 'MENU', 'AJUDA', 'HELP', 'OPCOES', 'OPÇÕES', 'OPCOES', 'OPÇOES', 'MATERIAL', 'MATERIAIS']:
                # Tentar buscar nas tags do Record Apoia antes de ignorar
                from crm_app.models import RecordApoia
                from django.db.models import Q
                import base64
                import os
                
                try:
                    # Buscar materiais por tag/palavra-chave
                    busca_texto = mensagem_texto.strip()
                    arquivos = RecordApoia.objects.filter(
                        ativo=True
                    ).filter(
                        Q(tags__icontains=busca_texto) |
                        Q(titulo__icontains=busca_texto) |
                        Q(descricao__icontains=busca_texto) |
                        Q(categoria__icontains=busca_texto)
                    )[:5]  # Limitar a 5 resultados
                    
                    if arquivos.exists():
                        logger.info(f"[Webhook] Material encontrado via tag/palavra-chave: {busca_texto}")
                        if arquivos.count() == 1:
                            # Um único resultado - enviar diretamente
                            arquivo = arquivos.first()
                            arquivo.downloads_count += 1
                            arquivo.save(update_fields=['downloads_count'])
                            
                            try:
                                # Ler arquivo do FileField
                                arquivo_field = arquivo.arquivo
                                if not arquivo_field:
                                    resposta = f"❌ Arquivo \"{arquivo.titulo}\" não encontrado."
                                else:
                                    # Verificar se o arquivo existe
                                    if not arquivo_field.name:
                                        resposta = f"❌ Arquivo \"{arquivo.titulo}\" não tem nome de arquivo."
                                    else:
                                        try:
                                            arquivo_field.open('rb')
                                            arquivo_bytes = arquivo_field.read()
                                            arquivo_field.close()
                                            arquivo_b64 = base64.b64encode(arquivo_bytes).decode('utf-8')
                                            
                                            nome_arquivo = arquivo.nome_original
                                            
                                            # Preparar mensagem de resposta
                                            if arquivo.tipo_arquivo == 'IMAGEM':
                                                resposta = f"✅ *MATERIAL ENCONTRADO*\n\n📷 {arquivo.titulo}\n\nEnviando imagem..."
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
                                                resposta = f"✅ *MATERIAL ENCONTRADO*\n\n📄 {arquivo.titulo}\nTipo: {arquivo.get_tipo_arquivo_display()}\n\nEnviando arquivo..."
                                                sessao.dados_temp = {
                                                    'material_para_envio': {
                                                        'tipo': 'DOCUMENTO',
                                                        'base64': arquivo_b64,
                                                        'nome': nome_arquivo,
                                                        'titulo': arquivo.titulo,
                                                        'tipo_display': arquivo.get_tipo_arquivo_display()
                                                    }
                                                }
                                            
                                            sessao.etapa = 'inicial'
                                            sessao.save()
                                        except (FileNotFoundError, IOError, OSError) as e:
                                            logger.error(f"[Webhook] Erro ao ler arquivo {arquivo_field.name}: {e}")
                                            resposta = f"❌ Erro ao acessar arquivo \"{arquivo.titulo}\": {str(e)}"
                                            sessao.etapa = 'inicial'
                                            sessao.dados_temp = {}
                                            sessao.save()
                            except Exception as e:
                                logger.error(f"[Webhook] Erro ao enviar arquivo por tag: {e}")
                                resposta = f"❌ Erro ao processar arquivo: {str(e)}"
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
                            
                            # Salvar arquivos na sessão
                            sessao.etapa = 'material_selecionar'
                            sessao.dados_temp = {
                                'busca': busca_texto,
                                'arquivos_ids': arquivos_ids_lista
                            }
                            sessao.save()
                            logger.info(f"[Webhook] Salvos {len(arquivos_ids_lista)} IDs de arquivos na sessão")
                        _registrar_estatistica(telefone_formatado, 'MATERIAL')
                    else:
                        # Nenhum material encontrado - não enviar resposta (não mostrar menu automaticamente)
                        resposta = None
                        logger.info(f"[Webhook] Nenhum material encontrado para '{busca_texto}' e não é comando conhecido. Ignorando mensagem.")
                except Exception as e:
                    logger.error(f"[Webhook] Erro ao buscar material por tag: {e}")
                    resposta = None  # Não enviar resposta de erro
            else:
                resposta = None  # Não enviar resposta se estiver em meio a um fluxo
        
        # Enviar resposta via WhatsApp (só se houver resposta para enviar)
        if resposta:
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
                
                # Verificar se há arquivo para enviar após a mensagem de texto
                if sessao:
                    invoice_para_pdf = sessao.dados_temp.get('invoice_para_pdf')
                    material_para_envio = sessao.dados_temp.get('material_para_envio')
                    
                    if invoice_para_pdf:
                        logger.info(f"[Webhook] PDF detectado, tentando enviar via WhatsApp...")
                        _enviar_pdf_whatsapp(whatsapp_service, telefone_formatado, invoice_para_pdf)
                    
                    elif material_para_envio:
                        logger.info(f"[Webhook] Material detectado, tentando enviar via WhatsApp...")
                        try:
                            import base64
                            if material_para_envio['tipo'] == 'IMAGEM':
                                caption = f"📷 {material_para_envio['titulo']}"
                                if material_para_envio.get('descricao'):
                                    caption += f"\n{material_para_envio['descricao'][:100]}"
                                resultado_img = whatsapp_service.enviar_imagem_b64(telefone_formatado, material_para_envio['base64'], caption)
                                if resultado_img:
                                    logger.info(f"[Webhook] ✅ Imagem enviada com sucesso: {material_para_envio['nome']}")
                                else:
                                    logger.error(f"[Webhook] ❌ Falha ao enviar imagem: {material_para_envio['nome']}")
                            else:  # DOCUMENTO
                                sucesso = whatsapp_service.enviar_pdf_b64(telefone_formatado, material_para_envio['base64'], material_para_envio['nome'])
                                if sucesso:
                                    logger.info(f"[Webhook] ✅ Documento enviado com sucesso: {material_para_envio['nome']}")
                                else:
                                    logger.error(f"[Webhook] ❌ Falha ao enviar documento: {material_para_envio['nome']}")
                        except Exception as e:
                            logger.error(f"[Webhook] ❌ Erro ao enviar material: {e}")
                            import traceback
                            traceback.print_exc()
                    
                    # Limpar dados temporários após enviar arquivo
                    if sessao.dados_temp:
                        sessao.dados_temp = {}
                        sessao.save()
            except Exception as e:
                logger.error(f"[Webhook] Erro ao enviar resposta: {e}")
                import traceback
                traceback.print_exc()
                return {'status': 'erro', 'mensagem': f'Erro ao enviar resposta: {str(e)}'}
        
        return {'status': 'ok', 'mensagem': 'Processado com sucesso'}
    
    except Exception as e:
        logger.exception(f"[Webhook] Erro ao processar mensagem: {e}")
        return {'status': 'erro', 'mensagem': str(e)}
