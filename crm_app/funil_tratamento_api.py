"""API — botão Tratar do Funil (todas as abas)."""
from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.services import funil_tratamento_service as svc
from crm_app.utils import is_member

GRUPOS = ['Diretoria', 'BackOffice', 'Admin']


def _sem_permissao(request) -> Response | None:
    if is_member(request.user, GRUPOS):
        return None
    return Response({'detail': 'Sem permissão para tratar no Funil.'}, status=status.HTTP_403_FORBIDDEN)


class FunilTratarView(APIView):
    """GET {aba,id} prévia | POST marca como tratado."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        aba = str(request.query_params.get('aba') or '').strip().upper()
        ref = request.query_params.get('id')
        try:
            ctx = svc.resolver_contexto(aba, ref)
        except ValueError as exc:
            return Response({'ok': False, 'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        atual = svc.mapa_por_refs(aba, [ctx['ref_id']]).get(str(ctx['ref_id'])) or svc.serializar(None)
        return Response({'ok': True, **ctx, **atual, 'wa_url': svc.wa_me(ctx.get('telefone') or '')})

    def post(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        aba = str(request.data.get('aba') or '').strip().upper()
        ref = request.data.get('id')
        observacao = str(request.data.get('observacao') or '').strip()
        try:
            result = svc.marcar_tratado(aba, ref, usuario=request.user, observacao=observacao)
        except ValueError as exc:
            return Response({'ok': False, 'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)
