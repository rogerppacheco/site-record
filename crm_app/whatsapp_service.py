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
        # Carrega credenciais
        self.instance_id = config('ZAPI_INSTANCE_ID', default='')
        self.token = config('ZAPI_TOKEN', default='')
        self.client_token = config('ZAPI_CLIENT_TOKEN', default='')
        
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

    def _formatar_telefone(self, telefone):
        if not telefone:
            return ""
        telefone_limpo = "".join(filter(str.isdigit, telefone))
        # Ajuste simples para garantir formato 55 + DDD + Numero
        if len(telefone_limpo) == 10 or len(telefone_limpo) == 11: 
            telefone_limpo = f"55{telefone_limpo}"
        return telefone_limpo

    def verificar_numero_existe(self, telefone):
        telefone_limpo = self._formatar_telefone(telefone)
        url = f"{self.base_url}/phone-exists/{telefone_limpo}"
        
        if not self.instance_id or not self.token:
            print("Z-API: Credenciais não encontradas.")
            return True # Retorna True para não travar a venda se faltar config

        try:
            print(f"Z-API: Consultando URL: {url}")
            response = requests.get(url, headers=self._get_headers())
            
            # --- DEBUG DETALHADO DO ERRO ---
            if response.status_code != 200:
                print(f"Z-API ERRO {response.status_code}: {response.text}")
                # IMPORTANTE: Se der erro na API (ex: 403, 500), assumimos que o número 
                # EXISTE (True) para não impedir o vendedor de trabalhar por culpa do sistema.
                return True 
            
            # Sucesso (200)
            data = response.json()
            exists = data.get('exists', False)
            print(f"Z-API Sucesso: {telefone_limpo} existe? {exists}")
            return exists

        except Exception as e:
            print(f"Z-API Exceção de Conexão: {e}")
            # Se a conexão falhar, assume True para não travar
            return True

    def enviar_mensagem_texto(self, telefone, mensagem):
        url = f"{self.base_url}/send-text"
        telefone_limpo = self._formatar_telefone(telefone)

        payload = {
            "phone": telefone_limpo,
            "message": mensagem
        }

        try:
            response = requests.post(url, json=payload, headers=self._get_headers())
            return True, response.json() if response.content else {}
        except Exception as e:
            logger.error(f"Erro ao enviar WhatsApp para {telefone_limpo}: {e}")
            return False, str(e)

    # --- ENVIAR IMAGEM (BASE64) ---
    def enviar_imagem_b64(self, telefone, base64_data, caption=""):
        url = f"{self.base_url}/send-image"
        telefone_limpo = self._formatar_telefone(telefone)
        
        payload = {
            "phone": telefone_limpo,
            "image": base64_data, 
            "caption": caption
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_headers())
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Exceção Imagem: {e}")
            return False

    # --- ENVIAR PDF (BASE64) ---
    def enviar_pdf_b64(self, telefone, base64_data, nome_arquivo="extrato.pdf"):
        url = f"{self.base_url}/send-document"
        telefone_limpo = self._formatar_telefone(telefone)
        
        payload = {
            "phone": telefone_limpo,
            "document": base64_data,
            "fileName": nome_arquivo
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_headers())
            return response.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Exceção PDF: {e}")
            return False

    # --- GERADOR DE IMAGEM DINÂMICA (Card Detalhado - Comissão) ---
    def _gerar_imagem_resumo_bytes(self, dados):
        if not Image:
            return None

        planos = dados.get('detalhes_planos', [])
        descontos = dados.get('detalhes_descontos', [])

        base_height = 250
        height_planos = (len(planos) * 35) + 40 if planos else 0
        height_descontos = (len(descontos) * 35) + 40 if descontos else 0
        final_height = max(base_height + height_planos + height_descontos, 400)
        width = 600

        # Cores
        bg_color = (245, 245, 245) 
        card_color = (255, 255, 255)
        primary_color = (0, 70, 140) 
        text_color = (60, 60, 60) 
        red_color = (200, 50, 50) 

        image = Image.new('RGB', (width, final_height), bg_color)
        draw = ImageDraw.Draw(image)

        margin = 20
        draw.rectangle([(margin, margin), (width-margin, final_height-margin)], fill=card_color, outline=(200,200,200), width=1)

        try:
            font_title = ImageFont.truetype("arial.ttf", 32)
            font_sub = ImageFont.truetype("arialbd.ttf", 22) 
            font_text = ImageFont.truetype("arial.ttf", 20)
            font_val_big = ImageFont.truetype("arialbd.ttf", 40)
        except:
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()
            font_text = ImageFont.load_default()
            font_val_big = ImageFont.load_default()

        y = 50
        draw.text((40, y), dados.get('titulo', 'Resumo Detalhado'), font=font_title, fill=primary_color)
        y += 45
        draw.text((40, y), f"Consultor: {dados.get('vendedor', '-')}", font=font_text, fill=text_color)
        draw.text((350, y), f"Ref: {dados.get('periodo', '-')}", font=font_text, fill=text_color)
        y += 40
        draw.line([(40, y), (560, y)], fill=(230,230,230), width=2)
        y += 20

        if planos:
            draw.text((40, y), "Vendas por Plano:", font=font_sub, fill=(50,50,50))
            y += 35
            for p in planos:
                texto_esq = f"{p['nome']} ({p['qtd']}x)"
                draw.text((40, y), texto_esq, font=font_text, fill=text_color)
                draw.text((420, y), p['valor'], font=font_text, fill=(0, 120, 0)) 
                y += 30
            y += 10 

        if descontos:
            draw.line([(40, y), (560, y)], fill=(230,230,230), width=1)
            y += 20
            draw.text((40, y), "Descontos Aplicados:", font=font_sub, fill=red_color)
            y += 35
            for d in descontos:
                draw.text((40, y), d['motivo'], font=font_text, fill=text_color)
                draw.text((420, y), d['valor'], font=font_text, fill=red_color)
                y += 30
        
        y_footer = final_height - 110 
        draw.rectangle([(25, y_footer), (575, final_height-25)], fill=(235, 245, 255))
        draw.text((45, y_footer + 30), "Líquido a Receber:", font=font_sub, fill=primary_color)
        
        total_str = dados.get('total', 'R$ 0,00')
        draw.text((300, y_footer + 20), total_str, font=font_val_big, fill=(0, 150, 0))

        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    def enviar_resumo_comissao(self, telefone, dados_comissao):
        try:
            img_buffer = self._gerar_imagem_resumo_bytes(dados_comissao)
            if not img_buffer: return False

            img_str = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
            base64_final = f"data:image/png;base64,{img_str}"
            caption = f"Olá {dados_comissao.get('vendedor')}, segue o detalhamento do fechamento {dados_comissao.get('periodo')}! 🚀"
            return self.enviar_imagem_b64(telefone, base64_final, caption=caption)
        except Exception as e:
            logger.error(f"Erro ao processar envio de resumo visual: {e}")
            return False

    def enviar_mensagem_cadastrada(self, venda, telefone_destino=None):
        is_dacc = "NÃO"
        if venda.forma_pagamento and "DÉBITO" in venda.forma_pagamento.nome.upper(): is_dacc = "SIM"

        agendamento_str = "A confirmar"
        if venda.data_agendamento:
            try:
                if isinstance(venda.data_agendamento, str):
                    dt = datetime.strptime(venda.data_agendamento, '%Y-%m-%d')
                    data_fmt = dt.strftime('%d/%m/%Y')
                else:
                    data_fmt = venda.data_agendamento.strftime('%d/%m/%Y')
                
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