"""APIs do módulo Qualidade (lentes vencimento/instalação, sync, cobrança)."""
from __future__ import annotations

import logging

from typing import Optional

from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from crm_app.services import qualidade_service as qs
from crm_app.utils import is_member

logger = logging.getLogger(__name__)


def _exige_acesso(user) -> Optional[Response]:
    if not qs.pode_acessar_qualidade(user):
        return Response({'error': 'Sem permissão para o módulo Qualidade'}, status=403)
    return None


class PageQualidadeMixin:
    """Helper para checagem de grupo nas pages HTML (JWT no front; reforço no back nas APIs)."""


class QualidadePeriodosView(APIView):
    """GET /api/qualidade/periodos/?lente=vencimento|instalacao"""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        lente = request.GET.get('lente', qs.LENTE_VENCIMENTO)
        try:
            data = qs.listar_periodos(lente)
            return Response({'lente': lente, 'periodos': data})
        except Exception as e:
            logger.exception('Erro ao listar períodos Qualidade')
            return Response({'error': str(e)}, status=500)


class QualidadeDashboardView(APIView):
    """GET /api/qualidade/dashboard/?lente=&mes=YYYY-MM&q=&status=&elegivel=&page="""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        lente = request.GET.get('lente', qs.LENTE_VENCIMENTO)
        mes = request.GET.get('mes')
        if not mes:
            return Response({'error': 'Parâmetro mes é obrigatório (YYYY-MM)'}, status=400)
        filtros = {
            'q': request.GET.get('q'),
            'status': request.GET.get('status'),
            'elegivel': request.GET.get('elegivel'),
            'vendedor': request.GET.get('vendedor'),
            'page': request.GET.get('page', 1),
            'page_size': request.GET.get('page_size', 100),
            'orfao': request.GET.get('orfao'),
            'status_fatura1': request.GET.get('status_fatura1'),
            'fila': request.GET.get('fila', 'todos'),
            'status_tratamento_id': request.GET.get('status_tratamento_id') or request.GET.get('status_tratamento'),
            'conferencia_fpd': request.GET.get('conferencia_fpd'),
            'faixa_atraso': request.GET.get('faixa_atraso') or request.GET.get('faixa'),
            'faturas_pagas': request.GET.get('faturas_pagas') or request.GET.get('faturas_pagas_n'),
        }
        try:
            data = qs.dashboard_qualidade(lente, mes, request.user, filtros)
            return Response(data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro no dashboard Qualidade')
            return Response({'error': str(e)}, status=500)


class QualidadeSincronizarFaltantesView(APIView):
    """POST /api/qualidade/sincronizar-faltantes/  body: { mes: YYYY-MM }"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        if not is_member(request.user, ['Admin', 'BackOffice', 'Diretoria', 'Qualidade']):
            return Response({'error': 'Sem permissão'}, status=403)
        mes = request.data.get('mes') or request.data.get('mes_referencia')
        if not mes:
            return Response({'error': 'mes é obrigatório (YYYY-MM)'}, status=400)
        try:
            resultado = qs.sincronizar_faltantes(mes, request.user)
            return Response(resultado)
        except PermissionError as e:
            return Response({'error': str(e)}, status=403)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro ao sincronizar faltantes')
            return Response({'error': str(e)}, status=500)


class QualidadeAtualizarContatoView(APIView):
    """POST /api/qualidade/contratos/<id>/contato/  body: { telefone?, email? }"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        try:
            resultado = qs.atualizar_contato(
                pk,
                telefone=request.data.get('telefone'),
                email=request.data.get('email'),
            )
            return Response(resultado)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro ao atualizar contato Qualidade')
            return Response({'error': str(e)}, status=500)


class QualidadeRegistrarLigacaoView(APIView):
    """POST /api/qualidade/contratos/<id>/registrar-ligacao/
    body: { destino?, sucesso?, detalhe? }
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        try:
            sucesso_raw = request.data.get('sucesso', True)
            sucesso = str(sucesso_raw).lower() not in ('0', 'false', 'no', 'nao', 'não')
            resultado = qs.registrar_ligacao_qualidade(
                pk,
                request.user,
                destino=request.data.get('destino') or '',
                sucesso=sucesso,
                detalhe=request.data.get('detalhe') or '',
            )
            return Response(resultado)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro ao registrar ligação Qualidade')
            return Response({'error': str(e)}, status=500)


class QualidadeEnviarCobrancaView(APIView):
    """POST /api/qualidade/contratos/<id>/enviar/
    body: { canal: whatsapp|email, fatura_id?, telefone?, email? }
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        canal = (request.data.get('canal') or '').strip().lower()
        fatura_id = request.data.get('fatura_id')
        if fatura_id in (None, '', 0, '0'):
            from crm_app.models import ContratoM10, FaturaM10

            try:
                contrato = ContratoM10.objects.get(pk=pk)
            except ContratoM10.DoesNotExist:
                return Response({'error': 'Contrato não encontrado'}, status=404)
            fatura = (
                FaturaM10.objects.filter(contrato=contrato)
                .exclude(status='PAGO')
                .order_by('numero_fatura')
                .first()
            )
            if not fatura:
                fatura = FaturaM10.objects.filter(contrato=contrato, numero_fatura=1).first()
            if not fatura:
                return Response({'error': 'Nenhuma fatura para envio'}, status=400)
            fatura_id = fatura.id
        try:
            fatura_id = int(fatura_id)
        except (TypeError, ValueError):
            return Response({'error': 'fatura_id inválido'}, status=400)

        try:
            if canal in ('whatsapp', 'wpp', 'zap'):
                resultado = qs.enviar_cobranca_whatsapp(
                    pk,
                    fatura_id,
                    request.user,
                    telefone_override=request.data.get('telefone'),
                )
            elif canal in ('email', 'e-mail', 'mail'):
                resultado = qs.enviar_cobranca_email(
                    pk,
                    fatura_id,
                    request.user,
                    email_override=request.data.get('email'),
                )
            else:
                return Response({'error': 'canal deve ser whatsapp ou email'}, status=400)
            code = status.HTTP_200_OK if resultado.get('ok') else status.HTTP_400_BAD_REQUEST
            return Response(resultado, status=code)
        except Exception as e:
            logger.exception('Erro ao enviar cobrança Qualidade')
            return Response({'error': str(e)}, status=500)


class QualidadeOrfaosView(APIView):
    """GET /api/qualidade/orfaos/ — contratos órfãos aguardando CPF/vínculo."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        from crm_app.models import ContratoM10

        qs_orf = ContratoM10.objects.filter(orfao=True).order_by('-atualizado_em')[:200]
        data = [
            {
                'id': c.id,
                'ordem_servico': c.ordem_servico or '-',
                'numero_contrato': c.numero_contrato,
                'cliente_nome': c.cliente_nome,
                'cpf_cliente': c.cpf_cliente or '',
                'status_contrato': c.status_contrato,
                'observacao': c.observacao or '',
            }
            for c in qs_orf
        ]
        return Response({'total': len(data), 'contratos': data})


class QualidadeFaltamNoCrmView(APIView):
    """GET /api/qualidade/faltam-no-crm/ — linhas FPD/SPD/TPD sem match no CRM."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        apenas = (request.GET.get('apenas_abertas') or '').strip().lower() in (
            '1', 'true', 'sim', 'yes',
        )
        try:
            data = qs.listar_faltam_no_crm(
                indicador=request.GET.get('indicador'),
                mes=request.GET.get('mes'),
                q=request.GET.get('q'),
                apenas_abertas=apenas,
                page=request.GET.get('page', 1),
                page_size=request.GET.get('page_size', 100),
            )
            return Response(data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro ao listar faltam no CRM')
            return Response({'error': str(e)}, status=500)


class QualidadeDashboardFpdNioView(APIView):
    """GET /api/qualidade/dashboard-fpd-nio/?indicador=FPD&meses=6

    Tabela no formato do dashboard Nio (pagas / total / % aberto / faixas).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        try:
            data = qs.dashboard_fpd_estilo_nio(
                indicador=request.GET.get('indicador', 'FPD'),
                meses=request.GET.get('meses', 6),
            )
            return Response(data)
        except Exception as e:
            logger.exception('Erro no dashboard FPD estilo Nio')
            return Response({'error': str(e)}, status=500)


class QualidadeContratoFaturasView(APIView):
    """GET/POST /api/qualidade/contratos/<id>/faturas/ — painel das 10 faturas."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        try:
            return Response(qs.detalhe_contrato_faturas(pk))
        except ValueError as e:
            return Response({'error': str(e)}, status=404)
        except Exception as e:
            logger.exception('Erro ao carregar faturas Qualidade')
            return Response({'error': str(e)}, status=500)

    def post(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        faturas = request.data.get('faturas') or []
        try:
            resultado = qs.salvar_faturas_contrato(pk, faturas, request.user)
            return Response(resultado)
        except PermissionError as e:
            return Response({'error': str(e)}, status=403)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro ao salvar faturas Qualidade')
            return Response({'error': str(e)}, status=500)


class QualidadeFaturaPdfView(APIView):
    """GET /api/qualidade/faturas/<id>/pdf/ — download ou redirect do PDF."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        from django.http import FileResponse, HttpResponseRedirect
        from crm_app.models import FaturaM10

        try:
            fatura = FaturaM10.objects.get(pk=pk)
        except FaturaM10.DoesNotExist:
            return Response({'error': 'Fatura não encontrada'}, status=404)

        if fatura.arquivo_pdf:
            try:
                return FileResponse(
                    fatura.arquivo_pdf.open('rb'),
                    as_attachment=True,
                    filename=f'fatura_{fatura.numero_fatura}_{fatura.contrato_id}.pdf',
                )
            except Exception as e:
                logger.exception('Erro ao abrir PDF fatura=%s', pk)
                return Response({'error': str(e)}, status=500)

        if fatura.pdf_url:
            return HttpResponseRedirect(fatura.pdf_url)

        return Response({'error': 'PDF não disponível nesta fatura'}, status=404)


class QualidadeFaturaUploadPdfView(APIView):
    """POST /api/qualidade/faturas/<id>/upload-pdf/ — anexa PDF à fatura."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        from crm_app.models import FaturaM10

        arquivo = request.FILES.get('file') or request.FILES.get('pdf')
        if not arquivo:
            return Response({'error': 'Arquivo PDF não enviado'}, status=400)
        try:
            fatura = FaturaM10.objects.get(pk=pk)
        except FaturaM10.DoesNotExist:
            return Response({'error': 'Fatura não encontrada'}, status=404)

        fatura.arquivo_pdf = arquivo
        fatura.save(update_fields=['arquivo_pdf', 'atualizado_em'])
        return Response({
            'ok': True,
            'fatura_id': fatura.id,
            'download_url': f'/api/qualidade/faturas/{fatura.id}/pdf/',
        })


class QualidadeBuscarNioOpcoesView(APIView):
    """POST /api/qualidade/contratos/<id>/buscar-nio/
    body: { numero_fatura: 1 }
    Lista opções da Nio para o BO aceitar/recusar.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        numero = request.data.get('numero_fatura')
        try:
            numero = int(numero)
        except (TypeError, ValueError):
            return Response({'error': 'numero_fatura inválido'}, status=400)
        try:
            data = qs.buscar_opcoes_nio_fatura(pk, numero, request.user)
            return Response(data)
        except PermissionError as e:
            return Response({'error': str(e)}, status=403)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro busca Nio opções Qualidade')
            return Response({'error': str(e)}, status=500)


class QualidadeAplicarNioOpcaoView(APIView):
    """POST /api/qualidade/contratos/<id>/aplicar-nio/
    body: { fatura_id, opcao, token?, api_base?, session_id?, cpf? }
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        fatura_id = request.data.get('fatura_id')
        opcao = request.data.get('opcao') or {}
        try:
            fatura_id = int(fatura_id)
        except (TypeError, ValueError):
            return Response({'error': 'fatura_id inválido'}, status=400)
        if not isinstance(opcao, dict) or not opcao:
            return Response({'error': 'opcao é obrigatória'}, status=400)
        try:
            resultado = qs.aplicar_opcao_nio_fatura(
                pk,
                fatura_id,
                opcao,
                request.user,
                token=request.data.get('token') or '',
                api_base=request.data.get('api_base') or '',
                session_id=request.data.get('session_id') or '',
                cpf=request.data.get('cpf') or '',
            )
            return Response(resultado)
        except PermissionError as e:
            return Response({'error': str(e)}, status=403)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro ao aplicar opção Nio Qualidade')
            return Response({'error': str(e)}, status=500)


class QualidadeStatusTratamentoView(APIView):
    """GET lista opções | PATCH/POST atualiza status do contrato.

    GET  /api/qualidade/status-tratamento/
    POST /api/qualidade/contratos/<id>/status-tratamento/  body: { status_id }
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        return Response({'status': qs.listar_status_tratamento_qualidade()})


class QualidadeAtualizarStatusTratamentoView(APIView):
    """POST/PATCH /api/qualidade/contratos/<id>/status-tratamento/  body: { status_id|null }"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        return self._atualizar(request, pk)

    def patch(self, request, pk: int):
        return self._atualizar(request, pk)

    def _atualizar(self, request, pk: int):
        bloqueio = _exige_acesso(request.user)
        if bloqueio:
            return bloqueio
        if not is_member(request.user, ['Admin', 'BackOffice', 'Diretoria', 'Qualidade']):
            return Response({'error': 'Sem permissão para alterar status de tratamento'}, status=403)
        status_id = request.data.get('status_id', request.data.get('status_tratamento_id'))
        try:
            resultado = qs.atualizar_status_tratamento_contrato(pk, status_id)
            return Response(resultado)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            logger.exception('Erro ao atualizar status tratamento Qualidade')
            return Response({'error': str(e)}, status=500)
