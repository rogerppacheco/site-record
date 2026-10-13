# crm_app/osab_busca_api.py
"""Busca de pedidos na base OSAB importada (colunas PEDIDO e NR_ORDEM_ORIGINAL)."""
from __future__ import annotations

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.utils import is_member

LIMITE_RESULTADOS = 50


def _fmt_data(valor) -> str:
    if not valor:
        return ""
    if hasattr(valor, "hour"):
        from django.utils import timezone

        if timezone.is_aware(valor):
            valor = timezone.localtime(valor)
        return valor.strftime("%d/%m/%Y %H:%M")
    return valor.strftime("%d/%m/%Y")


class BuscarPedidoOsabView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, ["Diretoria", "Admin", "BackOffice"]):
            return Response({"detail": "Sem permissão."}, status=403)

        from crm_app.models import ImportacaoOsab

        termo = (request.query_params.get("q") or "").strip()
        if len(termo) < 4:
            return Response({"error": "Digite pelo menos 4 caracteres do pedido."}, status=400)

        qs = (
            ImportacaoOsab.objects.filter(
                Q(documento__icontains=termo) | Q(nr_ordem_original__icontains=termo)
            )
            .order_by("-dt_ref", "-id")
        )
        total = qs.count()
        resultados = [
            {
                "id": o.id,
                "pedido": o.documento or "",
                "nr_ordem_original": o.nr_ordem_original or "",
                "situacao": o.situacao or "",
                "dt_ref": _fmt_data(o.dt_ref),
                "data_abertura": _fmt_data(o.data_abertura),
                "data_agendamento": _fmt_data(o.data_agendamento),
                "data_fechamento": _fmt_data(o.data_fechamento),
                "desc_pendencia": o.desc_pendencia or "",
                "localidade": o.localidade or "",
                "uf": o.uf or "",
                "velocidade": o.velocidade or "",
                "matricula_vendedor": o.matricula_vendedor or "",
                "numero_ba": o.numero_ba or "",
                "meio_pagamento": o.meio_pagamento or "",
            }
            for o in qs[:LIMITE_RESULTADOS]
        ]
        return Response({"total": total, "limite": LIMITE_RESULTADOS, "resultados": resultados})
