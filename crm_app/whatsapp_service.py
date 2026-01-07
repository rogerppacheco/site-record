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
            headers['client-token'] = self.client_token
        return headers

    def _send_request(self, url, payload=None, method='POST'):
        """
        Método auxiliar central para envio de requisições.
        Resolve o erro 'object has no attribute _send_request'.
        """
        # LOG DETALHADO PARA DEBUG
        logger.warning(f"[Z-API DEBUG] URL: {url}")
        logger.warning(f"[Z-API DEBUG] Instance ID: [{self.instance_id}]")
        logger.warning(f"[Z-API DEBUG] Token: [{self.token[:5]}...{self.token[-3:] if self.token else ''}]")
        logger.warning(f"[Z-API DEBUG] Client-Token: [{self.client_token[:5]}...{self.client_token[-3:] if self.client_token else ''}]")
        logger.warning(f"[Z-API DEBUG] Headers: {self._get_headers()}")
        if payload:
            logger.warning(f"[Z-API DEBUG] Payload: {payload}")
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
            # Tenta caminhos comuns de Windows e Linux (Heroku)
            font_paths = [
                "arial.ttf", "Arial.ttf", 
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "DejaVuSans-Bold.ttf"
            ]
            
            font_path_regular = None
            font_path_bold = None

            # Tenta achar uma fonte Bold
            for path in font_paths:
                try:
                    ImageFont.truetype(path, 20) # Teste
                    font_path_bold = path
                    break
                except: continue
            
            # Se não achou, usa padrão (mas avisa no log)
            if not font_path_bold:
                print("AVISO: Fontes TTF não encontradas. Usando default (feio).")
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
            # Define a área onde vai a lógica dinâmica
            box_y_start = 550
            box_y_end = 950
            d.rounded_rectangle([(50, box_y_start), (W-50, box_y_end)], radius=30, fill=(245, 245, 245))

            prox_meta = dados.get('prox_meta')
            premio_atual = float(dados.get('premio_atual', 0))
            prox_premio = float(dados.get('prox_premio', 0)) if dados.get('prox_premio') else 0

            # --- CENÁRIO A: TEM PRÓXIMA META (FALTA POUCO) ---
            if prox_meta:
                falta = int(prox_meta) - vendas
                # Barra de Progresso
                pct = min(vendas / prox_meta, 1.0)
                
                bar_x1, bar_y1 = 100, 620
                bar_x2, bar_y2 = W - 100, 660
                
                # Fundo da barra
                d.rectangle([(bar_x1, bar_y1), (bar_x2, bar_y2)], fill=cor_barra_fundo)
                # Preenchimento
                fill_width = (bar_x2 - bar_x1) * pct
                color_fill = cor_verde if pct > 0.8 else cor_laranja
                d.rectangle([(bar_x1, bar_y1), (bar_x1 + fill_width, bar_y2)], fill=color_fill)
                
                # Texto da barra
                d.text((W/2, 690), f"{int(pct*100)}% DA META DE {prox_meta}", fill=cor_texto_sec, anchor="mm", font=f_label)

                # Incentivo Financeiro
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
                # Se não tem prox_meta definida mas não tem prêmio, pega do dados['meta_atual'] ou uma meta padrão
                alvo = dados.get('meta_atual') or "A PRIMEIRA META"
                d.text((W/2, 650), "VAMOS ACELERAR!", fill=cor_cabecalho, anchor="mm", font=f_titulo)
                d.text((W/2, 750), "O FOCO É BATER:", fill=cor_texto_sec, anchor="mm", font=f_destaque)
                d.text((W/2, 830), f"{alvo} VENDAS", fill=cor_laranja, anchor="mm", font=f_titulo)

            # 5. RODAPÉ
            d.line([(0, 1000), (W, 1000)], fill=(220, 220, 220), width=2)
            periodo = dados.get('periodo', '')
            d.text((W/2, 1040), f"Período: {periodo} | Atualizado em {datetime.now().strftime('%H:%M')}", fill=cor_texto_sec, anchor="mm", font=ImageFont.load_default())

            # Converter para Base64
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
        dados_relatorio: {
            'titulo': 'PERFORMANCE PAP',
            'data': '20/12/2025',
            'lista': [{'nome': 'JOAO', 'total': 10, 'cc': 2, 'pct': '20%'}, ...],
            'totais': {'total': 100, 'cc': 20, 'pct': '20%'}
        }
        """
        if not Image: return None

        try:
            # 1. Configurações de Layout
            lista = dados_relatorio.get('lista', [])
            qtd_linhas = len(lista)
            
            # Altura dinâmica: Cabeçalho (250) + Linhas (60px cada) + Rodapé (150)
            H_BASE = 250
            H_LINHA = 60
            H_RODAPE = 150
            W = 1000
            H = H_BASE + (qtd_linhas * H_LINHA) + H_RODAPE

            # Cores
            cor_fundo = (255, 255, 255)
            cor_azul_escuro = (10, 30, 60)
            cor_azul_claro = (235, 240, 255) # Para linhas alternadas
            cor_texto = (50, 50, 50)
            cor_verde = (0, 150, 70)
            cor_destaque = (255, 100, 0)

            img = Image.new('RGB', (W, H), color=cor_fundo)
            d = ImageDraw.Draw(img)

            # Fontes (Tenta carregar ou usa padrão)
            try:
                # Tenta usar as fontes que já funcionam no seu servidor/local
                # Ajuste os caminhos se necessário, igual ao seu método anterior
                f_titulo = ImageFont.truetype("arial.ttf", 60)
                f_sub = ImageFont.truetype("arial.ttf", 35)
                f_texto = ImageFont.truetype("arial.ttf", 30)
                f_bold = ImageFont.truetype("arialbd.ttf", 30) # Arial Bold se tiver
            except:
                f_titulo = ImageFont.load_default()
                f_sub = ImageFont.load_default()
                f_texto = ImageFont.load_default()
                f_bold = ImageFont.load_default()

            # 2. Cabeçalho
            d.rectangle([(0, 0), (W, 180)], fill=cor_azul_escuro)
            d.text((W/2, 60), dados_relatorio['titulo'], fill="white", anchor="mm", font=f_titulo)
            d.text((W/2, 130), f"📅 {dados_relatorio['data']}", fill="white", anchor="mm", font=f_sub)

            # Cabeçalho da Tabela
            y_start = 200
            col_x = [50, 450, 700, 900] # Posições X das colunas: Nome, Total, CC, %
            
            d.text((col_x[0], y_start), "VENDEDOR", fill=cor_azul_escuro, anchor="lm", font=f_bold)
            d.text((col_x[1], y_start), "TOTAL", fill=cor_azul_escuro, anchor="mm", font=f_bold)
            d.text((col_x[2], y_start), "CARTÃO", fill=cor_azul_escuro, anchor="mm", font=f_bold)
            d.text((col_x[3], y_start), "%", fill=cor_azul_escuro, anchor="mm", font=f_bold)
            
            d.line([(30, y_start + 25), (W-30, y_start + 25)], fill=(200,200,200), width=2)

            # 3. Linhas da Tabela
            y = y_start + 60
            for i, item in enumerate(lista):
                # Fundo alternado
                if i % 2 == 0:
                    d.rectangle([(30, y-30), (W-30, y+30)], fill=cor_azul_claro)

                d.text((col_x[0], y), str(item['nome'])[:22], fill=cor_texto, anchor="lm", font=f_texto)
                
                # Destaque se vendeu
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

            # Converter para Base64
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            return f"data:image/png;base64,{img_str}"

        except Exception as e:
            print(f"Erro ao gerar imagem performance: {e}")
            return None