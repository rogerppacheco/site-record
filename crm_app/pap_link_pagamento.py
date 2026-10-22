"""Mensagem do comando WhatsApp LINK (reenvio do link de pagamento no PAP)."""
from __future__ import annotations

from typing import Any


def formatar_resultado_link_pagamento(detalhes: list[dict[str, Any]] | None, tempo_decorrido: float) -> str:
    linhas = ["💳 *Link de pagamento*", ""]
    if not detalhes:
        linhas.append("Não tem pedido com 30 dias para este CPF/CNPJ.")
    else:
        for pedido in detalhes:
            numero = (pedido.get("numero_os") or "-").strip() or "-"
            if pedido.get("nao_pertence_pdv"):
                linhas.append(f"O.S. *{numero}*: sem Detalhar neste PDV. O link não foi enviado.")
                continue
            link = pedido.get("link_pagamento") or {}
            if link.get("ok"):
                linhas.append(f"✅ O.S. *{numero}*: link reenviado ao cliente.")
                if link.get("whatsapp"):
                    linhas.append(f"WhatsApp: {link['whatsapp']}")
                if link.get("email"):
                    linhas.append(f"E-mail: {link['email']}")
                linhas.append(
                    "Peça para o cliente conferir o WhatsApp e o e-mail "
                    "para incluir os dados do cartão."
                )
            else:
                motivo = (link.get("mensagem") or "não foi possível reenviar o link.").strip()
                linhas.append(f"⚠️ O.S. *{numero}*: {motivo}")
            linhas.append("")
    linhas.append(f"⏱ _{tempo_decorrido}s_")
    return "\n".join(linhas).strip()
