"""
Controle de TT's: fila por dias sem vender (OSAB) e marcações diárias.
Usado pela API interna e pela automação WhatsApp VENDER (matrícula no PAP).
"""
import logging
from datetime import timedelta

from django.db.models import Max, Q
from django.utils import timezone

from crm_app.models import ControleTTDiaTratado, ImportacaoOsab

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
    Próximo TT da fila (não marcado hoje), para preencher o vendedor no PAP.
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
