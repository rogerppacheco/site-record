"""
Templates Meta Nio (Número B / WhatsAtende Cloud API).

Envio fora da janela 24h e fluxos oficiais (confirmação, instalação, cobrança).
Botões Quick Reply chegam no webhook como texto do botão.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Nomes aprovados / em aprovação na WABA (WhatsAtende Número B — conexão #247)
TEMPLATE_CONFIRMACAO_PEDIDO = "nio_confirmacao_pedido_v1"
TEMPLATE_LEMBRETE_INSTALACAO = "nio_lembrete_instalacao_v1"
TEMPLATE_INSTALACAO_CONFIRMADA = "nio_instalacao_confirmada_v1_2"
TEMPLATE_FATURA_LEMBRETE_5D = "nio_fatura_lembrete_5d_antes_v1"
TEMPLATE_FATURA_VENCIDA_5D = "nio_fatura_vencida_5d_v1"
TEMPLATE_FATURA_RECORRENTE = "nio_fatura_cobranca_recorrente_v1"
TEMPLATE_FATURA_REDUCAO_SINAL = "nio_fatura_reducao_sinal_v1"
TEMPLATE_PENDENCIA_REAGENDAMENTO = "nio_pendencia_reagendamento_v1"
TEMPLATE_BOAS_VINDAS = "nio_boas_vindas_v1"
TEMPLATE_REAGENDAMENTO_CLIENTE = "nio_reagendamento_cliente_v1"

# Funil de Tratamento (utilitários)
TEMPLATE_CONSULTA_VIABILIDADE = "nio_consulta_viabilidade_v1"
TEMPLATE_REATIVACAO_CONTRATO = "nio_reativacao_contrato_v1"
# Editar/reaprovar este nome na WABA #247: {{1}}=primeiro nome, {{2}}=Prot. {protocolo}
TEMPLATE_SELFIE_PENDENTE = "nio_selfie_pendente_v1"

# Mailings de mercado (UTILITY — copy sem oferta)
TEMPLATE_MAILING_REPARO = "mailing_reparo_v1"
TEMPLATE_MAILING_INSTALACAO = "mailing_instalacao_v1"
TEMPLATE_MAILING_MUDANCA = "mailing_mudanca_v1"
TEMPLATE_MAILING_SERVICO = "mailing_servico_v1"
TEMPLATE_MAILING_CANCELAMENTO = "mailing_cancelamento_v1"
TEMPLATE_MAILING_FECHADO = "mailing_fechado_v1"
TEMPLATE_MAILING_ABERTO = "mailing_aberto_v1"
TEMPLATE_MAILING_GENERICO = "mailing_generico_v1"

NIO_WHATSAPP_OFICIAL_EXIBICAO = "21 3605-1000"

LANGUAGE_PT_BR = "pt_BR"

# Respostas de botão (texto que o cliente envia ao clicar)
BTN_CORRETO = "CORRETO"
BTN_CORRIGIR = "CORRIGIR"
BTN_FALAR_ATENDENTE = "FALAR COM ATENDENTE"
BTN_CONFIRMAR = "CONFIRMAR"
BTN_REAGENDAR = "REAGENDAR"
BTN_SUPORTE = "SUPORTE"
BTN_ENTENDI = "ENTENDI"
BTN_SEGUNDA_VIA = "QUERO A 2A VIA"
BTN_JA_PAGUEI = "JA PAGUEI"
BTN_FALAR_SUPORTE = "FALAR COM SUPORTE"
BTN_INFORMAR_PREVISAO = "INFORMAR PREVISAO"


def templates_habilitados() -> bool:
    """Usa templates Meta quando o canal cliente é Cloud API (WhatsAtende B / hybrid)."""
    flag = getattr(settings, "WHATSAPP_USE_NIO_TEMPLATES", None)
    if flag is not None:
        return bool(flag)
    try:
        from crm_app.services.whatsapp_config_service import cliente_usa_cloud_api

        return cliente_usa_cloud_api()
    except Exception:
        provider = (getattr(settings, "WHATSAPP_PROVIDER", "") or "").strip().lower()
        return provider in ("whatsatende", "hybrid")


def saudacao_meta(agora: Optional[datetime] = None) -> str:
    """
    Saudação para {{1}} dos templates (fuso America/Sao_Paulo via TIME_ZONE).
    05–11 Bom dia | 12–17 Boa tarde | 18–04 Boa noite
    """
    dt = agora or timezone.localtime()
    hora = dt.hour
    if 5 <= hora <= 11:
        return "Bom dia"
    if 12 <= hora <= 17:
        return "Boa tarde"
    return "Boa noite"


def primeiro_nome(nome_completo: Optional[str]) -> str:
    nome = (nome_completo or "").strip()
    if not nome:
        return "Cliente"
    return nome.split()[0]


def mascarar_cpf(cpf: Optional[str]) -> str:
    digitos = re.sub(r"\D", "", cpf or "")
    if len(digitos) != 11:
        return "***.***.***-**"
    return f"***.{digitos[3:6]}.{digitos[6:9]}-**"


def mascarar_email(email: Optional[str]) -> str:
    e = (email or "").strip()
    if "@" not in e:
        return "***@***.***"
    local, _, dominio = e.partition("@")
    if not local:
        return f"***@{dominio}"
    if len(local) == 1:
        return f"{local}***@{dominio}"
    return f"{local[0]}***{local[-1]}@{dominio}"


def _fmt_cep(cep: Optional[str]) -> str:
    digitos = re.sub(r"\D", "", cep or "")
    if len(digitos) == 8:
        return f"{digitos[:5]}-{digitos[5:]}"
    return (cep or "").strip() or "-"


def _fmt_moeda(valor: Any) -> str:
    try:
        from crm_app.services.gdp_preco_service import formatar_moeda_br

        return formatar_moeda_br(valor)
    except Exception:
        try:
            n = float(valor)
            return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (TypeError, ValueError):
            return "R$ 0,00"


def _fmt_data(d: Any) -> str:
    if isinstance(d, datetime):
        d = timezone.localtime(d).date() if timezone.is_aware(d) else d.date()
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    s = str(d or "").strip()
    return s or "-"


def normalizar_texto_botao(texto: Optional[str]) -> str:
    """Uppercase sem acento para casar Quick Reply Meta com handlers."""
    raw = (texto or "").strip()
    if not raw:
        return ""
    nfkd = unicodedata.normalize("NFKD", raw)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).upper().replace("ª", "A").replace("º", "O")


def classificar_botao(texto: Optional[str]) -> Optional[str]:
    """Retorna constante BTN_* ou None."""
    n = normalizar_texto_botao(texto)
    if not n:
        return None
    mapa = {
        "CORRETO": BTN_CORRETO,
        "CORRIGIR": BTN_CORRIGIR,
        "FALAR COM ATENDENTE": BTN_FALAR_ATENDENTE,
        "CONFIRMAR": BTN_CONFIRMAR,
        "REAGENDAR": BTN_REAGENDAR,
        "SUPORTE": BTN_SUPORTE,
        "ENTENDI": BTN_ENTENDI,
        "QUERO A 2A VIA": BTN_SEGUNDA_VIA,
        "QUERO A 2 VIA": BTN_SEGUNDA_VIA,
        "JA PAGUEI": BTN_JA_PAGUEI,
        "FALAR COM SUPORTE": BTN_FALAR_SUPORTE,
        "INFORMAR PREVISAO": BTN_INFORMAR_PREVISAO,
        "INFORMAR PREVISAO DE PAGAMENTO": BTN_INFORMAR_PREVISAO,
    }
    if n in mapa:
        return mapa[n]
    # Fallbacks curtos
    if n in ("SIM", "S", "CONFIRMO", "OK"):
        return BTN_CONFIRMAR
    return None


def body_params_confirmacao_venda(venda: Any) -> List[str]:
    """14 variáveis de nio_confirmacao_pedido_v1 a partir de Venda."""
    cliente = getattr(venda, "cliente", None)
    nome = ""
    cpf = ""
    email = ""
    if cliente is not None:
        nome = (getattr(cliente, "nome_razao_social", None) or "").strip()
        cpf = getattr(cliente, "cpf_cnpj", None) or ""
        email = getattr(cliente, "email", None) or ""

    complemento = (getattr(venda, "complemento", None) or "").strip() or "-"
    cidade = (getattr(venda, "cidade", None) or "").strip()
    uf = (getattr(venda, "estado", None) or "").strip()
    cidade_uf = f"{cidade} - {uf}".strip(" -") if (cidade or uf) else "-"

    forma = ""
    if getattr(venda, "forma_pagamento", None):
        forma = (venda.forma_pagamento.nome or "").strip()
    forma = forma or "Boleto"

    plano_linha = "Não informado"
    if getattr(venda, "plano", None):
        try:
            from crm_app.services.gdp_preco_service import (
                VALOR_FIXO_NIO_MENSAL,
                formatar_moeda_br,
                resolver_valor_plano_venda,
            )

            valor_plano, _ = resolver_valor_plano_venda(venda)
            plano_linha = f"{venda.plano.nome} - {formatar_moeda_br(valor_plano)}/mês"
            if getattr(venda, "tem_fixo", False):
                total = float(valor_plano) + float(VALOR_FIXO_NIO_MENSAL)
                plano_linha = (
                    f"{venda.plano.nome} - {formatar_moeda_br(valor_plano)}/mês "
                    f"+ Fixo {formatar_moeda_br(VALOR_FIXO_NIO_MENSAL)}/mês "
                    f"= {formatar_moeda_br(total)}/mês"
                )
        except Exception as exc:
            logger.warning("[NioTemplates] plano venda=%s: %s", getattr(venda, "id", "?"), exc)
            plano_linha = getattr(venda.plano, "nome", None) or plano_linha

    return [
        saudacao_meta(),
        primeiro_nome(nome),
        nome or "Cliente",
        mascarar_cpf(cpf),
        mascarar_email(email),
        _fmt_cep(getattr(venda, "cep", None)),
        (getattr(venda, "logradouro", None) or "").strip() or "-",
        (getattr(venda, "numero_residencia", None) or "").strip() or "-",
        complemento,
        (getattr(venda, "bairro", None) or "").strip() or "-",
        cidade_uf,
        forma,
        plano_linha,
        "12 meses",
    ]


def body_params_confirmacao_pap(dados: Dict[str, Any]) -> List[str]:
    """14 variáveis a partir de dados_pedido do fluxo PAP."""
    nome = (dados.get("nome_cliente") or "Cliente").strip()
    cpf = dados.get("cpf") or dados.get("cpf_cnpj") or ""
    email = dados.get("email") or ""
    cep = dados.get("cep") or ""
    logradouro = (dados.get("logradouro") or dados.get("rua") or "").strip() or "-"
    numero = (dados.get("numero") or "").strip() or "-"
    complemento = (dados.get("complemento") or dados.get("referencia") or "").strip() or "-"
    bairro = (dados.get("bairro") or "").strip() or "-"
    cidade = (dados.get("cidade") or "").strip()
    uf = (dados.get("uf") or dados.get("estado") or "").strip()
    cidade_uf = f"{cidade} - {uf}".strip(" -") if (cidade or uf) else "-"

    plano = (dados.get("plano") or "500mega").upper()
    forma_raw = (dados.get("forma_pagamento") or "Boleto").strip().lower()
    cartao = "credito" in forma_raw or "cartao" in forma_raw or "cartão" in forma_raw
    valor_map = {
        "500MEGA": ("R$ 100,00/mês", "R$ 90,00/mês"),
        "700MEGA": ("R$ 130,00/mês", "R$ 120,00/mês"),
        "1GIGA": ("R$ 160,00/mês", "R$ 150,00/mês"),
    }
    par = valor_map.get(plano, ("R$ --/mês", "R$ --/mês"))
    valor = par[1] if cartao else par[0]
    plano_label = plano.replace("MEGA", " Mega").replace("GIGA", " Giga")
    forma_map = {
        "boleto": "Boleto",
        "cartao": "Cartão de Crédito",
        "cartão": "Cartão de Crédito",
        "debito": "Débito em Conta",
        "débito": "Débito em Conta",
    }
    forma = forma_map.get(forma_raw) or forma_raw.title()

    return [
        saudacao_meta(),
        primeiro_nome(nome),
        nome,
        mascarar_cpf(str(cpf)),
        mascarar_email(str(email)),
        _fmt_cep(str(cep)),
        logradouro,
        numero,
        complemento,
        bairro,
        cidade_uf or "-",
        forma,
        f"{plano_label} - {valor}",
        "12 meses",
    ]


def body_params_lembrete_instalacao(
    nome_cliente: str,
    data_agendamento: Any,
    periodo: str,
) -> List[str]:
    periodo_u = (periodo or "").strip().upper()
    if periodo_u in ("MANHA", "MANHÃ"):
        janela = "08:00 às 12:00"
    elif periodo_u in ("TARDE",):
        janela = "13:00 às 18:00"
    else:
        janela = (periodo or "").strip() or "a confirmar"
    data_txt = _fmt_data(data_agendamento)
    if isinstance(data_agendamento, date) and not isinstance(data_agendamento, datetime):
        # Preferência do template: dd/mm/yyyy; se for "hoje" o CRM já passa a data
        data_txt = data_agendamento.strftime("%d/%m/%Y")
    return [
        saudacao_meta(),
        primeiro_nome(nome_cliente),
        data_txt,
        janela,
    ]


def body_params_instalacao_confirmada(data_agendamento: Any, periodo: str) -> List[str]:
    """nio_instalacao_confirmada_v1_2: {{1}} data, {{2}} horário (sem saudação)."""
    periodo_u = (periodo or "").strip().upper()
    if periodo_u in ("MANHA", "MANHÃ"):
        janela = "08:00 às 12:00"
    elif periodo_u in ("TARDE",):
        janela = "13:00 às 18:00"
    else:
        janela = (periodo or "").strip() or "a confirmar"
    return [_fmt_data(data_agendamento), janela]


def body_params_pendencia_reagendamento(nome_cliente: str) -> List[str]:
    """nio_pendencia_reagendamento_v1: {{1}} saudação, {{2}} nome, {{3}} WhatsApp Nio."""
    return [
        saudacao_meta(),
        primeiro_nome(nome_cliente),
        NIO_WHATSAPP_OFICIAL_EXIBICAO,
    ]


def body_params_reagendamento_cliente(nome_cliente: str, parceiro: str) -> List[str]:
    """nio_reagendamento_cliente_v1: {{1}} saudação, {{2}} nome, {{3}} parceiro."""
    return [saudacao_meta(), primeiro_nome(nome_cliente), (parceiro or "").strip() or "parceiro Nio"]


def body_params_boas_vindas(nome_cliente: str) -> List[str]:
    """nio_boas_vindas_v1: {{1}} saudação, {{2}} nome (rascunho até aprovação Meta)."""
    return [saudacao_meta(), primeiro_nome(nome_cliente)]


def body_params_fatura(
    nome_cliente: str,
    referencia: str,
    valor: Any,
    vencimento: Any,
    *,
    dias_atraso: Optional[int] = None,
) -> List[str]:
    params = [
        saudacao_meta(),
        primeiro_nome(nome_cliente),
        (referencia or "-").strip() or "-",
        _fmt_moeda(valor) if not isinstance(valor, str) else (valor or "R$ 0,00"),
        _fmt_data(vencimento),
    ]
    if dias_atraso is not None:
        params.append(str(int(dias_atraso)))
    return params


def referencia_fatura(fatura: Any) -> str:
    if getattr(fatura, "numero_fatura_operadora", None):
        return str(fatura.numero_fatura_operadora).strip()
    venc = getattr(fatura, "data_vencimento", None)
    if isinstance(venc, date):
        meses = {
            1: "Janeiro",
            2: "Fevereiro",
            3: "Março",
            4: "Abril",
            5: "Maio",
            6: "Junho",
            7: "Julho",
            8: "Agosto",
            9: "Setembro",
            10: "Outubro",
            11: "Novembro",
            12: "Dezembro",
        }
        return f"{meses.get(venc.month, venc.month)}/{venc.year}"
    num = getattr(fatura, "numero_fatura", None)
    return f"Fatura {num}" if num else "Fatura Nio"


def montar_fallback_fatura_reducao_sinal(
    nome_cliente: str,
    fatura: Any,
) -> str:
    """Texto livre equivalente a nio_fatura_reducao_sinal_v1 (janela 24h / fallback)."""
    params = body_params_fatura(
        nome_cliente,
        referencia_fatura(fatura),
        getattr(fatura, "valor", 0),
        getattr(fatura, "data_vencimento", None),
    )
    saudacao, nome, ref, valor, venc = params[:5]
    return (
        f"Olá, {saudacao}!\n\n"
        f"{nome},\n\n"
        "Parceiro oficial da Nio Fibra.\n"
        "Sua internet está com a velocidade reduzida devido a uma pendência de pagamento.\n\n"
        f"Referência: *{ref}*\n"
        f"Valor: *{valor}*\n"
        f"Vencimento: *{venc}*\n\n"
        "Precisamos do seu retorno para programar a regularização e liberar "
        "novamente 100% do seu sinal de fibra óptica.\n\n"
        "Informe sua previsão de pagamento.\n\n"
        "SAC: 0800 001 1000 | WhatsApp: 21 3605-1000"
    )


def enviar_template_cliente(
    telefone: str,
    template_name: str,
    body_params: Sequence[str],
    *,
    language_code: str = LANGUAGE_PT_BR,
) -> Tuple[bool, Any]:
    """Envia template pelo Número B (Qualidade / #194). Retorna (ok, resposta)."""
    from crm_app.whatsapp_service import WhatsAppService

    params = [str(p) if p is not None and str(p).strip() != "" else "-" for p in body_params]
    svc = WhatsAppService.para_cliente()
    return svc.enviar_template(
        telefone,
        template_name,
        language_code=language_code,
        body_params=params,
    )


def _message_id_resposta(resp: Any) -> str:
    if not isinstance(resp, dict):
        return ""
    for key in ("messageId", "message_id", "id", "wamid", "keyId"):
        val = resp.get(key)
        if val:
            return str(val)[:128]
    msgs = resp.get("messages")
    if isinstance(msgs, list) and msgs and isinstance(msgs[0], dict):
        mid = msgs[0].get("id")
        if mid:
            return str(mid)[:128]
    data = resp.get("data")
    if isinstance(data, dict):
        return _message_id_resposta(data)
    return ""


def _espelhar_funil_no_inbox(
    *,
    telefone: str,
    template_name: str = "",
    texto: str = "",
    resp: Any = None,
    sucesso: bool = True,
    usuario=None,
    venda=None,
    aba: str = "",
    ref_id: str = "",
) -> None:
    """Espelho CRM: saída #247 → timeline do inbox (não propaga erro)."""
    try:
        from crm_app.services.whatsapp.atendimento_crm import espelhar_envio_funil_no_inbox

        mid = _message_id_resposta(resp) if sucesso else ""
        erro = "" if sucesso else str(resp)[:2000]
        espelhar_envio_funil_no_inbox(
            telefone=telefone,
            template_nome=template_name or "",
            texto=texto or "",
            message_id=mid,
            sucesso=bool(sucesso),
            erro=erro,
            usuario=usuario,
            venda=venda,
            aba=aba or "",
            ref_id=ref_id or "",
        )
    except Exception:
        logger.exception(
            "[NioTemplates] espelho Funil→inbox falhou tel=%s tpl=%s aba=%s ref=%s",
            telefone,
            template_name,
            aba,
            ref_id,
        )


def enviar_template_funil(
    telefone: str,
    template_name: str,
    body_params: Sequence[str],
    *,
    language_code: str = LANGUAGE_PT_BR,
    espelhar: bool = True,
    espelho_texto: str = "",
    usuario=None,
    venda=None,
    aba: str = "",
    ref_id: str = "",
) -> Tuple[bool, Any]:
    """Envia template pela conexão Funil (#247). Retorna (ok, resposta)."""
    from crm_app.whatsapp_service import WhatsAppService

    params = [str(p) if p is not None and str(p).strip() != "" else "-" for p in body_params]
    svc = WhatsAppService.para_funil()
    ok, resp = svc.enviar_template(
        telefone,
        template_name,
        language_code=language_code,
        body_params=params,
    )
    if espelhar:
        preview = (espelho_texto or "").strip()
        if not preview:
            preview = render_template_preview(template_name, params)
        _espelhar_funil_no_inbox(
            telefone=telefone,
            template_name=template_name,
            texto=preview[:500],
            resp=resp,
            sucesso=bool(ok),
            usuario=usuario,
            venda=venda,
            aba=aba,
            ref_id=ref_id,
        )
    return bool(ok), resp


def tentar_enviar_ou_texto(
    telefone: str,
    template_name: str,
    body_params: Sequence[str],
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    """
    Tenta template Meta; se desabilitado/falhar, envia texto livre.
    Retorna (ok, resposta, canal) com canal in ('template','texto').
    """
    from crm_app.whatsapp_service import WhatsAppService

    if templates_habilitados():
        ok, resp = enviar_template_cliente(telefone, template_name, body_params)
        if ok:
            return True, resp, "template"
        logger.warning(
            "[NioTemplates] Fallback texto após falha template=%s resp=%s",
            template_name,
            resp,
        )
    ok, resp = WhatsAppService.para_cliente().enviar_mensagem_texto(
        telefone, fallback_texto, variar=False
    )
    return bool(ok), resp, "texto"


def tentar_enviar_ou_texto_funil(
    telefone: str,
    template_name: str,
    body_params: Sequence[str],
    fallback_texto: str,
    *,
    usuario=None,
    venda=None,
    aba: str = "",
    ref_id: str = "",
    espelho_texto: str = "",
) -> Tuple[bool, Any, str]:
    """
    Template Meta pela conexão Funil (#247). Fallback de texto só se o template falhar.
    Espelha no inbox (mailing e demais callers).
    """
    from crm_app.whatsapp_service import WhatsAppService

    preview = (espelho_texto or fallback_texto or "").strip()
    if templates_habilitados():
        ok, resp = enviar_template_funil(
            telefone,
            template_name,
            body_params,
            espelho_texto=preview[:500],
            usuario=usuario,
            venda=venda,
            aba=aba,
            ref_id=ref_id,
        )
        if ok:
            return True, resp, "template"
        logger.warning(
            "[NioTemplates] Funil #247 fallback texto após falha template=%s resp=%s",
            template_name,
            resp,
        )
    ok, resp = WhatsAppService.para_funil().enviar_mensagem_texto(
        telefone, fallback_texto, variar=False
    )
    _espelhar_funil_no_inbox(
        telefone=telefone,
        template_name="" if ok else (template_name or ""),
        texto=(fallback_texto or "")[:500],
        resp=resp,
        sucesso=bool(ok),
        usuario=usuario,
        venda=venda,
        aba=aba,
        ref_id=ref_id,
    )
    return bool(ok), resp, "texto"


def enviar_confirmacao_pedido_venda(venda: Any, telefone: str) -> Tuple[bool, Any, str]:
    from crm_app.utils import montar_resumo_plano_para_whatsapp

    params = body_params_confirmacao_venda(venda)
    fallback = montar_resumo_plano_para_whatsapp(venda)
    fallback = (
        f"{fallback}\n\nToque em *CORRETO* ou *CORRIGIR*, "
        "ou digite CONFIRMAR / CORRETO."
    )
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_CONFIRMACAO_PEDIDO, params, fallback
    )


def enviar_confirmacao_pedido_pap(telefone: str, dados: Dict[str, Any], resumo_txt: str) -> Tuple[bool, Any, str]:
    params = body_params_confirmacao_pap(dados)
    fallback = (
        f"{resumo_txt}\n\nToque em *CORRETO* ou digite *SIM* / *CORRETO* para confirmar."
    )
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_CONFIRMACAO_PEDIDO, params, fallback
    )


def enviar_lembrete_instalacao(
    telefone: str,
    nome_cliente: str,
    data_agendamento: Any,
    periodo: str,
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    params = body_params_lembrete_instalacao(nome_cliente, data_agendamento, periodo)
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_LEMBRETE_INSTALACAO, params, fallback_texto
    )


def enviar_instalacao_confirmada(
    telefone: str,
    data_agendamento: Any,
    periodo: str,
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    params = body_params_instalacao_confirmada(data_agendamento, periodo)
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_INSTALACAO_CONFIRMADA, params, fallback_texto
    )


def enviar_template_fatura(
    telefone: str,
    template_name: str,
    nome_cliente: str,
    fatura: Any,
    *,
    fallback_texto: str,
    incluir_dias_atraso: bool = False,
) -> Tuple[bool, Any, str]:
    dias = None
    if incluir_dias_atraso:
        dias = int(getattr(fatura, "dias_atraso", 0) or 0)
        if dias <= 0 and getattr(fatura, "data_vencimento", None):
            hoje = timezone.localdate()
            dias = max(0, (hoje - fatura.data_vencimento).days)
    params = body_params_fatura(
        nome_cliente,
        referencia_fatura(fatura),
        getattr(fatura, "valor", 0),
        getattr(fatura, "data_vencimento", None),
        dias_atraso=dias,
    )
    return tentar_enviar_ou_texto(telefone, template_name, params, fallback_texto)


def enviar_pendencia_reagendamento(
    telefone: str,
    nome_cliente: str,
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    """Template Meta de pendência; fallback = texto livre da esteira."""
    params = body_params_pendencia_reagendamento(nome_cliente)
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_PENDENCIA_REAGENDAMENTO, params, fallback_texto
    )


def enviar_boas_vindas(
    telefone: str,
    nome_cliente: str,
    fallback_texto: str,
) -> Tuple[bool, Any, str]:
    """Template Meta nio_boas_vindas_v1; fallback = texto livre legado."""
    params = body_params_boas_vindas(nome_cliente)
    return tentar_enviar_ou_texto(
        telefone, TEMPLATE_BOAS_VINDAS, params, fallback_texto
    )


# Corpos aproximados para preview no inbox (não substituem o texto oficial da Meta).
# Placeholders {{1}}…{{n}} batem com body_params_* / envio Cloud API.
TEMPLATE_BODY_PREVIEW: Dict[str, str] = {
    TEMPLATE_FATURA_RECORRENTE: (
        "Olá, {{1}}!\n\n"
        "{{2}}, identificamos uma fatura em aberto.\n\n"
        "Referência: *{{3}}*\n"
        "Valor: *{{4}}*\n"
        "Vencimento: *{{5}}*\n"
        "Dias em atraso: *{{6}}*\n\n"
        "Regularize para evitar interrupção do serviço.\n"
        f"WhatsApp: {NIO_WHATSAPP_OFICIAL_EXIBICAO}"
    ),
    TEMPLATE_FATURA_LEMBRETE_5D: (
        "Olá, {{1}}!\n\n"
        "{{2}}, lembrete da sua fatura.\n\n"
        "Referência: *{{3}}*\n"
        "Valor: *{{4}}*\n"
        "Vencimento: *{{5}}*"
    ),
    TEMPLATE_FATURA_VENCIDA_5D: (
        "Olá, {{1}}!\n\n"
        "{{2}}, sua fatura está vencida.\n\n"
        "Referência: *{{3}}*\n"
        "Valor: *{{4}}*\n"
        "Vencimento: *{{5}}*"
    ),
    TEMPLATE_FATURA_REDUCAO_SINAL: (
        "Olá, {{1}}!\n\n"
        "{{2}},\n\n"
        "Parceiro oficial da Nio Fibra.\n"
        "Sua internet está com a velocidade reduzida devido a uma pendência de pagamento.\n\n"
        "Referência: *{{3}}*\n"
        "Valor: *{{4}}*\n"
        "Vencimento: *{{5}}*\n\n"
        "Precisamos do seu retorno para programar a regularização.\n"
        f"SAC: 0800 001 1000 | WhatsApp: {NIO_WHATSAPP_OFICIAL_EXIBICAO}"
    ),
    # Meta aprovado: {{1}}=saudação (ex. Bom Dia), {{2}}=nome — não repetir "Olá" em {{1}}.
    TEMPLATE_BOAS_VINDAS: (
        "Olá, {{1}}!\n\n"
        "{{2}},\n\n"
        "Sua instalação Nio Fibra foi concluída.\n"
        "Seja bem-vindo(a)!\n\n"
        "Guarde este WhatsApp para suporte e\n"
        "dúvidas sobre sua conexão.\n\n"
        "SAC: 0800 001 1000 | WhatsApp: 21 3605-1000\n\n"
        "Toque em um dos botões abaixo se precisar\n"
        "de ajuda agora."
    ),
    TEMPLATE_CONFIRMACAO_PEDIDO: (
        "Olá! Confirme os dados do pedido:\n\n{{1}}\n{{2}}\n{{3}}"
    ),
    TEMPLATE_LEMBRETE_INSTALACAO: (
        "Olá, {{1}} {{2}}! Lembrete da sua instalação."
    ),
    TEMPLATE_INSTALACAO_CONFIRMADA: (
        "Instalação confirmada para {{1}} no período {{2}}."
    ),
    TEMPLATE_PENDENCIA_REAGENDAMENTO: (
        "Olá, {{1}} {{2}}! Há uma pendência de reagendamento. "
        f"Fale conosco: {{{{3}}}}"
    ),
    TEMPLATE_REAGENDAMENTO_CLIENTE: (
        "Olá, {{1}} {{2}}! Reagendamento com {{3}}."
    ),
    TEMPLATE_CONSULTA_VIABILIDADE: "Olá, {{1}} {{2}}! Sobre a consulta de viabilidade.",
    TEMPLATE_REATIVACAO_CONTRATO: "Olá, {{1}} {{2}}! Sobre a reativação do contrato.",
    TEMPLATE_SELFIE_PENDENTE: (
        "Olá, {{1}}! Ainda precisamos da sua selfie/documentos. {{2}}"
    ),
    TEMPLATE_MAILING_GENERICO: "Olá, {{1}}! Podemos te ajudar com informações sobre internet no seu endereço.",
}


def _spec_mailing(nome: str) -> Optional[dict]:
    if not (nome or "").startswith("mailing_"):
        return None
    try:
        from crm_app.services.mailing_templates import TEMPLATE_SPECS

        for spec in TEMPLATE_SPECS:
            if (spec.get("nome") or "") == nome:
                return spec
    except Exception:
        return None
    return None


def _corpo_catalogo_template(nome: str) -> str:
    """Corpo legível: catálogo NIO + specs de mailing (mailing_*_v1)."""
    corpo = TEMPLATE_BODY_PREVIEW.get(nome) or ""
    if corpo:
        return corpo
    spec = _spec_mailing(nome)
    if spec:
        return (spec.get("corpo") or "").strip()
    return ""


def botoes_template_catalogo(template_name: str) -> List[str]:
    """Rótulos dos botões quick-reply do template (quando existirem no catálogo)."""
    nome = (template_name or "").strip()
    spec = _spec_mailing(nome)
    if not spec:
        return []
    raw = spec.get("botoes") or []
    return [str(b).strip() for b in raw if str(b).strip()]


def _chaves_telefone_simples(telefone: str) -> List[str]:
    digitos = "".join(ch for ch in (telefone or "") if ch.isdigit())
    if len(digitos) < 8:
        return []
    chaves = {digitos}
    if digitos.startswith("55") and len(digitos) >= 12:
        chaves.add(digitos[2:])
    elif len(digitos) in (10, 11):
        chaves.add("55" + digitos)
    # Variante com/sem 9º dígito (celular BR)
    local = digitos[2:] if digitos.startswith("55") and len(digitos) >= 12 else digitos
    if len(local) == 11 and local[2] == "9":
        chaves.add(("55" if digitos.startswith("55") else "") + local[:2] + local[3:])
        chaves.add(local[:2] + local[3:])
    elif len(local) == 10:
        chaves.add(("55" if digitos.startswith("55") else "") + local[:2] + "9" + local[2:])
        chaves.add(local[:2] + "9" + local[2:])
    return [c for c in chaves if c]


def params_mailing_por_telefone(
    telefone: str,
    template_name: str = "",
) -> List[str]:
    """Resolve {{1}}/{{2}} a partir do MailingContato (ou nome da conversa)."""
    from crm_app.models import MailingContato, WhatsAppConversation
    from crm_app.services.mailing_templates import body_params_contato

    chaves = _chaves_telefone_simples(telefone)
    contato = None
    if chaves:
        contato = (
            MailingContato.objects.filter(telefone_e164__in=chaves)
            .order_by("-id")
            .first()
        )
        if contato is None:
            # Match por sufixo (últimos 11/10 dígitos) se e164 divergir
            sufixo = max(chaves, key=len)[-11:]
            contato = (
                MailingContato.objects.filter(telefone_e164__endswith=sufixo)
                .order_by("-id")
                .first()
            )
    if contato is not None:
        return body_params_contato(contato)

    nome_contato = ""
    if chaves:
        conv = (
            WhatsAppConversation.objects.filter(telefone__in=chaves)
            .order_by("-id")
            .first()
        )
        if conv is not None:
            nome_contato = (conv.contact_name or "").strip()
    if not nome_contato:
        return []
    primeiro = nome_contato.split()[0]
    nome_tmpl = (template_name or "").strip()
    if nome_tmpl in (
        "mailing_cancelamento_v1",
        "mailing_fechado_v1",
        "mailing_aberto_v1",
    ):
        return [primeiro, "seu município"]
    return [primeiro]


def render_template_preview(template_name: str, body_params: Optional[Sequence[Any]] = None) -> str:
    """Monta texto legível do template para o histórico do inbox."""
    nome = (template_name or "").strip()
    params = [
        "" if p is None else str(p)
        for p in (body_params or [])
    ]
    corpo = _corpo_catalogo_template(nome)
    if corpo:
        texto = corpo
        for i, val in enumerate(params, start=1):
            texto = texto.replace("{{" + str(i) + "}}", val)
        # Remove placeholders sem valor
        texto = re.sub(r"\{\{\d+\}\}", "—", texto)
        return texto.strip()
    # Fallback legível (sem {{n}} cru)
    linhas = [f"Template: {nome or 'sem nome'}"]
    rotulos = {
        1: "Saudação",
        2: "Nome",
        3: "Referência",
        4: "Valor",
        5: "Vencimento",
        6: "Dias em atraso",
    }
    for i, val in enumerate(params, start=1):
        label = rotulos.get(i, f"Campo {i}")
        linhas.append(f"{label}: {val}")
    return "\n".join(linhas)


def parse_params_do_texto_modelo(texto: str) -> Tuple[str, List[str]]:
    """Extrai (template_name, params) do formato legado 'Modelo: x\\n{{1}} v'."""
    raw = (texto or "").strip()
    if not raw:
        return "", []
    linhas = raw.splitlines()
    nome = ""
    params: List[str] = []
    if linhas and linhas[0].lower().startswith("modelo:"):
        nome = linhas[0].split(":", 1)[1].strip()
        resto = linhas[1:]
    elif linhas and linhas[0].lower().startswith("template:"):
        nome = linhas[0].split(":", 1)[1].strip()
        resto = linhas[1:]
    else:
        resto = linhas
    for line in resto:
        m = re.match(r"^\{\{(\d+)\}\}\s*(.*)$", line.strip())
        if m:
            idx = int(m.group(1))
            while len(params) < idx:
                params.append("")
            params[idx - 1] = m.group(2)
            continue
        m2 = re.match(
            r"^(Saudação|Nome|Referência|Valor|Vencimento|Dias em atraso|Campo \d+):\s*(.*)$",
            line.strip(),
            re.I,
        )
        if m2:
            params.append(m2.group(2))
    return nome, params


def formatar_texto_template_exibicao(
    texto: str,
    template_name: str = "",
    *,
    telefone: str = "",
    body_params: Optional[Sequence[Any]] = None,
) -> str:
    """Reescreve dump legado {{n}} / [Mailing] nome para preview legível."""
    raw = (texto or "").strip()
    if not raw:
        return raw
    nome_hint = (template_name or "").strip()
    m_mail = re.match(r"^\[Mailing\]\s*(\S+)\s*$", raw, re.I)
    if m_mail:
        nome_hint = nome_hint or m_mail.group(1)

    params_in = list(body_params) if body_params is not None else None
    precisa_mailing = bool(
        nome_hint.startswith("mailing_")
        or m_mail
        or raw.startswith("[Mailing]")
    )
    if precisa_mailing and nome_hint:
        # Corpo já legível (com nome) — não consulta MailingContato de novo.
        precisa_resolver = bool(
            m_mail
            or raw.startswith("[Mailing]")
            or "—" in raw
            or "{{" in raw
            or len(raw) < 40
        )
        if not precisa_resolver and params_in is None:
            return raw
        params = params_in
        if params is None and telefone and precisa_resolver:
            params = params_mailing_por_telefone(telefone, nome_hint)
        params = list(params or [])
        if params or precisa_resolver:
            return render_template_preview(nome_hint, params)
        return raw

    # Já parece preview legível
    if "{{" not in raw and not raw.lower().startswith("modelo:") and not raw.lower().startswith("template:"):
        return raw

    nome, params = parse_params_do_texto_modelo(raw)
    nome = nome or nome_hint
    if params_in is not None:
        params = list(params_in)
    if not nome and not params:
        return raw
    return render_template_preview(nome, params)
