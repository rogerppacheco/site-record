"""Elegibilidade WhatsApp (celular BR + regras de negócio).

Usado por Venda.is_whatsapp_eligible e pelo Funil de Tratamento.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Celular BR: DDD (1-9)(0-9) + 9 + 8 dígitos; opcional prefixo 55.
REGEX_CELULAR_BR = re.compile(r"^(?:55)?([1-9]\d)9\d{8}$")
_DIGITS = re.compile(r"\D+")


def apenas_digitos(valor: Any) -> str:
    return _DIGITS.sub("", str(valor or ""))


def validar_celular_br(valor: Any) -> tuple[str, bool]:
    """Retorna (e164 sem +, ok?). Exige DDD + 9 dígitos (celular)."""
    digitos = apenas_digitos(valor)
    if not digitos:
        return "", False
    if digitos.startswith("55") and len(digitos) >= 12:
        digitos = digitos
    elif len(digitos) == 11:
        digitos = "55" + digitos
    elif len(digitos) == 13 and digitos.startswith("55"):
        pass
    else:
        return digitos[:20], False

    if not REGEX_CELULAR_BR.match(digitos):
        return digitos[:20], False
    return digitos, True


def _mailing_opt_out(telefone_e164: str, cpf: str = "") -> bool:
    if not telefone_e164 and not cpf:
        return False
    try:
        from crm_app.models import MailingContato

        qs = MailingContato.objects.filter(opt_out=True)
        if telefone_e164:
            local = telefone_e164[2:] if telefone_e164.startswith("55") else telefone_e164
            if qs.filter(telefone_e164__in=[telefone_e164, local, "55" + local]).exists():
                return True
        if cpf:
            digitos = apenas_digitos(cpf)
            if len(digitos) >= 11 and qs.filter(documento__icontains=digitos[-11:]).exists():
                return True
    except Exception:
        return False
    return False


def avaliar_elegibilidade_whatsapp(
    *,
    telefone: Any = "",
    telefone2: Any = "",
    nao_perturbe: bool = False,
    cpf: str = "",
    verificar_mailing_opt_out: bool = True,
) -> dict:
    """Avaliação base (telefone + não perturbe + opt-out).

    Retorno: {ok, telefone, motivos: list[str]}
    """
    motivos: list[str] = []
    if nao_perturbe:
        motivos.append('Marcado como "não perturbe".')

    tel, ok = validar_celular_br(telefone)
    if not ok:
        tel2, ok2 = validar_celular_br(telefone2)
        if ok2:
            tel, ok = tel2, True
        else:
            if not apenas_digitos(telefone) and not apenas_digitos(telefone2):
                motivos.append("Sem telefone cadastrado.")
            else:
                motivos.append("Telefone inválido (exige DDD + 9 dígitos de celular).")

    if ok and verificar_mailing_opt_out and _mailing_opt_out(tel, cpf):
        motivos.append("Contato com opt-out de mailing (não perturbe).")
        ok = False

    if motivos and ok:
        # não_perturbe sozinho já invalida
        ok = False

    return {
        "ok": bool(ok) and not motivos,
        "telefone": tel if ok or tel else "",
        "motivos": motivos,
    }


def elegibilidade_venda(venda) -> dict:
    """Property helper para o modelo Venda."""
    cpf = ""
    try:
        if getattr(venda, "cliente_id", None) and venda.cliente_id:
            cpf = getattr(venda.cliente, "cpf_cnpj", "") or ""
    except Exception:
        cpf = ""
    return avaliar_elegibilidade_whatsapp(
        telefone=getattr(venda, "telefone1", "") or "",
        telefone2=getattr(venda, "telefone2", "") or "",
        nao_perturbe=bool(getattr(venda, "nao_perturbe", False)),
        cpf=cpf,
    )
