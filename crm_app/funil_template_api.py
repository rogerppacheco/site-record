"""API — envio de templates Meta no Funil (WhatsAtende #247)."""
from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.services import funil_template_envio_service as svc
from crm_app.utils import is_member

GRUPOS = ['Diretoria', 'BackOffice', 'Admin']


def _sem_permissao(request) -> Response | None:
    if is_member(request.user, GRUPOS):
        return None
    return Response({'detail': 'Sem permissão para envio de templates do Funil.'}, status=status.HTTP_403_FORBIDDEN)


class FunilTemplateEnviarView(APIView):
    """POST { aba, id, force? } — envia template da linha."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        aba = str(request.data.get('aba') or '').strip().upper()
        ref = request.data.get('id')
        force = bool(request.data.get('force'))
        if not aba or ref in (None, ''):
            return Response({'detail': 'Informe aba e id.'}, status=status.HTTP_400_BAD_REQUEST)

        if aba == svc.ABA_BIO:
            result = svc.enviar_bio_por_cpf(str(ref), usuario=request.user, force=force)
        elif aba == svc.ABA_CHURN:
            try:
                result = svc.enviar_churn_por_id(int(ref), usuario=request.user, force=force)
            except (TypeError, ValueError):
                return Response({'detail': 'id do churn inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        elif aba == svc.ABA_INTERESSE:
            try:
                result = svc.enviar_interesse_por_pedido_id(int(ref), usuario=request.user, force=force)
            except (TypeError, ValueError):
                return Response({'detail': 'id do pedido inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'detail': f'Aba não suportada: {aba}'}, status=status.HTTP_400_BAD_REQUEST)

        code = status.HTTP_200_OK if result.get('ok') else status.HTTP_400_BAD_REQUEST
        return Response(result, status=code)


class FunilTemplatePreflightView(APIView):
    """POST { aba, id } — valida elegibilidade sem enviar (Bio sem Assertiva)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        aba = str(request.data.get('aba') or '').strip().upper()
        ref = request.data.get('id')
        if not aba or ref in (None, ''):
            return Response({'detail': 'Informe aba e id.'}, status=status.HTTP_400_BAD_REQUEST)

        if aba == svc.ABA_BIO:
            from datetime import timedelta
            from django.utils import timezone
            from crm_app.services import repescagem_bio_service as bio
            hoje = timezone.localdate()
            base = bio.montar_base(hoje - timedelta(days=30), hoje)
            digitos = ''.join(c for c in str(ref) if c.isdigit())
            linha = next((b for b in base if b.get('cpf') == digitos), None)
            if not linha:
                return Response({'ok': False, 'detail': 'CPF não encontrado na Bio.', 'contexto': None})
            ctx = svc.preflight_bio_linha(linha)
            # Se elegível exceto nome, sinaliza que Assertiva será chamada no envio
            if not ctx['elegivel'] and 'Sem nome' in (ctx.get('motivo_inelegivel') or ''):
                ctx['assertiva_no_envio'] = True
            return Response({'ok': ctx['elegivel'], 'contexto': ctx, 'detail': ctx.get('motivo_inelegivel') or 'Elegível.'})

        if aba == svc.ABA_CHURN:
            try:
                from crm_app.models import ImportacaoChurn, Venda
                from crm_app.churn_os_utils import build_venda_lookup_por_os, encontrar_venda_por_churn
                churn = ImportacaoChurn.objects.get(pk=int(ref))
                lookup = build_venda_lookup_por_os(Venda.objects.filter(ativo=True).select_related('cliente'))
                venda = encontrar_venda_por_churn(churn, lookup)
                pedido = (venda.ordem_servico if venda else None) or churn.numero_pedido or churn.nr_ordem or ''
                situacao = 'NAO_CONSULTADO'
                from crm_app.models import ChurnConsultaDebitoNio
                cpf_v = (venda.cliente.cpf_cnpj if venda and venda.cliente_id else '') or ''
                digitos = ''.join(c for c in cpf_v if c.isdigit())
                if digitos:
                    deb = ChurnConsultaDebitoNio.objects.filter(cpf__icontains=digitos[-11:]).order_by('-consultado_em').first()
                    if deb:
                        situacao = deb.situacao
                linha = {
                    'churn_id': churn.pk,
                    'venda_id': venda.pk if venda else None,
                    'pedido': pedido,
                    'cpf_cliente': cpf_v,
                    'nome_cliente': (venda.cliente.nome_razao_social if venda and venda.cliente_id else ''),
                    'situacao_nio': situacao,
                    'sem_venda_crm': venda is None,
                }
                ctx = svc.montar_contexto_churn(linha, venda=venda)
                return Response({'ok': ctx['elegivel'], 'contexto': ctx, 'detail': ctx.get('motivo_inelegivel') or 'Elegível.'})
            except Exception as exc:
                return Response({'ok': False, 'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if aba == svc.ABA_INTERESSE:
            try:
                from crm_app.models import HistoricoPapPedido
                from crm_app.historico_pap import map_pedido_api
                p = HistoricoPapPedido.objects.get(pk=int(ref))
                mapped = map_pedido_api(p.payload or {}, p.tipo_venda)
                mapped['tipo_venda'] = p.tipo_venda or mapped.get('tipo_venda')
                ctx = svc.montar_contexto_interesse(mapped, pedido_id=p.pk)
                return Response({'ok': ctx['elegivel'], 'contexto': ctx, 'detail': ctx.get('motivo_inelegivel') or 'Elegível.'})
            except Exception as exc:
                return Response({'ok': False, 'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'detail': f'Aba não suportada: {aba}'}, status=status.HTTP_400_BAD_REQUEST)
