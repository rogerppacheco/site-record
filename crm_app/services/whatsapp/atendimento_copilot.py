"""Copilot do inbox WhatsApp (Fase 4+6): resumo, sugestão e reescrita via Gemini + KB."""
from __future__ import annotations

import logging
from typing import Optional

from crm_app.services.whatsapp.atendimento_service import (
    canonicalizar_telefone,
    detalhe_conversa,
)

logger = logging.getLogger(__name__)

_MAX_MSGS = 40
_MAX_CHARS_CTX = 6000


def _kb_snippet(max_chars: int = 3500) -> str:
    """Trecho da base Conhecimento IA para o copiloto do inbox."""
    try:
        from crm_app.ai_context import get_contexto_sistema

        txt = (get_contexto_sistema(reduzido=False) or "").strip()
    except Exception:
        logger.exception("[copilot] falha ao carregar conhecimento IA")
        return ""
    if not txt:
        return ""
    if len(txt) > max_chars:
        txt = txt[:max_chars] + "\n... (conhecimento truncado)"
    return txt


def _montar_contexto_conversa(usuario, telefone: str) -> tuple[Optional[dict], str]:
    det = detalhe_conversa(usuario, telefone, limit_msgs=_MAX_MSGS)
    if det is None:
        return None, ""
    linhas = []
    lead = det.get("lead") or {}
    if lead:
        linhas.append(
            "LEAD: "
            f"cliente={lead.get('cliente') or '—'}; "
            f"pedido=#{lead.get('venda_id') or '—'}; "
            f"plano={lead.get('plano') or '—'}; "
            f"status={lead.get('status_tratamento') or '—'} / {lead.get('status_esteira') or '—'}; "
            f"nao_perturbe={lead.get('nao_perturbe')}"
        )
    if det.get("etapa_funil"):
        linhas.append(f"ETAPA_FUNIL: {det.get('etapa_funil_label') or det.get('etapa_funil')}")
    for m in det.get("mensagens") or []:
        lado = "CLIENTE" if m.get("direcao") == "ENTRADA" else "OPERADOR"
        txt = (m.get("texto") or "").replace("\n", " ").strip()
        if not txt:
            continue
        linhas.append(f"{lado}: {txt[:400]}")
    for n in reversed((det.get("notas") or [])[:5]):
        linhas.append(f"NOTA_INTERNA ({n.get('autor') or '?'}): {(n.get('texto') or '')[:200]}")
    ctx = "\n".join(linhas)
    if len(ctx) > _MAX_CHARS_CTX:
        ctx = ctx[-_MAX_CHARS_CTX:]
    return det, ctx


def _chamar_gemini(system_prompt: str, user_prompt: str) -> tuple[bool, str]:
    """Groq primeiro (padrão do bot), Gemini como fallback. Mensagens de erro úteis."""
    erros: list[str] = []

    try:
        from crm_app.groq_service import GROQ_API_KEY, responder_com_groq_custom

        if GROQ_API_KEY:
            texto = responder_com_groq_custom(user_prompt, system_prompt)
            if texto:
                return True, texto.strip()
            erros.append("Groq sem resposta")
        else:
            erros.append("GROQ_API_KEY ausente")
    except Exception as e:
        erros.append(f"Groq: {e}")

    try:
        from crm_app.gemini_service import GEMINI_API_KEY, responder_com_gemini_custom

        if GEMINI_API_KEY:
            texto = responder_com_gemini_custom(user_prompt, system_prompt)
            if texto:
                return True, texto.strip()
            erros.append(
                "Gemini falhou (chave inválida/revogada ou cota). "
                "Gere uma nova GEMINI_API_KEY no Google AI Studio se quiser o fallback."
            )
        else:
            erros.append("GEMINI_API_KEY ausente")
    except Exception as e:
        erros.append(f"Gemini: {e}")

    detalhe = "; ".join(erros) if erros else "nenhum provedor respondeu"
    return False, f"A IA não retornou resposta ({detalhe})."


def resumir_conversa(usuario, telefone: str) -> tuple[str, dict]:
    tel = canonicalizar_telefone(telefone)
    det, ctx = _montar_contexto_conversa(usuario, tel)
    if det is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    if not ctx.strip():
        return "invalido", {"detail": "Não há mensagens suficientes para resumir."}

    kb = _kb_snippet(2500)
    ok, texto = _chamar_gemini(
        system_prompt=(
            "Você é um copiloto de CRM de telecom (Record PAP). "
            "Resuma a conversa de WhatsApp em português do Brasil, objetivo e útil para o atendente. "
            "Se a base de conhecimento ajudar a interpretar o caso, use-a sem inventar fatos. "
            "Formato:\n"
            "1) Situação atual (1-2 frases)\n"
            "2) Pedidos / dúvidas do cliente\n"
            "3) O que já foi prometido/enviado\n"
            "4) Próximo passo sugerido\n"
            "5) Pontos em aberto\n"
            "Não invente dados que não estejam no contexto."
        ),
        user_prompt=(
            (f"Base de conhecimento:\n{kb}\n\n" if kb else "")
            + f"Contexto da conversa:\n{ctx}"
        ),
    )
    if not ok:
        return "falha_ia", {"detail": texto}
    return "ok", {"ok": True, "resumo": texto, "conversa": det}


def sugerir_resposta(usuario, telefone: str, *, instrucao: str = "") -> tuple[str, dict]:
    tel = canonicalizar_telefone(telefone)
    det, ctx = _montar_contexto_conversa(usuario, tel)
    if det is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}

    extra = (instrucao or "").strip()
    kb = _kb_snippet()
    ok, texto = _chamar_gemini(
        system_prompt=(
            "Você é um copiloto de atendimento WhatsApp da Record PAP (telecom). "
            "Escreva UMA resposta pronta para o operador enviar ao cliente. "
            "Tom: cordial, claro, profissional, português do Brasil. "
            "Use a base de conhecimento quando for relevante; não invente planos, preços ou processos. "
            "Sem markdown, sem aspas envolvendo o texto, sem explicar o que fez. "
            "Máximo 800 caracteres. Não invente protocolos, datas ou valores."
        ),
        user_prompt=(
            (f"Base de conhecimento:\n{kb}\n\n" if kb else "")
            + f"Contexto da conversa:\n{ctx}\n\n"
            + (f"Instrução extra do operador: {extra}\n" if extra else "")
            + "Escreva só a mensagem final."
        ),
    )
    if not ok:
        return "falha_ia", {"detail": texto}
    return "ok", {"ok": True, "sugestao": texto, "conversa": det}


def reescrever_texto(
    usuario,
    telefone: str,
    *,
    texto: str,
    tom: str = "profissional",
) -> tuple[str, dict]:
    corpo = (texto or "").strip()
    if not corpo:
        return "invalido", {"detail": "Informe o texto a reescrever."}
    tel = canonicalizar_telefone(telefone)
    det = None
    try:
        det = detalhe_conversa(usuario, tel, limit_msgs=10)
    except Exception:
        det = None

    tom_n = (tom or "profissional").strip().lower()
    mapa = {
        "profissional": "mais profissional e cordial",
        "curto": "mais curto e direto",
        "formal": "mais formal",
        "amigavel": "mais amigável e simples",
        "amigável": "mais amigável e simples",
    }
    estilo = mapa.get(tom_n, mapa["profissional"])

    ok, out = _chamar_gemini(
        system_prompt=(
            "Reescreva a mensagem de WhatsApp do operador. "
            f"Deixe o texto {estilo}. "
            "Mantenha o sentido. Português do Brasil. "
            "Responda só com a mensagem reescrita, sem explicações."
        ),
        user_prompt=corpo,
    )
    if not ok:
        return "falha_ia", {"detail": out}
    payload = {"ok": True, "texto": out, "tom": tom_n}
    if det:
        payload["conversa"] = det
    return "ok", payload


def resumir_lead(usuario, telefone: str) -> tuple[str, dict]:
    """Resumo focado no lead/pedido (painel direito)."""
    tel = canonicalizar_telefone(telefone)
    det, ctx = _montar_contexto_conversa(usuario, tel)
    if det is None:
        return "nao_encontrado", {"detail": "Conversa não encontrada."}
    kb = _kb_snippet(2000)
    ok, texto = _chamar_gemini(
        system_prompt=(
            "Você é um copiloto comercial. Em 4-6 linhas, resuma o lead/pedido "
            "e o estado da negociação no WhatsApp para o vendedor assumir rápido. "
            "Português do Brasil. Sem inventar dados."
        ),
        user_prompt=(
            (f"Base de conhecimento:\n{kb}\n\n" if kb else "")
            + (ctx or "Sem histórico.")
        ),
    )
    if not ok:
        return "falha_ia", {"detail": texto}
    return "ok", {"ok": True, "resumo_lead": texto, "conversa": det}
