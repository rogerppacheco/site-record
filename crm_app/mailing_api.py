"""API — Mailings de mercado (import XLS → disparo Meta → respostas no Funil)."""
from __future__ import annotations

from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.models import MailingContato, MailingLote
from crm_app.services import mailing_dispatch_service as dispatch
from crm_app.services import mailing_import_service as import_svc
from crm_app.utils import is_member

GRUPOS_MAILING = ['Diretoria', 'BackOffice', 'Admin']


def _sem_permissao(request) -> Response | None:
    if is_member(request.user, GRUPOS_MAILING):
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
    }


def _serialize_contato(c: MailingContato) -> dict:
    return {
        'id': c.pk,
        'lote_id': c.lote_id,
        'lote_nome': c.lote.nome if c.lote_id else '',
        'nome': c.nome,
        'cpf': c.cpf,
        'telefone': c.telefone_e164,
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
        try:
            lote = dispatch.iniciar_disparo(pk, usuario=request.user)
        except MailingLote.DoesNotExist:
            return Response({'detail': 'Lote não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        # processa um ciclo imediato (resto no scheduler)
        stats = dispatch.processar_ciclo(pk, limite=15, sleep=True)
        lote.refresh_from_db()
        return Response({'lote': _serialize_lote(lote), 'ciclo': stats})

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
        status_filtro = (request.query_params.get('status') or 'RESPONDEU').strip().upper()
        busca = (request.query_params.get('q') or request.query_params.get('busca') or '').strip()
        situacao = (request.query_params.get('situacao') or '').strip().upper()
        page = max(1, int(request.query_params.get('page') or 1))
        page_size = min(100, max(10, int(request.query_params.get('page_size') or 25)))

        qs = MailingContato.objects.select_related('lote').all()
        if status_filtro == 'PENDENTES':
            qs = qs.filter(status=MailingContato.STATUS_RESPONDEU)
        elif status_filtro == 'TODOS_FUNIL':
            qs = qs.filter(status__in=[
                MailingContato.STATUS_RESPONDEU,
                MailingContato.STATUS_TRATADO,
                MailingContato.STATUS_ENVIADO,
            ])
        elif status_filtro:
            qs = qs.filter(status=status_filtro)

        if situacao:
            qs = qs.filter(situacao=situacao)
        if busca:
            digitos = import_svc.normalizar_documento(busca)
            from django.db.models import Q
            filt = Q(nome__icontains=busca) | Q(cidade__icontains=busca) | Q(telefone_e164__icontains=busca)
            if digitos:
                filt |= Q(cpf__icontains=digitos) | Q(telefone_e164__icontains=digitos)
            qs = qs.filter(filt)

        qs = qs.order_by('-respondido_em', '-id')
        total = qs.count()
        inicio = (page - 1) * page_size
        lista = [_serialize_contato(c) for c in qs[inicio:inicio + page_size]]

        contagens = {
            'RESPONDEU': MailingContato.objects.filter(status=MailingContato.STATUS_RESPONDEU).count(),
            'TRATADO': MailingContato.objects.filter(status=MailingContato.STATUS_TRATADO).count(),
            'ENVIADO': MailingContato.objects.filter(status=MailingContato.STATUS_ENVIADO).count(),
        }
        return Response({
            'lista': lista,
            'paginacao': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': max(1, (total + page_size - 1) // page_size),
            },
            'contagens': contagens,
        })


class MailingContatoTratarView(APIView):
    """POST marca contato como TRATADO."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        negado = _sem_permissao(request)
        if negado:
            return negado
        try:
            c = MailingContato.objects.select_related('lote').get(pk=pk)
        except MailingContato.DoesNotExist:
            return Response({'detail': 'Contato não encontrado.'}, status=status.HTTP_404_NOT_FOUND)
        c.status = MailingContato.STATUS_TRATADO
        c.tratado_em = timezone.now()
        c.tratado_por = request.user
        c.save(update_fields=['status', 'tratado_em', 'tratado_por'])
        return Response(_serialize_contato(c))
