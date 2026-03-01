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


def _contexto_sistema() -> str:
    """Contexto do bot + base de conhecimento (conhecimento.md, tabelas)."""
    from crm_app.ai_context import get_contexto_sistema
    return get_contexto_sistema()


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
