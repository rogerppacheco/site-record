# site-record/crm_app/views.py

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
from operator import itemgetter
from io import BytesIO

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.timezone import now
from django.contrib.auth import get_user_model, authenticate
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.http import JsonResponse, HttpResponse
from django.template.loader import get_template
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags

from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated

from xhtml2pdf import pisa 

# --- ALTERAÇÃO 1: Importando VendaPermission ---
from usuarios.permissions import CheckAPIPermission, VendaPermission
# -----------------------------------------------

from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia,
    RegraComissao, Cliente, Venda, ImportacaoOsab, ImportacaoChurn,
    CicloPagamento, HistoricoAlteracaoVenda, PagamentoComissao
)
from .serializers import (
    OperadoraSerializer, PlanoSerializer, FormaPagamentoSerializer,
    StatusCRMSerializer, MotivoPendenciaSerializer, RegraComissaoSerializer,
    VendaSerializer, VendaCreateSerializer, ClienteSerializer,
    VendaUpdateSerializer, ImportacaoOsabSerializer, ImportacaoChurnSerializer,
    CicloPagamentoSerializer, VendaDetailSerializer
)

logger = logging.getLogger(__name__)

# --- FUNÇÃO AUXILIAR DE SEGURANÇA ---
def is_member(user, groups):
    """Verifica se o usuário pertence a algum dos grupos listados."""
    if user.is_superuser:
        return True
    if user.groups.filter(name__in=groups).exists():
        return True
    if hasattr(user, 'perfil') and user.perfil and user.perfil.nome in groups:
        return True
    return False
# ------------------------------------

class OperadoraListCreateView(generics.ListCreateAPIView):
    queryset = Operadora.objects.filter(ativo=True)
    serializer_class = OperadoraSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'operadora'

class OperadoraDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Operadora.objects.all()
    serializer_class = OperadoraSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'operadora'

class PlanoListCreateView(generics.ListCreateAPIView):
    queryset = Plano.objects.filter(ativo=True)
    serializer_class = PlanoSerializer
    permission_classes = [permissions.IsAuthenticated]

class PlanoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Plano.objects.all()
    serializer_class = PlanoSerializer
    permission_classes = [permissions.IsAuthenticated]

class FormaPagamentoListCreateView(generics.ListCreateAPIView):
    queryset = FormaPagamento.objects.filter(ativo=True)
    serializer_class = FormaPagamentoSerializer
    permission_classes = [permissions.IsAuthenticated]

class FormaPagamentoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FormaPagamento.objects.all()
    serializer_class = FormaPagamentoSerializer
    permission_classes = [permissions.IsAuthenticated]

class StatusCRMListCreateView(generics.ListCreateAPIView):
    serializer_class = StatusCRMSerializer
    permission_classes = [permissions.IsAuthenticated]
    resource_name = 'statuscrm'

    def get_queryset(self):
        user = self.request.user
        if is_member(user, ['Diretoria', 'BackOffice', 'Admin', 'Supervisor']):
            queryset = StatusCRM.objects.all()
            tipo = self.request.query_params.get('tipo', None)
            if tipo:
                queryset = queryset.filter(tipo__iexact=tipo)
            return queryset.order_by('nome')
        return StatusCRM.objects.none()

class StatusCRMDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = StatusCRM.objects.all()
    serializer_class = StatusCRMSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'statuscrm'

class MotivoPendenciaListCreateView(generics.ListCreateAPIView):
    queryset = MotivoPendencia.objects.all()
    serializer_class = MotivoPendenciaSerializer
    permission_classes = [permissions.IsAuthenticated]

class MotivoPendenciaDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = MotivoPendencia.objects.all()
    serializer_class = MotivoPendenciaSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'motivopendencia'

class RegraComissaoListCreateView(generics.ListCreateAPIView):
    queryset = RegraComissao.objects.all()
    serializer_class = RegraComissaoSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'regracomissao'

class RegraComissaoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = RegraComissao.objects.all()
    serializer_class = RegraComissaoSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'regracomissao'

class VendaViewSet(viewsets.ModelViewSet):
    # --- ALTERAÇÃO 2: Trocando a permissão restrita pela permissão inteligente ---
    permission_classes = [VendaPermission] 
    # -----------------------------------------------------------------------------
    resource_name = 'venda'
    
    queryset = Venda.objects.filter(ativo=True).order_by('-data_criacao')

    def get_serializer_context(self):
        context = super(VendaViewSet, self).get_serializer_context()
        context.update({"request": self.request})
        return context

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return VendaDetailSerializer
        if self.action == 'create':
            return VendaCreateSerializer
        if self.action in ['update', 'partial_update']:
            return VendaUpdateSerializer
        return VendaSerializer

    def get_queryset(self):
        queryset = Venda.objects.filter(ativo=True).select_related(
            'vendedor', 'cliente', 'plano', 'forma_pagamento',
            'status_tratamento', 'status_esteira', 'status_comissionamento',
            'motivo_pendencia'
        ).prefetch_related('historico_alteracoes__usuario').order_by('-data_criacao')
        
        user = self.request.user

        if self.action in ['retrieve', 'update', 'partial_update', 'destroy']:
            if user.is_superuser or is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
                return queryset
            if is_member(user, ['Supervisor']):
                liderados_ids = list(user.liderados.values_list('id', flat=True))
                liderados_ids.append(user.id)
                return queryset.filter(vendedor_id__in=liderados_ids)
            return queryset.filter(vendedor=user)

        view_type = self.request.query_params.get('view')
        flow = self.request.query_params.get('flow')

        if not view_type:
            if flow and is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
                view_type = 'geral'
            else:
                view_type = 'minhas_vendas'

        if view_type == 'minhas_vendas':
            queryset = queryset.filter(vendedor=user)

        elif view_type == 'visao_equipe' or view_type == 'geral':
            if is_member(user, ['Diretoria', 'Admin']):
                pass 
            elif is_member(user, ['BackOffice']):
                data_inicio_param = self.request.query_params.get('data_inicio')
                if not data_inicio_param and self.action == 'list':
                    hoje = timezone.now()
                    inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    queryset = queryset.filter(
                        Q(data_criacao__gte=inicio_mes) | 
                        Q(data_instalacao__gte=inicio_mes)
                    )
            elif is_member(user, ['Supervisor']):
                liderados_ids = list(user.liderados.values_list('id', flat=True))
                liderados_ids.append(user.id)
                queryset = queryset.filter(vendedor_id__in=liderados_ids)
            else:
                return queryset.none()

        ordem_servico = self.request.query_params.get('ordem_servico')
        data_inicio_str = self.request.query_params.get('data_inicio')
        data_fim_str = self.request.query_params.get('data_fim')
        consultor_id = self.request.query_params.get('consultor_id')
        
        if consultor_id:
            if view_type != 'minhas_vendas':
                queryset = queryset.filter(vendedor_id=consultor_id)

        if flow == 'auditoria':
            queryset = queryset.filter(status_tratamento__isnull=False, status_esteira__isnull=True)
        elif flow == 'esteira':
            queryset = queryset.filter(status_esteira__isnull=False, status_comissionamento__isnull=True).exclude(status_esteira__nome__iexact='Instalada')
        elif flow == 'comissionamento':
            queryset = queryset.filter(status_esteira__nome__iexact='Instalada').exclude(status_comissionamento__nome__iexact='Pago')

        if ordem_servico:
            queryset = queryset.filter(ordem_servico__icontains=ordem_servico)

        if data_inicio_str and data_fim_str:
            try:
                data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
                data_fim_ajustada = data_fim + timedelta(days=1)
                
                queryset = queryset.filter(
                    Q(data_criacao__range=(data_inicio, data_fim_ajustada)) |
                    Q(data_instalacao__range=(data_inicio, data_fim_ajustada))
                )
            except (ValueError, TypeError): 
                pass
        
        elif view_type == 'minhas_vendas' and self.action == 'list' and not is_member(user, ['Diretoria', 'BackOffice', 'Admin']):
             hoje = now()
             inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
             queryset = queryset.filter(
                Q(data_criacao__gte=inicio_mes) | 
                Q(data_instalacao__gte=inicio_mes)
             )
                
        return queryset

    def perform_create(self, serializer):
        cpf_cnpj = serializer.validated_data.pop('cliente_cpf_cnpj')
        nome = serializer.validated_data.pop('cliente_nome_razao_social')
        email = serializer.validated_data.pop('cliente_email', None)
        
        cliente, created = Cliente.objects.get_or_create(
            cpf_cnpj=cpf_cnpj,
            defaults={'nome_razao_social': nome, 'email': email}
        )
        if not created:
            cliente.nome_razao_social = nome
            if email: cliente.email = email
            cliente.save()
            
        status_inicial = StatusCRM.objects.filter(nome__iexact="SEM TRATAMENTO", tipo__iexact="Tratamento").first()
        if not status_inicial:
            status_inicial = StatusCRM.objects.filter(tipo__iexact="Tratamento").first()

        serializer.save(vendedor=self.request.user, cliente=cliente, status_tratamento=status_inicial)

    def perform_update(self, serializer):
        venda_antes = self.get_object()
        status_esteira_antes = venda_antes.status_esteira
        status_tratamento_antes = venda_antes.status_tratamento
        
        novo_status = serializer.validated_data.get('status_esteira')
        extra_updates = {}

        if novo_status:
            nome_status = novo_status.nome.upper()
            if 'PENDEN' not in nome_status and 'PENDÊN' not in nome_status:
                extra_updates['motivo_pendencia'] = None
            if 'AGENDADO' not in nome_status and 'INSTALADA' not in nome_status:
                extra_updates['data_agendamento'] = None
                extra_updates['periodo_agendamento'] = None

        venda_atualizada = serializer.save(**extra_updates)
        
        alteracoes = {}
        if venda_antes.status_esteira != venda_atualizada.status_esteira:
            alteracoes['status_esteira'] = {
                'de': str(status_esteira_antes), 
                'para': str(venda_atualizada.status_esteira)
            }
        if venda_antes.status_tratamento != venda_atualizada.status_tratamento:
            alteracoes['status_tratamento'] = {
                'de': str(status_tratamento_antes), 
                'para': str(venda_atualizada.status_tratamento)
            }

        if alteracoes:
            try:
                HistoricoAlteracaoVenda.objects.create(
                    venda=venda_atualizada,
                    usuario=self.request.user,
                    alteracoes=alteracoes
                )
            except Exception as e:
                logger.error(f"Erro ao salvar histórico: {e}")

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            instance.ativo = False
            instance.save()
            HistoricoAlteracaoVenda.objects.create(
                venda=instance,
                usuario=request.user,
                alteracoes={"acao": "exclusao_logica", "detalhe": f"Venda inativada por {request.user.username}."}
            )
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            logger.error(f"Erro ao excluir venda {kwargs.get('pk')}: {e}", exc_info=True)
            return Response({"detail": "Erro ao excluir venda."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class VendasStatusCountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        venda_viewset = VendaViewSet()
        venda_viewset.request = request
        venda_viewset.action = 'list'
        queryset = venda_viewset.get_queryset()

        status_counts = list(queryset.values('status_esteira__nome').annotate(count=Count('id')).order_by('-count'))
        order_priority = {"INSTALADA": 0, "AGENDADO": 1}
        filtered_counts = [item for item in status_counts if item.get('status_esteira__nome')]

        def sort_key(item):
            nome = item['status_esteira__nome'].upper()
            return (order_priority.get(nome, 99), -item['count'])

        sorted_counts = sorted(filtered_counts, key=sort_key)
        return Response({item['status_esteira__nome']: item['count'] for item in sorted_counts})

class DashboardResumoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        User = get_user_model()
        user = request.user
        hoje = now()
        inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        proximo_mes = (inicio_mes + timedelta(days=32)).replace(day=1)
        
        usuarios_para_calcular = []
        
        if is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            usuarios_para_calcular = User.objects.filter(is_active=True)
        elif is_member(user, ['Supervisor']):
            usuarios_para_calcular = [user]
        else:
            usuarios_para_calcular = [user]

        total_registradas_geral = 0
        total_instaladas_geral = 0
        comissao_total_geral = 0.0
        status_counts_geral = defaultdict(int)
        meta_display = 0
        detalhes_listas = defaultdict(list)

        exibir_comissao = True 

        for vendedor in usuarios_para_calcular:
            meta_individual = getattr(vendedor, 'meta_comissao', 0) or 0
            meta_display += float(meta_individual)

            vendas_registro = Venda.objects.filter(
                vendedor=vendedor, ativo=True,
                data_criacao__gte=inicio_mes, data_criacao__lt=proximo_mes
            ).select_related('cliente', 'status_esteira')
            
            qtd_registradas = vendas_registro.count()
            bateu_meta = qtd_registradas >= float(meta_individual)

            for v in vendas_registro:
                nome_status = v.status_esteira.nome.upper() if v.status_esteira else 'AGUARDANDO'
                if nome_status != 'INSTALADA':
                    status_counts_geral[nome_status] += 1
                
                obj_venda = {
                    'id': v.id,
                    'cliente': v.cliente.nome_razao_social if v.cliente else 'S/C',
                    'status': nome_status,
                    'data_iso': v.data_criacao.isoformat(), 
                    'vendedor': vendedor.username
                }
                detalhes_listas['TOTAL_REGISTRADAS'].append(obj_venda)
                if nome_status != 'INSTALADA':
                    detalhes_listas[nome_status].append(obj_venda)

            vendas_instaladas = Venda.objects.filter(
                vendedor=vendedor, ativo=True,
                status_esteira__nome__iexact='INSTALADA',
                data_instalacao__gte=inicio_mes, data_instalacao__lt=proximo_mes
            ).select_related('plano', 'cliente')

            qtd_instaladas = vendas_instaladas.count()
            status_counts_geral['INSTALADA'] += qtd_instaladas

            for vi in vendas_instaladas:
                obj_inst = {
                    'id': vi.id,
                    'cliente': vi.cliente.nome_razao_social if vi.cliente else 'S/C',
                    'status': 'INSTALADA',
                    'data_iso': vi.data_instalacao.isoformat() if vi.data_instalacao else None,
                    'vendedor': vendedor.username
                }
                detalhes_listas['TOTAL_INSTALADAS'].append(obj_inst)
                detalhes_listas['INSTALADA'].append(obj_inst)

            regras = RegraComissao.objects.filter(consultor=vendedor).select_related('plano')
            comissao_vendedor = 0.0
            for v in vendas_instaladas:
                valor_item = 0.0 
                doc = v.cliente.cpf_cnpj if v.cliente else ''
                doc_limpo = ''.join(filter(str.isdigit, doc))
                tipo_cliente_venda = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
                
                regra_encontrada = None
                for r in regras:
                    canal_vendedor = getattr(vendedor, 'canal', 'PAP') or 'PAP'
                    if r.plano.id == v.plano.id and r.tipo_cliente == tipo_cliente_venda and r.tipo_venda == canal_vendedor:
                        regra_encontrada = r
                        break
                
                if regra_encontrada:
                    valor_item = float(regra_encontrada.valor_acelerado if bateu_meta else regra_encontrada.valor_base)
                else:
                    valor_item = 0.0
                
                comissao_vendedor += valor_item

            total_registradas_geral += qtd_registradas
            total_instaladas_geral += qtd_instaladas
            comissao_total_geral += comissao_vendedor

        percentual_aproveitamento = 0.0
        if total_registradas_geral > 0:
            percentual_aproveitamento = (total_instaladas_geral / total_registradas_geral) * 100

        valor_comissao_final = comissao_total_geral

        dados = {
            "periodo": f"{inicio_mes.strftime('%d/%m')} a {hoje.strftime('%d/%m')}",
            "meta": meta_display,
            "total_vendas": total_registradas_geral,
            "total_instaladas": total_instaladas_geral,
            "percentual_meta": round((total_registradas_geral / meta_display * 100), 1) if meta_display > 0 else 0,
            "percentual_aproveitamento": round(percentual_aproveitamento, 1),
            "status_bateu_meta": (total_registradas_geral >= meta_display) if meta_display > 0 else False,
            "comissao_estimada": valor_comissao_final,
            "exibir_comissao": exibir_comissao, 
            "status_detalhado": status_counts_geral,
            "detalhes_listas": detalhes_listas
        }
        return Response(dados)

class ClienteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Cliente.objects.filter(vendas__ativo=True).distinct()
    serializer_class = ClienteSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'cliente'

    def get_queryset(self):
        queryset = Venda.objects.filter(ativo=True).select_related(
            'vendedor', 'cliente', 'plano', 'forma_pagamento',
            'status_tratamento', 'status_esteira', 'status_comissionamento',
            'motivo_pendencia'
        ).prefetch_related('historico_alteracoes__usuario')
        
        user = self.request.user

        if self.action in ['retrieve', 'update', 'partial_update', 'destroy']:
            if user.is_superuser or is_member(user, ['Diretoria', 'Admin']):
                return queryset
            if is_member(user, ['BackOffice']):
                return queryset
            if is_member(user, ['Supervisor']):
                liderados_ids = list(user.liderados.values_list('id', flat=True))
                liderados_ids.append(user.id)
                return queryset.filter(vendedor_id__in=liderados_ids)
            return queryset.filter(vendedor=user)

        view_type = self.request.query_params.get('view')
        flow = self.request.query_params.get('flow')

        if not view_type:
            if flow and is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
                view_type = 'geral'
            else:
                view_type = 'minhas_vendas'

        if view_type == 'minhas_vendas':
            queryset = queryset.filter(vendedor=user)

        elif view_type == 'visao_equipe' or view_type == 'geral':
            if is_member(user, ['Diretoria', 'Admin']):
                pass 
            elif is_member(user, ['BackOffice']):
                data_inicio_param = self.request.query_params.get('data_inicio')
                if not data_inicio_param and self.action == 'list':
                    hoje = timezone.now()
                    inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    queryset = queryset.filter(
                        Q(data_criacao__gte=inicio_mes) | 
                        Q(data_instalacao__gte=inicio_mes)
                    )
            elif is_member(user, ['Supervisor']):
                liderados_ids = list(user.liderados.values_list('id', flat=True))
                liderados_ids.append(user.id)
                queryset = queryset.filter(vendedor_id__in=liderados_ids)
            else:
                return queryset.none()

        ordem_servico = self.request.query_params.get('ordem_servico')
        data_inicio_str = self.request.query_params.get('data_inicio')
        data_fim_str = self.request.query_params.get('data_fim')
        consultor_id = self.request.query_params.get('consultor_id')
        
        if consultor_id:
            if view_type != 'minhas_vendas':
                queryset = queryset.filter(vendedor_id=consultor_id)

        if flow == 'auditoria':
            queryset = queryset.filter(status_tratamento__isnull=False, status_esteira__isnull=True)
        elif flow == 'esteira':
            queryset = queryset.filter(status_esteira__isnull=False, status_comissionamento__isnull=True).exclude(status_esteira__nome__iexact='Instalada')
        elif flow == 'comissionamento':
            queryset = queryset.filter(status_esteira__nome__iexact='Instalada').exclude(status_comissionamento__nome__iexact='Pago')

        if ordem_servico:
            queryset = queryset.filter(ordem_servico__icontains=ordem_servico)

        if data_inicio_str and data_fim_str:
            try:
                data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
                data_fim_ajustada = data_fim + timedelta(days=1)
                queryset = queryset.filter(
                    Q(data_criacao__range=(data_inicio, data_fim_ajustada)) |
                    Q(data_instalacao__range=(data_inicio, data_fim_ajustada))
                )
            except (ValueError, TypeError): 
                pass
        
        elif view_type == 'minhas_vendas' and not is_member(user, ['Diretoria', 'BackOffice', 'Admin']):
             hoje = now()
             inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
             queryset = queryset.filter(
                Q(data_criacao__gte=inicio_mes) | 
                Q(data_instalacao__gte=inicio_mes)
             )
                
        return queryset

class ListaVendedoresView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        User = get_user_model()
        vendedores = User.objects.filter(is_active=True).values('id', 'username').order_by('username')
        return Response(list(vendedores))

class ComissionamentoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        hoje = timezone.now()
        try:
            ano = int(request.query_params.get('ano', hoje.year))
            mes = int(request.query_params.get('mes', hoje.month))
        except ValueError:
            ano = hoje.year
            mes = hoje.month
        
        data_inicio = datetime(ano, mes, 1)
        if mes == 12:
            data_fim = datetime(ano + 1, 1, 1)
        else:
            data_fim = datetime(ano, mes + 1, 1)

        User = get_user_model()
        consultores = User.objects.filter(is_active=True).order_by('username')
        relatorio = []
        todas_regras = list(RegraComissao.objects.select_related('plano', 'consultor').all())
        
        anomes_str = f"{ano}{mes:02d}"
        churns_mes = ImportacaoChurn.objects.filter(anomes_retirada=anomes_str)

        for consultor in consultores:
            vendas = Venda.objects.filter(
                vendedor=consultor,
                ativo=True,
                status_esteira__nome__iexact='INSTALADA',
                data_instalacao__gte=data_inicio,
                data_instalacao__lt=data_fim
            ).select_related('plano', 'forma_pagamento', 'cliente')

            qtd_instaladas = vendas.count()
            meta = consultor.meta_comissao or 0
            atingimento = (qtd_instaladas / meta * 100) if meta > 0 else 0
            bateu_meta = qtd_instaladas >= meta
            
            comissao_bruta = 0.0
            for v in vendas:
                doc = v.cliente.cpf_cnpj if v.cliente else ''
                doc_limpo = ''.join(filter(str.isdigit, doc))
                tipo_cliente = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
                canal_vendedor = getattr(consultor, 'canal', 'PAP') or 'PAP'
                
                regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor_id == consultor.id), None)
                
                if not regra:
                    regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor is None), None)
                
                valor_item = 0.0

                if regra:
                    valor_item = float(regra.valor_acelerado if bateu_meta else regra.valor_base)
                else:
                    valor_item = 0.0
                
                comissao_bruta += valor_item

            qtd_boleto = 0
            for v in vendas:
                if v.forma_pagamento and 'BOLETO' in v.forma_pagamento.nome.upper():
                    qtd_boleto += 1
            
            valor_desc_boleto_unit = float(consultor.desconto_boleto or 0)
            desc_boleto_total = qtd_boleto * valor_desc_boleto_unit

            qtd_inclusao = vendas.filter(inclusao=True).count()
            valor_desc_inclusao_unit = float(consultor.desconto_inclusao_viabilidade or 0)
            desc_inclusao_total = qtd_inclusao * valor_desc_inclusao_unit

            qtd_antecipacao = vendas.filter(antecipou_instalacao=True).count()
            valor_desc_antecipacao_unit = float(consultor.desconto_instalacao_antecipada or 0)
            desc_antecipacao_total = qtd_antecipacao * valor_desc_antecipacao_unit

            qtd_cnpj = 0
            for v in vendas:
                doc = v.cliente.cpf_cnpj if v.cliente else ''
                if len(''.join(filter(str.isdigit, doc))) > 11:
                    qtd_cnpj += 1
            
            valor_desc_cnpj_unit = float(consultor.adiantamento_cnpj or 0)
            desc_cnpj_total = qtd_cnpj * valor_desc_cnpj_unit

            valor_churn_total = 0.0
            premiacao = 0.0 
            bonus = 0.0
            total_descontos = desc_boleto_total + desc_inclusao_total + desc_antecipacao_total + desc_cnpj_total + valor_churn_total
            valor_liquido = (comissao_bruta + premiacao + bonus) - total_descontos

            relatorio.append({
                'consultor_id': consultor.id,
                'consultor_nome': consultor.username.upper(),
                'qtd_instaladas': qtd_instaladas,
                'meta': meta,
                'atingimento_pct': round(atingimento, 1),
                'comissao_bruta': comissao_bruta,
                'desc_boleto': desc_boleto_total,
                'desc_inclusao': desc_inclusao_total,
                'desc_antecipacao': desc_antecipacao_total,
                'desc_cnpj': desc_cnpj_total,
                'valor_liquido': valor_liquido,
            })

        historico = []
        for i in range(6):
            d = hoje - timedelta(days=30*i)
            mes_iter = d.month
            ano_iter = d.year
            total_ciclo = CicloPagamento.objects.filter(ano=ano_iter, mes=str(mes_iter)).aggregate(Sum('valor_comissao_final'))['valor_comissao_final__sum'] or 0
            fechamento = PagamentoComissao.objects.filter(referencia_ano=ano_iter, referencia_mes=mes_iter).first()
            total_pago = fechamento.total_pago_consultores if fechamento else 0.0
            historico.append({
                'ano_mes': f"{mes_iter}/{ano_iter}",
                'total_pago_equipe': total_pago,
                'total_recebido_ciclo': total_ciclo,
                'status': 'Fechado' if fechamento else 'Aberto'
            })

        return Response({
            'periodo': f"{mes}/{ano}",
            'relatorio_consultores': relatorio,
            'historico_pagamentos': historico
        })

@method_decorator(ensure_csrf_cookie, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            refresh = RefreshToken.for_user(user)
            response = JsonResponse({
                'access_token': str(refresh.access_token),
                'refresh_token': str(refresh)
            })
            response.set_cookie('access_token', str(refresh.access_token), httponly=True, secure=True, samesite='Lax')
            return response
        else:
            return Response({"detail": "Credenciais inválidas"}, status=status.HTTP_401_UNAUTHORIZED)

class ImportacaoOsabView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_osab'
    parser_classes = [MultiPartParser, FormParser]
    def _clean_key(self, key):
        if pd.isna(key) or key is None: return None
        return str(key).replace('.0', '').strip()
    def get(self, request):
        queryset = ImportacaoOsab.objects.all().order_by('-id')
        serializer = ImportacaoOsabSerializer(queryset, many=True)
        return Response(serializer.data)
    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Nenhum arquivo foi enviado.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            df = None
            if file_obj.name.endswith('.xlsb'): df = pd.read_excel(file_obj, engine='pyxlsb')
            elif file_obj.name.endswith(('.xlsx', '.xls')): df = pd.read_excel(file_obj)
            else: return Response({'error': 'Formato de arquivo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e: return Response({'error': f'Erro ao ler o arquivo: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        df.columns = [str(col).strip().upper() for col in df.columns]
        if 'DOCUMENTO' not in df.columns or 'SITUACAO' not in df.columns: return Response({"error": "O arquivo precisa conter as colunas 'DOCUMENTO' e 'SITUACAO'."}, status=status.HTTP_400_BAD_REQUEST)
        df = df.replace({np.nan: None, pd.NaT: None})
        STATUS_MAP = {'CONCLUÍDO': 'INSTALADA', 'CANCELADO': 'CANCELADA', 'CANCELADO - SEM APROVISIONAMENTO': 'CANCELADA', 'PENDÊNCIA CLIENTE': 'PENDENCIADA', 'PENDÊNCIA TÉCNICA': 'PENDENCIADA', 'EM APROVISIONAMENTO': 'EM ANDAMENTO', 'AGUARDANDO PAGAMENTO': 'AGUARDANDO PAGAMENTO', 'REPROVADO ANALISE DE FRAUDE': 'REPROVADO CARTÃO DE CRÉDITO', 'DRAFT': 'DRAFT', 'DRAFT - PRAZO CC EXPIRADO': 'DRAFT'}
        status_esteira_objects = StatusCRM.objects.filter(tipo='Esteira')
        status_esteira_map = {status.nome.upper(): status for status in status_esteira_objects}
        vendas_com_os = Venda.objects.filter(ativo=True, ordem_servico__isnull=False).exclude(ordem_servico__exact='')
        vendas_map = {self._clean_key(v.ordem_servico): v for v in vendas_com_os}
        report = {"status": "sucesso", "total_registros": len(df), "criados": 0, "atualizados": 0, "vendas_encontradas": 0, "ja_corretos": 0, "status_nao_mapeado": 0, "erros": []}
        vendas_para_atualizar = []
        for index, row in df.iterrows():
            doc = self._clean_key(row.get('DOCUMENTO'))
            sit = row.get('SITUACAO')
            if not doc: continue
            venda = vendas_map.get(doc)
            if not venda:
                report["erros"].append(f"Linha {index + 2}: Documento {doc} não encontrado.")
                continue
            report["vendas_encontradas"] += 1
            if not sit: continue
            target_name = STATUS_MAP.get(str(sit).upper())
            if not target_name: report["status_nao_mapeado"] += 1; continue
            target_obj = status_esteira_map.get(target_name.upper())
            if not target_obj: report["status_nao_mapeado"] += 1; continue
            if venda.status_esteira and venda.status_esteira.id == target_obj.id: report["ja_corretos"] += 1
            else:
                venda.status_esteira = target_obj
                vendas_para_atualizar.append(venda)
        if vendas_para_atualizar:
            report["atualizados"] = len(vendas_para_atualizar)
            Venda.objects.bulk_update(vendas_para_atualizar, ['status_esteira'])
        return Response(report, status=status.HTTP_200_OK)

class ImportacaoOsabDetailView(generics.RetrieveUpdateAPIView):
    queryset = ImportacaoOsab.objects.all()
    serializer_class = ImportacaoOsabSerializer
    permission_classes = [permissions.IsAuthenticated]

class ImportacaoChurnView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_churn'
    parser_classes = [MultiPartParser, FormParser]
    def get(self, request):
        queryset = ImportacaoChurn.objects.all().order_by('-id')
        serializer = ImportacaoChurnSerializer(queryset, many=True)
        return Response(serializer.data)
    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Nenhum arquivo.'}, status=400)
        coluna_map = {'UF': 'uf', 'PRODUTO': 'produto', 'MATRICULA_VENDEDOR': 'matricula_vendedor', 'GV': 'gv', 'SAP_PRINCIPAL_FIM': 'sap_principal_fim', 'GESTAO': 'gestao', 'ST_REGIONAL': 'st_regional', 'GC': 'gc', 'NUMERO_PEDIDO': 'numero_pedido', 'DT_GROSS': 'dt_gross', 'ANOMES_GROSS': 'anomes_gross', 'DT_RETIRADA': 'dt_retirada', 'ANOMES_RETIRADA': 'anomes_retirada', 'GRUPO_UNIDADE': 'grupo_unidade', 'CODIGO_SAP': 'codigo_sap', 'MUNICIPIO': 'municipio', 'TIPO_RETIRADA': 'tipo_retirada', 'MOTIVO_RETIRADA': 'motivo_retirada', 'SUBMOTIVO_RETIRADA': 'submotivo_retirada', 'CLASSIFICACAO': 'classificacao', 'DESC_APELIDO': 'desc_apelido'}
        try:
            df = pd.read_excel(file_obj) if file_obj.name.endswith(('.xlsx', '.xls')) else None
            if df is None: return Response({'error': 'Formato inválido.'}, status=400)
        except Exception as e: return Response({'error': str(e)}, status=400)
        df.columns = [str(col).strip().upper() for col in df.columns]
        for f in ['DT_GROSS', 'DT_RETIRADA']:
            if f in df.columns: df[f] = pd.to_datetime(df[f], errors='coerce')
        df = df.replace({np.nan: None, pd.NaT: None})
        df.rename(columns=coluna_map, inplace=True)
        criados, atualizados, erros = 0, 0, []
        fields = {f.name for f in ImportacaoChurn._meta.get_fields()}
        for idx, row in df.iterrows():
            data = row.to_dict()
            pedido = data.get('numero_pedido')
            if not pedido: continue
            defaults = {k: v for k, v in data.items() if k in fields}
            try:
                obj, created = ImportacaoChurn.objects.update_or_create(numero_pedido=pedido, defaults=defaults)
                if created: criados += 1
                else: atualizados += 1
            except Exception as e: erros.append(f"Linha {idx+2}: {e}")
        return Response({'status': 'sucesso', 'total_registros': len(df), 'criados': criados, 'atualizados': atualizados, 'erros': erros}, status=200)

class ImportacaoChurnDetailView(generics.RetrieveUpdateAPIView):
    queryset = ImportacaoChurn.objects.all()
    serializer_class = ImportacaoChurnSerializer
    permission_classes = [permissions.IsAuthenticated]

class ImportacaoCicloPagamentoView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_ciclo_pagamento'
    parser_classes = [MultiPartParser, FormParser]
    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Arquivo não enviado.'}, status=400)
        coluna_map = {'ANO': 'ano', 'MES': 'mes', 'QUINZENA': 'quinzena', 'CICLO': 'ciclo', 'CICLO_COMPLEMENTAR': 'ciclo_complementar', 'EVENTO': 'evento', 'SUB_EVENTO': 'sub_evento', 'CANAL_DETALHADO': 'canal_detalhado', 'CANAL_AGRUPADO': 'canal_agrupado', 'SUB_CANAL': 'sub_canal', 'COD_SAP': 'cod_sap', 'COD_SAP_AGR': 'cod_sap_agr', 'PARCEIRO_AGR': 'parceiro_agr', 'UF_PARCEIRO_AGR': 'uf_parceiro_agr', 'FAMILIA': 'familia', 'PRODUTO': 'produto', 'OFERTA': 'oferta', 'PLANO_DETALHADO': 'plano_detalhado', 'CELULA': 'celula', 'METODO_PAGAMENTO': 'metodo_pagamento', 'CONTRATO': 'contrato', 'NUM_OS_PEDIDO_SIEBEL': 'num_os_pedido_siebel', 'ID_BUNDLE': 'id_bundle', 'DATA_ATV': 'data_atv', 'DATA_RETIRADA': 'data_retirada', 'QTD': 'qtd', 'COMISSAO_BRUTA': 'comissao_bruta', 'FATOR': 'fator', 'IQ': 'iq', 'VALOR_COMISSAO_FINAL': 'valor_comissao_final'}
        try:
            df = pd.read_excel(file_obj)
        except Exception as e: return Response({'error': str(e)}, status=400)
        df.columns = [str(col).strip().upper() for col in df.columns]
        df.rename(columns=coluna_map, inplace=True)
        for f in ['data_atv', 'data_retirada']:
            if f in df.columns: df[f] = pd.to_datetime(df[f], errors='coerce')
        for f in ['comissao_bruta', 'fator', 'iq', 'valor_comissao_final']:
            if f in df.columns:
                df[f] = df[f].astype(str).str.replace('R$', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df[f] = pd.to_numeric(df[f], errors='coerce')
        df = df.replace({np.nan: None, pd.NaT: None})
        criados, atualizados, erros = 0, 0, []
        fields = {f.name for f in CicloPagamento._meta.get_fields()}
        for idx, row in df.iterrows():
            data = row.to_dict()
            contrato = data.get('contrato')
            if not contrato: continue
            defaults = {k: v for k, v in data.items() if k in fields}
            try:
                obj, created = CicloPagamento.objects.update_or_create(contrato=contrato, defaults=defaults)
                if created: criados += 1
                else: atualizados += 1
            except Exception as e: erros.append(f"Linha {idx+2}: {e}")
        return Response({'total': len(df), 'criados': criados, 'atualizados': atualizados, 'erros': erros}, status=200)

class PerformanceVendasView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request, *args, **kwargs):
        User = get_user_model()
        hoje = timezone.now().date()
        start_of_week = hoje - timedelta(days=hoje.weekday())
        start_of_month = hoje.replace(day=1)
        current_user = self.request.user
        if is_member(current_user, ['Diretoria', 'BackOffice', 'Admin']):
            users_to_process = User.objects.filter(is_active=True).select_related('supervisor')
        elif is_member(current_user, ['Supervisor']):
            users_to_process = User.objects.filter(Q(id=current_user.id) | Q(supervisor=current_user), is_active=True).select_related('supervisor')
        else:
            users_to_process = User.objects.filter(id=current_user.id, is_active=True).select_related('supervisor')
        base_filters = (Q(ativo=True) & Q(status_tratamento__isnull=False) & (Q(status_esteira__isnull=True) | ~Q(status_esteira__nome__iexact='CANCELADA')))
        vendas = Venda.objects.filter(base_filters).values('vendedor_id').annotate(total_dia=Count('id', filter=Q(data_pedido__date=hoje)), total_mes=Count('id', filter=Q(data_pedido__date__gte=start_of_month)), total_mes_instalado=Count('id', filter=Q(data_pedido__date__gte=start_of_month, status_esteira__nome__iexact='Instalada')), vendas_segunda=Count('id', filter=Q(data_pedido__date=start_of_week)), vendas_terca=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=1))), vendas_quarta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=2))), vendas_quinta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=3))), vendas_sexta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=4))), vendas_sabado=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=5))))
        vendas_por_vendedor = {v['vendedor_id']: v for v in vendas}
        teams = defaultdict(lambda: {'supervisor_name': 'Sem Supervisor', 'members': [], 'totals': {'daily': 0, 'weekly_breakdown': {'seg': 0, 'ter': 0, 'qua': 0, 'qui': 0, 'sex': 0, 'sab': 0}, 'weekly_total': 0, 'monthly': {'total': 0, 'instalados': 0}}})
        for user in users_to_process:
            supervisor_id = user.supervisor.id if user.supervisor else 'none'
            if supervisor_id != 'none' and user.supervisor: teams[supervisor_id]['supervisor_name'] = user.supervisor.username
            v_data = vendas_por_vendedor.get(user.id, {})
            weekly_total = sum([v_data.get('vendas_segunda', 0), v_data.get('vendas_terca', 0), v_data.get('vendas_quarta', 0), v_data.get('vendas_quinta', 0), v_data.get('vendas_sexta', 0), v_data.get('vendas_sabado', 0)])
            total_mes = v_data.get('total_mes', 0)
            instalados_mes = v_data.get('total_mes_instalado', 0)
            aproveitamento_str = f"{(instalados_mes / total_mes * 100):.1f}%" if total_mes > 0 else "0.0%"
            teams[supervisor_id]['members'].append({'name': user.username, 'daily': v_data.get('total_dia', 0), 'weekly_breakdown': {'seg': v_data.get('vendas_segunda', 0), 'ter': v_data.get('vendas_terca', 0), 'qua': v_data.get('vendas_quarta', 0), 'qui': v_data.get('vendas_quinta', 0), 'sex': v_data.get('vendas_sexta', 0), 'sab': v_data.get('vendas_sabado', 0)}, 'weekly_total': weekly_total, 'monthly': {'total': total_mes, 'instalados': instalados_mes, 'aproveitamento': aproveitamento_str}})
        final_result = []
        for supervisor_id, team_data in teams.items():
            if not team_data['members']: continue
            team_data['members'] = sorted(team_data['members'], key=itemgetter('name'))
            for member in team_data['members']:
                team_data['totals']['daily'] += member['daily']
                for day, count in member['weekly_breakdown'].items(): team_data['totals']['weekly_breakdown'][day] += count
                team_data['totals']['weekly_total'] += member['weekly_total']
                team_data['totals']['monthly']['total'] += member['monthly']['total']
                team_data['totals']['monthly']['instalados'] += member['monthly']['instalados']
            total_geral = team_data['totals']['monthly']['total']
            inst_geral = team_data['totals']['monthly']['instalados']
            team_data['totals']['monthly']['aproveitamento'] = f"{(inst_geral / total_geral * 100):.1f}%" if total_geral > 0 else "0.0%"
            final_result.append(team_data)
        final_result = sorted(final_result, key=itemgetter('supervisor_name'))
        return Response(final_result)

class FecharPagamentoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            ano = int(request.data.get('ano'))
            mes = int(request.data.get('mes'))
            total_pago = request.data.get('total_pago', 0)
            
            status_pago = StatusCRM.objects.filter(tipo='Comissionamento', nome__iexact='PAGO').first()
            if not status_pago:
                status_pago = StatusCRM.objects.create(tipo='Comissionamento', nome='PAGO', cor='#198754')

            data_inicio = datetime(ano, mes, 1)
            if mes == 12: data_fim = datetime(ano + 1, 1, 1)
            else: data_fim = datetime(ano, mes + 1, 1)

            vendas_para_atualizar = Venda.objects.filter(
                ativo=True,
                status_esteira__nome__iexact='INSTALADA',
                data_instalacao__gte=data_inicio,
                data_instalacao__lt=data_fim
            ).exclude(status_comissionamento=status_pago)

            count = vendas_para_atualizar.count()
            vendas_para_atualizar.update(
                status_comissionamento=status_pago,
                data_pagamento_comissao=timezone.now().date()
            )

            PagamentoComissao.objects.update_or_create(
                referencia_ano=ano,
                referencia_mes=mes,
                defaults={
                    'total_pago_consultores': total_pago,
                    'data_fechamento': timezone.now()
                }
            )

            return Response({"mensagem": f"Fechamento realizado! {count} vendas atualizadas.", "vendas_atualizadas": count})
        
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ReabrirPagamentoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            ano = int(request.data.get('ano'))
            mes = int(request.data.get('mes'))

            status_pendente = StatusCRM.objects.filter(tipo='Comissionamento', nome__iexact='PENDENTE').first()
            if not status_pendente:
                return Response({"error": "Status 'PENDENTE' de comissionamento não encontrado."}, status=400)

            data_inicio = datetime(ano, mes, 1)
            if mes == 12: data_fim = datetime(ano + 1, 1, 1)
            else: data_fim = datetime(ano, mes + 1, 1)

            vendas_revertidas = Venda.objects.filter(
                status_esteira__nome__iexact='INSTALADA',
                data_instalacao__gte=data_inicio,
                data_instalacao__lt=data_fim,
                status_comissionamento__nome__iexact='PAGO'
            ).update(
                status_comissionamento=status_pendente,
                data_pagamento_comissao=None
            )

            PagamentoComissao.objects.filter(referencia_ano=ano, referencia_mes=mes).delete()

            return Response({"mensagem": "Mês reaberto com sucesso!", "vendas_revertidas": vendas_revertidas})

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class GerarRelatorioPDFView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ano = int(request.data.get('ano'))
        mes = int(request.data.get('mes'))
        consultores_ids = request.data.get('consultores', [])

        data_inicio = datetime(ano, mes, 1)
        if mes == 12: data_fim = datetime(ano + 1, 1, 1)
        else: data_fim = datetime(ano, mes + 1, 1)

        vendas = Venda.objects.filter(
            ativo=True,
            status_esteira__nome__iexact='INSTALADA',
            data_instalacao__gte=data_inicio,
            data_instalacao__lt=data_fim
        ).select_related('vendedor', 'cliente', 'plano', 'forma_pagamento', 'status_esteira')

        if consultores_ids:
            vendas = vendas.filter(vendedor_id__in=consultores_ids)

        anomes_str = f"{ano}{mes:02d}"
        churns = ImportacaoChurn.objects.filter(anomes_retirada=anomes_str)
        churn_map = {c.numero_pedido: c for c in churns}

        lista_final = []
        for v in vendas:
            eh_dacc = "SIM" if v.forma_pagamento and "DÉBITO" in v.forma_pagamento.nome.upper() else "NÃO"
            
            chave_busca = v.ordem_servico or "SEM_OS"
            dados_churn = churn_map.get(chave_busca)
            
            status_final = "ATIVO"
            dt_churn = "-"
            motivo_churn = "-"
            
            if dados_churn:
                status_final = "CHURN"
                dt_churn = dados_churn.dt_retirada.strftime('%d/%m/%Y') if dados_churn.dt_retirada else "S/D"
                motivo_churn = dados_churn.motivo_retirada or "Não informado"

            lista_final.append({
                'vendedor': v.vendedor.username.upper() if v.vendedor else 'SEM VENDEDOR',
                'cpf_cnpj': v.cliente.cpf_cnpj,
                'dacc': eh_dacc,
                'cliente': v.cliente.nome_razao_social.upper(),
                'plano': v.plano.nome.upper(),
                'dt_criacao': v.data_criacao.strftime('%d/%m/%Y'),
                'dt_instalacao': v.data_instalacao.strftime('%d/%m/%Y') if v.data_instalacao else "-",
                'os': v.ordem_servico or "-",
                'status_esteira': v.status_esteira.nome.upper() if v.status_esteira else "-",
                'dt_churn': dt_churn,
                'motivo_churn': motivo_churn,
                'situacao': status_final,
                'style_class': 'color: red; font-weight: bold;' if status_final == 'CHURN' else ''
            })

        lista_final.sort(key=itemgetter('vendedor', 'cliente'))

        html_string = f"""
        <html>
        <head>
            <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
            <style>
                @page {{ size: A4 landscape; margin: 1cm; }}
                body {{ font-family: Helvetica, sans-serif; font-size: 9px; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th {{ background-color: #f2f2f2; border: 1px solid #ccc; padding: 4px; text-align: left; font-weight: bold; }}
                td {{ border: 1px solid #ccc; padding: 3px; }}
                h2 {{ text-align: center; color: #333; margin-bottom: 5px; }}
                .meta {{ text-align: center; font-size: 10px; margin-bottom: 15px; color: #666; }}
            </style>
        </head>
        <body>
            <h2>Extrato de Comissionamento - {mes}/{ano}</h2>
            <div class="meta">Gerado em: {timezone.now().strftime('%d/%m/%Y %H:%M')} | Total Vendas: {len(lista_final)}</div>
            <table>
                <thead>
                    <tr>
                        <th>VENDEDOR</th>
                        <th>CPF/CNPJ</th>
                        <th>DACC</th>
                        <th>CLIENTE</th>
                        <th>PLANO</th>
                        <th>DT VENDA</th>
                        <th>DT INST</th>
                        <th>O.S.</th>
                        <th>STATUS</th>
                        <th>DT CHURN</th>
                        <th>MOTIVO</th>
                        <th>SITUAÇÃO</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for item in lista_final:
            html_string += f"""
            <tr style="{item['style_class']}">
                <td>{item['vendedor']}</td>
                <td>{item['cpf_cnpj']}</td>
                <td>{item['dacc']}</td>
                <td>{item['cliente'][:25]}</td>
                <td>{item['plano']}</td>
                <td>{item['dt_criacao']}</td>
                <td>{item['dt_instalacao']}</td>
                <td>{item['os']}</td>
                <td>{item['status_esteira']}</td>
                <td>{item['dt_churn']}</td>
                <td>{item['motivo_churn'][:15]}</td>
                <td>{item['situacao']}</td>
            </tr>
            """
        
        html_string += """
                </tbody>
            </table>
        </body>
        </html>
        """

        result = BytesIO()
        pdf = pisa.pisaDocument(BytesIO(html_string.encode("UTF-8")), result, encoding='utf-8')
        
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="extrato_comissao_{mes}_{ano}.pdf"'
            return response
        return Response({"error": "Erro ao gerar PDF"}, status=500)

class EnviarExtratoEmailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            # 1. Receber dados
            ano = int(request.data.get('ano'))
            mes = int(request.data.get('mes'))
            consultores_ids = request.data.get('consultores', []) 
            email_destino_manual = request.data.get('email_destino') 

            if not consultores_ids:
                return Response({"error": "Nenhum consultor selecionado."}, status=400)

            User = get_user_model()
            data_inicio = datetime(ano, mes, 1)
            if mes == 12: data_fim = datetime(ano + 1, 1, 1)
            else: data_fim = datetime(ano, mes + 1, 1)

            # Carregar dados de churn para o mês
            anomes_str = f"{ano}{mes:02d}"
            churns = ImportacaoChurn.objects.filter(anomes_retirada=anomes_str)
            churn_map = {c.numero_pedido: c for c in churns}

            sucessos = 0
            erros = []

            # 2. Loop para processar cada consultor selecionado
            for c_id in consultores_ids:
                try:
                    consultor = User.objects.get(id=c_id)
                    
                    # Regra de E-mail: 
                    target_email = None
                    if len(consultores_ids) == 1 and email_destino_manual:
                        target_email = email_destino_manual
                    else:
                        target_email = getattr(consultor, 'email', None)

                    if not target_email:
                        erros.append(f"{consultor.username}: Sem e-mail cadastrado.")
                        continue

                    # Buscar Vendas do Consultor
                    vendas = Venda.objects.filter(
                        ativo=True,
                        vendedor_id=c_id,
                        status_esteira__nome__iexact='INSTALADA',
                        data_instalacao__gte=data_inicio,
                        data_instalacao__lt=data_fim
                    ).select_related('plano', 'forma_pagamento', 'cliente')

                    if not vendas.exists():
                        erros.append(f"{consultor.username}: Sem vendas instaladas no período.")
                        continue

                    # --- Montar Dados ---
                    lista_detalhada = []
                    for v in vendas:
                        eh_dacc = "SIM" if v.forma_pagamento and "DÉBITO" in v.forma_pagamento.nome.upper() else "NÃO"
                        chave_busca = v.ordem_servico or "SEM_OS"
                        dados_churn = churn_map.get(chave_busca)
                        
                        status_final = "ATIVO"
                        dt_churn = "-"
                        motivo_churn = "-"
                        if dados_churn:
                            status_final = "CHURN"
                            dt_churn = dados_churn.dt_retirada.strftime('%d/%m/%Y') if dados_churn.dt_retirada else "S/D"
                            motivo_churn = dados_churn.motivo_retirada or "Não informado"

                        dt_pedido = v.data_pedido.strftime('%d/%m/%Y') if v.data_pedido else v.data_criacao.strftime('%d/%m/%Y')
                        dt_inst = v.data_instalacao.strftime('%d/%m/%Y') if v.data_instalacao else "-"

                        lista_detalhada.append({
                            'vendedor': v.vendedor.username.upper() if v.vendedor else 'SEM VENDEDOR',
                            'cpf_cnpj': v.cliente.cpf_cnpj,
                            'dacc': eh_dacc,
                            'cliente': v.cliente.nome_razao_social.upper(),
                            'plano': v.plano.nome.upper(),
                            'dt_pedido': dt_pedido,
                            'dt_inst': dt_inst,
                            'os': v.ordem_servico or "-",
                            'situacao': v.status_esteira.nome.upper() if v.status_esteira else "-",
                            'dt_churn': dt_churn,
                            'motivo_churn': motivo_churn,
                            'churn_ativo': status_final,
                            'color_style': 'color: red;' if status_final == 'CHURN' else ''
                        })
                    
                    lista_detalhada.sort(key=itemgetter('cliente'))

                    # --- Gerar HTML E-mail ---
                    html_content = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif; font-size: 12px;">
                        <h2 style="color: #333;">Extrato de Comissionamento - {consultor.username.upper()}</h2>
                        <p>Referência: <strong>{mes}/{ano}</strong></p>
                        <table border="1" cellpadding="4" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 10px;">
                            <thead style="background-color: #f2f2f2;">
                                <tr>
                                    <th>VENDEDOR</th><th>CPF/CNPJ</th><th>DACC</th><th>NOME CLIENTE</th><th>PLANO</th>
                                    <th>DT PEDIDO</th><th>DT INST</th><th>O.S</th><th>SITUAÇÃO</th>
                                    <th>DT CHURN</th><th>MOTIVO CHURN</th><th>CHURN_OU_ATIVO</th>
                                </tr>
                            </thead>
                            <tbody>
                    """
                    for item in lista_detalhada:
                        html_content += f"""
                            <tr style="{item['color_style']}">
                                <td>{item['vendedor']}</td>
                                <td>{item['cpf_cnpj']}</td>
                                <td>{item['dacc']}</td>
                                <td>{item['cliente'][:20]}</td>
                                <td>{item['plano']}</td>
                                <td>{item['dt_pedido']}</td>
                                <td>{item['dt_inst']}</td>
                                <td>{item['os']}</td>
                                <td>{item['situacao']}</td>
                                <td>{item['dt_churn']}</td>
                                <td>{item['motivo_churn'][:20]}</td>
                                <td><strong>{item['churn_ativo']}</strong></td>
                            </tr>
                        """
                    html_content += "</tbody></table><br><p>Segue anexo detalhado.</p></body></html>"

                    # --- Gerar PDF (Anexo) ---
                    html_pdf = f"""
                    <html><head><meta charset="utf-8">
                    <style>@page {{ size: A4 landscape; margin: 1cm; }} body {{ font-family: Helvetica; font-size: 9px; }} table {{ width: 100%; border-collapse: collapse; }} th, td {{ border: 1px solid #ccc; padding: 3px; }} th {{ background: #f2f2f2; }}</style>
                    </head><body>
                        <h2>Extrato {mes}/{ano} - {consultor.username.upper()}</h2>
                        <table><thead><tr>
                            <th>VENDEDOR</th><th>CPF/CNPJ</th><th>DACC</th><th>CLIENTE</th><th>PLANO</th>
                            <th>DT PEDIDO</th><th>DT INST</th><th>O.S</th><th>SITUAÇÃO</th>
                            <th>DT CHURN</th><th>MOTIVO</th><th>STATUS</th>
                        </tr></thead><tbody>
                    """
                    for item in lista_detalhada:
                        html_pdf += f"""<tr style="{item.get('color_style', '')}">
                            <td>{item['vendedor']}</td><td>{item['cpf_cnpj']}</td><td>{item['dacc']}</td>
                            <td>{item['cliente'][:25]}</td><td>{item['plano']}</td><td>{item['dt_pedido']}</td>
                            <td>{item['dt_inst']}</td><td>{item['os']}</td><td>{item['situacao']}</td>
                            <td>{item['dt_churn']}</td><td>{item['motivo_churn'][:15]}</td><td>{item['churn_ativo']}</td>
                        </tr>"""
                    html_pdf += "</tbody></table></body></html>"

                    pdf_buffer = BytesIO()
                    pisa_status = pisa.pisaDocument(BytesIO(html_pdf.encode("UTF-8")), pdf_buffer, encoding='utf-8')
                    
                    if pisa_status.err:
                        erros.append(f"{consultor.username}: Erro ao gerar PDF.")
                        continue

                    # --- Enviar ---
                    msg = EmailMultiAlternatives(
                        f"Extrato Comissionamento - {mes}/{ano} - {consultor.username}",
                        strip_tags(html_content),
                        settings.DEFAULT_FROM_EMAIL,
                        [target_email]
                    )
                    msg.attach_alternative(html_content, "text/html")
                    msg.attach(f"Extrato_{consultor.username}_{mes}_{ano}.pdf", pdf_buffer.getvalue(), 'application/pdf')
                    msg.send()
                    
                    sucessos += 1

                except Exception as e:
                    erros.append(f"Erro interno id {c_id}: {str(e)}")

            # 3. Retorno Final
            msg_final = f"Processo finalizado. Enviados: {sucessos}."
            if erros:
                msg_final += f" Falhas: {len(erros)}. Detalhes: {', '.join(erros)}"
            
            return Response({"mensagem": msg_final, "sucessos": sucessos, "erros": erros})

        except Exception as e:
            logger.error(f"Erro geral envio email: {e}")
            return Response({"error": str(e)}, status=500)