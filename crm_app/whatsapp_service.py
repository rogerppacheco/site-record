import requests
import logging
from decouple import config
import os

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
        if len(telefone_limpo) <= 11: 
            telefone_limpo = f"55{telefone_limpo}"
        return telefone_limpo

    def verificar_numero_existe(self, telefone):
        telefone_limpo = self._formatar_telefone(telefone)
        url = f"{self.base_url}/phone-exists/{telefone_limpo}"
        
        if not self.instance_id or not self.token:
            logger.error("Z-API credentials não configuradas.")
            return False 

        try:
            # Usa _get_headers para incluir o token de segurança
            response = requests.get(url, headers=self._get_headers())
            
            if response.status_code != 200:
                logger.error(f"Falha Z-API verificar numero {telefone_limpo}. Status: {response.status_code}. Resposta: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            
            existe = data.get('exists', False)
            
            if existe:
                logger.info(f"Número {telefone_limpo} verificado: Possui WhatsApp.")
            else:
                logger.warning(f"Número {telefone_limpo} verificado: NÃO possui WhatsApp.")
                
            return existe

        except Exception as e:
            if "Falha Z-API" not in str(e):
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
            # Usa _get_headers para incluir o token de segurança
            response = requests.post(url, json=payload, headers=self._get_headers())
            response.raise_for_status()
            logger.info(f"WhatsApp enviado para {telefone_limpo}: {response.json()}")
            return True, response.json()
        except Exception as e:
            logger.error(f"Erro ao enviar WhatsApp para {telefone_limpo}: {e}")
            return False, str(e)

    def enviar_mensagem_cadastrada(self, venda, telefone_destino=None):
        """
        Formata e envia a mensagem de Venda Cadastrada/Aprovada.
        """
        # 1. Lógica do DACC
        is_dacc = "NÃO"
        # Verifica se existe forma de pagamento e se contém 'DÉBITO' (maiúsculo/minúsculo)
        if venda.forma_pagamento and "DÉBITO" in venda.forma_pagamento.nome.upper():
            is_dacc = "SIM"

        # 2. Lógica do Agendamento
        agendamento_str = "A confirmar"
        if venda.data_agendamento:
            data_fmt = venda.data_agendamento.strftime('%d/%m/%Y')
            periodo_texto = ""
            
            if venda.periodo_agendamento == 'MANHA':
                periodo_texto = "8h às 12h"
            elif venda.periodo_agendamento == 'TARDE':
                periodo_texto = "13h às 18h"
            
            agendamento_str = f"Agendamento confirmado para o dia {data_fmt}"
            if periodo_texto:
                agendamento_str += f" entre {periodo_texto}"

        # 3. Dados auxiliares
        vendedor_nome = venda.vendedor.first_name if (venda.vendedor and venda.vendedor.first_name) else (venda.vendedor.username if venda.vendedor else 'N/A')
        os_cod = venda.ordem_servico or "Gerando..."
        cliente_nome = venda.cliente.nome_razao_social if venda.cliente else "Cliente"
        cliente_doc = venda.cliente.cpf_cnpj if venda.cliente else "-"
        plano_nome = venda.plano.nome if venda.plano else "-"

        # 4. Montagem da Mensagem (Template Solicitado)
        mensagem = (
            f"APROVADO!✅✅\n"
            f"PLANO ADQUIRIDO: {plano_nome}\n"
            f"NOME DO CLIENTE: {cliente_nome}\n"
            f"CPF/CNPJ: {cliente_doc}\n"
            f"OS: {os_cod}\n"
            f"DACC: {is_dacc}\n"
            f"AGENDAMENTO: {agendamento_str}\n"
            f"VENDEDOR: {vendedor_nome}\n"
            f"⚠FATURA, SEGUNDA VIA OU DÚVIDAS\n"
            f"https://www.niointernet.com.br/\n"
            f"WhatsApp: 31985186530\n"
            f"Para que sua instalação seja concluída favor salvar esse CTO no seu telefone, "
            f"Técnico Nio 21 2533-9053 para receber informações da Visita."
        )

        # 5. Envio
        # Se foi passado um telefone específico (ex: do vendedor via signals), usa ele.
        # Senão, tenta usar o do cliente (venda.telefone1).
        fone_para_envio = telefone_destino if telefone_destino else venda.telefone1
        
        if fone_para_envio:
            return self.enviar_mensagem_texto(fone_para_envio, mensagem)
        else:
            logger.warning(f"Venda {venda.id} sem telefone de destino definido.")
            return False, "Telefone não informado"