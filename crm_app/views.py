import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from collections import defaultdict
from operator import itemgetter
import base64
from io import BytesIO
import json
import os 

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
from django.contrib.staticfiles import finders

from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.decorators import api_view, permission_classes, action # <--- ACTION IMPORTADA

# --- IMPORTS WHATSAPP ---
from .whatsapp_service import WhatsAppService 
# ------------------------

from xhtml2pdf import pisa 

# Importando permissões customizadas
from usuarios.permissions import CheckAPIPermission, VendaPermission

from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia,
    RegraComissao, Cliente, Venda, ImportacaoOsab, ImportacaoChurn,
    CicloPagamento, HistoricoAlteracaoVenda, PagamentoComissao,
    Campanha 
)
from .serializers import (
    OperadoraSerializer, PlanoSerializer, FormaPagamentoSerializer,
    StatusCRMSerializer, MotivoPendenciaSerializer, RegraComissaoSerializer,
    VendaSerializer, VendaCreateSerializer, ClienteSerializer,
    VendaUpdateSerializer, ImportacaoOsabSerializer, ImportacaoChurnSerializer,
    CicloPagamentoSerializer, VendaDetailSerializer,
    CampanhaSerializer 
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

# --- FUNÇÃO PARA PEGAR/CRIAR O USUÁRIO ROBÔ DA IMPORTAÇÃO ---
def get_osab_bot_user():
    User = get_user_model()
    # Tenta buscar ou criar, passando uma senha dummy para passar na validação 'full_clean'
    bot, created = User.objects.get_or_create(
        username='OSAB_IMPORT',
        defaults={
            'first_name': 'OSAB',
            'last_name': 'Automático',
            'email': 'osab_import@sistema.local',
            'is_active': True,
            'password': 'senha_temporaria_validacao_sistema' # Necessário para passar no save() do model
        }
    )
    if created:
        bot.set_unusable_password() # Invalida a senha para ninguém logar com ela
        bot.save()
    return bot
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

# --- VIEWS DE CAMPANHAS ---
class CampanhaListCreateView(generics.ListCreateAPIView):
    queryset = Campanha.objects.filter(ativo=True)
    serializer_class = CampanhaSerializer
    permission_classes = [permissions.IsAuthenticated]

class CampanhaDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Campanha.objects.all()
    serializer_class = CampanhaSerializer
    permission_classes = [permissions.IsAuthenticated]
# --------------------------

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
    permission_classes = [VendaPermission] 
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
            'motivo_pendencia', 'auditor_atual'
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

    # --- AÇÃO 1: PEGAR TAREFA (TRAVAR VENDA) ---
    @action(detail=True, methods=['post'], url_path='alocar-auditoria')
    def alocar_auditoria(self, request, pk=None):
        venda = self.get_object()
        usuario = request.user

        if venda.auditor_atual and venda.auditor_atual != usuario:
            return Response(
                {"detail": f"Esta venda já está sendo auditada por {venda.auditor_atual}."},
                status=status.HTTP_409_CONFLICT
            )
        
        venda.auditor_atual = usuario
        venda.save()
        
        serializer = self.get_serializer(venda)
        return Response(serializer.data)

    # --- AÇÃO 2: LIBERAR TAREFA (DESTRAVAR) ---
    @action(detail=True, methods=['post'], url_path='liberar-auditoria')
    def liberar_auditoria(self, request, pk=None):
        venda = self.get_object()
        usuario = request.user
        
        is_supervisor = is_member(usuario, ['Diretoria', 'Admin', 'Supervisor'])
        
        if venda.auditor_atual and venda.auditor_atual != usuario and not is_supervisor:
             return Response(
                {"detail": "Você não tem permissão para liberar uma venda travada por outro auditor."},
                status=status.HTTP_403_FORBIDDEN
            )

        venda.auditor_atual = None
        venda.save()
        
        return Response({"detail": "Venda liberada com sucesso."})

    def perform_create(self, serializer):
        cpf = serializer.validated_data.pop('cliente_cpf_cnpj')
        nome = serializer.validated_data.pop('cliente_nome_razao_social')
        email = serializer.validated_data.pop('cliente_email', None)
        
        cliente, created = Cliente.objects.get_or_create(
            cpf_cnpj=cpf,
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
        instance = self.get_object()
        
        try:
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
        
        tem_permissao_card = user.has_perm('crm_app.can_view_comissao_dashboard')
        eh_gestor = is_member(user, ['Diretoria', 'Admin'])
        exibir_comissao = tem_permissao_card or eh_gestor

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

            if exibir_comissao:
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
                    
                    comissao_vendedor += valor_item
                comissao_total_geral += comissao_vendedor

            total_registradas_geral += qtd_registradas
            total_instaladas_geral += qtd_instaladas

        percentual_aproveitamento = 0.0
        if total_registradas_geral > 0:
            percentual_aproveitamento = (total_instaladas_geral / total_registradas_geral) * 100

        valor_comissao_final = comissao_total_geral if exibir_comissao else 0.0

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
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'cliente'

    def get_queryset(self):
        # ANOTAÇÃO: Conta vendas onde ativo=True
        queryset = Cliente.objects.annotate(
            vendas_count=Count('vendas', filter=Q(vendas__ativo=True))
        ).order_by('nome_razao_social')
        
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(nome_razao_social__icontains=search) | 
                Q(cpf_cnpj__icontains=search)
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
            
            # --- AGREGADORES ---
            stats_planos = defaultdict(lambda: {'qtd': 0, 'total': 0.0})
            stats_descontos = defaultdict(float)
            
            for v in vendas:
                # 1. Regra de Comissão
                doc = v.cliente.cpf_cnpj if v.cliente else ''
                doc_limpo = ''.join(filter(str.isdigit, doc))
                tipo_cliente = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
                canal_vendedor = getattr(consultor, 'canal', 'PAP') or 'PAP'
                
                regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor_id == consultor.id), None)
                if not regra:
                    regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor is None), None)
                
                valor_item = float(regra.valor_acelerado if bateu_meta else regra.valor_base) if regra else 0.0
                comissao_bruta += valor_item

                # AGREGAR PLANO (Nome, ValorUnit)
                key_plano = (v.plano.nome, valor_item)
                stats_planos[key_plano]['qtd'] += 1
                stats_planos[key_plano]['total'] += valor_item

                # 2. Calcular Descontos (Acumulado)
                if v.forma_pagamento and 'BOLETO' in v.forma_pagamento.nome.upper():
                    val = float(consultor.desconto_boleto or 0)
                    if val > 0: stats_descontos['Boleto'] += val

                if v.inclusao:
                    val = float(consultor.desconto_inclusao_viabilidade or 0)
                    if val > 0: stats_descontos['Inclusão/Viab.'] += val

                if v.antecipou_instalacao:
                    val = float(consultor.desconto_instalacao_antecipada or 0)
                    if val > 0: stats_descontos['Antecipação'] += val

                if len(doc_limpo) > 11:
                    val = float(consultor.adiantamento_cnpj or 0)
                    if val > 0: stats_descontos['Adiant. CNPJ'] += val

            # Consolidação Final
            total_descontos = sum(stats_descontos.values())
            premiacao = 0.0 
            bonus = 0.0
            valor_liquido = (comissao_bruta + premiacao + bonus) - total_descontos

            # Formatar lista de planos
            lista_planos_detalhe = []
            for (nome_plano, unitario), dados in stats_planos.items():
                lista_planos_detalhe.append({
                    'plano': nome_plano,
                    'unitario': unitario,
                    'qtd': dados['qtd'],
                    'total': dados['total']
                })
            lista_planos_detalhe.sort(key=lambda x: x['total'], reverse=True)

            # Formatar lista de descontos
            lista_descontos_detalhe = [{'motivo': k, 'valor': v} for k, v in stats_descontos.items()]

            relatorio.append({
                'consultor_id': consultor.id,
                'consultor_nome': consultor.username.upper(),
                'qtd_instaladas': qtd_instaladas,
                'meta': meta,
                'atingimento_pct': round(atingimento, 1),
                'comissao_bruta': comissao_bruta,
                'total_descontos': total_descontos,
                'valor_liquido': valor_liquido,
                'detalhes_planos': lista_planos_detalhe,
                'detalhes_descontos': lista_descontos_detalhe
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

class ImportacaoOsabView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_osab'
    parser_classes = [MultiPartParser, FormParser]

    def _clean_key(self, key):
        if pd.isna(key) or key is None: return None
        return str(key).replace('.0', '').strip()

    def get(self, request):
        queryset = ImportacaoOsab.objects.all().order_by('-id')[:100]
        serializer = ImportacaoOsabSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Nenhum arquivo foi enviado.'}, status=status.HTTP_400_BAD_REQUEST)
        
        # --- MAPEAMENTO NOVO DA PLANILHA ---
        coluna_map = {
            'PRODUTO': 'produto',
            'UF': 'uf',
            'DT_REF': 'dt_ref',
            'PEDIDO': 'documento',
            'SEGMENTO': 'segmento',
            'LOCALIDADE': 'localidade',
            'CELULA': 'celula',
            'ID_BUNDLE': 'id_bundle',
            'TELEFONE': 'telefone',
            'VELOCIDADE': 'velocidade',
            'MATRICULA_VENDEDOR': 'matricula_vendedor',
            'CLASSE_PRODUTO': 'classe_produto',
            'NOME_CNAL': 'nome_canal',
            'PDV_SAP': 'pdv_sap',
            'DESCRICAO': 'descricao',
            'DATA_ABERTURA': 'data_abertura',
            'DATA_FECHAMENTO': 'data_fechamento',
            'SITUACAO': 'situacao',
            'CLASSIFICACAO': 'classificacao',
            'DATA_AGENDAMENTO': 'data_agendamento',
            'COD_PENDENCIA': 'cod_pendencia',
            'DESC_PENDENCIA': 'desc_pendencia',
            'NUMERO_BA': 'numero_ba',
            'FG_VENDA_VALIDA': 'fg_venda_valida',
            'DESC_MOTIVO_ORDEM': 'desc_motivo_ordem',
            'DESC_SUB_MOTIVO_ORDEM': 'desc_sub_motivo_ordem',
            'MEIO_PAGAMENTO': 'meio_pagamento',
            'CAMPANHA': 'campanha',
            'FLG_MEI': 'flg_mei',
            'NM_DIRETORIA': 'nm_diretoria',
            'NM_REGIONAL': 'nm_regional',
            'CD_REDE': 'cd_rede',
            'GP_CANAL': 'gp_canal',
            'GERENCIA': 'gerencia',
            'NM_GC': 'gc',
        }

        try:
            df = None
            if file_obj.name.endswith('.xlsb'): df = pd.read_excel(file_obj, engine='pyxlsb')
            elif file_obj.name.endswith(('.xlsx', '.xls')): df = pd.read_excel(file_obj)
            else: return Response({'error': 'Formato de arquivo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e: return Response({'error': f'Erro ao ler o arquivo: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        
        df.columns = [str(col).strip().upper() for col in df.columns]
        
        date_cols = ['DT_REF', 'DATA_ABERTURA', 'DATA_FECHAMENTO', 'DATA_AGENDAMENTO']
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        df = df.replace({np.nan: None, pd.NaT: None})

        colunas_validas = {k: v for k, v in coluna_map.items() if k in df.columns}
        
        # --- MAPEAMENTO DE STATUS (OSAB -> SISTEMA) ---
        STATUS_MAP = {
            'REPROVADO ANALISE DE FRAUDE-PAYMENT_NOT_AUTHORIZED_RULE': 'REPROVADO CARTÃO DE CRÉDITO',
            'DRAFT-PAYMENT_STATUS_FAILED': 'DRAFT',
            'DRAFT-INVALID_SESSION_DATA': 'DRAFT',
            'DRAFT-SESSION_DATA_INVALID': 'DRAFT',
            'AGUARDANDO PAGAMENTO-SESSION_DATA_INVALID': 'AGUARDANDO PAGAMENTO',
            'AGUARDANDO PAGAMENTO-INVALID_SESSION_DATA': 'AGUARDANDO PAGAMENTO',
            'EM APROVISIONAMENTO': 'EM ANDAMENTO',
            'PENDÊNCIA CLIENTE': 'PENDENCIADA', 'PENDENCIA CLIENTE': 'PENDENCIADA',
            'CANCELADO': 'CANCELADA',
            'CONCLUÍDO': 'INSTALADA', 'CONCLUIDO': 'INSTALADA',
            'PENDÊNCIA TÉCNICA': 'PENDENCIADA', 'PENDENCIA TECNICA': 'PENDENCIADA'
        }
        
        status_esteira_objects = StatusCRM.objects.filter(tipo='Esteira')
        status_esteira_map = {status.nome.upper(): status for status in status_esteira_objects}
        
        vendas_com_os = Venda.objects.filter(ativo=True, ordem_servico__isnull=False).exclude(ordem_servico__exact='')
        vendas_map = {self._clean_key(v.ordem_servico): v for v in vendas_com_os}
        
        # --- PREPARAÇÃO PARA PENDÊNCIAS ---
        todos_motivos = MotivoPendencia.objects.all()
        motivo_pendencia_map = {}
        for m in todos_motivos:
            codigo = "".join(filter(str.isdigit, m.nome))[:2]
            if codigo:
                motivo_pendencia_map[codigo] = m
        
        motivo_validar_osab, _ = MotivoPendencia.objects.get_or_create(
            nome="VALIDAR OSAB", 
            defaults={'tipo_pendencia': 'Operacional'}
        )

        osab_bot = get_osab_bot_user()

        report = {
            "status": "sucesso", 
            "total_registros": len(df), 
            "criados": 0,             
            "atualizados": 0,          
            "vendas_encontradas": 0, 
            "ja_corretos": 0, 
            "status_nao_mapeado": 0, 
            "erros": []
        }
        
        vendas_para_atualizar_db = []
        registros_criados = 0
        registros_atualizados_imp = 0
        
        historicos_para_criar = []

        for index, row in df.iterrows():
            try:
                # 1. PROCESSAMENTO DA TABELA IMPORTACAO_OSAB
                dados_model = {}
                for col_planilha, campo_model in colunas_validas.items():
                    val = row.get(col_planilha)
                    if col_planilha == 'PEDIDO' and val is not None:
                        val = self._clean_key(val)
                    
                    if isinstance(val, (pd.Timestamp, datetime)):
                        val = val.date()
                    
                    dados_model[campo_model] = val
                
                doc_chave = dados_model.get('documento')
                
                if doc_chave:
                    obj_existente = ImportacaoOsab.objects.filter(documento=doc_chave).first()
                    
                    should_create = False
                    should_update = False

                    if not obj_existente:
                        should_create = True
                    else:
                        nova_dt = dados_model.get('dt_ref')
                        antiga_dt = obj_existente.dt_ref
                        
                        if nova_dt:
                            if not antiga_dt:
                                should_update = True
                            elif nova_dt > antiga_dt:
                                should_update = True
                    
                    if should_create:
                        ImportacaoOsab.objects.create(**dados_model)
                        registros_criados += 1
                    elif should_update:
                        for key, value in dados_model.items():
                            setattr(obj_existente, key, value)
                        obj_existente.save()
                        registros_atualizados_imp += 1

                # 2. ATUALIZACAO DE STATUS DA VENDA
                doc = self._clean_key(row.get('PEDIDO'))
                sit = row.get('SITUACAO')
                
                if not doc: continue
                
                venda = vendas_map.get(doc)
                if not venda: continue
                
                report["vendas_encontradas"] += 1
                
                if not sit: continue
                
                target_name = STATUS_MAP.get(str(sit).strip())
                if not target_name:
                    target_name = STATUS_MAP.get(str(sit).strip().upper())
                
                if not target_name:
                    sit_upper = str(sit).strip().upper()
                    if sit_upper.startswith("DRAFT"):
                        target_name = "DRAFT"
                    elif sit_upper.startswith("AGUARDANDO PAGAMENTO"):
                        target_name = "AGUARDANDO PAGAMENTO"
                
                if not target_name: 
                    report["status_nao_mapeado"] += 1
                    continue
                
                target_obj = status_esteira_map.get(target_name.upper())
                if not target_obj: 
                    report["status_nao_mapeado"] += 1
                    continue
                
                mudou_status = (venda.status_esteira is None) or (venda.status_esteira.id != target_obj.id)
                mudou_pendencia = False
                mudou_data_instalacao = False

                novo_motivo_pendencia = None
                if target_name == "PENDENCIADA":
                    cod_pendencia_planilha = str(row.get('COD_PENDENCIA', '')).strip()
                    prefixo = cod_pendencia_planilha[:2] if len(cod_pendencia_planilha) >= 2 else cod_pendencia_planilha
                    
                    if prefixo in motivo_pendencia_map:
                        novo_motivo_pendencia = motivo_pendencia_map[prefixo]
                    else:
                        novo_motivo_pendencia = motivo_validar_osab
                    
                    if venda.motivo_pendencia != novo_motivo_pendencia:
                        venda.motivo_pendencia = novo_motivo_pendencia
                        mudou_pendencia = True

                # NOVA REGRA: Atualizar Data Instalação se for INSTALADA
                if target_name == 'INSTALADA':
                    data_fechamento = row.get('DATA_FECHAMENTO')
                    if data_fechamento and not pd.isna(data_fechamento):
                        if isinstance(data_fechamento, (pd.Timestamp, datetime)):
                            data_fechamento = data_fechamento.date()
                        
                        if venda.data_instalacao != data_fechamento:
                            venda.data_instalacao = data_fechamento
                            mudou_data_instalacao = True

                if not mudou_status and not mudou_pendencia and not mudou_data_instalacao:
                    report["ja_corretos"] += 1
                else:
                    if mudou_status:
                        venda.status_esteira = target_obj
                    
                    vendas_para_atualizar_db.append(venda)
                    
                    detalhes_hist = {}
                    if mudou_status:
                        detalhes_hist['status_esteira'] = f"Alterado para {target_obj.nome} via Importação OSAB"
                    if mudou_pendencia:
                        detalhes_hist['motivo_pendencia'] = f"Definido como {novo_motivo_pendencia.nome} (Cód: {row.get('COD_PENDENCIA')})"
                    if mudou_data_instalacao:
                        detalhes_hist['data_instalacao'] = f"Atualizada para {venda.data_instalacao} via OSAB"
                    
                    historicos_para_criar.append(
                        HistoricoAlteracaoVenda(
                            venda=venda,
                            usuario=osab_bot,
                            alteracoes=detalhes_hist
                        )
                    )

            except Exception as ex:
                report['erros'].append(f"Erro linha {index}: {str(ex)}")

        report["criados"] = registros_criados
        
        if vendas_para_atualizar_db:
            report["atualizados"] = len(vendas_para_atualizar_db)
            campos_update = ['status_esteira', 'data_instalacao', 'motivo_pendencia']
            Venda.objects.bulk_update(vendas_para_atualizar_db, campos_update)
            
            if historicos_para_criar:
                HistoricoAlteracaoVenda.objects.bulk_create(historicos_para_criar)

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

# --- LOGIN E TROCA DE SENHA ---

@method_decorator(ensure_csrf_cookie, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        u = authenticate(request, username=username, password=password)
        
        if u:
            refresh = RefreshToken.for_user(u)
            
            # Verifica se o usuário precisa trocar a senha
            # Usamos getattr com default False para evitar erro caso o campo não exista
            precisa_trocar = getattr(u, 'must_change_password', False)

            return JsonResponse({
                'access_token': str(refresh.access_token),
                'refresh_token': str(refresh),
                'must_change_password': precisa_trocar,  # Envia o flag para o frontend
                'user_id': u.id
            })
            
        return Response({"detail": "Credenciais inválidas"}, status=401)

class DefinirNovaSenhaView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        nova_senha = request.data.get('nova_senha')
        if not nova_senha:
            return Response({"error": "A nova senha é obrigatória."}, status=400)
        
        user = request.user
        user.set_password(nova_senha)
        
        # Se o modelo tiver esse campo, atualizamos para False
        if hasattr(user, 'must_change_password'):
            user.must_change_password = False
            
        user.save()
        return Response({"mensagem": "Senha alterada com sucesso!"})

# --- NOVO ENDPOINT PARA VERIFICAR WHATSAPP ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_verificar_whatsapp(request, telefone):
    service = WhatsAppService()
    return Response({'telefone': telefone, 'possui_whatsapp': service.verificar_numero_existe(telefone)})

# --- VIEW ENVIO WHATSAPP ---
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def enviar_comissao_whatsapp(request):
    try:
        data = json.loads(request.body)
        ano = int(data.get('ano'))
        mes = int(data.get('mes'))
        consultores_ids = data.get('consultores', [])

        if not consultores_ids:
            return JsonResponse({'error': 'Nenhum consultor selecionado'}, status=400)

        User = get_user_model()
        data_inicio = datetime(ano, mes, 1)
        if mes == 12: data_fim = datetime(ano + 1, 1, 1)
        else: data_fim = datetime(ano, mes + 1, 1)

        img_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'banner_comissao.png')
        
        imagem_b64_final = None
        if os.path.exists(img_path):
            try:
                with open(img_path, "rb") as img_file:
                    encoded_string = base64.b64encode(img_file.read()).decode('utf-8')
                    imagem_b64_final = f"data:image/png;base64,{encoded_string}"
            except Exception as e:
                print(f"Erro ao ler imagem: {e}")

        service = WhatsAppService()
        sucessos = 0
        erros = []

        for user_id in consultores_ids:
            try:
                consultor = User.objects.get(id=user_id)
                telefone = getattr(consultor, 'tel_whatsapp', None)
                
                if not telefone:
                    erros.append(f"{consultor.username}: Sem WhatsApp.")
                    continue
                
                pdf_buffer = BytesIO()
                html_dummy = f"""
                <html>
                <body>
                    <h1 style="color: blue;">Extrato de Comissão</h1>
                    <p>Referência: {mes}/{ano}</p>
                    <p>Consultor: <strong>{consultor.username}</strong></p>
                    <p>Este é um teste de envio.</p>
                </body>
                </html>
                """
                pisa.CreatePDF(BytesIO(html_dummy.encode('utf-8')), dest=pdf_buffer)
                pdf_bytes = pdf_buffer.getvalue()
                pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                pdf_final = f"data:application/pdf;base64,{pdf_b64}"

                msg = f"Olá {consultor.username}, segue seu extrato de {mes}/{ano}."
                service.enviar_mensagem_texto(telefone, msg)
                
                if imagem_b64_final:
                    service.enviar_imagem_b64(telefone, imagem_b64_final, caption="Pagamento")
                
                service.enviar_pdf_b64(telefone, pdf_final, nome_arquivo="extrato.pdf")
                sucessos += 1

            except Exception as e:
                print(f"Erro user {user_id}: {e}")
                erros.append(str(e))

        return JsonResponse({'mensagem': f'Enviado: {sucessos}. Erros: {len(erros)}'})

    except Exception as e:
        print(f"Erro Geral View: {e}")
        return JsonResponse({'error': str(e)}, status=500)