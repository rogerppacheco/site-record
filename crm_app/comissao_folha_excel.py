"""Geração de XLSX da folha de comissão (extrato por venda)."""
from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Tuple

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


COLUNAS_EXTRATO = [
    ('venda_id', 'VENDA'),
    ('grupo', 'GRUPO'),
    ('nome', 'NOME'),
    ('dacc', 'DACC'),
    ('cnpj', 'CNPJ'),
    ('classificacao_mei', 'MEI/NMEI'),
    ('plano', 'PLANO'),
    ('dt_pedido', 'DT PEDIDO'),
    ('dt_inst', 'DT INST'),
    ('os', 'OS'),
    ('situacao', 'SITUAÇÃO'),
    ('churn', 'CHURN'),
    ('adiantada', 'ADIANT.'),
    ('valor_comissao', 'COMISSÃO'),
    ('comissao_tipo', 'TIPO COMISSÃO'),
]

_LARGURAS = {
    'VENDA': 8,
    'GRUPO': 22,
    'NOME': 36,
    'DACC': 6,
    'CNPJ': 6,
    'MEI/NMEI': 10,
    'PLANO': 14,
    'DT PEDIDO': 11,
    'DT INST': 11,
    'OS': 12,
    'SITUAÇÃO': 24,
    'CHURN': 8,
    'ADIANT.': 9,
    'COMISSÃO': 12,
    'TIPO COMISSÃO': 14,
}


def _norm(txt) -> str:
    return (txt or '').strip().upper()


def _bloco_extrato(linha: Dict[str, Any]) -> Tuple[int, str]:
    situacao = _norm(linha.get('situacao'))
    is_churn = _norm(linha.get('churn')) == 'SIM'
    if situacao == 'INSTALADA' and not is_churn:
        return 0, 'INSTALADAS'
    if situacao == 'INSTALADA' and is_churn:
        return 1, 'INSTALADAS COM CHURN'
    if 'CANCELADA' in situacao:
        return 2, 'CANCELADAS'
    return 3, 'DEMAIS STATUS'


def _parse_br_date_key(dt: str) -> str:
    parts = (dt or '').strip().split('/')
    if len(parts) != 3:
        return '9999-99-99'
    dd, mm, yyyy = parts
    if not (dd and mm and yyyy):
        return '9999-99-99'
    return f'{yyyy.zfill(4)}-{mm.zfill(2)}-{dd.zfill(2)}'


def _tipo_comissao_label(tipo: str | None) -> str:
    return {
        'a_pagar': 'A pagar',
        'antecipada': 'Antecipada',
        'referencia': 'Referência',
        'churn': 'Churn',
    }.get((tipo or '').lower(), '')


def _linhas_extrato_vendedor(vendedor_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    extrato = list(vendedor_data.get('extrato') or [])
    blocos: Dict[int, List[Dict[str, Any]]] = {0: [], 1: [], 2: [], 3: []}
    titulos = {
        0: 'INSTALADAS',
        1: 'INSTALADAS COM CHURN',
        2: 'CANCELADAS',
        3: 'DEMAIS STATUS',
    }
    for e in extrato:
        ordem, titulo = _bloco_extrato(e)
        blocos[ordem].append({**e, '_grupo': titulo})

    rows: List[Dict[str, Any]] = []
    for ordem in (0, 1, 2, 3):
        itens = sorted(
            blocos[ordem],
            key=lambda x: (_parse_br_date_key(x.get('dt_pedido')), (x.get('nome') or '').upper()),
        )
        if not itens:
            continue
        rows.append({'_is_grupo': True, 'grupo': f'{titulos[ordem]} — {len(itens)} venda(s)'})
        for e in itens:
            rows.append({
                'venda_id': e.get('venda_id'),
                'grupo': e.get('_grupo') or titulos[ordem],
                'nome': e.get('nome') or '',
                'dacc': e.get('dacc') or '',
                'cnpj': e.get('cnpj') or '',
                'classificacao_mei': e.get('classificacao_mei') or '-',
                'plano': e.get('plano') or '',
                'dt_pedido': e.get('dt_pedido') or '',
                'dt_inst': e.get('dt_inst') or '',
                'os': e.get('os') or '',
                'situacao': e.get('situacao') or '',
                'churn': e.get('churn') or '',
                'adiantada': e.get('adiantada') or '-',
                'valor_comissao': e.get('valor_comissao'),
                'comissao_tipo': _tipo_comissao_label(e.get('comissao_tipo')),
            })
    return rows


def _titulo_aba_seguro(nome: str, usados: set) -> str:
    base = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in (nome or 'Extrato'))[:28].strip() or 'Extrato'
    titulo = base
    n = 2
    while titulo in usados:
        suf = f'_{n}'
        titulo = (base[: 28 - len(suf)] + suf).strip()
        n += 1
    usados.add(titulo)
    return titulo


def _preencher_aba(ws, linhas: List[Dict[str, Any]]):
    headers = [h for _, h in COLUNAS_EXTRATO]
    col_keys = [k for k, _ in COLUNAS_EXTRATO]
    ws.append(headers)

    fill_hdr = PatternFill(start_color='1F4E78', end_color='1F4E78', fill_type='solid')
    font_hdr = Font(bold=True, color='FFFFFF')
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col)
        c.fill = fill_hdr
        c.font = font_hdr
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    fill_grupo = PatternFill(start_color='E9ECEF', end_color='E9ECEF', fill_type='solid')
    idx_comissao = col_keys.index('valor_comissao') + 1
    dinheiro_fmt = 'R$ #,##0.00'

    for row in linhas:
        if row.get('_is_grupo'):
            ws.append([row.get('grupo')] + [''] * (len(headers) - 1))
            r = ws.max_row
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(headers))
            cell = ws.cell(row=r, column=1)
            cell.fill = fill_grupo
            cell.font = Font(bold=True)
            continue
        ws.append([row.get(k, '') for k in col_keys])
        r = ws.max_row
        val = row.get('valor_comissao')
        if val is not None and val != '':
            com_cell = ws.cell(row=r, column=idx_comissao)
            com_cell.number_format = dinheiro_fmt
            com_cell.alignment = Alignment(horizontal='right')

    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = _LARGURAS.get(h, 12)
    ws.freeze_panes = 'A2'


def gerar_xlsx_extrato_comissao(vendedores_data: List[Dict[str, Any]]) -> BytesIO:
    """Gera XLSX com extrato igual à tela (uma aba por vendedor)."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    usados: set = set()

    if not vendedores_data:
        ws = wb.create_sheet(title='Extrato')
        ws.append(['Sem dados de extrato para o período'])
    else:
        for vd in vendedores_data:
            nome = vd.get('vendedor_nome') or f"ID {vd.get('vendedor_id')}"
            ws = wb.create_sheet(title=_titulo_aba_seguro(nome, usados))
            _preencher_aba(ws, _linhas_extrato_vendedor(vd))

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output
