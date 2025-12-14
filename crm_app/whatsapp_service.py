import requests
import logging
from decouple import config
import os
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
        # Carrega credenciais do arquivo .env ou settings
        self.instance_id = config('ZAPI_INSTANCE_ID', default='')
        self.token = config('ZAPI_TOKEN', default='')
        self.client_token = config('ZAPI_CLIENT_TOKEN', default='')
        
        # URL Base da API
        self.base_url = f"https://api.z-api.io/instances/{self.instance_id}/token/{self.token}"

        # DEBUG: Mostra no terminal o que foi carregado (oculta parte da senha)
        print(f"--- DEBUG Z-API ---")
        print(f"Instancia: {self.instance_id}")
        print(f"ClientToken Carregado: {self.client_token[:5]}...{self.client_token[-3:] if self.client_token else 'VAZIO'}")
        print(f"-------------------")

    def _get_headers(self):
        headers = {
            'Content-Type': 'application/json'
        }
        if self.client_token:
            headers['Client-Token'] = self.client_token
        return headers

    def _send_request(self, url, payload=None, method='POST'):
        """
        Método auxiliar central para envio de requisições.
        Resolve o erro 'object has no attribute _send_request'.
        """
        try:
            if method == 'GET':
                response = requests.get(url, headers=self._get_headers(), timeout=15)
            else:
                response = requests.post(url, json=payload, headers=self._get_headers(), timeout=30)
            
            if response.status_code not in [200, 201]:
                logger.error(f"Z-API Erro {response.status_code}: {response.text}")
                return None
            
            try:
                return response.json()
            except ValueError:
                return response.text

        except requests.exceptions.RequestException as e:
            logger.error(f"Z-API Connection Error: {e}")
            return None
        except Exception as e:
            logger.error(f"Z-API Generic Error: {e}")
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

        payload = {
            "phone": telefone_limpo,
            "message": mensagem
        }

        resp = self._send_request(url, payload)
        if resp:
            return True, resp
        return False, "Erro ao enviar"

    # ---------------------------------------------------------
    # 3. ENVIAR IMAGEM (BASE64)
    # ---------------------------------------------------------
    def enviar_imagem_b64(self, telefone, base64_data, caption=""):
        return self.enviar_imagem_base64_direto(telefone, base64_data, caption)

    def enviar_imagem_base64_direto(self, telefone, base64_img, caption=""):
        url = f"{self.base_url}/send-image"
        
        # Remove espaços em branco do telefone/ID
        telefone_limpo = str(telefone).strip()
        
        # Garante que o base64 esteja limpo (sem prefixo para a Z-API em alguns casos, 
        # mas a documentação padrão pede com prefixo. Vamos manter COM prefixo pois é o padrão).
        image_data = base64_img
        if not image_data.startswith('data:image'):
            image_data = f"data:image/png;base64,{base64_img}"

        payload = {
            "phone": telefone_limpo,
            "image": image_data,
            "caption": caption
        }
        
        print(f"--- Z-API ENVIANDO IMAGEM ---")
        print(f"Destino: {telefone_limpo}")
        print(f"Tamanho Imagem: {len(image_data)} chars")
        
        resp = self._send_request(url, payload)
        
        print(f"Z-API Resposta: {resp}")
        
        # Verifica se houve erro na resposta da API (ex: messageId ausente)
        if resp and isinstance(resp, dict):
            if 'messageId' in resp or 'id' in resp:
                return True
            if 'error' in resp:
                logger.error(f"Z-API Erro Lógico: {resp}")
                return False
                
        return resp is not None

    # ---------------------------------------------------------
    # 4. ENVIAR PDF (BASE64)
    # ---------------------------------------------------------
    def enviar_pdf_b64(self, telefone, base64_data, nome_arquivo="extrato.pdf"):
        url = f"{self.base_url}/send-document"
        telefone_limpo = self._formatar_telefone(telefone)
        
        payload = {
            "phone": telefone_limpo,
            "document": base64_data,
            "fileName": nome_arquivo
        }
        
        resp = self._send_request(url, payload)
        return resp is not None

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
        # ... Lógica do Pillow mantida se necessária para card de comissão ...
        # (Se quiser economizar espaço e não usar card de comissão, pode remover essa função)
        # Vou manter simplificada para não quebrar imports
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