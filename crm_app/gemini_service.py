# crm_app/gemini_service.py
"""
Serviço para respostas com Gemini API, no contexto do sistema/site.
Usado quando um vendedor envia mensagem que não é um comando do bot:
a IA interpreta e responde com base no conhecimento do sistema.
"""
import os
import logging

logger = logging.getLogger(__name__)

# Chave da API: use variável de ambiente GEMINI_API_KEY (nunca commitar a chave).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()


def _contexto_sistema():
    """
    Texto que descreve o sistema/bot para o Gemini responder no contexto correto.
    Pode ser expandido ou carregado de arquivo/settings no futuro.
    """
    return """
Você é um assistente do sistema interno (CRM/gestão) usado por vendedores da operadora de internet.
O bot do WhatsApp oferece estes comandos e fluxos:

- *Fachada*: consultar fachadas por CEP
- *Viabilidade*: consultar viabilidade por CEP e número (mapa/mancha)
- *Inclusão*: solicitar viabilidade via formulário
- *Status*: consultar status de pedido
- *Fatura*: consultar fatura por CPF (Nio Negociar)
- *Conta*: 2ª via de conta por CPF
- *Material* / *Apoia*: buscar materiais e documentos por palavra-chave (Record Apoia)
- *Andamento*: ver agendamentos do dia
- *Crédito*: análise de crédito por CPF
- *Pedido*: consultar pedido/O.S. por CPF no PAP
- *Vender*: realizar venda pelo WhatsApp (fluxo completo)
- *Nova Venda*: cadastrar venda no CRM (Via APP ou Sem APP)
- *MENU* ou *AJUDA*: listar opções

Regras para suas respostas:
- Seja objetivo e cordial. Responda em português.
- Se a dúvida for sobre como usar o bot, indique o comando ou diga para digitar MENU.
- Se for dúvida sobre processo, prazos, planos ou regras internas, responda com base no que você sabe sobre CRM de operadora e vendas; se não souber, sugira falar com o gestor ou suporte.
- Respostas devem ser curtas (ideais para WhatsApp). Evite parágrafos longos.
- Não invente dados de clientes, vendas ou faturas; oriente a usar o comando correto (Fatura, Pedido, Status, etc.).
"""


def responder_com_gemini(mensagem_usuario: str, nome_vendedor: str = "") -> str | None:
    """
    Envia a mensagem do usuário ao Gemini com o contexto do sistema e retorna a resposta em texto.
    Retorna None em caso de erro ou se GEMINI_API_KEY não estiver configurada.
    """
    if not GEMINI_API_KEY:
        logger.debug("[Gemini] GEMINI_API_KEY não configurada, ignorando.")
        return None

    mensagem_usuario = (mensagem_usuario or "").strip()
    if not mensagem_usuario:
        return None

    try:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(
            "gemini-1.5-flash",
            system_instruction=_contexto_sistema().strip(),
        )

        user_content = mensagem_usuario
        if nome_vendedor:
            user_content = f"[Mensagem do vendedor {nome_vendedor}]: {user_content}"

        response = model.generate_content(
            user_content,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=1024,
                temperature=0.4,
            ),
        )

        if not response or not response.text:
            logger.warning("[Gemini] Resposta vazia.")
            return None

        return response.text.strip()
    except ImportError as e:
        logger.warning("[Gemini] google-generativeai não instalado: %s", e)
        return None
    except Exception as e:
        logger.exception("[Gemini] Erro ao chamar API: %s", e)
        return None
