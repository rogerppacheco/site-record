import requests
import logging
from decouple import config
import os
import base64
import io
from datetime import datetime

# Tenta importar o Pillow para geração de imagens (opcional, mas necessário para o resumo de comissão)
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

logger = logging.getLogger(__name__)

class WhatsAppService:
    def __init__(self):
        self.instance_id = config('ZAPI_INSTANCE_ID', default='')
        self.token = config('ZAPI_TOKEN', default='')
        self.client_token = config('ZAPI_CLIENT_TOKEN', default='')
        
        self.base_url = f"https://api.z-api.io/instances/{self.instance_id}/token/{self.token}"

    def _get_headers(self):
        """
        Retorna os cabeçalhos necessários, incluindo o Client-Token se existir.
        """
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
            # logger.error("Z-API credentials não configuradas.")
            return False 

        try:
            response = requests.get(url, headers=self._get_headers())
            
            if response.status_code != 200:
                # Silencia erros comuns de conexão para não poluir log em dev
                pass
            
            if response.status_code == 200:
                data = response.json()
                return data.get('exists', False)
            
            return False

        except Exception as e:
            logger.error(f"Erro ao verificar número na Z-API: {e}")
            return False

    def enviar_mensagem_texto(self, telefone, mensagem):
        url = f"{self.base_url}/send-text"
        telefone_limpo = self._formatar_telefone(telefone)

        payload = {
            "phone": telefone_limpo,
            "message": mensagem
        }

        try:
            response = requests.post(url, json=payload, headers=self._get_headers())
            # response.raise_for_status() # Opcional
            logger.info(f"WhatsApp enviado para {telefone_limpo}")
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
            "image": base64_data, # String deve começar com "data:image/..."
            "caption": caption
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_headers())
            if response.status_code not in [200, 201]:
                logger.error(f"Erro Z-API Imagem: {response.text}")
                return False
            return True
        except Exception as e:
            logger.error(f"Exceção Imagem: {e}")
            return False

    # --- ENVIAR PDF (BASE64) ---
    def enviar_pdf_b64(self, telefone, base64_data, nome_arquivo="extrato.pdf"):
        url = f"{self.base_url}/send-document"
        telefone_limpo = self._formatar_telefone(telefone)
        
        payload = {
            "phone": telefone_limpo,
            "document": base64_data, # String deve começar com "data:application/pdf..."
            "fileName": nome_arquivo
        }
        
        try:
            response = requests.post(url, json=payload, headers=self._get_headers())
            if response.status_code not in [200, 201]:
                logger.error(f"Erro Z-API PDF: {response.text}")
                return False
            return True
        except Exception as e:
            logger.error(f"Exceção PDF: {e}")
            return False

    # --- GERADOR DE IMAGEM DINÂMICA (Card Detalhado - Comissão) ---
    def _gerar_imagem_resumo_bytes(self, dados):
        """
        Gera uma imagem dinâmica que cresce conforme a quantidade de itens.
        dados esperado: {
            'titulo': str, 'vendedor': str, 'periodo': str, 
            'total': str,
            'detalhes_planos': [{'nome': 'Plano X', 'qtd': 5, 'valor': 'R$ 500'}],
            'detalhes_descontos': [{'motivo': 'Boleto', 'valor': '-R$ 50'}]
        }
        """
        if not Image:
            logger.error("Biblioteca Pillow (PIL) não instalada.")
            return None

        # 1. Recuperar listas
        planos = dados.get('detalhes_planos', [])
        descontos = dados.get('detalhes_descontos', [])

        # 2. Calcular Altura Necessária da Imagem
        # Header (140px) + Footer (100px) = 240px base
        base_height = 250
        
        # Cada linha de plano ocupa ~35px. Título da seção +40px.
        height_planos = (len(planos) * 35) + 40 if planos else 0
        
        # Cada linha de desconto ocupa ~35px. Título da seção +40px.
        height_descontos = (len(descontos) * 35) + 40 if descontos else 0
        
        final_height = base_height + height_planos + height_descontos
        final_height = max(final_height, 400)
        
        width = 600

        # Cores
        bg_color = (245, 245, 245) 
        card_color = (255, 255, 255)
        primary_color = (0, 70, 140) 
        text_color = (60, 60, 60) 
        red_color = (200, 50, 50) 

        image = Image.new('RGB', (width, final_height), bg_color)
        draw = ImageDraw.Draw(image)

        # Desenhar Fundo do Card
        margin = 20
        draw.rectangle([(margin, margin), (width-margin, final_height-margin)], fill=card_color, outline=(200,200,200), width=1)

        # Carregar Fontes (Fallback para padrão se não achar ttf)
        try:
            # Tenta carregar fontes do sistema ou pasta local (ajuste os caminhos se tiver as fontes)
            font_title = ImageFont.truetype("arial.ttf", 32)
            font_sub = ImageFont.truetype("arialbd.ttf", 22) 
            font_text = ImageFont.truetype("arial.ttf", 20)
            font_val_big = ImageFont.truetype("arialbd.ttf", 40)
        except:
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()
            font_text = ImageFont.load_default()
            font_val_big = ImageFont.load_default()

        # --- CABEÇALHO ---
        y = 50
        draw.text((40, y), dados.get('titulo', 'Resumo Detalhado'), font=font_title, fill=primary_color)
        y += 45
        draw.text((40, y), f"Consultor: {dados.get('vendedor', '-')}", font=font_text, fill=text_color)
        draw.text((350, y), f"Ref: {dados.get('periodo', '-')}", font=font_text, fill=text_color)
        y += 40
        draw.line([(40, y), (560, y)], fill=(230,230,230), width=2)
        y += 20

        # --- SEÇÃO: PLANOS ---
        if planos:
            draw.text((40, y), "Vendas por Plano:", font=font_sub, fill=(50,50,50))
            y += 35
            for p in planos:
                texto_esq = f"{p['nome']} ({p['qtd']}x)"
                draw.text((40, y), texto_esq, font=font_text, fill=text_color)
                # Valor alinhado à direita
                draw.text((420, y), p['valor'], font=font_text, fill=(0, 120, 0)) 
                y += 30
            y += 10 

        # --- SEÇÃO: DESCONTOS ---
        if descontos:
            draw.line([(40, y), (560, y)], fill=(230,230,230), width=1)
            y += 20
            draw.text((40, y), "Descontos Aplicados:", font=font_sub, fill=red_color)
            y += 35
            for d in descontos:
                draw.text((40, y), d['motivo'], font=font_text, fill=text_color)
                draw.text((420, y), d['valor'], font=font_text, fill=red_color)
                y += 30
        
        # --- FOOTER (TOTAL) ---
        y_footer = final_height - 110 
        draw.rectangle([(25, y_footer), (575, final_height-25)], fill=(235, 245, 255))
        draw.text((45, y_footer + 30), "Líquido a Receber:", font=font_sub, fill=primary_color)
        
        total_str = dados.get('total', 'R$ 0,00')
        draw.text((300, y_footer + 20), total_str, font=font_val_big, fill=(0, 150, 0))

        # Salvar em Buffer
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    def enviar_resumo_comissao(self, telefone, dados_comissao):
        """
        Orquestra a geração e envio da imagem detalhada de comissão.
        """
        try:
            logger.info(f"Gerando card detalhado para {telefone}...")
            
            # 1. Gerar imagem dinâmica
            img_buffer = self._gerar_imagem_resumo_bytes(dados_comissao)
            
            if not img_buffer:
                return False

            # 2. Converter Base64
            img_str = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
            base64_final = f"data:image/png;base64,{img_str}"
            
            # 3. Caption e Envio
            caption = f"Olá {dados_comissao.get('vendedor')}, segue o detalhamento do fechamento {dados_comissao.get('periodo')}! 🚀"
            return self.enviar_imagem_b64(telefone, base64_final, caption=caption)

        except Exception as e:
            logger.error(f"Erro ao processar envio de resumo visual: {e}")
            return False

    # --- MÉTODO DE ENVIO DE O.S. (CADASTRADA) ---
    def enviar_mensagem_cadastrada(self, venda, telefone_destino=None):
        """
        Envia a mensagem padrão de 'Venda Aprovada/Cadastrada' com todos os detalhes técnicos.
        """
        # 1. Verifica DACC (Débito Automático)
        is_dacc = "NÃO"
        if venda.forma_pagamento and "DÉBITO" in venda.forma_pagamento.nome.upper():
            is_dacc = "SIM"

        # 2. Formata Agendamento
        agendamento_str = "A confirmar"
        if venda.data_agendamento:
            try:
                # Se for string ISO, converte. Se já for date, usa direto.
                if isinstance(venda.data_agendamento, str):
                    dt = datetime.strptime(venda.data_agendamento, '%Y-%m-%d')
                    data_fmt = dt.strftime('%d/%m/%Y')
                else:
                    data_fmt = venda.data_agendamento.strftime('%d/%m/%Y')
                
                horario = ""
                turno = venda.periodo_agendamento
                if turno == 'MANHA':
                    horario = "08:00 às 12:00"
                elif turno == 'TARDE':
                    horario = "13:00 às 18:00"
                elif turno: 
                    horario = turno 
                
                agendamento_str = f"Agendamento confirmado para o dia {data_fmt}"
                if horario:
                    agendamento_str += f" entre {horario}"
            except Exception as e:
                logger.warning(f"Erro ao formatar data agendamento: {e}")
                agendamento_str = str(venda.data_agendamento)

        # 3. Nome do Vendedor
        vendedor_nome = "N/A"
        if venda.vendedor:
            # Tenta pegar first_name, se não tiver usa username
            vendedor_nome = (venda.vendedor.first_name or venda.vendedor.username).upper()

        # 4. Montagem do Texto (TEMPLATE PADRÃO NIO)
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
            f"Para que sua instalação seja concluída favor salvar esse CTO no seu telefone, Técnico Nio 21 2533-9053 para receber informações da Visita."
        )

        # 5. Define destinatário e envia
        # Prioridade: Telefone passado no argumento (do vendedor) > Telefone 1 do cadastro da venda
        fone_para_envio = telefone_destino if telefone_destino else venda.telefone1
        
        if fone_para_envio:
            logger.info(f"Enviando msg detalhada de aprovação para {fone_para_envio}")
            return self.enviar_mensagem_texto(fone_para_envio, mensagem)
        else:
            logger.warning("Tentativa de envio de mensagem cadastrada sem telefone de destino.")
            return False, "Telefone não informado"