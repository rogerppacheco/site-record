# crm_app/pool_bo_pap.py
"""
Pool de logins BackOffice para automação PAP.

Vendedores (perfil Vendedor) não conseguem fazer vendas pelo site pap.niointernet.com.br.
Usuários com autorizar_venda_sem_auditoria usam logins de perfil BackOffice,
com seleção randômica entre os disponíveis e bloqueio para evitar conflitos.
"""
import logging
import random
from datetime import timedelta
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Timeout em minutos - locks mais antigos são considerados órfãos (sessão travou)
LOCK_TIMEOUT_MINUTOS = 30


def _limpar_locks_expirados():
    """Remove registros de BO em uso há mais de LOCK_TIMEOUT_MINUTOS."""
    from crm_app.models import PapBoEmUso

    limite = timezone.now() - timedelta(minutes=LOCK_TIMEOUT_MINUTOS)
    deletados = PapBoEmUso.objects.filter(locked_at__lt=limite).delete()
    if deletados[0] > 0:
        logger.info(f"[POOL BO] Liberados {deletados[0]} lock(s) expirado(s)")


def obter_login_bo(
    vendedor_telefone: str,
    sessao_whatsapp_id: Optional[int] = None,
) -> Tuple[Optional["Usuario"], Optional[str]]:
    """
    Obtém um login BackOffice disponível para uso na automação PAP.

    Usa seleção randômica entre os BOs livres. Garante que o próximo vendedor
    não pegue o mesmo BO que outro em uso.

    Args:
        vendedor_telefone: Telefone do vendedor que está iniciando a venda
        sessao_whatsapp_id: ID da SessaoWhatsapp (opcional, para rastreamento)

    Returns:
        (bo_usuario, None) em sucesso
        (None, "mensagem_erro") quando todos os BOs estão ocupados
    """
    from usuarios.models import Usuario
    from crm_app.models import PapBoEmUso

    _limpar_locks_expirados()

    # IDs dos BOs atualmente em uso
    ids_em_uso = set(
        PapBoEmUso.objects.values_list('bo_usuario_id', flat=True)
    )

    # Buscar usuários BackOffice com matrícula e senha configuradas
    bo_queryset = Usuario.objects.filter(
        perfil__cod_perfil__iexact='backoffice',
        is_active=True,
        matricula_pap__isnull=False,
    ).exclude(
        matricula_pap='',
    ).exclude(
        senha_pap__isnull=True,
    ).exclude(
        senha_pap='',
    )

    # Excluir os que já estão em uso
    if ids_em_uso:
        bo_queryset = bo_queryset.exclude(id__in=ids_em_uso)

    bo_list = list(bo_queryset)
    if not bo_list:
        return (
            None,
            (
                "⚠️ *TODOS OS ACESSOS BACKOFFICE ESTÃO EM USO*\n\n"
                "No momento todos os logins de backoffice estão ocupados com outras vendas.\n\n"
                "Aguarde alguns minutos e tente novamente.\n\n"
                "Digite *VENDER* para tentar novamente."
            ),
        )

    # Seleção randômica
    bo_usuario = random.choice(bo_list)

    try:
        with transaction.atomic():
            PapBoEmUso.objects.create(
                bo_usuario=bo_usuario,
                vendedor_telefone=vendedor_telefone,
                sessao_whatsapp_id=sessao_whatsapp_id,
            )
        logger.info(
            f"[POOL BO] BO {bo_usuario.username} (matricula {bo_usuario.matricula_pap}) "
            f"alocado para {vendedor_telefone}"
        )
        return bo_usuario, None
    except Exception as e:
        logger.exception(f"[POOL BO] Erro ao alocar BO: {e}")
        return (
            None,
            "❌ Erro ao alocar acesso. Tente novamente em instantes.",
        )


def liberar_bo(
    bo_usuario_id: int,
    vendedor_telefone: str,
) -> bool:
    """
    Libera o login BackOffice após conclusão da venda (sucesso, erro ou cancelamento).

    Args:
        bo_usuario_id: ID do usuário BackOffice
        vendedor_telefone: Telefone do vendedor que estava usando

    Returns:
        True se liberou com sucesso, False caso contrário
    """
    from crm_app.models import PapBoEmUso

    try:
        deletados = PapBoEmUso.objects.filter(
            bo_usuario_id=bo_usuario_id,
            vendedor_telefone=vendedor_telefone,
        ).delete()
        if deletados[0] > 0:
            logger.info(
                f"[POOL BO] Liberado BO id={bo_usuario_id} usado por {vendedor_telefone}"
            )
        return deletados[0] > 0
    except Exception as e:
        logger.exception(f"[POOL BO] Erro ao liberar BO: {e}")
        return False
