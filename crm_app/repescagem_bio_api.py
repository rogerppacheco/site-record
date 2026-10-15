"""API — Repescagem Bio (aba do Funil): base de biometria do GED360 cruzada com as vendas do CRM."""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import RepescagemBioImportacao
from crm_app.services import repescagem_bio_service as svc
from crm_app.utils import is_member

GRUPOS_REPESCAGEM_BIO = ['Diretoria', 'BackOffice', 'Admin']
DIAS_PADRAO = 7


def _parse_data(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor or '').strip()[:10])
    except ValueError:
        return None


def _periodo(params) -> tuple[date, date] | str:
    hoje = timezone.localdate()
    fim = _parse_data(params.get('ate')) or hoje
    inicio = _parse_data(params.get('de')) or (fim - timedelta(days=DIAS_PADRAO - 1))
    if inicio > fim:
        return 'A data inicial é maior que a final.'
    if (fim - inicio).days + 1 > svc.MAX_DIAS_PERIODO:
        return f'Período máximo de {svc.MAX_DIAS_PERIODO} dias.'
    return inicio, fim


def _sem_permissao(request) -> Response | None:
    if is_member(request.user, GRUPOS_REPESCAGEM_BIO):
        return None
    return Response({'detail': 'Sem permissão para a Repescagem Bio.'}, status=status.HTTP_403_FORBIDDEN)


class RepescagemBioListaView(APIView):
    """GET ?de=&ate=&situacao=&busca=&page=&page_size= — uma linha por CPF."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        periodo = _periodo(request.query_params)
        if isinstance(periodo, str):
            return Response({'detail': periodo}, status=status.HTTP_400_BAD_REQUEST)
        inicio, fim = periodo

        base = svc.montar_base(inicio, fim)
        contagens = {s: 0 for s in svc.SITUACOES}
        contagens['APTO_SEM_VENDA'] = 0
        for linha in base:
            contagens[linha['situacao']] += 1
            if linha['situacao'] == svc.APTO and not linha['venda_id']:
                contagens['APTO_SEM_VENDA'] += 1

        situacao = (request.query_params.get('situacao') or '').strip().upper()
        if situacao == 'REPESCAR':
            base = [b for b in base if b['situacao'] in svc.SITUACOES_REPESCAR]
        elif situacao == 'APTO_SEM_VENDA':
            base = [b for b in base if b['situacao'] == svc.APTO and not b['venda_id']]
        elif situacao in svc.SITUACOES:
            base = [b for b in base if b['situacao'] == situacao]

        busca = (request.query_params.get('busca') or '').strip().lower()
        if busca:
            digitos = svc.normalizar_documento(busca)
            base = [
                b for b in base
                if busca in (b['nome_cliente'] or '').lower()
                or busca in (b['vendedor'] or '').lower()
                or (digitos and (digitos in b['cpf'] or digitos in (b['ordem_servico'] or '')
                                 or digitos in (b['protocolo'] or '') or digitos in (b['telefone'] or '')))
            ]

        try:
            page_size = min(max(int(request.query_params.get('page_size') or 25), 1), 200)
        except ValueError:
            page_size = 25
        total = len(base)
        total_pages = max(1, -(-total // page_size))
        try:
            page = min(max(int(request.query_params.get('page') or 1), 1), total_pages)
        except ValueError:
            page = 1
        lista = base[(page - 1) * page_size: page * page_size]

        ultima = RepescagemBioImportacao.objects.filter(status=RepescagemBioImportacao.STATUS_CONCLUIDO).first()
        inicio_dt = svc._inicio_do_dia(inicio)
        buscado_ate = next((b for a, b in svc.cobertura_ged() if a <= inicio_dt < b), None)
        return Response({
            'periodo': {'de': inicio.isoformat(), 'ate': fim.isoformat()},
            'ged_buscado_ate': buscado_ate.isoformat() if buscado_ate else None,
            'contagens': contagens,
            'lista': lista,
            'paginacao': {'page': page, 'page_size': page_size, 'total': total, 'total_pages': total_pages},
            'ultima_importacao': svc.serializar_importacao(ultima),
        })


class RepescagemBioImportacaoView(APIView):
    """GET: importação em andamento ou a última. POST {data_inicial, data_final}: busca no GED360."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        importacao = svc.importacao_em_andamento() or RepescagemBioImportacao.objects.first()
        return Response({'importacao': svc.serializar_importacao(importacao)})

    def post(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        periodo = _periodo({'de': request.data.get('data_inicial'), 'ate': request.data.get('data_final')})
        if isinstance(periodo, str):
            return Response({'detail': periodo}, status=status.HTTP_400_BAD_REQUEST)
        inicio, fim = periodo
        if fim > timezone.localdate():
            return Response({'detail': 'A data final não pode ser futura.'}, status=status.HTTP_400_BAD_REQUEST)
        importacao, criada = svc.iniciar_importacao(request.user, inicio, fim)
        return Response(
            {'importacao': svc.serializar_importacao(importacao), 'criada': criada},
            status=status.HTTP_201_CREATED if criada else status.HTTP_200_OK,
        )
