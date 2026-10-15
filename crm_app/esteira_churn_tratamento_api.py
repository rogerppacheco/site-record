"""API — Churn / cancelamentos na Esteira de Vendas (lista para tratamento + ranking)."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.churn_os_utils import anomes_filtro_variantes, build_venda_lookup_por_os, encontrar_venda_por_churn
from crm_app.models import ChurnConsultaDebitoNio, ImportacaoChurn, Venda
from crm_app.services.churn_debito_nio_service import normalizar_documento
from crm_app.utils import is_member

GRUPOS_CHURN_TRATAMENTO_ESTEIRA = ['Diretoria', 'BackOffice', 'Admin']
NAO_CONSULTADO = 'NAO_CONSULTADO'
SITUACOES_NIO_FILTRO = (
    ChurnConsultaDebitoNio.ADIMPLENTE,
    ChurnConsultaDebitoNio.INADIMPLENTE,
    ChurnConsultaDebitoNio.A_VENCER,
    NAO_CONSULTADO,
    ChurnConsultaDebitoNio.ERRO,
)


def _debito_display(debito: dict | None) -> dict | None:
    if not debito:
        return None
    return {
        'qtd_vencidas': debito['qtd_vencidas'],
        'valor_vencido': float(debito['valor_vencido'] or 0),
        'vencimento_mais_antigo': _fmt_data(debito['vencimento_mais_antigo']),
        'qtd_a_vencer': debito['qtd_a_vencer'],
        'valor_a_vencer': float(debito['valor_a_vencer'] or 0),
        'detalhe': debito['detalhe'],
        'consultado_em': debito['consultado_em'].isoformat() if debito['consultado_em'] else None,
    }


def _parse_mes_referencia(raw: str | None) -> tuple[date, date, str]:
    hoje = timezone.localdate()
    if not raw or not str(raw).strip():
        inicio = hoje.replace(day=1)
        fim = hoje
        mes_ref = inicio.strftime('%Y-%m')
    else:
        s = str(raw).strip()[:7]
        try:
            y, m = int(s[:4]), int(s[5:7])
            inicio = date(y, m, 1)
            fim = date(y, m, monthrange(y, m)[1])
            mes_ref = f'{y:04d}-{m:02d}'
        except (ValueError, TypeError):
            inicio = hoje.replace(day=1)
            fim = hoje
            mes_ref = inicio.strftime('%Y-%m')
    return inicio, fim, mes_ref


def _meses_churn(campo_mes: str) -> list[dict]:
    """Meses disponíveis na base churn, para o filtro da aba do Funil."""
    campo_data = 'dt_gross' if campo_mes == 'gross' else 'dt_retirada'
    linhas = (
        ImportacaoChurn.objects.exclude(**{f'{campo_data}__isnull': True})
        .annotate(mes=TruncMonth(campo_data))
        .values('mes')
        .annotate(total=Count('id'))
        .order_by('-mes')
    )
    return [
        {'mes': linha['mes'].strftime('%Y-%m'), 'total': linha['total']}
        for linha in linhas
        if linha['mes']
    ]


def _fmt_data(val) -> str | None:
    if val is None:
        return None
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    return str(val)


def _churn_display_fields(churn) -> dict:
    tp = churn.tipo_retirada or ''
    motivo = churn.motivo_retirada or ''
    cd_vdd = getattr(churn, 'cd_tr_vdd_original', None) or churn.matricula_vendedor or ''
    return {
        'TP_RETIRADA': tp,
        'DS_MOTIVO_RETIRADA': motivo,
        'cd_tr_vdd_original': cd_vdd,
        'ANOMES_GROSS': churn.anomes_gross or '',
        'tipo_retirada': tp,
        'motivo_retirada': motivo,
        'anomes_retirada': churn.anomes_retirada or '',
        'dt_retirada': _fmt_data(churn.dt_retirada),
        'dt_gross': _fmt_data(churn.dt_gross),
    }


class EsteiraChurnTratamentoView(APIView):
    """
    Lista vendas cruzadas com base churn + ranking de consultores.
    Filtros: mes_referencia, campo_mes (retirada|gross), vendedor_id, busca, tipo_retirada, motivo.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not is_member(request.user, GRUPOS_CHURN_TRATAMENTO_ESTEIRA):
            return Response(
                {'detail': 'Acesso restrito à gestão da esteira.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        User = get_user_model()
        raw_mes = (request.query_params.get('mes_referencia') or '').strip()
        todos_meses = raw_mes.lower() in ('todos', 'all')
        if todos_meses:
            inicio_mes, fim_mes, mes_ref = date(2000, 1, 1), timezone.localdate(), 'todos'
        else:
            inicio_mes, fim_mes, mes_ref = _parse_mes_referencia(raw_mes or None)
        campo_mes = (request.query_params.get('campo_mes') or 'retirada').strip().lower()
        if campo_mes not in ('retirada', 'gross'):
            campo_mes = 'retirada'

        anomes_alvo = inicio_mes.strftime('%Y%m')
        variantes_anomes = anomes_filtro_variantes(anomes_alvo)

        churn_qs = ImportacaoChurn.objects.all().order_by('-dt_retirada', '-id')
        if not todos_meses:
            if campo_mes == 'gross':
                churn_qs = churn_qs.filter(anomes_gross__in=variantes_anomes)
            else:
                churn_qs = churn_qs.filter(
                    Q(anomes_retirada__in=variantes_anomes)
                    | Q(dt_retirada__gte=inicio_mes, dt_retirada__lte=fim_mes)
                )

        anomes_gross_extra = (request.query_params.get('anomes_gross') or '').strip()
        if anomes_gross_extra:
            churn_qs = churn_qs.filter(anomes_gross__in=anomes_filtro_variantes(anomes_gross_extra.replace('-', '')[:6]))

        anomes_ret_extra = (request.query_params.get('anomes_retirada') or '').strip()
        if anomes_ret_extra:
            churn_qs = churn_qs.filter(anomes_retirada__in=anomes_filtro_variantes(anomes_ret_extra.replace('-', '')[:6]))

        tipo_f = (request.query_params.get('tipo_retirada') or request.query_params.get('TP_RETIRADA') or '').strip()
        if tipo_f:
            churn_qs = churn_qs.filter(tipo_retirada__icontains=tipo_f)

        motivo_f = (request.query_params.get('motivo_retirada') or request.query_params.get('DS_MOTIVO_RETIRADA') or '').strip()
        if motivo_f:
            churn_qs = churn_qs.filter(motivo_retirada__icontains=motivo_f)

        users = User.objects.exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])
        consultor_id = request.query_params.get('consultor_id') or request.query_params.get('vendedor_id')
        if consultor_id:
            try:
                users = users.filter(id=int(consultor_id))
            except (TypeError, ValueError):
                pass

        filtro_cluster = (request.query_params.get('cluster') or '').strip()
        if filtro_cluster:
            users = users.filter(cluster=filtro_cluster)

        user_ids = list(users.values_list('id', flat=True))

        vendas_qs = Venda.objects.filter(
            ativo=True,
            vendedor_id__in=user_ids,
        ).exclude(
            Q(ordem_servico__isnull=True) | Q(ordem_servico=''),
        ).select_related('vendedor', 'cliente', 'status_esteira')
        from crm_app.services.escopo_operadora import filtrar_vendas_por_operadora

        vendas_qs = filtrar_vendas_por_operadora(vendas_qs, request.user)

        lookup = build_venda_lookup_por_os(vendas_qs)

        busca = (request.query_params.get('busca') or '').strip().upper()
        somente_com_venda = request.query_params.get('somente_com_venda', '1').strip().lower() not in (
            '0', 'false', 'nao', 'não',
        )

        situacao_nio_f = (request.query_params.get('situacao_nio') or '').strip().upper()
        debitos = {
            d['cpf']: d
            for d in ChurnConsultaDebitoNio.objects.values(
                'cpf', 'situacao', 'qtd_vencidas', 'valor_vencido', 'vencimento_mais_antigo',
                'qtd_a_vencer', 'valor_a_vencer', 'detalhe', 'consultado_em',
            )
        }
        contagens_nio = {s: 0 for s in SITUACOES_NIO_FILTRO}

        linhas = []
        ranking_map: dict[int, dict] = {}

        for churn in churn_qs.iterator(chunk_size=2000):
            venda = encontrar_venda_por_churn(churn, lookup)
            if somente_com_venda and not venda:
                continue
            if venda and venda.vendedor_id and venda.vendedor_id not in user_ids:
                continue

            pedido = (venda.ordem_servico if venda else None) or churn.numero_pedido or churn.nr_ordem or ''
            cpf = ''
            nome_cliente = ''
            vendedor_nome = ''
            vendedor_id = None
            data_inst = None
            status_esteira = ''
            venda_id = None

            if venda:
                venda_id = venda.id
                data_inst = venda.data_instalacao_fisica or venda.data_instalacao
                if venda.cliente:
                    cpf = venda.cliente.cpf_cnpj or ''
                    nome_cliente = venda.cliente.nome_razao_social or ''
                if venda.vendedor:
                    vendedor_id = venda.vendedor_id
                    vendedor_nome = (venda.vendedor.username or '').upper()
                if venda.status_esteira:
                    status_esteira = venda.status_esteira.nome or ''

            if busca:
                blob = ' '.join([
                    str(venda_id or ''),
                    pedido,
                    cpf,
                    nome_cliente,
                    vendedor_nome,
                    churn.motivo_retirada or '',
                    churn.tipo_retirada or '',
                ]).upper()
                if busca not in blob:
                    continue

            debito = debitos.get(normalizar_documento(cpf)) if cpf else None
            situacao_nio = debito['situacao'] if debito else NAO_CONSULTADO
            contagens_nio[situacao_nio] = contagens_nio.get(situacao_nio, 0) + 1
            if situacao_nio_f and situacao_nio != situacao_nio_f:
                continue

            churn_fields = _churn_display_fields(churn)
            linhas.append({
                'venda_id': venda_id,
                'data_instalacao': _fmt_data(data_inst),
                'pedido': pedido,
                'cpf_cliente': cpf,
                'nome_cliente': nome_cliente,
                'vendedor_id': vendedor_id,
                'vendedor': vendedor_nome or '—',
                'status_esteira': status_esteira,
                'churn_id': churn.id,
                'sem_venda_crm': venda is None,
                'situacao_nio': situacao_nio,
                'debito_nio': _debito_display(debito),
                **churn_fields,
            })

            rk_key = vendedor_id if vendedor_id is not None else -1
            rk_label = vendedor_nome or (churn_fields['cd_tr_vdd_original'] or 'Sem vendedor CRM')
            if rk_key not in ranking_map:
                ranking_map[rk_key] = {
                    'vendedor_id': vendedor_id,
                    'vendedor': rk_label,
                    'cd_tr_vdd_original': churn_fields['cd_tr_vdd_original'],
                    'total_churn': 0,
                }
            ranking_map[rk_key]['total_churn'] += 1

        linhas.sort(key=lambda x: (x.get('vendedor') or '', x.get('pedido') or ''))

        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(500, max(10, int(request.query_params.get('page_size', 50))))
        except (TypeError, ValueError):
            page_size = 50

        total = len(linhas)
        start = (page - 1) * page_size
        lista_pagina = linhas[start:start + page_size]

        # Elegibilidade de template (página atual) — telefone/endereço vêm da venda CRM.
        from crm_app.services.funil_template_envio_service import enriquecer_linha_churn
        venda_ids = [x['venda_id'] for x in lista_pagina if x.get('venda_id')]
        vendas_map = {
            v.pk: v
            for v in Venda.objects.filter(pk__in=venda_ids).select_related('cliente')
        } if venda_ids else {}
        lista_pagina = [
            enriquecer_linha_churn(item, venda=vendas_map.get(item.get('venda_id')))
            for item in lista_pagina
        ]

        ranking = sorted(ranking_map.values(), key=lambda x: (-x['total_churn'], x['vendedor']))
        pos = 1
        for r in ranking:
            r['posicao'] = pos
            pos += 1

        consultores_opts = [
            {'id': u.id, 'username': (u.username or '').upper(), 'cluster': u.cluster or ''}
            for u in users.order_by('username')
        ]

        tipos_opts = list(
            churn_qs.exclude(tipo_retirada__isnull=True)
            .exclude(tipo_retirada='')
            .values_list('tipo_retirada', flat=True)
            .distinct()[:80]
        )

        return Response({
            'periodo': {
                'mes_referencia': mes_ref,
                'inicio': inicio_mes.isoformat(),
                'fim': fim_mes.isoformat(),
                'campo_mes': campo_mes,
            },
            'filtros': {
                'consultor_id': consultor_id,
                'busca': busca,
                'tipo_retirada': tipo_f,
                'motivo_retirada': motivo_f,
                'somente_com_venda': somente_com_venda,
            },
            'totais': {
                'churn_base': churn_qs.count(),
                'linhas_lista': total,
                'consultores_ranking': len(ranking),
            },
            'contagens_nio': contagens_nio,
            'lista': lista_pagina,
            'paginacao': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': (total + page_size - 1) // page_size if page_size else 0,
            },
            'ranking': ranking,
            'opcoes': {
                'consultores': consultores_opts,
                'tipos_retirada': sorted({t for t in tipos_opts if t}),
            },
            'meses': _meses_churn(campo_mes),
            'notas': {
                'cruzamento': (
                    'Cruzamento pelo número do pedido/O.S. (variantes com e sem zeros). '
                    'Colunas TP_RETIRADA e DS_MOTIVO_RETIRADA vêm da base ImportacaoChurn.'
                ),
            },
        })


class ChurnDebitoNioLoteView(APIView):
    """GET: lote em andamento ou o último. POST: inicia consulta de débitos Nio (body: forcar)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from crm_app.models import ChurnConsultaDebitoLote
        from crm_app.services.churn_debito_nio_service import lote_em_andamento, serializar_lote

        if not is_member(request.user, GRUPOS_CHURN_TRATAMENTO_ESTEIRA):
            return Response({'detail': 'Acesso restrito à gestão.'}, status=status.HTTP_403_FORBIDDEN)
        lote = lote_em_andamento() or ChurnConsultaDebitoLote.objects.select_related('iniciado_por').first()
        return Response({'lote': serializar_lote(lote)})

    def post(self, request):
        from crm_app.services.churn_debito_nio_service import iniciar_lote, serializar_lote

        if not is_member(request.user, GRUPOS_CHURN_TRATAMENTO_ESTEIRA):
            return Response({'detail': 'Acesso restrito à gestão.'}, status=status.HTTP_403_FORBIDDEN)
        forcar = str(request.data.get('forcar', '')).strip().lower() in ('1', 'true', 'sim', 'yes')
        lote, criado = iniciar_lote(request.user, forcar=forcar)
        return Response(
            {'lote': serializar_lote(lote), 'criado': criado},
            status=status.HTTP_201_CREATED if criado else status.HTTP_200_OK,
        )


class ChurnDebitoNioLoteCancelarView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        from crm_app.models import ChurnConsultaDebitoLote as L
        from crm_app.services.churn_debito_nio_service import serializar_lote

        if not is_member(request.user, GRUPOS_CHURN_TRATAMENTO_ESTEIRA):
            return Response({'detail': 'Acesso restrito à gestão.'}, status=status.HTTP_403_FORBIDDEN)
        L.objects.filter(pk=pk, status=L.STATUS_EM_ANDAMENTO).update(
            status=L.STATUS_CANCELADO, atualizado_em=timezone.now(), mensagem='Cancelando…',
        )
        return Response({'lote': serializar_lote(L.objects.filter(pk=pk).first())})
