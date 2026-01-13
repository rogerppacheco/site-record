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
    
    # Tentar múltiplos formatos de mensagem
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
    
    logger.info(f"[Webhook] Telefone extraído: {telefone}")
    logger.info(f"[Webhook] Mensagem extraída: {mensagem_texto}")
    
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
        
        elif 'VIABILIDADE' in mensagem_limpa or 'VIABIL' in mensagem_limpa:
            logger.info(f"[Webhook] Comando VIABILIDADE reconhecido!")
            sessao.etapa = 'viabilidade_cep'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "🗺️ *CONSULTA VIABILIDADE (KMZ)*\n\nIdentifiquei que você quer consultar a mancha.\nPor favor, digite o CEP:"
            logger.info(f"[Webhook] Resposta preparada para VIABILIDADE: {resposta[:50]}...")
        
        elif mensagem_limpa in ['STATUS', 'STAT']:
            sessao.etapa = 'status_tipo'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "📋 *CONSULTA DE STATUS*\n\nComo deseja pesquisar o pedido?\n\n1️⃣ Por CPF\n2️⃣ Por O.S (Ordem de Serviço)\n\nDigite o número da opção (1 ou 2):"
        
        elif mensagem_limpa in ['FATURA', 'FAT']:
            sessao.etapa = 'fatura_cpf'
            sessao.dados_temp = {}
            sessao.save()
            resposta = "💳 *CONSULTA DE FATURA NIO*\n\nPor favor, digite o CPF ou ID do cliente para buscar a fatura:"
        
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
            if not cpf_limpo:
                resposta = "❌ CPF inválido. Por favor, digite o CPF (apenas números):"
            else:
                logger.info(f"[Webhook] Buscando fatura para CPF: {cpf_limpo}")
                try:
                    resultado = consultar_dividas_nio(cpf_limpo, offset=0, limit=1, headless=True)
                    invoices = resultado.get('invoices', [])
                    
                    if not invoices:
                        resposta = f"🔎 Buscando fatura para o cliente {cpf_limpo}...\n\n❌ *FATURA NÃO ENCONTRADA*\n\nNão encontrei nenhuma fatura para este CPF."
                    else:
                        invoice = invoices[0]
                        valor = invoice.get('amount', 0)
                        codigo_pix = invoice.get('pix', '') or invoice.get('codigo_pix', '')
                        codigo_barras = invoice.get('barcode', '') or invoice.get('codigo_barras', '')
                        data_vencimento = invoice.get('due_date_raw') or invoice.get('data_vencimento')
                        
                        resposta_parts = [f"🔎 Buscando fatura para o cliente {cpf_limpo}...\n\n✅ *Fatura encontrada:*"]
                        
                        if valor:
                            # Formatar valor como float/Decimal
                            try:
                                valor_formatado = float(valor) if valor else 0
                                resposta_parts.append(f"valor: {valor_formatado:.2f}")
                            except:
                                resposta_parts.append(f"valor: {valor}")
                        if codigo_pix:
                            resposta_parts.append(f"codigo_pix: {codigo_pix}")
                        if codigo_barras:
                            resposta_parts.append(f"codigo_barras: {codigo_barras}")
                        if data_vencimento:
                            if isinstance(data_vencimento, str):
                                resposta_parts.append(f"data_vencimento: {data_vencimento}")
                            else:
                                from datetime import datetime
                                if hasattr(data_vencimento, 'strftime'):
                                    resposta_parts.append(f"data_vencimento: {data_vencimento.strftime('%Y-%m-%d')}")
                                else:
                                    resposta_parts.append(f"data_vencimento: {data_vencimento}")
                        
                        resposta = "\n".join(resposta_parts)
                except Exception as e:
                    logger.error(f"[Webhook] Erro ao buscar fatura: {e}")
                    import traceback
                    traceback.print_exc()
                    resposta = f"🔎 Buscando fatura para o cliente {cpf_limpo}...\n\n❌ *ERRO*\n\nErro ao buscar fatura: {str(e)}"
                
                sessao.etapa = 'inicial'
                sessao.dados_temp = {}
                sessao.save()
        
        else:
            # Mensagem não reconhecida
            resposta = (
                "❓ *Comando não reconhecido*\n\n"
                "Comandos disponíveis:\n"
                "• *Fachada* - Consultar fachadas por CEP\n"
                "• *Viabilidade* - Consultar viabilidade por CEP e número\n"
                "• *Status* - Consultar status de pedido\n"
                "• *Fatura* - Consultar fatura por CPF\n\n"
                "Digite um dos comandos acima para começar."
            )
        
        # Enviar resposta via WhatsApp
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
            except Exception as e:
                logger.error(f"[Webhook] Erro ao enviar resposta: {e}")
                import traceback
                traceback.print_exc()
                return {'status': 'erro', 'mensagem': f'Erro ao enviar resposta: {str(e)}'}
        
        return {'status': 'ok', 'mensagem': 'Processado com sucesso'}
    
    except Exception as e:
        logger.exception(f"[Webhook] Erro ao processar mensagem: {e}")
        return {'status': 'erro', 'mensagem': str(e)}
