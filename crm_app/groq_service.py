# crm_app/groq_service.py
"""
Respostas com Groq API (REST, OpenAI-compatible).
Cota gratuita generosa (~14.400 req/dia). Usado como primeira opção antes do Gemini.
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def _contexto_sistema():
    """Contexto do bot para a IA responder no contexto do sistema (igual ao Gemini)."""
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


def responder_com_groq(mensagem_usuario: str, nome_vendedor: str = "") -> str | None:
    """
    Envia a mensagem ao Groq (Llama) e retorna a resposta em texto.
    Retorna None se GROQ_API_KEY não estiver configurada ou em caso de erro.
    """
    if not GROQ_API_KEY:
        logger.debug("[Groq] GROQ_API_KEY não configurada.")
        return None

    mensagem_usuario = (mensagem_usuario or "").strip()
    if not mensagem_usuario:
        return None

    user_content = mensagem_usuario
    if nome_vendedor:
        user_content = f"[Mensagem do vendedor {nome_vendedor}]: {user_content}"

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _contexto_sistema().strip()},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 1024,
        "temperature": 0.4,
    }

    try:
        resp = requests.post(
            GROQ_API_URL,
            json=payload,
            timeout=30,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            logger.warning("[Groq] Resposta sem choices.")
            return None
        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            return None
        return text
    except requests.exceptions.RequestException as e:
        logger.warning("[Groq] Erro de rede/HTTP: %s", e)
        return None
    except (KeyError, IndexError, TypeError) as e:
        logger.warning("[Groq] Erro ao interpretar resposta: %s", e)
        return None
    except Exception as e:
        logger.exception("[Groq] Erro ao chamar API: %s", e)
        return None
