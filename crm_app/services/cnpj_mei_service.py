# -*- coding: utf-8 -*-
"""
Classificação MEI / NMEI via BrasilAPI com cache Django.

Uso principal: consulta ao cadastrar venda com CNPJ (14 dígitos).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

BRASILAPI_CNPJ_URL = 'https://brasilapi.com.br/api/cnpj/v1/{cnpj}'
CACHE_KEY_PREFIX = 'cnpj_mei:'
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 dias
REQUEST_TIMEOUT_SECONDS = 12

CLASSIFICACAO_MEI = 'MEI'
CLASSIFICACAO_NMEI = 'NMEI'
CLASSIFICACAO_INDETERMINADO = 'INDETERMINADO'
CLASSIFICACAO_CPF = 'CPF'

CLASSIFICACAO_CHOICES = [
    (CLASSIFICACAO_MEI, 'MEI'),
    (CLASSIFICACAO_NMEI, 'Não MEI'),
    (CLASSIFICACAO_INDETERMINADO, 'Indeterminado'),
    (CLASSIFICACAO_CPF, 'CPF (não aplicável)'),
]

CLASSIFICACAO_LABELS = {
    CLASSIFICACAO_MEI: 'MEI',
    CLASSIFICACAO_NMEI: 'NMEI',
    CLASSIFICACAO_INDETERMINADO: 'NMEI',
    CLASSIFICACAO_CPF: '-',
}


def classificacao_resumida_cnpj(codigo: Optional[str]) -> Optional[str]:
    """Somente MEI ou NMEI para persistência de CNPJ."""
    if codigo == CLASSIFICACAO_MEI:
        return CLASSIFICACAO_MEI
    if codigo:
        return CLASSIFICACAO_NMEI
    return None


def rotulo_classificacao_mei(codigo: Optional[str], *, documento: str = '') -> str:
    """Rótulo exibido: MEI, NMEI ou - (CPF / sem CNPJ)."""
    doc = _limpar_documento(documento)
    if len(doc) == 11:
        return '-'
    if codigo == CLASSIFICACAO_MEI:
        return CLASSIFICACAO_MEI
    if len(doc) == 14:
        return CLASSIFICACAO_NMEI if codigo else '-'
    return '-'


def _normalizar_resultado_cnpj(resultado: ResultadoClassificacaoMei) -> ResultadoClassificacaoMei:
    if resultado.classificacao is None:
        return resultado
    resumido = classificacao_resumida_cnpj(resultado.classificacao) or CLASSIFICACAO_NMEI
    resultado.classificacao = resumido
    resultado.descricao = resumido
    return resultado


@dataclass
class ResultadoClassificacaoMei:
    classificacao: str
    descricao: str
    cnpj: str = ''
    codigo_natureza_juridica: Optional[int] = None
    natureza_juridica: str = ''
    opcao_pelo_mei: Optional[str] = None
    fonte: str = 'brasilapi'
    cache_hit: bool = False
    erro: Optional[str] = None

    def para_dict(self) -> dict[str, Any]:
        return {
            'classificacao_mei': self.classificacao,
            'classificacao_mei_descricao': self.descricao,
            'cnpj': self.cnpj,
            'codigo_natureza_juridica': self.codigo_natureza_juridica,
            'natureza_juridica': self.natureza_juridica,
            'opcao_pelo_mei': self.opcao_pelo_mei,
            'fonte': self.fonte,
            'cache_hit': self.cache_hit,
            'erro': self.erro,
        }


def _limpar_documento(doc: str) -> str:
    return re.sub(r'\D', '', str(doc or ''))


def _cache_key(cnpj_limpo: str) -> str:
    return f'{CACHE_KEY_PREFIX}{cnpj_limpo}'


def _normalizar_opcao_mei(valor: Any) -> str:
    if valor is None:
        return ''
    return str(valor).strip().upper()


def _interpretar_resposta_brasilapi(payload: dict, cnpj_limpo: str) -> ResultadoClassificacaoMei:
    codigo_nj = payload.get('codigo_natureza_juridica')
    try:
        codigo_nj_int = int(codigo_nj) if codigo_nj is not None else None
    except (TypeError, ValueError):
        codigo_nj_int = None

    natureza = (payload.get('natureza_juridica') or '').strip()
    opcao = _normalizar_opcao_mei(payload.get('opcao_pelo_mei'))
    excluido = payload.get('data_exclusao_do_mei')

    if opcao in ('S', 'SIM', 'TRUE', '1'):
        if not excluido:
            classificacao = CLASSIFICACAO_MEI
        else:
            classificacao = CLASSIFICACAO_NMEI
    elif opcao in ('N', 'NAO', 'NÃO', 'FALSE', '0'):
        classificacao = CLASSIFICACAO_NMEI
    elif codigo_nj_int is not None and codigo_nj_int != 2135:
        classificacao = CLASSIFICACAO_NMEI
    else:
        classificacao = CLASSIFICACAO_NMEI

    return _normalizar_resultado_cnpj(ResultadoClassificacaoMei(
        classificacao=classificacao,
        descricao=classificacao,
        cnpj=cnpj_limpo,
        codigo_natureza_juridica=codigo_nj_int,
        natureza_juridica=natureza,
        opcao_pelo_mei=opcao or None,
        fonte='brasilapi',
    ))


def _consultar_brasilapi(cnpj_limpo: str, *, tentativas: int = 1) -> Optional[dict]:
    import urllib.error
    import urllib.request

    url = BRASILAPI_CNPJ_URL.format(cnpj=cnpj_limpo)
    req = urllib.request.Request(url, headers={'User-Agent': 'RecordCRM/1.0'})
    max_tentativas = max(1, int(tentativas))
    for tentativa in range(1, max_tentativas + 1):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            logger.warning('[CNPJ MEI] BrasilAPI HTTP %s para %s', e.code, cnpj_limpo)
            return None
        except Exception as e:
            if tentativa < max_tentativas:
                logger.warning(
                    '[CNPJ MEI] Tentativa %s/%s falhou para %s: %s',
                    tentativa, max_tentativas, cnpj_limpo, e,
                )
                continue
            logger.warning('[CNPJ MEI] Erro BrasilAPI para %s: %s', cnpj_limpo, e)
            return None
    return None


def classificar_cnpj_mei(cnpj: str, *, usar_cache: bool = True) -> ResultadoClassificacaoMei:
    """
    Classifica CNPJ como MEI ou NMEI. CPF (11 dígitos) não recebe classificação.
    """
    doc = _limpar_documento(cnpj)
    if len(doc) == 11:
        return ResultadoClassificacaoMei(
            classificacao=None,
            descricao='-',
            fonte='local',
        )
    if len(doc) != 14:
        return ResultadoClassificacaoMei(
            classificacao=CLASSIFICACAO_NMEI,
            descricao=CLASSIFICACAO_NMEI,
            cnpj=doc,
            fonte='local',
            erro='CNPJ deve ter 14 dígitos.',
        )

    chave = _cache_key(doc)
    if usar_cache:
        cached = cache.get(chave)
        if isinstance(cached, dict) and cached.get('classificacao'):
            cod_cache = classificacao_resumida_cnpj(cached['classificacao'])
            return ResultadoClassificacaoMei(
                classificacao=cod_cache or CLASSIFICACAO_NMEI,
                descricao=cod_cache or CLASSIFICACAO_NMEI,
                cnpj=doc,
                codigo_natureza_juridica=cached.get('codigo_natureza_juridica'),
                natureza_juridica=cached.get('natureza_juridica') or '',
                opcao_pelo_mei=cached.get('opcao_pelo_mei'),
                fonte=cached.get('fonte') or 'cache',
                cache_hit=True,
            )

    payload = _consultar_brasilapi(doc, tentativas=2)
    if not payload:
        resultado = ResultadoClassificacaoMei(
            classificacao=CLASSIFICACAO_NMEI,
            descricao=CLASSIFICACAO_NMEI,
            cnpj=doc,
            fonte='brasilapi',
            erro='Não foi possível consultar o CNPJ na BrasilAPI.',
        )
    else:
        resultado = _interpretar_resposta_brasilapi(payload, doc)

    resultado = _normalizar_resultado_cnpj(resultado)

    if usar_cache:
        cache.set(
            chave,
            {
                'classificacao': resultado.classificacao,
                'descricao': resultado.descricao,
                'codigo_natureza_juridica': resultado.codigo_natureza_juridica,
                'natureza_juridica': resultado.natureza_juridica,
                'opcao_pelo_mei': resultado.opcao_pelo_mei,
                'fonte': resultado.fonte,
            },
            CACHE_TTL_SECONDS,
        )
    return resultado


def _aplicar_resultado_no_cliente(cliente, resultado: ResultadoClassificacaoMei) -> None:
    doc = _limpar_documento(cliente.cpf_cnpj)
    if len(doc) == 11:
        cliente.classificacao_mei = None
    else:
        cliente.classificacao_mei = resultado.classificacao
    cliente.classificacao_mei_consultada_em = timezone.now()
    cliente.save(update_fields=['classificacao_mei', 'classificacao_mei_consultada_em'])


def persistir_classificacao_mei(cliente, venda=None, *, usar_cache: bool = True) -> ResultadoClassificacaoMei:
    """
    Consulta (se CNPJ), grava em Cliente e opcionalmente na Venda.
    """
    from crm_app.models import Cliente, Venda

    if not isinstance(cliente, Cliente):
        raise TypeError('cliente deve ser instância de Cliente')

    resultado = classificar_cnpj_mei(cliente.cpf_cnpj, usar_cache=usar_cache)
    _aplicar_resultado_no_cliente(cliente, resultado)

    if venda is not None and isinstance(venda, Venda):
        doc = _limpar_documento(cliente.cpf_cnpj)
        venda.classificacao_mei = None if len(doc) == 11 else resultado.classificacao
        venda.save(update_fields=['classificacao_mei'])

    return resultado


def persistir_classificacao_mei_cliente_e_vendas(cliente, *, usar_cache: bool = True) -> ResultadoClassificacaoMei:
    """Atualiza cliente e todas as vendas vinculadas (backfill histórico)."""
    from crm_app.models import Cliente, Venda

    if not isinstance(cliente, Cliente):
        raise TypeError('cliente deve ser instância de Cliente')

    resultado = classificar_cnpj_mei(cliente.cpf_cnpj, usar_cache=usar_cache)
    _aplicar_resultado_no_cliente(cliente, resultado)
    doc = _limpar_documento(cliente.cpf_cnpj)
    if len(doc) == 11:
        Venda.objects.filter(cliente_id=cliente.id).update(classificacao_mei=None)
    else:
        Venda.objects.filter(cliente_id=cliente.id).update(classificacao_mei=resultado.classificacao)
    return resultado


def normalizar_classificacoes_legadas_no_banco() -> dict[str, int]:
    """Converte INDETERMINADO/CPF em MEI/NMEI (ou limpa CPF pessoa física)."""
    from django.db.models import Q
    from django.db.models.functions import Length

    from crm_app.models import Cliente, Venda

    upd_cli = Cliente.objects.filter(classificacao_mei='INDETERMINADO').update(
        classificacao_mei=CLASSIFICACAO_NMEI
    )
    upd_ven = Venda.objects.filter(classificacao_mei='INDETERMINADO').update(
        classificacao_mei=CLASSIFICACAO_NMEI
    )
    cli_cpf = Cliente.objects.annotate(doc_len=Length('cpf_cnpj')).filter(doc_len=11)
    ven_cpf = Venda.objects.filter(
        cliente_id__in=cli_cpf.values_list('id', flat=True)
    )
    limp_cli = cli_cpf.exclude(
        Q(classificacao_mei__isnull=True) | Q(classificacao_mei='')
    ).update(classificacao_mei=None)
    limp_ven = ven_cpf.exclude(
        Q(classificacao_mei__isnull=True) | Q(classificacao_mei='')
    ).update(classificacao_mei=None)
    corr_cli = Cliente.objects.annotate(doc_len=Length('cpf_cnpj')).filter(
        doc_len=14, classificacao_mei='CPF'
    ).update(classificacao_mei=CLASSIFICACAO_NMEI)
    corr_ven = Venda.objects.filter(classificacao_mei='CPF').update(
        classificacao_mei=CLASSIFICACAO_NMEI
    )
    return {
        'clientes_indeterminado_para_nmei': upd_cli,
        'vendas_indeterminado_para_nmei': upd_ven,
        'clientes_cpf_limpos': limp_cli,
        'vendas_cpf_limpos': limp_ven,
        'clientes_cpf_errado_cnpj': corr_cli,
        'vendas_cpf_errado': corr_ven,
    }


def queryset_clientes_cnpj(*, apenas_sem_classificacao: bool = True):
    """Clientes com CNPJ (14 dígitos no cadastro), opcionalmente sem classificação."""
    from django.db.models import Q
    from django.db.models.functions import Length

    from crm_app.models import Cliente

    qs = Cliente.objects.annotate(doc_len=Length('cpf_cnpj')).filter(doc_len=14)
    if apenas_sem_classificacao:
        qs = qs.filter(Q(classificacao_mei__isnull=True) | Q(classificacao_mei=''))
    return qs.order_by('id')


def backfill_classificacao_mei_lote(
    *,
    offset: int = 0,
    limite: int = 20,
    apenas_sem_classificacao: bool = True,
    pausa_api_segundos: float = 0.35,
) -> dict[str, Any]:
    """
    Processa um lote de CNPJs para preencher classificacao_mei em Cliente e Vendas.

    Sempre pega os primeiros ``limite`` clientes ainda sem classificação (offset ignorado
    na seleção). A fila encolhe a cada lote; usar offset crescente fazia o job parar cedo.
    """
    import time

    limite = max(1, min(int(limite), 50))

    qs = queryset_clientes_cnpj(apenas_sem_classificacao=apenas_sem_classificacao)
    total_pendentes = qs.count()
    clientes = list(qs[:limite])

    try:
        normalizar_classificacoes_legadas_no_banco()
    except Exception:
        logger.exception('[CNPJ MEI] Erro ao normalizar classificações legadas')

    contagem = {
        CLASSIFICACAO_MEI: 0,
        CLASSIFICACAO_NMEI: 0,
    }
    vendas_atualizadas = 0
    erros = 0

    from crm_app.models import Venda

    for cliente in clientes:
        try:
            qtd_vendas = Venda.objects.filter(cliente_id=cliente.id).count()
            resultado = persistir_classificacao_mei_cliente_e_vendas(cliente)
            contagem[resultado.classificacao] = contagem.get(resultado.classificacao, 0) + 1
            vendas_atualizadas += qtd_vendas
            if not resultado.cache_hit and pausa_api_segundos > 0:
                time.sleep(pausa_api_segundos)
        except Exception:
            logger.exception('[CNPJ MEI] Erro no backfill cliente id=%s', cliente.id)
            erros += 1

    processados = len(clientes)
    restantes = max(0, total_pendentes - processados)
    concluido = processados == 0 or restantes == 0

    return {
        'total_pendentes': total_pendentes,
        'restantes': restantes,
        'processados_lote': processados,
        'proximo_offset': offset + processados,
        'concluido': concluido,
        'mei': contagem.get(CLASSIFICACAO_MEI, 0),
        'nmei': contagem.get(CLASSIFICACAO_NMEI, 0),
        'indeterminado': 0,
        'erros': erros,
        'vendas_atualizadas': vendas_atualizadas,
    }
