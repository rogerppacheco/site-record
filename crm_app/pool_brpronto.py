# crm_app/pool_brpronto.py
"""
Pool de logins Br Pronto PDV (ged360) usado por todas as automações de biometria
(auditoria Checar biometria, comando BIO no WhatsApp e Repescagem Bio).

Os logins ficam em Governança > Contas de Serviço (Robôs), função "Br Pronto / GED360".
O GED bloqueia sessão simultânea — o serviço sempre faz logoff; a trava (em_uso)
evita dois jobs usarem o mesmo login ao mesmo tempo.
"""
from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

FUNCAO_ROBO_BRPRONTO = "BRPRONTO_GED"
LOCK_TIMEOUT_MINUTOS = 20

MSG_TODOS_BRPRONTO_EM_USO = (
    "⚠️ *Todos os logins Br Pronto estão em uso*\n\n"
    "Aguarde alguns minutos e tente novamente.\n\n"
    "Digite *BIO* para tentar de novo."
)

MSG_NENHUM_BRPRONTO = (
    "⚠️ *Nenhum login Br Pronto liberado para automação*\n\n"
    "Cadastre o login em *Governança > Contas de Serviço (Robôs)* "
    "com a função *Br Pronto / GED360 (Biometria)*."
)


def _robos_brpronto():
    from usuarios.models import CredencialRoboPAP

    return (
        CredencialRoboPAP.objects.filter(funcao=FUNCAO_ROBO_BRPRONTO, ativo=True)
        .exclude(matricula="")
        .exclude(senha="")
    )


def _limpar_locks_expirados() -> int:
    from usuarios.models import CredencialRoboPAP

    limite = timezone.now() - timedelta(minutes=LOCK_TIMEOUT_MINUTOS)
    liberados = CredencialRoboPAP.objects.filter(
        funcao=FUNCAO_ROBO_BRPRONTO, em_uso=True, ultimo_uso__lt=limite,
    ).update(em_uso=False)
    if liberados:
        logger.info("[POOL BrPronto] Liberados %s lock(s) expirado(s)", liberados)
    return liberados


def obter_login_brpronto(
    solicitante_telefone: str = "",
    sessao_whatsapp_id: Optional[int] = None,
    origem: str = "bio",
):
    """
    Obtém um login Br Pronto disponível (randômico entre os livres).

    Returns:
        (robo, None) em sucesso — o robô expõe brpronto_login, brpronto_senha e brpronto_dominio
        (None, mensagem_erro) quando indisponível
    """
    from usuarios.models import CredencialRoboPAP

    _limpar_locks_expirados()

    elegiveis = _robos_brpronto()
    if not elegiveis.exists():
        return None, MSG_NENHUM_BRPRONTO

    candidatos = list(elegiveis.filter(em_uso=False))
    random.shuffle(candidatos)
    for candidato in candidatos:
        with transaction.atomic():
            robo = CredencialRoboPAP.objects.select_for_update().get(id=candidato.id)
            if robo.em_uso:
                continue
            robo.em_uso = True
            robo.ultimo_uso = timezone.now()
            robo.save(update_fields=["em_uso", "ultimo_uso"])
        logger.info(
            "[POOL BrPronto] login=%s alocado para %s origem=%s",
            robo.matricula,
            solicitante_telefone or "sistema",
            origem,
        )
        return robo, None

    return None, MSG_TODOS_BRPRONTO_EM_USO


def renovar_login_brpronto(robo_id: int) -> None:
    """Renova a trava de um login em uso por um job longo, para não expirar no meio."""
    from usuarios.models import CredencialRoboPAP

    CredencialRoboPAP.objects.filter(id=robo_id, em_uso=True).update(ultimo_uso=timezone.now())


def liberar_login_brpronto(
    bo_usuario_id: int,
    solicitante_telefone: str = "",
) -> bool:
    """Libera a trava do login Br Pronto após a consulta."""
    from usuarios.models import CredencialRoboPAP

    try:
        n = CredencialRoboPAP.objects.filter(
            id=bo_usuario_id, funcao=FUNCAO_ROBO_BRPRONTO, em_uso=True,
        ).update(em_uso=False)
        if n:
            logger.info(
                "[POOL BrPronto] Liberado robo_id=%s telefone=%s",
                bo_usuario_id,
                solicitante_telefone or "-",
            )
        return n > 0
    except Exception as e:
        logger.exception("[POOL BrPronto] Erro ao liberar: %s", e)
        return False


def liberar_todos_brpronto() -> Tuple[int, str]:
    """Libera todas as travas Br Pronto (painel / emergência)."""
    from usuarios.models import CredencialRoboPAP

    try:
        total = CredencialRoboPAP.objects.filter(funcao=FUNCAO_ROBO_BRPRONTO, em_uso=True).update(em_uso=False)
        if total == 0:
            return 0, "Nenhum login Br Pronto estava em uso."
        return total, f"Liberados {total} login(s) Br Pronto."
    except Exception as e:
        logger.exception("[POOL BrPronto] Erro ao liberar todos: %s", e)
        return 0, f"Erro ao liberar: {e}"
