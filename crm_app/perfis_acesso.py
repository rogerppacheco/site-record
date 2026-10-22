"""Constantes de perfis e grupos de acesso (visualização vs edição)."""
from __future__ import annotations

from typing import Any

from crm_app.utils import is_member

PERFIL_GERENTE_CONTAS = 'Gerente de Contas'

GRUPOS_SOMENTE_LEITURA: list[str] = [PERFIL_GERENTE_CONTAS]

GRUPOS_VISUALIZACAO_GESTAO: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    'Auditoria',
    'Qualidade',
    PERFIL_GERENTE_CONTAS,
]

GRUPOS_FPD_DASHBOARD: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    'Qualidade',
    'Auditoria',
    PERFIL_GERENTE_CONTAS,
]

# Perfis que já entram sem marcação extra. Os demais recebem o acesso
# pela permissão correspondente em Gestão de Perfis de Acesso.
GRUPOS_ESTEIRA_GESTAO_APROVEITAMENTO: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
]

PERM_VER_GESTAO_ESTEIRA = 'crm_app.can_view_gestao_esteira'
PERM_EXPORTAR_AGENDADOS_PENDENTES_ESTEIRA = 'crm_app.can_export_agendados_pendentes_esteira'

GRUPOS_CDOI_EDICAO: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    PERFIL_GERENTE_CONTAS,
]

GRUPOS_EXPORT_AGENDADOS_PENDENTES: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    'Supervisor',
]


def _tem_permissao_django(user: Any, codename: str) -> bool:
    """Permissão marcada no grupo (Gestão de Perfis de Acesso) ou no usuário."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    try:
        return bool(user.has_perm(codename))
    except Exception:
        return False


def pode_ver_gestao_esteira(user: Any) -> bool:
    """Aba Gestão da esteira: perfis padrão ou permissão can_view_gestao_esteira."""
    if is_member(user, GRUPOS_ESTEIRA_GESTAO_APROVEITAMENTO):
        return True
    return _tem_permissao_django(user, PERM_VER_GESTAO_ESTEIRA)


def pode_exportar_agendados_pendentes(user: Any) -> bool:
    """Excel Agendados e Pendentes: perfis padrão ou permissão do perfil."""
    if is_member(user, GRUPOS_EXPORT_AGENDADOS_PENDENTES):
        return True
    return _tem_permissao_django(user, PERM_EXPORTAR_AGENDADOS_PENDENTES_ESTEIRA)


def _pertence_grupo_ou_perfil(user: Any, grupos: list[str]) -> bool:
    """Membership real por Group/Perfil, sem o atalho de superuser de is_member()."""
    if not user:
        return False
    try:
        if user.groups.filter(name__in=grupos).exists():
            return True
    except Exception:
        pass
    try:
        if getattr(user, 'perfil_id', None):
            perfil = user.perfil
            if perfil and perfil.nome in grupos:
                return True
    except Exception:
        pass
    return False


def is_somente_leitura(user: Any) -> bool:
    """True se o perfil do usuário é somente leitura (sem ações de escrita).

    Não usar is_member() aqui: aquele helper retorna True para superuser em
    qualquer grupo, o que bloqueava Admin/Diretoria de salvar vendas.
    """
    if not user or getattr(user, 'is_superuser', False):
        return False
    if _pertence_grupo_ou_perfil(user, ['Diretoria', 'Admin', 'BackOffice']):
        return False
    return _pertence_grupo_ou_perfil(user, GRUPOS_SOMENTE_LEITURA)


def pode_acessar_fpd_dashboard(user: Any) -> bool:
    """Acesso ao Dashboard FPD (inclui Gerente de Contas)."""
    return is_member(user, GRUPOS_FPD_DASHBOARD)
