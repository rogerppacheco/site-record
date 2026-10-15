"""Consulta em lote de débitos na Nio para os clientes da aba Tratar Churn (Funil)."""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

WORKERS = 5
VALIDADE_CONSULTA = timedelta(hours=24)
LOTE_SEM_PROGRESSO_MAX = timedelta(minutes=5)
TENTATIVAS_POR_CPF = 4

STATUS_QUITADOS = {
    'PAID', 'PAGO', 'PAGA', 'QUITADO', 'QUITADA', 'LIQUIDADO', 'LIQUIDADA',
    'CANCELED', 'CANCELLED', 'CANCELADO', 'CANCELADA',
}
STATUS_VENCIDOS = {'OVERDUE', 'LATE', 'ATRASADO', 'ATRASADA', 'VENCIDO', 'VENCIDA'}

SEGUNDA_VIA_API = 'https://www.niointernet.com.br/api/rest/invoices/document'
SEGUNDA_VIA_PAGINA = 'https://www.niointernet.com.br/ajuda/servicos/segunda-via/'
# Valor fixo usado pelo próprio site da 2ª via; sem o Referer a API responde 404.
SEGUNDA_VIA_TOKEN = '1234567890abcdef'
SEGUNDA_VIA_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/130.0 Safari/537.36'
)

_lock_inicio = threading.Lock()


def normalizar_documento(valor: Any) -> str:
    return re.sub(r'\D', '', str(valor or ''))


def _parse_data(valor: Any) -> Optional[date]:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    for fmt, tam in (('%Y-%m-%d', 10), ('%d/%m/%Y', 10), ('%Y%m%d', 8)):
        try:
            return datetime.strptime(s[:tam], fmt).date()
        except ValueError:
            continue
    return None


def _parse_valor(valor: Any) -> Decimal:
    if valor in (None, ''):
        return Decimal('0')
    if isinstance(valor, (int, float, Decimal)):
        return Decimal(str(valor))
    s = str(valor).replace('R$', '').strip()
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal('0')


def classificar_faturas(invoices: Iterable[dict], hoje: Optional[date] = None) -> dict:
    """Situação do cliente a partir das faturas devolvidas por consultar_dividas_nio."""
    from crm_app.models import ChurnConsultaDebitoNio as M

    hoje = hoje or timezone.localdate()
    qtd_venc, valor_venc, venc_antigo = 0, Decimal('0'), None
    qtd_av, valor_av = 0, Decimal('0')
    for inv in invoices or []:
        status = str(inv.get('status') or '').strip().upper()
        if status in STATUS_QUITADOS:
            continue
        venc = _parse_data(inv.get('due_date_raw') or inv.get('expiration'))
        valor = _parse_valor(inv.get('amount'))
        vencida = (venc is not None and venc < hoje) or (venc is None and status in STATUS_VENCIDOS)
        if vencida:
            qtd_venc += 1
            valor_venc += valor
            if venc and (venc_antigo is None or venc < venc_antigo):
                venc_antigo = venc
        else:
            qtd_av += 1
            valor_av += valor

    if qtd_venc:
        situacao = M.INADIMPLENTE
    elif qtd_av:
        situacao = M.A_VENCER
    else:
        situacao = M.ADIMPLENTE
    return {
        'situacao': situacao,
        'qtd_vencidas': qtd_venc,
        'valor_vencido': valor_venc,
        'vencimento_mais_antigo': venc_antigo,
        'qtd_a_vencer': qtd_av,
        'valor_a_vencer': valor_av,
        'detalhe': '',
    }


def cpfs_churn_cruzados(usuario) -> list[str]:
    """Documentos (só dígitos) dos clientes cujo churn cruza com venda do CRM, como na aba Tratar Churn."""
    from django.contrib.auth import get_user_model

    from crm_app.churn_os_utils import build_venda_lookup_por_os, encontrar_venda_por_churn
    from crm_app.models import ImportacaoChurn, Venda
    from crm_app.services.escopo_operadora import filtrar_vendas_por_operadora

    User = get_user_model()
    user_ids = list(
        User.objects.exclude(username__in=['OSAB_IMPORT', 'admin', 'root']).values_list('id', flat=True)
    )
    vendas = Venda.objects.filter(ativo=True, vendedor_id__in=user_ids).exclude(
        Q(ordem_servico__isnull=True) | Q(ordem_servico='')
    ).select_related('cliente')
    vendas = filtrar_vendas_por_operadora(vendas, usuario)
    lookup = build_venda_lookup_por_os(vendas)

    docs: dict[str, None] = {}
    for churn in ImportacaoChurn.objects.all().iterator(chunk_size=2000):
        venda = encontrar_venda_por_churn(churn, lookup)
        if not venda or not venda.cliente:
            continue
        doc = normalizar_documento(venda.cliente.cpf_cnpj)
        if len(doc) in (11, 14):
            docs.setdefault(doc, None)
    return list(docs)


def _status_http(exc: Exception) -> Optional[int]:
    resp = getattr(exc, 'response', None)
    return getattr(resp, 'status_code', None)


class _Pausa:
    """Pausa compartilhada entre as threads quando a Nio responde 429."""

    def __init__(self):
        self._ate = 0.0
        self._lock = threading.Lock()

    def aguardar(self):
        while True:
            with self._lock:
                falta = self._ate - time.monotonic()
            if falta <= 0:
                return
            time.sleep(min(falta, 5))

    def pausar(self, segundos: float):
        with self._lock:
            self._ate = max(self._ate, time.monotonic() + segundos)


class _DocumentoInvalido(Exception):
    pass


def faturas_negocia(doc: str) -> list[dict]:
    """Dívidas no Nio Negocia (cobrança). Não enxerga contas de contrato recém-cancelado."""
    from crm_app.nio_api import consultar_dividas_nio

    res = consultar_dividas_nio(doc, offset=0, limit=50, headless=True)
    if res.get('erro_400'):
        detalhe = str(res.get('detail') or '')
        if 'not found' in detalhe.lower():
            return []
        raise _DocumentoInvalido(detalhe or 'CPF inválido na Nio')
    return list(res.get('invoices') or [])


def faturas_segunda_via(doc: str) -> list[dict]:
    """Contas em aberto da 2ª via do site da Nio (inclui contrato cancelado por inadimplência)."""
    import requests

    sessao = requests.Session()
    sessao.headers.update({
        'User-Agent': SEGUNDA_VIA_UA,
        'Referer': SEGUNDA_VIA_PAGINA,
        'Accept': '*/*',
        'Token': SEGUNDA_VIA_TOKEN,
    })
    r1 = sessao.get(SEGUNDA_VIA_API, headers={'Document': doc}, timeout=30)
    r1.raise_for_status()
    hash_doc = (r1.json() or {}).get('hash')
    if not hash_doc:
        raise ValueError('2ª via sem hash na resposta')
    r2 = sessao.get(SEGUNDA_VIA_API, headers={'Hash': hash_doc}, timeout=30)
    if r2.status_code == 500 and 'não encontrado' in r2.text.lower():
        return []
    r2.raise_for_status()
    dados = r2.json() or {}

    faturas = []
    contas = [b for p in dados.get('products') or [] for b in p.get('bills') or []]
    contas += dados.get('businessInvoices') or []
    for conta in contas:
        status = str(conta.get('statusBill') or '')
        if status == 'invalid_status':
            continue
        atraso = conta.get('delayedDays') or 0
        faturas.append({
            'amount': conta.get('amountDue'),
            'due_date_raw': conta.get('paymentDueDate'),
            'status': 'OVERDUE' if atraso > 0 else 'OPEN',
            'origem': '2via',
            'status_nio': status,
        })
    return faturas


def _chave_fatura(fatura: dict) -> tuple:
    return (_parse_data(fatura.get('due_date_raw') or fatura.get('expiration')), _parse_valor(fatura.get('amount')))


def _consultar_fonte(nome: str, funcao, doc: str, pausa: _Pausa, cancelado: threading.Event):
    """Chama uma fonte com retentativa. Devolve (faturas, erro); faturas None quando cancelado ou falhou."""
    from crm_app.nio_api import invalidate_token_cache

    ultimo_erro = ''
    for tentativa in range(TENTATIVAS_POR_CPF):
        if cancelado.is_set():
            return None, ''
        pausa.aguardar()
        try:
            return funcao(doc), ''
        except _DocumentoInvalido as exc:
            return None, f'{nome}: {exc}'
        except Exception as exc:  # noqa: BLE001 — qualquer falha vira retentativa ou ERRO
            codigo = _status_http(exc)
            ultimo_erro = f'HTTP {codigo}' if codigo else str(exc)[:200]
            if codigo == 429:
                pausa.pausar(30 * (tentativa + 1))
            elif codigo in (401, 403):
                invalidate_token_cache()
            else:
                time.sleep(2 * (tentativa + 1))
    return None, f'Falha na consulta {nome}: {ultimo_erro}'


def consultar_documento(doc: str, pausa: _Pausa, cancelado: threading.Event) -> dict:
    """Consulta o CPF/CNPJ no Nio Negocia e na 2ª via; só é adimplente se nenhuma das duas mostrar conta."""
    from crm_app.models import ChurnConsultaDebitoNio as M

    negocia, erro_negocia = _consultar_fonte('Nio Negocia', faturas_negocia, doc, pausa, cancelado)
    via2, erro_via2 = _consultar_fonte('2ª via', faturas_segunda_via, doc, pausa, cancelado)
    if cancelado.is_set():
        return {'situacao': None}
    if negocia is None or via2 is None:
        return {'situacao': M.ERRO, 'detalhe': ' | '.join(e for e in (erro_negocia, erro_via2) if e)[:255]}

    faturas = {}
    for fatura in negocia + via2:
        faturas.setdefault(_chave_fatura(fatura), fatura)
    resultado = classificar_faturas(faturas.values())
    if resultado['situacao'] == M.ADIMPLENTE:
        resultado['detalhe'] = 'Nenhuma conta em aberto no Nio Negocia nem na 2ª via'
    else:
        resultado['detalhe'] = f'Nio Negocia: {len(negocia)} conta(s) · 2ª via: {len(via2)} conta(s)'
    return resultado


def encerrar_lotes_parados() -> None:
    from crm_app.models import ChurnConsultaDebitoLote as L

    limite = timezone.now() - LOTE_SEM_PROGRESSO_MAX
    L.objects.filter(status=L.STATUS_EM_ANDAMENTO, atualizado_em__lt=limite).update(
        status=L.STATUS_ERRO,
        mensagem='Interrompido (servidor reiniciou ou parou de responder). Clique em consultar para continuar.',
        finalizado_em=timezone.now(),
    )


def lote_em_andamento():
    from crm_app.models import ChurnConsultaDebitoLote as L

    encerrar_lotes_parados()
    return L.objects.filter(status=L.STATUS_EM_ANDAMENTO).order_by('-iniciado_em').first()


def iniciar_lote(usuario, forcar: bool = False):
    """Cria o lote e dispara a thread. Devolve (lote, criado)."""
    from crm_app.models import ChurnConsultaDebitoLote as L

    with _lock_inicio:
        atual = lote_em_andamento()
        if atual:
            return atual, False
        lote = L.objects.create(iniciado_por=usuario, forcar=forcar, mensagem='Preparando lista de CPFs…')
    threading.Thread(target=_executar_lote, args=(lote.id, usuario.id), daemon=True, name=f'churn-debito-{lote.id}').start()
    return lote, True


def _executar_lote(lote_id: int, usuario_id: int) -> None:
    from django.contrib.auth import get_user_model

    from crm_app.models import ChurnConsultaDebitoLote as L
    from crm_app.models import ChurnConsultaDebitoNio as M

    close_old_connections()
    cancelado = threading.Event()
    try:
        lote = L.objects.get(pk=lote_id)
        usuario = get_user_model().objects.get(pk=usuario_id)
        docs = cpfs_churn_cruzados(usuario)
        if not lote.forcar:
            recentes = set(
                M.objects.filter(consultado_em__gte=timezone.now() - VALIDADE_CONSULTA)
                .exclude(situacao=M.ERRO)
                .values_list('cpf', flat=True)
            )
            docs = [d for d in docs if d not in recentes]
        L.objects.filter(pk=lote_id).update(
            total=len(docs), mensagem='Consultando na Nio…', atualizado_em=timezone.now(),
        )
        if not docs:
            L.objects.filter(pk=lote_id).update(
                status=L.STATUS_CONCLUIDO, finalizado_em=timezone.now(), atualizado_em=timezone.now(),
                mensagem='Nenhum CPF pendente: todos foram consultados nas últimas 24 horas.',
            )
            return

        cont = {'processados': 0, 'adimplentes': 0, 'inadimplentes': 0, 'a_vencer': 0, 'erros': 0}
        campo_contador = {
            M.ADIMPLENTE: 'adimplentes', M.INADIMPLENTE: 'inadimplentes',
            M.A_VENCER: 'a_vencer', M.ERRO: 'erros',
        }
        pausa = _Pausa()
        ultimo_flush = time.monotonic()

        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix=f'churn-debito-{lote_id}') as pool:
            futuros = {pool.submit(consultar_documento, d, pausa, cancelado): d for d in docs}
            for fut in as_completed(futuros):
                doc = futuros[fut]
                try:
                    res = fut.result()
                except Exception as exc:  # noqa: BLE001
                    res = {'situacao': M.ERRO, 'detalhe': str(exc)[:255]}
                situacao = res.pop('situacao', None)
                if situacao:
                    M.objects.update_or_create(
                        cpf=doc,
                        defaults={**res, 'situacao': situacao, 'consultado_em': timezone.now(), 'lote_id': lote_id},
                    )
                    cont['processados'] += 1
                    cont[campo_contador[situacao]] += 1

                if time.monotonic() - ultimo_flush >= 2 or cont['processados'] == len(docs):
                    ultimo_flush = time.monotonic()
                    L.objects.filter(pk=lote_id).update(**cont, atualizado_em=timezone.now())
                    if L.objects.filter(pk=lote_id, status=L.STATUS_CANCELADO).exists():
                        cancelado.set()
                        for f in futuros:
                            f.cancel()

        L.objects.filter(pk=lote_id).update(**cont, atualizado_em=timezone.now())
        if cancelado.is_set():
            L.objects.filter(pk=lote_id).update(finalizado_em=timezone.now(), mensagem='Cancelado pelo usuário.')
        else:
            L.objects.filter(pk=lote_id, status=L.STATUS_EM_ANDAMENTO).update(
                status=L.STATUS_CONCLUIDO, finalizado_em=timezone.now(), mensagem='Consulta concluída.',
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception('[CHURN DEBITO] lote %s falhou', lote_id)
        L.objects.filter(pk=lote_id).update(
            status=L.STATUS_ERRO, finalizado_em=timezone.now(), atualizado_em=timezone.now(),
            mensagem=f'Erro: {exc}'[:500],
        )
    finally:
        close_old_connections()


def serializar_lote(lote) -> Optional[dict]:
    if not lote:
        return None
    return {
        'id': lote.id,
        'status': lote.status,
        'total': lote.total,
        'processados': lote.processados,
        'adimplentes': lote.adimplentes,
        'inadimplentes': lote.inadimplentes,
        'a_vencer': lote.a_vencer,
        'erros': lote.erros,
        'mensagem': lote.mensagem,
        'iniciado_em': lote.iniciado_em.isoformat() if lote.iniciado_em else None,
        'finalizado_em': lote.finalizado_em.isoformat() if lote.finalizado_em else None,
        'iniciado_por': getattr(lote.iniciado_por, 'username', None),
    }
