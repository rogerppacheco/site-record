"""Importação de mailings comprados (OPTIC, ATV ALG e variações de mercado)."""
from __future__ import annotations

import io
import logging
import re
import unicodedata
from collections import Counter
from typing import Any, BinaryIO, Iterable

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook

from crm_app.models import MailingContato, MailingLote

logger = logging.getLogger(__name__)

COLS_OPTIC = {
    'NOME', 'CPF', 'TELEFONE_COMPLETO', 'Macro Atividade',
}
COLS_ATV = {
    'Cliente', 'Documento', 'Telefone', 'Status',
}

# Planilhas de mercado (Algar / TIM / Nio / Vero) usam aliases desses campos.
ALIASES_NOME = ('cliente', 'nome', 'nome_razao', 'razao_social')
ALIASES_DOC = ('documento', 'cpf', 'cpf/cnpj', 'cnpj', 'documento_representante')
ALIASES_TEL = (
    'telefone',
    'telefone_completo',
    'telefone1',
    'tel',
    'celular',
    'whatsapp',
)
ALIASES_TEL2 = ('telefone2', 'telefne2', 'tel2', 'telefone_2')
ALIASES_STATUS = (
    'status',
    'contrato_status',
    'macro atividade',
    'situacao',
    'situação',
)
ALIASES_ENDERECO = ('endereco', 'endereço', 'logradouro')
ALIASES_CIDADE = ('cidade',)
ALIASES_UF = ('uf',)
ALIASES_BAIRRO = ('bairro',)
ALIASES_PRODUTO = ('produto', 'plano', 'contrato_produto', 'velocidade contratada', 'serviço', 'servico')

SIT = MailingContato


def _norm_header(valor: str) -> str:
    txt = unicodedata.normalize('NFKD', str(valor or ''))
    txt = ''.join(ch for ch in txt if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', txt).strip().lower()


def _valor_col(d: dict, *aliases: str) -> Any:
    """Busca coluna por nome exato ou alias normalizado (acento/caixa)."""
    wanted = {_norm_header(a) for a in aliases}
    for key, val in d.items():
        if _norm_header(str(key)) in wanted:
            return val
    return None


def normalizar_documento(valor: Any) -> str:
    raw = str(valor or '').strip()
    if raw.lower() in {'null', 'none', 'nan', '-'}:
        return ''
    return re.sub(r'\D', '', raw)


def normalizar_telefone_e164(valor: Any) -> tuple[str, bool]:
    """Retorna (e164 sem +, válido?). Celular BR com 10/11 dígitos → 55…"""
    raw = str(valor or '').strip()
    digitos = re.sub(r'\D', '', raw)
    if digitos.startswith('55') and len(digitos) >= 12:
        digitos = digitos
    elif len(digitos) in (10, 11):
        digitos = '55' + digitos
    elif len(digitos) == 12 and digitos.startswith('55'):
        pass
    else:
        return digitos[:20], False

    # 55 + DDD(2) + número(8 ou 9)
    local = digitos[2:]
    if len(local) == 11 and local[2] == '9':
        return digitos, True
    if len(local) == 10:
        # fixo ou celular antigo — aceita como válido mas marca celular preferencialmente
        return digitos, True
    if len(local) == 11:
        return digitos, True
    return digitos[:20], False


def primeiro_nome(nome: str) -> str:
    partes = re.split(r'\s+', (nome or '').strip())
    return (partes[0] if partes and partes[0] else 'Cliente').title()


def _headers_norm(headers: Iterable[str]) -> set[str]:
    return {_norm_header(h) for h in headers if str(h or '').strip()}


def _tem_alias(norm: set[str], aliases: Iterable[str]) -> bool:
    return bool(norm & {_norm_header(a) for a in aliases})


def detectar_layout(headers: Iterable[str]) -> str | None:
    cols = {str(h or '').strip() for h in headers}
    if COLS_OPTIC.issubset(cols):
        return MailingLote.LAYOUT_OPTIC
    if COLS_ATV.issubset(cols):
        return MailingLote.LAYOUT_ATV_ALG
    norm = _headers_norm(headers)
    if {'nome', 'cpf', 'telefone_completo', 'macro atividade'} <= norm:
        return MailingLote.LAYOUT_OPTIC
    # Mercado: Nome/Cliente + qualquer coluna de telefone (Status opcional).
    tem_nome = _tem_alias(norm, ALIASES_NOME)
    tem_tel = _tem_alias(norm, ALIASES_TEL + ALIASES_TEL2)
    if tem_nome and tem_tel:
        return MailingLote.LAYOUT_ATV_ALG
    return None


def classificar_optic(macro: str) -> str:
    m = (macro or '').strip().upper()
    if 'REP' in m:
        return SIT.SIT_REPARO
    if 'INST' in m:
        return SIT.SIT_INSTALACAO
    if 'MUD' in m:
        return SIT.SIT_MUDANCA
    if 'SRV' in m or 'RET' in m:
        return SIT.SIT_SERVICO
    return SIT.SIT_GENERICO


def classificar_atv(status: str) -> str:
    """Classifica Status / CONTRATO_STATUS / nome do arquivo."""
    s = _norm_header(status).upper()
    if not s:
        return SIT.SIT_GENERICO
    if 'CANCEL' in s or 'DESIST' in s:
        return SIT.SIT_CANCELAMENTO
    if s == 'FECHADO':
        return SIT.SIT_FECHADO
    if 'SUSPEN' in s:
        return SIT.SIT_GENERICO
    if any(tok in s for tok in ('ABERTO', 'TECNICO', 'APROVISION', 'PENDENC')):
        return SIT.SIT_ABERTO
    if 'CONCLUID' in s or 'INSTAL' in s:
        return SIT.SIT_INSTALACAO
    return SIT.SIT_GENERICO


def situacao_pelo_arquivo(arquivo_nome: str) -> str:
    """Quando a planilha não tem Status, usa o nome do XLS (ex.: SUSPENSÃO VERO)."""
    return classificar_atv(arquivo_nome or '')


def _row_dict(headers: list, row: tuple) -> dict:
    out = {}
    for i, h in enumerate(headers):
        key = str(h or '').strip()
        out[key] = row[i] if i < len(row) else None
    return out


def _ler_planilha(arquivo: BinaryIO | bytes) -> tuple[list[str], list[tuple]]:
    if isinstance(arquivo, (bytes, bytearray)):
        stream = io.BytesIO(arquivo)
    else:
        stream = arquivo
    wb = load_workbook(stream, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        raise ValueError('Planilha vazia.')
    headers = [str(h or '').strip() for h in rows[0]]
    return headers, rows[1:]


def _montar_endereco_optic(d: dict) -> tuple[str, str, str]:
    partes = [
        str(d.get('Tipo Logradouro') or '').strip(),
        str(d.get('Logradouro') or '').strip(),
        str(d.get('Número') or '').strip(),
        str(d.get('Tipo Complemento') or '').strip(),
        str(d.get('Abrev. Tipo Comp.') or '').strip(),
    ]
    endereco = ' '.join(p for p in partes if p and p.lower() != 'null')[:255]
    bairro = str(d.get('Bairro') or '').strip()[:120]
    uf = str(d.get('UF') or '').strip()[:2].upper()
    return endereco, bairro, uf


def _texto(valor: Any) -> str:
    raw = '' if valor is None else str(valor).strip()
    return '' if raw.lower() in {'null', 'none', 'nan'} else raw


def parse_linhas(
    headers: list[str],
    rows: list[tuple],
    layout: str,
    arquivo_nome: str = '',
) -> list[dict]:
    contatos: list[dict] = []
    vistos: set[str] = set()
    dica_arquivo = situacao_pelo_arquivo(arquivo_nome)
    for row in rows:
        if not row or all(c is None or str(c).strip() == '' for c in row):
            continue
        d = _row_dict(headers, row)
        if layout == MailingLote.LAYOUT_OPTIC:
            nome = _texto(d.get('NOME'))[:200]
            cpf = normalizar_documento(d.get('CPF'))[:14]
            tel_raw = _texto(d.get('TELEFONE_COMPLETO'))
            e164, valido = normalizar_telefone_e164(tel_raw)
            situacao = classificar_optic(_texto(d.get('Macro Atividade')))
            origem = _texto(d.get('Macro Atividade'))[:80]
            endereco, bairro, uf = _montar_endereco_optic(d)
            cidade = bairro  # OPTIC não tem cidade explícita; usa bairro como referência
            produto = _texto(d.get('Velocidade Contratada') or d.get('Serviço'))[:160]
        else:
            nome = _texto(_valor_col(d, *ALIASES_NOME))[:200]
            cpf = normalizar_documento(_valor_col(d, *ALIASES_DOC))[:14]
            tel_raw = _texto(_valor_col(d, *ALIASES_TEL))
            e164, valido = normalizar_telefone_e164(tel_raw)
            if not valido:
                tel2 = _texto(_valor_col(d, *ALIASES_TEL2))
                e1642, ok2 = normalizar_telefone_e164(tel2)
                if ok2:
                    tel_raw, e164, valido = tel2, e1642, True
            origem_status = _texto(_valor_col(d, *ALIASES_STATUS))
            situacao = classificar_atv(origem_status) if origem_status else dica_arquivo
            origem = (origem_status or arquivo_nome or '')[:80]
            endereco = _texto(_valor_col(d, *ALIASES_ENDERECO))[:255]
            bairro = _texto(_valor_col(d, *ALIASES_BAIRRO))[:120]
            cidade = _texto(_valor_col(d, *ALIASES_CIDADE))[:120]
            uf = _texto(_valor_col(d, *ALIASES_UF))[:2].upper()
            produto = _texto(_valor_col(d, *ALIASES_PRODUTO))[:160]

        if e164 and e164 in vistos:
            continue
        if e164:
            vistos.add(e164)

        contatos.append({
            'nome': nome,
            'cpf': cpf,
            'telefone_e164': e164 if valido or e164 else '',
            'telefone_raw': tel_raw[:40],
            'cidade': cidade,
            'uf': uf,
            'endereco': endereco,
            'bairro': bairro,
            'situacao': situacao,
            'situacao_origem': origem,
            'produto': produto,
            'payload': {k: (str(v) if v is not None else '') for k, v in d.items()},
            'telefone_valido': bool(valido and e164),
            'status': SIT.STATUS_NOVO if (valido and e164) else SIT.STATUS_IGNORADO,
        })
    return contatos


@transaction.atomic
def importar_arquivo(
    arquivo: BinaryIO | bytes,
    *,
    nome_lote: str,
    arquivo_nome: str = '',
    usuario=None,
) -> MailingLote:
    headers, rows = _ler_planilha(arquivo)
    layout = detectar_layout(headers)
    if not layout:
        raise ValueError(
            'Layout não reconhecido. Use OPTIC (NOME/CPF/TELEFONE_COMPLETO/Macro Atividade) '
            'ou planilha de mercado com Nome + Telefone '
            '(Status, CPF/CNPJ, Cidade e Endereço são opcionais).'
        )
    parsed = parse_linhas(headers, rows, layout, arquivo_nome=arquivo_nome)
    contagens = Counter(c['situacao'] for c in parsed)
    validos = sum(1 for c in parsed if c['telefone_valido'])

    lote = MailingLote.objects.create(
        nome=(nome_lote or arquivo_nome or f'Mailing {timezone.localdate():%d/%m/%Y}')[:160],
        tipo_layout=layout,
        arquivo_nome=(arquivo_nome or '')[:255],
        status=MailingLote.STATUS_PRONTO if validos else MailingLote.STATUS_RASCUNHO,
        total_linhas=len(rows),
        total_contatos=len(parsed),
        total_validos=validos,
        contagens_situacao=dict(contagens),
        criado_por=usuario if getattr(usuario, 'is_authenticated', False) else None,
        mensagem=f'{len(parsed)} contatos únicos; {validos} com telefone válido.',
    )
    objs = [MailingContato(lote=lote, **c) for c in parsed]
    MailingContato.objects.bulk_create(objs, batch_size=500)
    logger.info('[Mailing] Lote #%s importado layout=%s contatos=%s validos=%s', lote.pk, layout, len(parsed), validos)
    return lote
