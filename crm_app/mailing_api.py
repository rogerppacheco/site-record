"""API — Mailings de mercado (import XLS → disparo Meta → respostas no Funil)."""
from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import MailingContato, MailingEnvio, MailingLote
from crm_app.services import mailing_dispatch_service as dispatch
from crm_app.services import mailing_import_service as import_svc
from crm_app.services.funil_tratamento_service import wa_me
from crm_app.perfis_acesso import pode_acessar_recurso_funil

GRUPOS_MAILING = ['Diretoria', 'BackOffice', 'Admin']


def _sem_permissao(request) -> Response | None:
    if pode_acessar_recurso_funil(request.user, GRUPOS_MAILING):
        return None
    return Response({'detail': 'Sem permissão para Mailings.'}, status=status.HTTP_403_FORBIDDEN)


def _serialize_lote(lote: MailingLote) -> dict:
    return {
        'id': lote.pk,
        'nome': lote.nome,
        'tipo_layout': lote.tipo_layout,
        'arquivo_nome': lote.arquivo_nome,
        'status': lote.status,
        'total_linhas': lote.total_linhas,
        'total_contatos': lote.total_contatos,
        'total_validos': lote.total_validos,
        'total_enviados': lote.total_enviados,
        'total_falhas': lote.total_falhas,
        'total_respostas': lote.total_respostas,
        'contagens_situacao': lote.contagens_situacao or {},
        'mensagem': lote.mensagem,
        'criado_em': lote.criado_em.isoformat() if lote.criado_em else None,
        'disparo_iniciado_em': lote.disparo_iniciado_em.isoformat() if lote.disparo_iniciado_em else None,
        'disparo_finalizado_em': lote.disparo_finalizado_em.isoformat() if lote.disparo_finalizado_em else None,
        'filtro_situacao': lote.filtro_situacao or '',
    }


def _ultimo_envio(c: MailingContato) -> dict:
    envios = list(c.envios.all()[:1]) if hasattr(c, 'envios') else []
    if not envios:
        return {}
    e = envios[0]
    return {
        'ultimo_envio_id': e.pk,
        'ultimo_template': e.template_nome,
        'ultimo_message_id': e.message_id,
        'ultimo_status_entrega': e.status_entrega,
        'ultimo_sucesso': e.sucesso,
        'ultimo_erro': (e.erro or '')[:300],
        'ultimo_enviado_em': e.enviado_em.isoformat() if e.enviado_em else None,
    }


def _serialize_contato(c: MailingContato) -> dict:
    return {
        'id': c.pk,
        'lote_id': c.lote_id,
        'lote_nome': c.lote.nome if c.lote_id else '',
        'nome': c.nome,
        'cpf': c.cpf,
        'telefone': c.telefone_e164,
        'wa_url': wa_me(c.telefone_e164),
        'cidade': c.cidade,
        'uf': c.uf,
        'endereco': c.endereco,
        'bairro': c.bairro,
        'situacao': c.situacao,
        'situacao_origem': c.situacao_origem,
        'produto': c.produto,
        'status': c.status,
        'opt_out': c.opt_out,
        'resposta_texto': c.resposta_texto,
        'respondido_em': c.respondido_em.isoformat() if c.respondido_em else None,
        'tratado_em': c.tratado_em.isoformat() if c.tratado_em else None,
        'tratado_por': (c.tratado_por.username if getattr(c, 'tratado_por_id', None) else '') or '',
        'data_carga': c.criado_em.isoformat() if c.criado_em else None,
        **_ultimo_envio(c),
    }


class MailingLoteListCreateView(APIView):
    """GET lista lotes | POST multipart upload XLS."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        qs = MailingLote.objects.all()[:50]
        return Response({'lista': [_serialize_lote(l) for l in qs]})

    def post(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        arquivo = request.FILES.get('arquivo') or request.FILES.get('file')
        if not arquivo:
            return Response({'detail': 'Envie o arquivo XLS no campo arquivo.'}, status=status.HTTP_400_BAD_REQUEST)
        nome = (request.data.get('nome') or arquivo.name or '').strip()
        try:
            conteudo = arquivo.read()
            lote = import_svc.importar_arquivo(
                conteudo,
                nome_lote=nome,
                arquivo_nome=arquivo.name,
                usuario=request.user,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'detail': f'Falha ao importar: {exc}'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize_lote(lote), status=status.HTTP_201_CREATED)


class MailingLoteDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        negado = _sem_permissao(request)
        if negado:
            return negado
        try:
            lote = MailingLote.objects.get(pk=pk)
        except MailingLote.DoesNotExist:
            return Response({'detail': 'Lote não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_lote(lote))


class MailingLoteDisparoView(APIView):
    """POST inicia | DELETE pausa."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        negado = _sem_permissao(request)
        if negado:
            return negado
        situacao = str(request.data.get('situacao') or '').strip().upper()
        incluir_falhas = str(request.data.get('incluir_falhas') or '').lower() in ('1', 'true', 'sim')
        try:
            lote = dispatch.iniciar_disparo(
                pk, usuario=request.user, situacao=situacao, incluir_falhas=incluir_falhas,
            )
        except MailingLote.DoesNotExist:
            return Response({'detail': 'Lote não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        stats = dispatch.processar_ciclo(pk, limite=15, sleep=False)
        lote.refresh_from_db()
        return Response({
            'lote': _serialize_lote(lote),
            'ciclo': stats,
            'elegiveis': dispatch.contar_elegiveis(pk, situacao),
        })

    def delete(self, request, pk):
        negado = _sem_permissao(request)
        if negado:
            return negado
        try:
            lote = dispatch.pausar_disparo(pk)
        except MailingLote.DoesNotExist:
            return Response({'detail': 'Lote não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_lote(lote))


class MailingFunilListaView(APIView):
    """GET contatos para a aba MAILING do Funil (respostas / pendentes)."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        status_filtro = (request.query_params.get('status') or 'NOVO').strip().upper()
        busca = (request.query_params.get('q') or request.query_params.get('busca') or '').strip()
        situacao = (request.query_params.get('situacao') or '').strip().upper()
        lote_id = (request.query_params.get('lote_id') or '').strip()
        page = max(1, int(request.query_params.get('page') or 1))
        page_size = min(100, max(10, int(request.query_params.get('page_size') or 25)))

        from django.db.models import Count, Prefetch

        qs = MailingContato.objects.select_related('lote', 'tratado_por').prefetch_related(
            Prefetch('envios', queryset=MailingEnvio.objects.order_by('-enviado_em'))
        )
        if lote_id.isdigit():
            qs = qs.filter(lote_id=int(lote_id))
        if status_filtro == 'PENDENTES':
            qs = qs.filter(status=MailingContato.STATUS_RESPONDEU)
        elif status_filtro == 'FILA':
            qs = qs.filter(status=MailingContato.STATUS_NOVO, telefone_valido=True, opt_out=False)
        elif status_filtro == 'TODOS':
            pass
        elif status_filtro == 'TODOS_FUNIL':
            qs = qs.filter(status__in=[
                MailingContato.STATUS_RESPONDEU,
                MailingContato.STATUS_TRATADO,
                MailingContato.STATUS_ENVIADO,
                MailingContato.STATUS_NOVO,
            ])
        elif status_filtro:
            qs = qs.filter(status=status_filtro)

        if situacao:
            qs = qs.filter(situacao=situacao)
        if busca:
            digitos = import_svc.normalizar_documento(busca)
            from django.db.models import Q
            filt = Q(nome__icontains=busca) | Q(cidade__icontains=busca) | Q(telefone_e164__icontains=busca) | Q(bairro__icontains=busca)
            if digitos:
                filt |= Q(cpf__icontains=digitos) | Q(telefone_e164__icontains=digitos)
            qs = qs.filter(filt)

        cpf_filtro = ''.join(c for c in str(request.query_params.get('cpf') or '') if c.isdigit())
        if len(cpf_filtro) >= 3:
            qs = qs.filter(cpf__icontains=cpf_filtro)

        qs = qs.order_by('-respondido_em', '-id')
        total = qs.count()
        inicio = (page - 1) * page_size
        lista = [_serialize_contato(c) for c in qs[inicio:inicio + page_size]]

        base_cont = MailingContato.objects.all()
        if lote_id.isdigit():
            base_cont = base_cont.filter(lote_id=int(lote_id))
        contagens = {
            'NOVO': base_cont.filter(status=MailingContato.STATUS_NOVO, telefone_valido=True, opt_out=False).count(),
            'RESPONDEU': base_cont.filter(status=MailingContato.STATUS_RESPONDEU).count(),
            'TRATADO': base_cont.filter(status=MailingContato.STATUS_TRATADO).count(),
            'ENVIADO': base_cont.filter(status=MailingContato.STATUS_ENVIADO).count(),
            'FALHOU': base_cont.filter(status=MailingContato.STATUS_FALHOU).count(),
            'TOTAL': base_cont.count(),
        }
        sits = {
            row['situacao']: row['n']
            for row in base_cont.values('situacao').annotate(n=Count('id'))
        }
        sits_fila = {
            row['situacao']: row['n']
            for row in base_cont.filter(
                status=MailingContato.STATUS_NOVO, telefone_valido=True, opt_out=False,
            ).exclude(telefone_e164='').values('situacao').annotate(n=Count('id'))
        }
        lote_pk = int(lote_id) if lote_id.isdigit() else None
        return Response({
            'lista': lista,
            'paginacao': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': max(1, (total + page_size - 1) // page_size),
            },
            'contagens': contagens,
            'contagens_situacao': sits,
            'elegiveis_situacao': sits_fila,
            'elegiveis': dispatch.contar_elegiveis(lote_pk, situacao),
            'lotes': [_serialize_lote(l) for l in MailingLote.objects.all()[:20]],
        })


class MailingContatoTratarView(APIView):
    """POST marca contato como TRATADO."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        negado = _sem_permissao(request)
        if negado:
            return negado
        from crm_app.services import funil_tratamento_service as trat
        try:
            result = trat.marcar_tratado('MAILING', pk, usuario=request.user, observacao=str(request.data.get('observacao') or ''))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_404_NOT_FOUND)
        c = MailingContato.objects.select_related('lote', 'tratado_por').prefetch_related('envios').get(pk=pk)
        return Response({**_serialize_contato(c), **result})


class MailingDisparoElegiveisView(APIView):
    """POST dispara todos os lotes com fila (opcionalmente uma situação)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        negado = _sem_permissao(request)
        if negado:
            return negado
        situacao = str(request.data.get('situacao') or '').strip().upper()
        incluir_falhas = str(request.data.get('incluir_falhas') or '').lower() in ('1', 'true', 'sim')
        lote_id = request.data.get('lote_id')
        qs = MailingLote.objects.all()
        if lote_id not in (None, ''):
            qs = qs.filter(pk=int(lote_id))
        iniciados = []
        ciclos = []
        for lote in qs:
            stats_pre = dispatch.contar_elegiveis(lote.pk, situacao)
            if stats_pre['elegiveis'] <= 0 and not (incluir_falhas and stats_pre.get('falhas')):
                continue
            dispatch.iniciar_disparo(
                lote.pk, usuario=request.user, situacao=situacao, incluir_falhas=incluir_falhas,
            )
            stats = dispatch.processar_ciclo(lote.pk, limite=15, sleep=False)
            lote.refresh_from_db()
            iniciados.append(_serialize_lote(lote))
            ciclos.append({'lote_id': lote.pk, **stats})
        if not iniciados:
            return Response({'detail': 'Nenhum contato elegível para envio.', 'lotes': [], 'ciclos': []}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'lotes': iniciados,
            'ciclos': ciclos,
            'elegiveis': dispatch.contar_elegiveis(int(lote_id) if str(lote_id or '').isdigit() else None, situacao),
        })
