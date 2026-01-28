import requests
import logging
# from decouple import config  <-- REMOVIDO PARA CORRIGIR O ERRO
import os  # <-- ADICIONADO PARA CORREÇÃO
import base64
import io
from datetime import datetime

# Tenta importar o Pillow para geração de imagens
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self):
        # --- CORREÇÃO DO ERRO DE INSTANCE NOT FOUND ---
        # Substituimos o 'config' pelo 'os.environ.get' para garantir que ele pegue
        # as variáveis reais do servidor Railway e não de arquivos .env antigos.
        self.instance_id = os.environ.get('ZAPI_INSTANCE_ID', '')
        self.token = os.environ.get('ZAPI_TOKEN', '')
        self.client_token = os.environ.get('ZAPI_CLIENT_TOKEN', '')
        
        # URL Base da API
        self.base_url = f"https://api.z-api.io/instances/{self.instance_id}/token/{self.token}"

        # DEBUG: Mostra no terminal o que foi carregado (oculta parte da senha)
        print(f"--- DEBUG Z-API (CORRIGIDO V2) ---")
        print(f"Instancia: {self.instance_id}")
        if self.client_token:
            print(f"ClientToken Carregado: {self.client_token[:5]}...{self.client_token[-3:]}")
        else:
            print("ClientToken Carregado: VAZIO")
        print(f"-------------------")
        
        if not self.instance_id or not self.token:
            logger.error("Z-API CRITICO: Credenciais não encontradas nas variáveis de ambiente!")

    def _get_headers(self):
        headers = {
            'Content-Type': 'application/json'
        }
        if self.client_token:
            headers['client-token'] = self.client_token
        return headers

    def _send_request(self, url, payload=None, method='POST'):
        """
        Método auxiliar central para envio de requisições.
        Resolve o erro 'object has no attribute _send_request'.
        """
        # LOG DETALHADO PARA DEBUG
        logger.info(f"[Z-API] Método: {method}, URL: {url}")
        logger.info(f"[Z-API] Headers: {self._get_headers()}")
        
        if payload:
            # Para documentos, não logar o base64 completo (muito grande)
            if 'document' in payload and isinstance(payload.get('document'), str):
                payload_log = payload.copy()
                doc_size = len(payload['document'])
                payload_log['document'] = f"[BASE64: {doc_size} chars] {payload['document'][:50]}..."
                logger.info(f"[Z-API] Payload: {payload_log}")
                print(f"[Z-API] Payload: phone={payload.get('phone')}, fileName={payload.get('fileName')}, document size={doc_size} chars")
            else:
                logger.info(f"[Z-API] Payload: {payload}")
                print(f"[Z-API] Payload: {payload}")

        try:
            # Timeout maior para documentos (arquivos grandes podem demorar mais)
            timeout_val = 60 if 'send-document' in url else (15 if method == 'GET' else 30)
            
            if method == 'GET':
                response = requests.get(url, headers=self._get_headers(), timeout=timeout_val)
            else:
                response = requests.post(url, json=payload, headers=self._get_headers(), timeout=timeout_val)
            
            logger.info(f"[Z-API] Status Code: {response.status_code}")
            logger.info(f"[Z-API] Response Headers: {dict(response.headers)}")
            logger.info(f"[Z-API] Response Text (primeiros 500 chars): {response.text[:500]}...")
            print(f"[Z-API] Status: {response.status_code}, Response length: {len(response.text)} chars")
            
            if response.status_code not in [200, 201]:
                logger.error(f"[Z-API] ❌ Erro HTTP {response.status_code}")
                logger.error(f"[Z-API] Response completa: {response.text}")
                print(f"[Z-API] ❌ ERRO HTTP {response.status_code}: {response.text[:200]}")
                # Tentar parsear JSON mesmo com erro para retornar a mensagem de erro
                try:
                    error_json = response.json()
                    return error_json  # Retornar o erro como dict para tratamento
                except:
                    return None
            
            try:
                json_response = response.json()
                logger.info(f"[Z-API] ✅ JSON Response: {json_response}")
                print(f"[Z-API] ✅ Resposta JSON: {json_response}")
                return json_response
            except ValueError as ve:
                logger.warning(f"[Z-API] ⚠️ Resposta não é JSON (ValueError: {ve})")
                logger.warning(f"[Z-API] Response text (primeiros 200 chars): {response.text[:200]}")
                print(f"[Z-API] ⚠️ Resposta não é JSON: {response.text[:200]}")
                return response.text

        except requests.exceptions.Timeout as te:
            logger.error(f"[Z-API] ❌ Timeout Error: {te}")
            print(f"[Z-API] ❌ TIMEOUT: {te}")
            import traceback
            traceback.print_exc()
            return None
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"[Z-API] ❌ Connection Error: {ce}")
            print(f"[Z-API] ❌ CONEXÃO: {ce}")
            import traceback
            traceback.print_exc()
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"[Z-API] ❌ Request Exception: {type(e).__name__}: {e}")
            print(f"[Z-API] ❌ REQUEST EXCEPTION: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None
        except Exception as e:
            logger.error(f"[Z-API] ❌ Generic Error: {type(e).__name__}: {e}")
            print(f"[Z-API] ❌ ERRO GENÉRICO: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _formatar_telefone(self, telefone):
        if not telefone:
            return ""
        telefone_limpo = "".join(filter(str.isdigit, str(telefone)))
        # Ajuste simples para garantir formato 55 + DDD + Numero
        if len(telefone_limpo) == 10 or len(telefone_limpo) == 11: 
            telefone_limpo = f"55{telefone_limpo}"
        return telefone_limpo

    # ---------------------------------------------------------
    # 1. VERIFICAR SE NÚMERO TEM WHATSAPP
    # ---------------------------------------------------------
    def verificar_numero_existe(self, telefone):
        telefone_limpo = self._formatar_telefone(telefone)
        url = f"{self.base_url}/phone-exists/{telefone_limpo}"
        
        if not self.instance_id or not self.token:
            print("Z-API: Credenciais não encontradas.")
            return True 

        data = self._send_request(url, method='GET')
        
        if isinstance(data, dict):
            # Verificar se a resposta contém erro da Z-API
            # Ex: {"message":"Whatsapp did not respond","error":"Bad Request","statusCode":400}
            if 'error' in data or data.get('statusCode', 200) != 200:
                erro_msg = data.get('message', data.get('error', 'Erro desconhecido'))
                logger.warning(f"[Z-API] ⚠️ Erro ao verificar número {telefone_limpo}: {erro_msg}")
                print(f"Z-API Erro: {telefone_limpo} - {erro_msg}")
                # Retorna None para indicar que não foi possível verificar
                # A view tratará isso como "não bloquear o cadastro"
                return None
            
            # Resposta normal com o campo 'exists'
            exists = data.get('exists', False)
            print(f"Z-API Sucesso: {telefone_limpo} existe? {exists}")
            return exists
        return True # Fallback

    # ---------------------------------------------------------
    # 2. ENVIAR MENSAGEM DE TEXTO
    # ---------------------------------------------------------
    def enviar_mensagem_texto(self, telefone, mensagem):
        url = f"{self.base_url}/send-text"
        telefone_limpo = self._formatar_telefone(telefone)

        logger.info(f"[WhatsAppService] Enviando mensagem para {telefone_limpo}")
        logger.info(f"[WhatsAppService] URL: {url}")
        logger.info(f"[WhatsAppService] Mensagem (primeiros 100 chars): {mensagem[:100]}...")

        payload = {
            "phone": telefone_limpo,
            "message": mensagem
        }

        logger.info(f"[WhatsAppService] Payload: phone={telefone_limpo}, message_length={len(mensagem)}")

        resp = self._send_request(url, payload)
        if resp:
            logger.info(f"[WhatsAppService] Resposta recebida: {resp}")
            return True, resp
        else:
            logger.error(f"[WhatsAppService] Erro: resposta vazia ou None")
            return False, "Erro ao enviar - resposta vazia"

    # ---------------------------------------------------------
    # 3. ENVIAR IMAGEM (BASE64)
    # ---------------------------------------------------------
    def enviar_imagem_b64(self, telefone, img_b64, caption=""):
        """
        Envia imagem em Base64 com legenda (caption) via Z-API.
        """
        url = f"{self.base_url}/send-image"
        
        # Z-API exige o prefixo data:image/png;base64,
        # Se não tiver, adicionamos.
        if "base64," not in img_b64:
            img_b64 = "data:image/png;base64," + img_b64

        payload = {
            "phone": telefone,
            "image": img_b64,
            "caption": caption  # <--- Este é o "Cabeçalho" da mensagem
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_headers())
            return response.json()
        except Exception as e:
            logger.error(f"Erro ao enviar imagem Z-API: {e}")
            return None

    # Alias para compatibilidade (caso a view chame com outro nome)
    def enviar_imagem_base64_direto(self, telefone, img_b64, caption=""):
        return self.enviar_imagem_b64(telefone, img_b64, caption)

    # ---------------------------------------------------------
    # 4. ENVIAR PDF (BASE64 OU URL)
    # ---------------------------------------------------------
    def enviar_pdf_url(self, telefone, pdf_url, nome_arquivo="extrato.pdf", caption=None):
        """
        Envia documento (PDF, Word, Excel, etc) via URL pública usando Z-API.
        Z-API requer: /send-document/{extension}
        Recomendado para arquivos grandes (>5MB).
        
        Args:
            telefone: Número do destinatário
            pdf_url: URL pública do PDF
            nome_arquivo: Nome do arquivo
            caption: Mensagem de legenda (opcional, será enviada como mensagem separada se não suportado)
        """
        # Extrair extensão do arquivo para incluir na URL (ex: pdf, docx, xlsx)
        extensao = 'pdf'  # padrão
        if '.' in nome_arquivo:
            extensao = nome_arquivo.split('.')[-1].lower()
        
        url = f"{self.base_url}/send-document/{extensao}"
        telefone_limpo = self._formatar_telefone(telefone)
        
        logger.info(f"[WhatsAppService] 📄 INICIANDO ENVIO DE PDF VIA URL")
        logger.info(f"[WhatsAppService] Telefone: {telefone} -> Formatado: {telefone_limpo}")
        logger.info(f"[WhatsAppService] Arquivo: {nome_arquivo}")
        logger.info(f"[WhatsAppService] URL do PDF: {pdf_url}")
        if caption:
            logger.info(f"[WhatsAppService] Caption: {caption[:100]}...")
        print(f"[PDF-ENVIO] Enviando PDF via URL: {nome_arquivo} para {telefone_limpo}")
        print(f"[PDF-ENVIO] URL: {pdf_url}")
        if caption:
            print(f"[PDF-ENVIO] Caption: {caption[:100]}...")
        
        payload = {
            "phone": telefone_limpo,
            "document": pdf_url,  # Z-API aceita URL ou base64
            "fileName": nome_arquivo
        }
        
        # Tentar adicionar caption (Z-API pode não suportar diretamente, mas vamos tentar)
        # Se não funcionar, enviaremos a mensagem separadamente após o envio
        if caption:
            # Algumas APIs aceitam "caption" ou "message" como parâmetro
            payload["caption"] = caption
            logger.info(f"[WhatsAppService] Adicionando caption ao payload")
        
        logger.info(f"[WhatsAppService] Payload preparado:")
        logger.info(f"[WhatsAppService]   - phone: {telefone_limpo}")
        logger.info(f"[WhatsAppService]   - fileName: {nome_arquivo}")
        logger.info(f"[WhatsAppService]   - document (URL): {pdf_url}")
        logger.info(f"[WhatsAppService] URL completa: {url}")
        logger.info(f"[WhatsAppService] Extensão usada: {extensao}")
        print(f"[PDF-ENVIO] Enviando requisição para: {url}")
        print(f"[PDF-ENVIO] Extensão: {extensao}, Payload: phone={telefone_limpo}, fileName={nome_arquivo}, document={pdf_url}")
        
        try:
            resp = self._send_request(url, payload)
            logger.info(f"[WhatsAppService] Resposta recebida do _send_request: {resp}")
            print(f"[PDF-ENVIO] Resposta da API: {resp}")
            
            if resp:
                # Verificar se a resposta contém erro
                if isinstance(resp, dict) and resp.get('error'):
                    erro_msg = resp.get('message', resp.get('error', 'Erro desconhecido'))
                    logger.error(f"[WhatsAppService] ❌ Erro da API Z-API: {erro_msg}")
                    logger.error(f"[WhatsAppService] Resposta completa: {resp}")
                    print(f"[PDF-ENVIO] ❌ ERRO DA API: {erro_msg}")
                    return False
                
                # Verificar se tem campos de sucesso (messageId, zaapId, id)
                if isinstance(resp, dict) and (resp.get('messageId') or resp.get('zaapId') or resp.get('id')):
                    message_id = resp.get('messageId') or resp.get('zaapId') or resp.get('id')
                    logger.info(f"[WhatsAppService] ✅ Documento enviado com sucesso via URL: {nome_arquivo}")
                    logger.info(f"[WhatsAppService] MessageId: {message_id}")
                    print(f"[PDF-ENVIO] ✅ SUCESSO: Documento enviado via URL (MessageId: {message_id})")
                    
                    # Se caption foi fornecido, retornar para que seja enviado imediatamente após
                    # (Z-API pode não suportar caption diretamente no envio)
                    if caption:
                        logger.info(f"[WhatsAppService] Caption fornecido, será retornado para envio imediato após PDF")
                        # O caption será enviado pelo webhook_handler imediatamente após o PDF
                        # para aparecer junto na mesma conversa
                    
                    return True
                else:
                    logger.warning(f"[WhatsAppService] ⚠️ Resposta inesperada: {resp}")
                    print(f"[PDF-ENVIO] ⚠️ AVISO: Resposta inesperada")
                    return False
            else:
                logger.error(f"[WhatsAppService] ❌ Erro ao enviar documento: resposta vazia ou None")
                print(f"[PDF-ENVIO] ❌ ERRO: Resposta vazia ou None")
                return False
        except Exception as e:
            logger.error(f"[WhatsAppService] ❌ Erro ao enviar documento via URL: {type(e).__name__}: {e}")
            print(f"[PDF-ENVIO] ❌ EXCEÇÃO: {type(e).__name__}: {e}")
            import traceback
            tb_str = traceback.format_exc()
            logger.error(f"[WhatsAppService] Traceback completo:\n{tb_str}")
            print(f"[PDF-ENVIO] Traceback: {tb_str}")
            return False
    
    def enviar_pdf_b64(self, telefone, base64_data, nome_arquivo="extrato.pdf", caption=None):
        """
        Envia documento (PDF, Word, Excel, etc) em Base64 via Z-API.
        Z-API requer: /send-document/{extension}
        
        Args:
            telefone: Número do destinatário
            base64_data: PDF em base64
            nome_arquivo: Nome do arquivo
            caption: Mensagem de legenda (opcional, será enviada como mensagem separada se não suportado)
        """
        # Extrair extensão do arquivo para incluir na URL (ex: pdf, docx, xlsx)
        extensao = 'pdf'  # padrão
        if '.' in nome_arquivo:
            extensao = nome_arquivo.split('.')[-1].lower()
        
        url = f"{self.base_url}/send-document/{extensao}"
        telefone_limpo = self._formatar_telefone(telefone)
        
        logger.info(f"[WhatsAppService] 📄 INICIANDO ENVIO DE PDF")
        logger.info(f"[WhatsAppService] Telefone: {telefone} -> Formatado: {telefone_limpo}")
        logger.info(f"[WhatsAppService] Arquivo: {nome_arquivo}")
        logger.info(f"[WhatsAppService] Tamanho base64 original: {len(base64_data)} chars")
        if caption:
            logger.info(f"[WhatsAppService] Caption: {caption[:100]}...")
        
        # Calcular tamanho aproximado em MB (base64 tem ~33% de overhead)
        tamanho_mb = (len(base64_data) * 3 / 4) / (1024 * 1024)
        logger.info(f"[WhatsAppService] Tamanho aproximado do arquivo: {tamanho_mb:.2f} MB")
        
        # Avisar se arquivo muito grande (WhatsApp limita a 100MB, mas Z-API pode ter limite menor para base64)
        if tamanho_mb > 10:
            logger.warning(f"[WhatsAppService] ⚠️ Arquivo grande ({tamanho_mb:.2f} MB). Z-API pode ter limitações para base64 grande.")
            logger.warning(f"[WhatsAppService] ⚠️ Se falhar, considere usar URL pública ao invés de base64.")
        
        logger.info(f"[WhatsAppService] Primeiros 100 chars base64: {base64_data[:100]}...")
        print(f"[PDF-ENVIO] Iniciando envio de PDF: {nome_arquivo} para {telefone_limpo}")
        print(f"[PDF-ENVIO] Tamanho base64: {len(base64_data)} chars (~{tamanho_mb:.2f} MB)")
        
        # Z-API send-document geralmente aceita apenas base64 puro (sem prefixo data:)
        # Remover prefixo se existir
        base64_original = base64_data
        if base64_data.startswith('data:'):
            logger.info(f"[WhatsAppService] ⚠️ Base64 contém prefixo 'data:', removendo...")
            # Extrair apenas o base64 (depois do "base64,")
            if 'base64,' in base64_data:
                base64_data = base64_data.split('base64,', 1)[1]
                logger.info(f"[WhatsAppService] Base64 após remoção do prefixo: {len(base64_data)} chars")
        
        # Validar base64
        try:
            import base64 as b64_module
            # Tentar decodificar para validar
            b64_module.b64decode(base64_data[:100])  # Testar apenas os primeiros chars
            logger.info(f"[WhatsAppService] ✅ Base64 válido (teste de decodificação)")
        except Exception as e:
            logger.error(f"[WhatsAppService] ❌ Base64 inválido: {e}")
            print(f"[PDF-ENVIO] ERRO: Base64 inválido - {e}")
        
        payload = {
            "phone": telefone_limpo,
            "document": base64_data,
            "fileName": nome_arquivo
        }
        
        # Tentar adicionar caption (Z-API pode não suportar diretamente, mas vamos tentar)
        if caption:
            payload["caption"] = caption
            logger.info(f"[WhatsAppService] Adicionando caption ao payload")
        
        logger.info(f"[WhatsAppService] Payload preparado:")
        logger.info(f"[WhatsAppService]   - phone: {telefone_limpo}")
        logger.info(f"[WhatsAppService]   - fileName: {nome_arquivo}")
        logger.info(f"[WhatsAppService]   - document (tamanho): {len(base64_data)} chars")
        logger.info(f"[WhatsAppService] URL completa: {url}")
        logger.info(f"[WhatsAppService] Extensão usada: {extensao}")
        print(f"[PDF-ENVIO] Enviando requisição para: {url}")
        print(f"[PDF-ENVIO] Extensão: {extensao}, Payload size: phone={telefone_limpo}, fileName={nome_arquivo}, document={len(base64_data)} chars")
        
        try:
            resp = self._send_request(url, payload)
            logger.info(f"[WhatsAppService] Resposta recebida do _send_request: {resp}")
            print(f"[PDF-ENVIO] Resposta da API: {resp}")
            
            if resp:
                # Verificar se a resposta contém erro
                if isinstance(resp, dict) and resp.get('error'):
                    erro_msg = resp.get('message', resp.get('error', 'Erro desconhecido'))
                    logger.error(f"[WhatsAppService] ❌ Erro da API Z-API: {erro_msg}")
                    logger.error(f"[WhatsAppService] Resposta completa: {resp}")
                    logger.error(f"[WhatsAppService] Arquivo: {nome_arquivo}, Tamanho: {tamanho_mb:.2f} MB")
                    
                    # Mensagem específica para erro de base64 não lido
                    if 'Base64' in erro_msg or 'could not be read' in erro_msg:
                        logger.error(f"[WhatsAppService] 💡 SUGESTÃO: Este erro geralmente ocorre com arquivos grandes (>5MB).")
                        logger.error(f"[WhatsAppService] 💡 Considere usar URL pública ao invés de base64 para arquivos grandes.")
                    
                    print(f"[PDF-ENVIO] ❌ ERRO DA API: {erro_msg}")
                    print(f"[PDF-ENVIO] Arquivo: {nome_arquivo}, Tamanho: {tamanho_mb:.2f} MB")
                    return False
                
                # Verificar se tem campos de sucesso (messageId, zaapId, id)
                if isinstance(resp, dict) and (resp.get('messageId') or resp.get('zaapId') or resp.get('id')):
                    message_id = resp.get('messageId') or resp.get('zaapId') or resp.get('id')
                    logger.info(f"[WhatsAppService] ✅ Documento enviado com sucesso: {nome_arquivo}")
                    logger.info(f"[WhatsAppService] MessageId: {message_id}")
                    print(f"[PDF-ENVIO] ✅ SUCESSO: Documento enviado (MessageId: {message_id})")
                    
                    # Se caption foi fornecido, retornar para que seja enviado imediatamente após
                    # (Z-API pode não suportar caption diretamente no envio)
                    if caption:
                        logger.info(f"[WhatsAppService] Caption fornecido, será retornado para envio imediato após PDF")
                        # O caption será enviado pelo webhook_handler imediatamente após o PDF
                        # para aparecer junto na mesma conversa
                    
                    return True
                else:
                    # Resposta não tem erro, mas também não tem indicadores de sucesso
                    logger.warning(f"[WhatsAppService] ⚠️ Resposta inesperada: {resp}")
                    print(f"[PDF-ENVIO] ⚠️ AVISO: Resposta inesperada")
                    return False
            else:
                logger.error(f"[WhatsAppService] ❌ Erro ao enviar documento: resposta vazia ou None")
                logger.error(f"[WhatsAppService] Tipo da resposta: {type(resp)}")
                print(f"[PDF-ENVIO] ❌ ERRO: Resposta vazia ou None")
                return False
        except Exception as e:
            logger.error(f"[WhatsAppService] ❌ Erro ao enviar documento: {e}")
            logger.error(f"[WhatsAppService] Tipo do erro: {type(e).__name__}")
            import traceback
            tb_str = traceback.format_exc()
            logger.error(f"[WhatsAppService] Traceback completo:\n{tb_str}")
            print(f"[PDF-ENVIO] ❌ EXCEÇÃO: {type(e).__name__}: {e}")
            print(f"[PDF-ENVIO] Traceback: {tb_str}")
            return False

    # ---------------------------------------------------------
    # 5. LISTAR GRUPOS (Z-API)
    # ---------------------------------------------------------
    def listar_grupos(self):
        """
        Retorna a lista de grupos que o número conectado participa.
        """
        url = f"{self.base_url}/groups"
        data = self._send_request(url, method='GET')
        
        # Tratamento de retorno variado da Z-API
        if data:
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'response' in data:
                return data['response']
            elif isinstance(data, dict) and 'groups' in data:
                return data['groups']
        
        return []

    # ---------------------------------------------------------
    # 6. FUNÇÕES LEGADAS / AUXILIARES
    # ---------------------------------------------------------
    
    def _gerar_imagem_resumo_bytes(self, dados):
        if not Image: return None
        return None 

    def enviar_resumo_comissao(self, telefone, dados_comissao):
        # Fallback texto se imagem falhar ou Pillow não existir
        msg = (
            f"💰 *RESUMO COMISSÃO*\n"
            f"Vendedor: {dados_comissao.get('vendedor')}\n"
            f"Período: {dados_comissao.get('periodo')}\n"
            f"Total Líquido: {dados_comissao.get('total')}"
        )
        return self.enviar_mensagem_texto(telefone, msg)

    def enviar_mensagem_cadastrada(self, venda, telefone_destino=None):
        is_dacc = "NÃO"
        if venda.forma_pagamento and "DÉBITO" in venda.forma_pagamento.nome.upper(): is_dacc = "SIM"

        agendamento_str = "A confirmar"
        if venda.data_agendamento:
            try:
                dt = venda.data_agendamento
                if isinstance(dt, str): dt = datetime.strptime(dt, '%Y-%m-%d')
                data_fmt = dt.strftime('%d/%m/%Y')
                
                turno = venda.periodo_agendamento or ""
                if turno == 'MANHA': horario = "08:00 às 12:00"
                elif turno == 'TARDE': horario = "13:00 às 18:00"
                else: horario = turno 
                
                agendamento_str = f"Agendamento confirmado para o dia {data_fmt} {horario}"
            except: pass

        vendedor_nome = (venda.vendedor.first_name or venda.vendedor.username).upper() if venda.vendedor else "N/A"
        nome_cliente = venda.cliente.nome_razao_social.upper() if venda.cliente else '-'
        cpf_cnpj = venda.cliente.cpf_cnpj if venda.cliente else '-'
        nome_plano = venda.plano.nome.upper() if venda.plano else '-'
        os_num = venda.ordem_servico or "Gerando..."

        mensagem = (
            f"APROVADO!✅✅\n"
            f"PLANO ADQUIRIDO: {nome_plano}\n"
            f"NOME DO CLIENTE: {nome_cliente}\n"
            f"CPF/CNPJ: {cpf_cnpj}\n"
            f"OS: {os_num}\n"
            f"DACC: {is_dacc}\n"
            f"AGENDAMENTO: {agendamento_str}\n"
            f"VENDEDOR: {vendedor_nome}\n"
            f"⚠FATURA, SEGUNDA VIA OU DÚVIDAS\n"
            f"https://www.niointernet.com.br/\n"
            f"WhatsApp: 31985186530\n"
            f"Para que sua instalação seja concluída favor salvar esse CTO no seu telefone, Técnico Nio 21 4040-1810 para receber informações da Visita."
        )

        fone_para_envio = telefone_destino if telefone_destino else venda.telefone1
        if fone_para_envio:
            return self.enviar_mensagem_texto(fone_para_envio, mensagem)
        return False, "Telefone não informado"

    # ---------------------------------------------------------
    # NOVO MÉTODO: GERAR CARD DE CAMPANHA
    # ---------------------------------------------------------
    def gerar_card_campanha_b64(self, dados):
        """
        Gera um card visual limpo com barra de progresso e destaque financeiro.
        """
        if not Image: 
            return None

        try:
            # 1. Configuração do Canvas (Quadrado HD)
            W, H = 1080, 1080
            cor_fundo = (255, 255, 255) # Branco total
            cor_cabecalho = (10, 30, 60) # Azul Escuro Profissional
            cor_texto_pri = (40, 40, 40)
            cor_texto_sec = (100, 100, 100)
            cor_verde = (0, 160, 80)
            cor_laranja = (255, 120, 0)
            cor_barra_fundo = (230, 230, 230)

            img = Image.new('RGB', (W, H), color=cor_fundo)
            d = ImageDraw.Draw(img)

            # --- CARREGAMENTO DE FONTES (Tentativa robusta) ---
            font_paths = [
                "arial.ttf", "Arial.ttf", 
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "DejaVuSans-Bold.ttf"
            ]
            
            font_path_bold = None
            for path in font_paths:
                try:
                    ImageFont.truetype(path, 20)
                    font_path_bold = path
                    break
                except: continue
            
            if not font_path_bold:
                # print("AVISO: Fontes TTF não encontradas. Usando default (feio).")
                f_titulo = f_nome = f_num = f_label = f_premio = ImageFont.load_default()
            else:
                f_titulo = ImageFont.truetype(font_path_bold, 55)
                f_nome = ImageFont.truetype(font_path_bold, 50)
                f_num = ImageFont.truetype(font_path_bold, 160)
                f_label = ImageFont.truetype(font_path_bold, 35)
                f_destaque = ImageFont.truetype(font_path_bold, 45)
                f_premio = ImageFont.truetype(font_path_bold, 80)

            # =================== DESENHO ===================

            # 1. CABEÇALHO (Topo Azul)
            d.rectangle([(0, 0), (W, 180)], fill=cor_cabecalho)
            campanha_nome = str(dados.get('campanha', 'Campanha')).upper()
            d.text((W/2, 90), campanha_nome, fill="white", anchor="mm", font=f_titulo)

            # 2. IDENTIFICAÇÃO (Nome do Vendedor)
            nome_vendedor = str(dados.get('vendedor', '')).upper()
            d.text((W/2, 260), f"CONSULTOR: {nome_vendedor}", fill=cor_texto_pri, anchor="mm", font=f_label)

            # 3. SCORE PRINCIPAL (Número de Vendas)
            vendas = int(dados.get('vendas', 0))
            d.text((W/2, 380), str(vendas), fill=cor_cabecalho, anchor="mm", font=f_num)
            d.text((W/2, 480), "VENDAS VÁLIDAS", fill=cor_texto_sec, anchor="mm", font=f_label)

            # 4. ÁREA DE RESULTADO (Caixa Cinza Inferior)
            box_y_start = 550
            box_y_end = 950
            d.rounded_rectangle([(50, box_y_start), (W-50, box_y_end)], radius=30, fill=(245, 245, 245))

            prox_meta = dados.get('prox_meta')
            premio_atual = float(dados.get('premio_atual', 0))
            prox_premio = float(dados.get('prox_premio', 0)) if dados.get('prox_premio') else 0

            # --- CENÁRIO A: TEM PRÓXIMA META (FALTA POUCO) ---
            if prox_meta:
                falta = int(prox_meta) - vendas
                pct = min(vendas / prox_meta, 1.0)
                
                bar_x1, bar_y1 = 100, 620
                bar_x2, bar_y2 = W - 100, 660
                
                d.rectangle([(bar_x1, bar_y1), (bar_x2, bar_y2)], fill=cor_barra_fundo)
                fill_width = (bar_x2 - bar_x1) * pct
                color_fill = cor_verde if pct > 0.8 else cor_laranja
                d.rectangle([(bar_x1, bar_y1), (bar_x1 + fill_width, bar_y2)], fill=color_fill)
                
                d.text((W/2, 690), f"{int(pct*100)}% DA META DE {prox_meta}", fill=cor_texto_sec, anchor="mm", font=f_label)
                d.text((W/2, 800), f"FALTAM {falta} VENDAS PARA GANHAR:", fill=cor_laranja, anchor="mm", font=f_destaque)
                val_fmt = f"R$ {prox_premio:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                d.text((W/2, 880), val_fmt, fill=cor_verde, anchor="mm", font=f_premio)

            # --- CENÁRIO B: BATEU O MÁXIMO (LENDÁRIO) ---
            elif premio_atual > 0:
                d.text((W/2, 650), "🏆 META MÁXIMA ATINGIDA!", fill=cor_verde, anchor="mm", font=f_titulo)
                d.text((W/2, 750), "BÔNUS GARANTIDO:", fill=cor_texto_sec, anchor="mm", font=f_destaque)
                val_fmt = f"R$ {premio_atual:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                d.text((W/2, 850), val_fmt, fill=cor_verde, anchor="mm", font=f_premio)

            # --- CENÁRIO C: INÍCIO (SEM PREMIO AINDA) ---
            else:
                alvo = dados.get('meta_atual') or "A PRIMEIRA META"
                d.text((W/2, 650), "VAMOS ACELERAR!", fill=cor_cabecalho, anchor="mm", font=f_titulo)
                d.text((W/2, 750), "O FOCO É BATER:", fill=cor_texto_sec, anchor="mm", font=f_destaque)
                d.text((W/2, 830), f"{alvo} VENDAS", fill=cor_laranja, anchor="mm", font=f_titulo)

            # 5. RODAPÉ
            d.line([(0, 1000), (W, 1000)], fill=(220, 220, 220), width=2)
            periodo = dados.get('periodo', '')
            d.text((W/2, 1040), f"Período: {periodo} | Atualizado em {datetime.now().strftime('%H:%M')}", fill=cor_texto_sec, anchor="mm", font=ImageFont.load_default())

            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            return f"data:image/png;base64,{img_str}"

        except Exception as e:
            print(f"Erro imagem Pillow: {e}")
            return None

    # ---------------------------------------------------------
    # NOVO: GERAR IMAGEM DE PERFORMANCE (TABELA)
    # ---------------------------------------------------------
    def gerar_imagem_performance_b64(self, dados_relatorio):
        """
        Gera uma imagem com a tabela de performance do dia.
        """
        if not Image: return None

        try:
            # 1. Configurações de Layout
            lista = dados_relatorio.get('lista', [])
            qtd_linhas = len(lista)
            
            H_BASE = 250
            H_LINHA = 60
            H_RODAPE = 150
            W = 1000
            H = H_BASE + (qtd_linhas * H_LINHA) + H_RODAPE

            cor_fundo = (255, 255, 255)
            cor_azul_escuro = (10, 30, 60)
            cor_azul_claro = (235, 240, 255) # Para linhas alternadas
            cor_texto = (50, 50, 50)
            cor_verde = (0, 150, 70)
            cor_destaque = (255, 100, 0)

            img = Image.new('RGB', (W, H), color=cor_fundo)
            d = ImageDraw.Draw(img)

            # Fontes
            try:
                f_titulo = ImageFont.truetype("arial.ttf", 60)
                f_sub = ImageFont.truetype("arial.ttf", 35)
                f_texto = ImageFont.truetype("arial.ttf", 30)
                f_bold = ImageFont.truetype("arialbd.ttf", 30)
            except:
                f_titulo = f_sub = f_texto = f_bold = ImageFont.load_default()

            # 2. Cabeçalho
            d.rectangle([(0, 0), (W, 180)], fill=cor_azul_escuro)
            d.text((W/2, 60), dados_relatorio['titulo'], fill="white", anchor="mm", font=f_titulo)
            d.text((W/2, 130), f"📅 {dados_relatorio['data']}", fill="white", anchor="mm", font=f_sub)

            # Cabeçalho da Tabela
            y_start = 200
            col_x = [50, 450, 700, 900]
            
            d.text((col_x[0], y_start), "VENDEDOR", fill=cor_azul_escuro, anchor="lm", font=f_bold)
            d.text((col_x[1], y_start), "TOTAL", fill=cor_azul_escuro, anchor="mm", font=f_bold)
            d.text((col_x[2], y_start), "CARTÃO", fill=cor_azul_escuro, anchor="mm", font=f_bold)
            d.text((col_x[3], y_start), "%", fill=cor_azul_escuro, anchor="mm", font=f_bold)
            
            d.line([(30, y_start + 25), (W-30, y_start + 25)], fill=(200,200,200), width=2)

            # 3. Linhas da Tabela
            y = y_start + 60
            for i, item in enumerate(lista):
                if i % 2 == 0:
                    d.rectangle([(30, y-30), (W-30, y+30)], fill=cor_azul_claro)

                d.text((col_x[0], y), str(item['nome'])[:22], fill=cor_texto, anchor="lm", font=f_texto)
                
                cor_num = cor_verde if item['total'] > 0 else (150,150,150)
                d.text((col_x[1], y), str(item['total']), fill=cor_num, anchor="mm", font=f_bold)
                d.text((col_x[2], y), str(item['cc']), fill=cor_texto, anchor="mm", font=f_texto)
                d.text((col_x[3], y), item['pct'], fill=cor_texto, anchor="mm", font=f_texto)
                
                y += H_LINHA

            # 4. Totais (Rodapé)
            y_totais = H - 100
            d.rectangle([(0, y_totais - 40), (W, H)], fill=cor_azul_escuro)
            
            totais = dados_relatorio.get('totais', {})
            resumo = f"🏆 TOTAL: {totais['total']}   |   💳 CARTÃO: {totais['cc']} ({totais['pct']})"
            d.text((W/2, y_totais + 20), resumo, fill="white", anchor="mm", font=f_sub)

            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            return f"data:image/png;base64,{img_str}"

        except Exception as e:
            print(f"Erro ao gerar imagem performance: {e}")
            return None