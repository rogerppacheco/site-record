# crm_app/ai_chat_service.py
"""
Orquestrador de IA para dúvidas no WhatsApp: tenta Groq primeiro (cota gratuita maior),
depois Gemini como fallback.
"""
import logging

logger = logging.getLogger(__name__)


def responder_com_ia(mensagem_usuario: str, nome_vendedor: str = "", contexto_externo: bool = False) -> str | None:
    """
    Tenta responder usando IA: primeiro Groq, depois Gemini.
    Retorna o texto da resposta ou None se nenhum conseguir.
    contexto_externo=True: prompt para contatos não cadastrados (resposta acolhedora, analista retornará).
    """
    # 1) Groq (cota gratuita ~14.400 req/dia)
    try:
        from crm_app.groq_service import responder_com_groq
        resposta = responder_com_groq(mensagem_usuario, nome_vendedor=nome_vendedor, contexto_externo=contexto_externo)
        if resposta:
            logger.info("[IA] Resposta enviada via Groq.")
            return resposta
    except Exception as e:
        logger.warning("[IA] Groq falhou: %s", e)

    # 2) Gemini (fallback; cota free mais restrita)
    try:
        from crm_app.gemini_service import responder_com_gemini
        resposta = responder_com_gemini(mensagem_usuario, nome_vendedor=nome_vendedor, contexto_externo=contexto_externo)
        if resposta:
            logger.info("[IA] Resposta enviada via Gemini.")
            return resposta
    except Exception as e:
        logger.warning("[IA] Gemini falhou: %s", e)

    return None
