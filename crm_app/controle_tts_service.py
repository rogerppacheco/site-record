"""
Controle de TT's: fila por dias sem vender (OSAB) e marcações diárias.
Usado pela API interna, VENDER (fila OSAB) e CRÉDITO (menor carga do dia).
"""
import logging
import random
from datetime import timedelta
from typing import Optional, Set

from django.conf import settings
from django.db.models import F, Max, Q
from django.utils import timezone

from crm_app.models import ControleTTDiaTratado, ControleTTCreditoUsoDiario, ImportacaoOsab

logger = logging.getLogger(__name__)

SITUACOES_VENDA_VALIDA_OSAB = [
    "Concluído",
    "Pendência Cliente",
    "Cancelado",
    "Pendência Técnica",
    "Em Aprovisionamento",
]


def controle_tts_listar_ordenado():
    """
    Lista de TTs com última venda válida e dias sem vender; ordenado por dias sem vender (decrescente).
    Mesma lógica do endpoint GET controle-tts/.
    """
    hoje = timezone.localdate()
    ontem = hoje - timedelta(days=1)
    dois_meses_atras = hoje - timedelta(days=60)
    matriculas_qs = (
        ImportacaoOsab.objects.filter(data_abertura__gte=dois_meses_atras, matricula_vendedor__isnull=False)
        .exclude(matricula_vendedor="")
        .values_list("matricula_vendedor", flat=True)
        .distinct()
    )
    matriculas = list(matriculas_qs)
    filtro_situacao_valida = Q(situacao__in=SITUACOES_VENDA_VALIDA_OSAB)
    resultado = []
    for mat in matriculas:
        ultima = (
            ImportacaoOsab.objects.filter(matricula_vendedor=mat)
            .filter(filtro_situacao_valida)
            .filter(data_abertura__isnull=False)
            .aggregate(Max("data_abertura"))
        )
        ultima_venda = ultima.get("data_abertura__max")
        if ultima_venda is not None:
            if hasattr(ultima_venda, "date"):
                ultima_venda = ultima_venda.date()
            dias_sem_vender = (ontem - ultima_venda).days
        else:
            dias_sem_vender = None
        resultado.append(
            {
                "matricula_vendedor": mat,
                "ultima_venda": ultima_venda.isoformat() if ultima_venda else None,
                "dias_sem_vender": dias_sem_vender,
            }
        )

    def sort_key(item):
        d = item["dias_sem_vender"]
        if d is None:
            return -1
        return -d

    resultado.sort(key=sort_key)
    return resultado


def obter_matricula_tt_para_novo_pedido_pap(matricula_fallback: str) -> str:
    """
    Próximo TT da fila (não marcado hoje), para preencher o vendedor no PAP — fluxo VENDER.
    Ordenação: maior dias sem vender (OSAB) primeiro.
    Se não houver próximo, usa matricula_fallback (cadastro do operador).
    """
    matricula_fallback = (matricula_fallback or "").strip()
    lista = controle_tts_listar_ordenado()
    hoje = timezone.localdate()
    marcadas = set(
        ControleTTDiaTratado.objects.filter(data=hoje).values_list("matricula_vendedor", flat=True)
    )
    lista_filtrada = [x for x in lista if x["matricula_vendedor"] not in marcadas]
    proximo = lista_filtrada[0] if lista_filtrada else None
    if proximo and proximo.get("matricula_vendedor"):
        m = str(proximo["matricula_vendedor"]).strip()
        if m:
            logger.info("[Controle TT] PAP novo pedido: TT da vez = %s", m)
            return m
    logger.info(
        "[Controle TT] PAP novo pedido: sem próximo na fila — usando operador %s",
        matricula_fallback or "(vazio)",
    )
    return matricula_fallback


def _max_consultas_credito_por_tt_dia() -> int:
    return max(1, int(getattr(settings, "PAP_CREDITO_MAX_CONSULTAS_POR_TT_DIA", 6)))


def _mapa_uso_credito_hoje(matriculas: list[str]) -> dict[str, int]:
    hoje = timezone.localdate()
    if not matriculas:
        return {}
    rows = ControleTTCreditoUsoDiario.objects.filter(
        data=hoje,
        matricula_vendedor__in=matriculas,
    )
    return {r.matricula_vendedor: r.consultas for r in rows}


def obter_matricula_tt_para_credito_pap(
    matricula_fallback: str,
    excluir: Optional[Set[str]] = None,
) -> str:
    """
    Escolhe TT para consulta de crédito distribuindo carga no dia:
    - prioriza quem tem MENOS consultas hoje;
    - respeita teto PAP_CREDITO_MAX_CONSULTAS_POR_TT_DIA;
    - em empate, sorteia entre os candidatos (evita sempre o mesmo TT).
    """
    matricula_fallback = (matricula_fallback or "").strip()
    excluir_norm = {(m or "").strip().upper() for m in (excluir or set()) if (m or "").strip()}

    lista = controle_tts_listar_ordenado()
    matriculas = [
        str(x["matricula_vendedor"]).strip()
        for x in lista
        if x.get("matricula_vendedor")
    ]
    if not matriculas:
        logger.warning(
            "[Controle TT] Crédito: fila OSAB vazia — fallback %s",
            matricula_fallback or "(vazio)",
        )
        return matricula_fallback

    uso_map = _mapa_uso_credito_hoje(matriculas)
    max_dia = _max_consultas_credito_por_tt_dia()

    def uso(mat: str) -> int:
        return uso_map.get(mat, 0)

    def disponivel(mat: str) -> bool:
        return mat.strip().upper() not in excluir_norm

    candidatos = [m for m in matriculas if disponivel(m) and uso(m) < max_dia]
    if not candidatos:
        candidatos = [m for m in matriculas if disponivel(m)]
    if not candidatos:
        logger.warning(
            "[Controle TT] Crédito: nenhum TT disponível (excluídos=%s) — fallback %s",
            len(excluir_norm),
            matricula_fallback or "(vazio)",
        )
        return matricula_fallback

    min_uso = min(uso(m) for m in candidatos)
    empate = [m for m in candidatos if uso(m) == min_uso]
    escolhido = random.choice(empate)
    logger.info(
        "[Controle TT] Crédito: TT=%s uso_hoje=%s min=%s empate=%s teto=%s",
        escolhido,
        uso(escolhido),
        min_uso,
        len(empate),
        max_dia,
    )
    return escolhido


def registrar_uso_tt_credito(matricula_vendedor: str) -> None:
    """Incrementa contador de consultas de crédito do TT no dia."""
    m = (matricula_vendedor or "").strip()
    if not m:
        return
    hoje = timezone.localdate()
    try:
        obj, _ = ControleTTCreditoUsoDiario.objects.get_or_create(
            matricula_vendedor=m,
            data=hoje,
            defaults={"consultas": 0},
        )
        ControleTTCreditoUsoDiario.objects.filter(pk=obj.pk).update(
            consultas=F("consultas") + 1
        )
        logger.info("[Controle TT] Crédito: uso registrado para %s em %s", m, hoje.isoformat())
    except Exception as e:
        logger.warning("[Controle TT] Falha ao registrar uso crédito %s: %s", m, e)


def pular_tt_credito_indisponivel(matricula_vendedor: str) -> None:
    """
    Marca TT no teto do dia (ex.: inexistente no PAP) para não reescolher na mesma sessão.
    """
    m = (matricula_vendedor or "").strip()
    if not m:
        return
    hoje = timezone.localdate()
    max_dia = _max_consultas_credito_por_tt_dia()
    try:
        ControleTTCreditoUsoDiario.objects.update_or_create(
            matricula_vendedor=m,
            data=hoje,
            defaults={"consultas": max_dia},
        )
        logger.info("[Controle TT] Crédito: TT %s marcado indisponível (teto %s)", m, max_dia)
    except Exception as e:
        logger.warning("[Controle TT] Falha ao pular TT crédito %s: %s", m, e)


def marcar_tt_tratado_apos_geracao_os(matricula_vendedor: str) -> None:
    """
    Marca tratado no dia atual para a matrícula usada no PAP (O.S. gerada).
    Idempotente (update_or_create). usuario=None (automático).
    """
    m = (matricula_vendedor or "").strip()
    if not m:
        return
    hoje = timezone.localdate()
    try:
        ControleTTDiaTratado.objects.update_or_create(
            matricula_vendedor=m,
            data=hoje,
            defaults={"tipo": ControleTTDiaTratado.TIPO_TRATADO, "usuario": None},
        )
        logger.info("[Controle TT] Marcado tratado (O.S.) para %s em %s", m, hoje.isoformat())
    except Exception as e:
        logger.warning("[Controle TT] Falha ao marcar tratado para %s: %s", m, e)
