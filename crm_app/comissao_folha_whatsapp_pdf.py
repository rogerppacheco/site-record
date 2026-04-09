"""
HTML único para PDF da folha de comissão (layout alinhado à tela) + extrato.
Usado no envio WhatsApp (um arquivo PDF em vez de imagem + PDF separado).
"""
from __future__ import annotations

import html as html_module
from typing import Any, Dict, List


def _fmt_br(val: Any) -> str:
    try:
        n = float(val)
        s = f"{n:,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def _e(s: Any) -> str:
    return html_module.escape(str(s) if s is not None else "")


def _plano_linha_visivel(p: Dict[str, Any]) -> bool:
    qtd_ant = int(p.get("qtd_antecipada") or 0)
    val_adiant = p.get("valor_total_antecipado")
    if val_adiant is None:
        val_adiant = 0
    try:
        val_adiant = float(val_adiant)
    except (TypeError, ValueError):
        val_adiant = 0.0
    return (
        int(p.get("qtd_instalada_a_pagar") or 0) > 0
        or qtd_ant > 0
        or float(p.get("valor_total_instalados") or 0) > 0
        or val_adiant > 0
    )


def _agrupar_descontos(detalhes: List[Dict[str, Any]]):
    tipos_agrupados = {
        "folha_boleto_vendas",
        "folha_antecipacao_instalacao",
        "adiant_cnpj",
        "adiant_comissao",
        "churn_m0",
        "churn_m1",
        "boleto",
        "antecipacao_instalacao",
        "processamento_auto_misto",
    }

    def filtro(codigo: str):
        return [x for x in detalhes if (x.get("tipo_exibicao") or "").lower() == codigo]

    folha_boleto = filtro("folha_boleto_vendas")
    folha_antecip = filtro("folha_antecipacao_instalacao")
    adiant = filtro("adiant_cnpj")
    churn_m0 = filtro("churn_m0")
    churn_m1 = filtro("churn_m1")
    outros = [x for x in detalhes if (x.get("tipo_exibicao") or "").lower() not in tipos_agrupados]
    return folha_boleto, folha_antecip, adiant, churn_m0, churn_m1, outros


def montar_html_folha_e_extrato_pdf(vendedor_data: Dict[str, Any], periodo: str) -> str:
    r = vendedor_data.get("resumo") or {}
    por_plano: List[Dict[str, Any]] = list(r.get("por_plano") or [])
    nome_v = _e(vendedor_data.get("vendedor_nome") or "")
    faixa = _e(r.get("faixa_aplicada") or "-")
    periodo_e = _e(periodo)

    sum_q_ant = 0
    sum_val_adiant = 0.0
    sum_val_tot_inst = 0.0
    linhas_plano: List[str] = []

    for p in por_plano:
        if not _plano_linha_visivel(p):
            continue
        q_ap = int(p.get("qtd_instalada_a_pagar") or 0)
        q_ant = int(p.get("qtd_antecipada") or 0)
        v_adiant = p.get("valor_total_antecipado")
        try:
            v_adiant_f = float(v_adiant) if v_adiant is not None else 0.0
        except (TypeError, ValueError):
            v_adiant_f = 0.0
        sum_q_ant += q_ant
        sum_val_adiant += v_adiant_f
        v_tot = float(p.get("valor_total_instalados") or 0)
        sum_val_tot_inst += v_tot

        v_unit = p.get("valor_unitario_instalados")
        v_unit_s = _fmt_br(v_unit) if v_unit is not None else "—"
        cell_adiant = _fmt_br(v_adiant_f) if q_ant > 0 else "—"

        linhas_plano.append(
            "<tr>"
            f"<td>{_e(p.get('plano') or '')}</td>"
            f'<td class="c">{q_ap}</td>'
            f'<td class="c">{q_ant}</td>'
            f'<td class="r info">{cell_adiant}</td>'
            f'<td class="r">{v_unit_s}</td>'
            f'<td class="r">{_fmt_br(v_tot)}</td>'
            f'<td class="r b">{_fmt_br(p.get("comissao_total") or 0)}</td>'
            "</tr>"
        )

    total_q_pagar = int(r.get("total_qtd_instalada_a_pagar") or 0)
    total_row = (
        '<tr class="total">'
        "<td><b>TOTAL</b></td>"
        f'<td class="c"><b>{total_q_pagar}</b></td>'
        f'<td class="c"><b>{sum_q_ant}</b></td>'
        f'<td class="r info"><b>{_fmt_br(sum_val_adiant) if sum_q_ant > 0 else "—"}</b></td>'
        '<td class="r">—</td>'
        f'<td class="r"><b>{_fmt_br(sum_val_tot_inst)}</b></td>'
        f'<td class="r b"><b>{_fmt_br(r.get("comissao_total_geral") or 0)}</b></td>'
        "</tr>"
    )

    parts: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">',
        '<html xmlns="http://www.w3.org/1999/xhtml">',
        "<head>",
        '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8"/>',
        "<style>",
        "@page { size: A4 landscape; margin: 8mm; }",
        "body { font-family: Helvetica, Arial, sans-serif; font-size: 9px; color: #212529; }",
        "h1 { font-size: 13px; margin: 0; font-weight: bold; }",
        "h2 { font-size: 11px; margin: 16px 0 8px 0; border-bottom: 1px solid #dee2e6; padding-bottom: 4px; }",
        ".hdr { background: #0d6efd; color: #fff; padding: 8px 10px; margin: -8px -8px 12px -8px; }",
        "table.hdr-bar { width: 100%; border-collapse: collapse; table-layout: fixed; }",
        "table.hdr-bar td { border: none; vertical-align: middle; padding: 4px 6px; }",
        ".hdr-faixa { width: 24%; font-size: 9px; text-align: left; }",
        ".hdr-nome { width: 52%; text-align: center; }",
        ".hdr-periodo { width: 24%; font-size: 9px; text-align: right; }",
        "table.folha { width: 100%; border-collapse: collapse; margin-bottom: 8px; table-layout: fixed; }",
        "table.folha th, table.folha td { border: 1px solid #dee2e6; padding: 4px 5px; }",
        "table.folha th { background: #f8f9fa; font-weight: bold; text-align: left; }",
        "table.folha th.c, td.c { text-align: center; }",
        "table.folha th.r, td.r { text-align: right; }",
        "table.folha tr.total td { background: #f8f9fa; }",
        "td.b { font-weight: bold; }",
        "td.info { color: #0dcaf0; }",
        ".resumo { margin: 10px 0; font-size: 9px; }",
        ".resumo span { margin-right: 18px; }",
        ".neg { color: #dc3545; font-weight: bold; }",
        ".pos { color: #198754; font-weight: bold; }",
        ".liquido { font-size: 10px; }",
        ".aviso { background: #fff3cd; border: 1px solid #ffc107; padding: 6px; margin: 8px 0; font-size: 8px; }",
        ".bloco { margin-top: 8px; font-size: 8px; }",
        ".bloco-tit { color: #6c757d; font-weight: bold; margin-bottom: 4px; }",
        "table.extrato { width: 100%; border-collapse: collapse; table-layout: fixed; }",
        "table.extrato th, table.extrato td { border: 1px solid #dee2e6; padding: 2px 3px; font-size: 6.5px; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; }",
        "table.extrato th { background: #f8f9fa; font-size: 6px; }",
        "table.extrato th.c, table.extrato td.c { text-align: center; }",
        "table.extrato col.col-nome { width: 18%; }",
        "table.extrato col.col-dacc { width: 5%; }",
        "table.extrato col.col-cnpj { width: 5%; }",
        "table.extrato col.col-plano { width: 9%; }",
        "table.extrato col.col-dtped { width: 7%; }",
        "table.extrato col.col-dtinst { width: 7%; }",
        "table.extrato col.col-os { width: 9%; }",
        "table.extrato col.col-sit { width: 16%; }",
        "table.extrato col.col-churn { width: 6%; }",
        "table.extrato col.col-adiant { width: 8%; }",
        "table.extrato td.c-dt, table.extrato td.c-os { white-space: nowrap; font-size: 6px; }",
        ".churn-sim { background-color: #f8d7da; }",
        ".churn-nao { background-color: #d4edda; }",
        ".adiant-linha { background-color: #cff4fc; }",
        "</style>",
        "</head><body>",
        '<div class="hdr">'
        '<table class="hdr-bar"><tr>'
        '<td class="hdr-faixa">Faixa: ' + faixa + "</td>"
        '<td class="hdr-nome"><h1>' + nome_v + "</h1></td>"
        '<td class="hdr-periodo">Período: ' + periodo_e + "</td>"
        "</tr></table></div>",
        '<table class="folha">',
        "<thead><tr>",
        "<th>PLANO</th>",
        '<th class="c">QTD A PAGAR</th>',
        '<th class="c">QTD ANTECIPADA</th>',
        '<th class="r">VALOR JÁ ADIANT.</th>',
        '<th class="r">VALOR UNIT.</th>',
        '<th class="r">VALOR TOTAL</th>',
        '<th class="r">COMISSÃO</th>',
        "</tr></thead><tbody>",
        "".join(linhas_plano),
        total_row,
        "</tbody></table>",
        '<div class="resumo">',
        '<span class="neg">Descontos: - ' + _fmt_br(r.get("total_descontos") or 0) + "</span>",
        '<span class="pos">Bônus: + ' + _fmt_br(r.get("total_bonus") or 0) + "</span>",
        '<span class="pos liquido">LÍQUIDO A PAGAR: ' + _fmt_br(r.get("liquido") or 0) + "</span>",
        "</div>",
    ]

    if r.get("desconta_boleto_pap") is False:
        parts.append(
            '<div class="aviso">Regras por vendedor: <b>boleto não desconta no líquido</b>. '
            "A linha de boleto abaixo mostra o valor cheio (informativo); o total de descontos já está sem esse valor.</div>"
        )

    detalhes = list(r.get("detalhes_descontos") or [])
    if detalhes:
        folha_boleto, folha_antecip, adiant, churn_m0, churn_m1, outros = _agrupar_descontos(detalhes)
        parts.append('<div class="bloco"><div class="bloco-tit">Lançamentos descontados</div>')
        qadc = r.get("qtd_a_descontar")
        if qadc is not None and int(qadc) > 0:
            parts.append('<div style="color:#6c757d;font-weight:bold;margin-bottom:4px;">QTD A DESCONTAR: ' + _e(qadc) + "</div>")

        def linha_desconto(d: Dict[str, Any]) -> str:
            motivo = _e(d.get("motivo") or "Desconto")
            q = d.get("quantidade")
            if q is not None and q != "":
                motivo += " (" + _e(q) + " un.)"
            return f'<div class="neg">{motivo}: - {_fmt_br(d.get("valor") or 0)}</div>'

        for d in folha_boleto:
            parts.append(linha_desconto(d))
        for d in folha_antecip:
            parts.append(linha_desconto(d))
        if adiant:
            parts.append('<div class="bloco-tit" style="margin-top:6px;">Adiant. CNPJ</div>')
            for d in adiant:
                parts.append(linha_desconto(d))
        if churn_m0:
            parts.append('<div class="bloco-tit" style="margin-top:6px;">Desconto Churn M0</div>')
            for d in churn_m0:
                parts.append(linha_desconto(d))
        if churn_m1:
            parts.append('<div class="bloco-tit" style="margin-top:6px;">Desconto Churn M-1</div>')
            for d in churn_m1:
                parts.append(linha_desconto(d))
        if outros:
            parts.append('<div class="bloco-tit" style="margin-top:6px;">Outros</div>')
            for d in outros:
                parts.append(linha_desconto(d))
        parts.append("</div>")

    info_ad = r.get("info_comissao_adiantada") or {}
    if int(info_ad.get("quantidade_total") or 0) > 0:
        parts.append('<div class="bloco"><div class="bloco-tit">Referência — não entra em descontos</div>')
        parts.append(
            '<div style="color:#0dcaf0;">Comissão já adiantada (esteira + tabela Adiantamento) <b>('
            + _e(info_ad.get("quantidade_total"))
            + " un.)</b> → "
            + _fmt_br(info_ad.get("valor_total") or 0)
            + "</div>"
        )
        for row in info_ad.get("por_plano") or []:
            if int(row.get("qtd") or 0) > 0:
                parts.append(
                    '<div style="color:#6c757d;margin-left:8px;">'
                    + _e(row.get("plano"))
                    + ": "
                    + _e(row.get("qtd"))
                    + " un. → "
                    + _fmt_br(row.get("valor_total") or 0)
                    + "</div>"
                )
        parts.append("</div>")

    bonus = list(r.get("detalhes_bonus") or [])
    if bonus:
        parts.append('<div class="bloco"><div class="bloco-tit">Bônus / premiação</div>')
        for b in bonus:
            parts.append(
                '<div class="pos">'
                + _e(b.get("motivo") or "Bônus/Premiação")
                + ": + "
                + _fmt_br(b.get("valor") or 0)
                + "</div>"
            )
        parts.append("</div>")

    extrato = list(vendedor_data.get("extrato") or [])
    parts.append(
        "<h2>Extrato (" + str(len(extrato)) + " vendas)</h2>"
        '<table class="extrato">'
        "<colgroup>"
        '<col class="col-nome"/><col class="col-dacc"/><col class="col-cnpj"/><col class="col-plano"/>'
        '<col class="col-dtped"/><col class="col-dtinst"/><col class="col-os"/><col class="col-sit"/>'
        '<col class="col-churn"/><col class="col-adiant"/>'
        "</colgroup>"
        "<thead><tr>"
        '<th style="width:18%">NOME</th><th style="width:5%" class="c">DACC</th><th style="width:5%" class="c">CNPJ</th>'
        '<th style="width:9%">PLANO</th>'
        '<th style="width:7%" class="c">DT PEDIDO</th><th style="width:7%" class="c">DT INST</th><th style="width:9%" class="c">OS</th>'
        '<th style="width:16%">SITUAÇÃO</th><th style="width:6%" class="c">CHURN</th><th style="width:8%" class="c">ADIANT.</th>'
        "</tr></thead><tbody>"
    )

    for e in extrato:
        churn_sim = (str(e.get("churn") or "").strip().upper() == "SIM")
        adiant_sim = (str(e.get("adiantada") or "").strip().upper() == "SIM")
        if churn_sim:
            cls = "churn-sim"
        elif adiant_sim:
            cls = "adiant-linha"
        else:
            cls = "churn-nao"
        parts.append(
            f'<tr class="{cls}">'
            f"<td>{_e(e.get('nome'))}</td>"
            f"<td class=\"c\">{_e(e.get('dacc'))}</td>"
            f"<td class=\"c\">{_e(e.get('cnpj'))}</td>"
            f"<td>{_e(e.get('plano'))}</td>"
            f'<td class="c c-dt">{_e(e.get("dt_pedido"))}</td>'
            f'<td class="c c-dt">{_e(e.get("dt_inst"))}</td>'
            f'<td class="c c-os">{_e(e.get("os"))}</td>'
            f"<td>{_e(e.get('situacao'))}</td>"
            f"<td class=\"c\">{_e(e.get('churn'))}</td>"
            f'<td class="c">{_e(e.get("adiantada") or "—")}</td>'
            "</tr>"
        )

    parts.append("</tbody></table></body></html>")
    return "".join(parts)
