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


def sugerir_status_boas_vindas(texto: str) -> str:
    """
    Sugere status para resposta do cliente às boas-vindas.
    Retorna: OK, ERRO_VENDAS, ERRO_TECNICO ou OUTROS.
    Usa regras por palavras-chave (pode ser ampliado com IA depois).
    """
    if not texto or not texto.strip():
        return 'OUTROS'
    t = texto.lower().strip()
    # Erro técnico: internet, velocidade, caiu, instável, não funciona, lento, etc.
    termos_tecnico = [
        'internet', 'velocidade', 'lento', 'lenta', 'caiu', 'cai', 'instável', 'instavel',
        'não funciona', 'nao funciona', 'não entrega', 'nao entrega', 'queda', 'sinal',
        'conexão', 'conexao', 'wi-fi', 'wifi', 'roteador', 'modem', 'fibra', 'reclamação',
        'reclamacao', 'problema técnico', 'problema tecnico', 'velocidade não', 'velocidade nao',
    ]
    for termo in termos_tecnico:
        if termo in t:
            return 'ERRO_TECNICO'
    # Erro de vendas: vendedor, prometeu, mentiu, atendimento, insatisfeito
    termos_vendas = [
        'vendedor', 'vendedora', 'prometeu', 'prometeu e não', 'mentiu', 'enganou',
        'atendimento ruim', 'atendimento péssimo', 'atendimento pessimo', 'insatisfeito',
        'insatisfeita', 'não era o que', 'nao era o que', 'diferente do que', 'esperava',
    ]
    for termo in termos_vendas:
        if termo in t:
            return 'ERRO_VENDAS'
    # OK: agradecimento, confirmação positiva
    termos_ok = ['obrigado', 'obrigada', 'valeu', 'ok', 'tudo bem', 'tudo certo', 'perfeito', 'ótimo', 'otimo']
    for termo in termos_ok:
        if termo in t and len(t) < 100:  # mensagem curta e positiva
            return 'OK'
    return 'OUTROS'
