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
import calendar
import re
import xml.etree.ElementTree as ET
import unicodedata
import threading
import requests


# --- CORREÇÃO CRÍTICA: Importar transaction e IntegrityError ---
from django.db import transaction, IntegrityError
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.timezone import now
from django.contrib.auth import get_user_model, authenticate
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.http import JsonResponse, HttpResponse
from django.template.loader import get_template
from django.shortcuts import render  # <--- Adicionado para renderizar HTML
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from .models import CdoiSolicitacao, CdoiBloco
from .onedrive_service import OneDriveUploader

from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.decorators import api_view, permission_classes, action
from openpyxl.utils import get_column_letter


# --- IMPORTS EXTRAS DO PROJETO ---
from core.models import DiaFiscal
from core.validators import validar_cpf, validar_cnpj, validar_cpf_ou_cnpj
from .whatsapp_service import WhatsAppService
from xhtml2pdf import pisa
from usuarios.permissions import CheckAPIPermission, VendaPermission
import openpyxl 
from openpyxl.styles import Font, PatternFill, Alignment
from .models import GrupoDisparo
from .serializers import GrupoDisparoSerializer
from .models import LancamentoFinanceiro
from .serializers import LancamentoFinanceiroSerializer


# Funções de Mapa (Geometria e Busca)
from .utils import (
    verificar_viabilidade_por_cep,
    verificar_viabilidade_por_coordenadas,
    verificar_viabilidade_exata
)

# Modelos do App
from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia,
    RegraComissao, Cliente, Venda, ImportacaoOsab, ImportacaoChurn,
    CicloPagamento, HistoricoAlteracaoVenda, PagamentoComissao,
    Campanha, ComissaoOperadora, Comunicado, AreaVenda,
    SessaoWhatsapp, DFV, GrupoDisparo, LancamentoFinanceiro,
    AgendamentoDisparo
)

# Serializers do App
from .serializers import (
    OperadoraSerializer, PlanoSerializer, FormaPagamentoSerializer,
    StatusCRMSerializer, MotivoPendenciaSerializer, RegraComissaoSerializer,
    VendaSerializer, VendaCreateSerializer, ClienteSerializer,
    VendaUpdateSerializer, ImportacaoOsabSerializer, ImportacaoChurnSerializer,
    CicloPagamentoSerializer, VendaDetailSerializer,
    CampanhaSerializer, ComissaoOperadoraSerializer, ComunicadoSerializer
)

logger = logging.getLogger(__name__)

def is_member(user, groups):
    if user.is_superuser:
        return True
    if user.groups.filter(name__in=groups).exists():
        return True
    if hasattr(user, 'perfil') and user.perfil and user.perfil.nome in groups:
        return True
    return False

def get_osab_bot_user():
    User = get_user_model()
    bot, created = User.objects.get_or_create(
        username='OSAB_IMPORT',
        defaults={
            'first_name': 'OSAB',
            'last_name': 'Automático',
            'email': 'osab_import@sistema.local',
            'is_active': True,
            'password': 'senha_temporaria_validacao_sistema'
        }
    )
    if created:
        bot.set_unusable_password()
        bot.save()
    return bot

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
    serializer_class = PlanoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Plano.objects.filter(ativo=True)
        operadora_id = self.request.query_params.get('operadora')
        if operadora_id:
            queryset = queryset.filter(operadora_id=operadora_id)
        return queryset

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

class CampanhaListCreateView(generics.ListCreateAPIView):
    queryset = Campanha.objects.filter(ativo=True)
    serializer_class = CampanhaSerializer
    permission_classes = [permissions.IsAuthenticated]

class CampanhaDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Campanha.objects.all()
    serializer_class = CampanhaSerializer
    permission_classes = [permissions.IsAuthenticated]

class ComissaoOperadoraViewSet(viewsets.ModelViewSet):
    queryset = ComissaoOperadora.objects.select_related('plano').all()
    serializer_class = ComissaoOperadoraSerializer
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

class ComunicadoViewSet(viewsets.ModelViewSet):
    queryset = Comunicado.objects.all().order_by('-id')
    serializer_class = ComunicadoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(criado_por=self.request.user)

class VendaViewSet(viewsets.ModelViewSet):
    permission_classes = [VendaPermission]
    resource_name = 'venda'
    queryset = Venda.objects.filter(ativo=True).order_by('-data_criacao')

    def get_serializer_context(self):
        context = super(VendaViewSet, self).get_serializer_context()
        context.update({"request": self.request})
        return context

    def get_serializer_class(self):
        if self.action == 'retrieve': return VendaDetailSerializer
        if self.action == 'create': return VendaCreateSerializer
        if self.action in ['update', 'partial_update']: return VendaUpdateSerializer
        return VendaSerializer

    def get_queryset(self):
        queryset = Venda.objects.filter(ativo=True).select_related(
            'vendedor', 'cliente', 'plano', 'forma_pagamento',
            'status_tratamento', 'status_esteira', 'status_comissionamento',
            'motivo_pendencia', 'auditor_atual'
        ).prefetch_related('historico_alteracoes__usuario').order_by('-data_criacao')
        
        user = self.request.user
        view_type = self.request.query_params.get('view')
        flow = self.request.query_params.get('flow')
        search = self.request.query_params.get('search')
        
        # --- REGRA DE DATA OBRIGATÓRIA (MÊS ATUAL) ---
        grupos_livres = ['Diretoria', 'Admin', 'BackOffice', 'Auditoria', 'Qualidade']
        eh_gestao_total = is_member(user, grupos_livres)

        if not eh_gestao_total and not search:
            # Se não for gestão e não estiver buscando por CPF/OS específico:
            hoje = timezone.now()
            inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Filtra vendas criadas ou instaladas neste mês
            queryset = queryset.filter(Q(data_criacao__gte=inicio_mes) | Q(data_instalacao__gte=inicio_mes))

        # --- FILTRO DE STATUS ---
        status_filter = self.request.query_params.get('status')
        if status_filter:
            status_upper = status_filter.upper()
            if status_upper == 'CANCELADO':
                queryset = queryset.filter(status_esteira__nome__icontains='CANCELAD')
            elif 'PENDEN' in status_upper:
                queryset = queryset.filter(status_esteira__nome__icontains='PENDEN')
            else:
                queryset = queryset.filter(status_esteira__nome__iexact=status_filter)

        # --- FILTRO DE BUSCA GLOBAL ---
        if search:
            search_clean = re.sub(r'\D', '', search)
            filters = Q(ordem_servico__icontains=search) | \
                      Q(cliente__nome_razao_social__icontains=search) | \
                      Q(cliente__cpf_cnpj__icontains=search)
            if search_clean:
                filters |= Q(cliente__cpf_cnpj__icontains=search_clean)
                filters |= Q(ordem_servico__icontains=search_clean)
            queryset = queryset.filter(filters)

        # --- PERMISSÕES DE VISUALIZAÇÃO ---
        acoes_gestao = ['retrieve', 'update', 'partial_update', 'destroy', 'alocar_auditoria', 'liberar_auditoria', 'finalizar_auditoria', 'pendentes_auditoria', 'reenviar_whatsapp_aprovacao', 'exportar_excel']

        if self.action in acoes_gestao:
            grupos_gestao_acao = ['Diretoria', 'Admin', 'BackOffice', 'Auditoria', 'Qualidade']
            if user.is_superuser or is_member(user, grupos_gestao_acao):
                return queryset
            if is_member(user, ['Supervisor']):
                liderados_ids = list(user.liderados.values_list('id', flat=True))
                liderados_ids.append(user.id)
                return queryset.filter(vendedor_id__in=liderados_ids)
            return queryset.filter(vendedor=user)

        if not view_type:
            if flow and is_member(user, ['Diretoria', 'Admin', 'BackOffice', 'Auditoria', 'Qualidade']):
                view_type = 'geral'
            else:
                view_type = 'minhas_vendas'

        if view_type == 'minhas_vendas':
            queryset = queryset.filter(vendedor=user)
        
        elif view_type == 'visao_equipe' or view_type == 'geral':
            if is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
                pass 
            elif is_member(user, ['Auditoria', 'Qualidade']):
                pass # Já filtrado no inicio
            elif is_member(user, ['Supervisor']):
                liderados_ids = list(user.liderados.values_list('id', flat=True))
                liderados_ids.append(user.id)
                queryset = queryset.filter(vendedor_id__in=liderados_ids)
            else:
                return queryset.none()

        # Filtros Avançados (Data, OS, Consultor)
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
            queryset = queryset.filter(status_esteira__isnull=False, status_esteira__estado__iexact='ABERTO')
        elif flow == 'comissionamento':
            queryset = queryset.filter(status_esteira__nome__iexact='Instalada').exclude(status_comissionamento__nome__iexact='Pago')

        if ordem_servico:
            queryset = queryset.filter(ordem_servico__icontains=ordem_servico)

        # Se houver datas especificas vindas do front (e o usuário tiver permissão de filtrar), aplica
        if data_inicio_str and data_fim_str and eh_gestao_total:
            try:
                dt_ini = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                dt_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date() + timedelta(days=1)
                queryset = queryset.filter(Q(data_criacao__range=(dt_ini, dt_fim)) | Q(data_instalacao__range=(dt_ini, dt_fim)))
            except: pass
            
        return queryset
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # Validar CPF/CNPJ antes de processar
        if 'cliente_cpf_cnpj' in request.data:
            try:
                validar_cpf_ou_cnpj(request.data['cliente_cpf_cnpj'])
            except ValidationError as e:
                return Response({"cliente_cpf_cnpj": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validar CPF do Representante Legal se fornecido
        if 'cpf_representante_legal' in request.data and request.data['cpf_representante_legal']:
            try:
                validar_cpf(request.data['cpf_representante_legal'])
            except ValidationError as e:
                return Response({"cpf_representante_legal": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        
        if not serializer.is_valid():
            # --- LOG DE ERRO NO TERMINAL ---
            import json
            print("\n" + "="*60)
            print(f"!!! ERRO 400 AO SALVAR VENDA #{instance.id} !!!")
            print(f"DADOS ENVIADOS: {json.dumps(request.data, indent=2, default=str)}")
            print("-" * 10)
            print(f"MOTIVO DO ERRO: {json.dumps(serializer.errors, indent=2, default=str)}")
            print("="*60 + "\n")
            # -------------------------------
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self.perform_update(serializer)

        if getattr(instance, '_prefetched_objects_cache', None):
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        # Validar CPF/CNPJ antes de processar
        if 'cliente_cpf_cnpj' in request.data:
            try:
                validar_cpf_ou_cnpj(request.data['cliente_cpf_cnpj'])
            except ValidationError as e:
                return Response({"cliente_cpf_cnpj": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validar CPF do Representante Legal se fornecido
        if 'cpf_representante_legal' in request.data and request.data['cpf_representante_legal']:
            try:
                validar_cpf(request.data['cpf_representante_legal'])
            except ValidationError as e:
                return Response({"cpf_representante_legal": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=True, methods=['post'], url_path='reenviar-whatsapp-aprovacao', permission_classes=[permissions.IsAuthenticated])
    def reenviar_whatsapp_aprovacao(self, request, pk=None):
        venda = self.get_object()
        if not venda.vendedor or not venda.vendedor.tel_whatsapp:
            return Response({"detail": "Venda sem vendedor ou vendedor sem WhatsApp cadastrado."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            svc = WhatsAppService()
            svc.enviar_mensagem_cadastrada(venda, telefone_destino=venda.vendedor.tel_whatsapp)
            return Response({"detail": "Mensagem reenviada com sucesso!"})
        except Exception as e:
            logger.error(f"Erro reenvio zap: {e}")
            return Response({"detail": "Erro ao tentar enviar mensagem."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def pendentes_auditoria(self, request):
        request.GET._mutable = True; request.GET['flow'] = 'auditoria'; request.GET['view'] = 'geral'; request.GET._mutable = False
        qs = self.filter_queryset(self.get_queryset())
        qs = qs.exclude(status_tratamento__estado__iexact='FECHADO')
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='alocar-auditoria', permission_classes=[permissions.IsAuthenticated])
    def alocar_auditoria(self, request, pk=None):
        venda = self.get_object()
        usuario = request.user
        grupos_permitidos = ['Diretoria', 'Admin', 'BackOffice', 'Supervisor', 'Auditoria', 'Qualidade']
        if not is_member(usuario, grupos_permitidos):
             return Response({"detail": "Permissão negada. Apenas auditores podem alocar vendas."}, status=status.HTTP_403_FORBIDDEN)
        if venda.auditor_atual and venda.auditor_atual != usuario:
            return Response({"detail": f"Esta venda já está sendo auditada por {venda.auditor_atual}."}, status=status.HTTP_409_CONFLICT)
        venda.auditor_atual = usuario
        venda.save()
        serializer = self.get_serializer(venda)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='liberar-auditoria', permission_classes=[permissions.IsAuthenticated])
    def liberar_auditoria(self, request, pk=None):
        venda = self.get_object()
        usuario = request.user
        is_supervisor = is_member(usuario, ['Diretoria', 'Admin', 'Supervisor'])
        if venda.auditor_atual and venda.auditor_atual != usuario and not is_supervisor:
             return Response({"detail": "Você não tem permissão para liberar uma venda travada por outro auditor."}, status=status.HTTP_403_FORBIDDEN)
        venda.auditor_atual = None
        venda.save()
        return Response({"detail": "Venda liberada com sucesso."})

    @action(detail=True, methods=['post'], url_path='finalizar_auditoria', permission_classes=[permissions.IsAuthenticated])
    def finalizar_auditoria(self, request, pk=None):
        venda = self.get_object()
        grupos_permitidos = ['Diretoria', 'Admin', 'BackOffice', 'Supervisor', 'Auditoria', 'Qualidade']
        if not is_member(request.user, grupos_permitidos):
             return Response({"detail": "Permissão negada."}, status=status.HTTP_403_FORBIDDEN)

        status_novo_id = request.data.get('status')
        observacoes = request.data.get('observacoes', '')
        dados_edicao = request.data.get('dados_atualizados', {})

        if not status_novo_id:
             return Response({"detail": "Status inválido."}, status=status.HTTP_400_BAD_REQUEST)

        status_obj = None
        if str(status_novo_id).isdigit():
             status_obj = StatusCRM.objects.filter(id=int(status_novo_id)).first()
        else:
             termo = str(status_novo_id).upper()
             if 'APROVAD' in termo: termo = 'AUDITADA'
             status_obj = StatusCRM.objects.filter(nome__iexact=termo, tipo='Tratamento').first()
             if not status_obj:
                 status_obj = StatusCRM.objects.filter(nome__icontains=termo, tipo='Tratamento').first()

        if not status_obj:
             return Response({"detail": f"Status '{status_novo_id}' não encontrado no banco."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                if dados_edicao:
                    cli_updates = {}
                    if 'cliente_nome' in dados_edicao: cli_updates['nome_razao_social'] = dados_edicao['cliente_nome'].upper()
                    if 'cliente_cpf' in dados_edicao: cli_updates['cpf_cnpj'] = re.sub(r'\D', '', dados_edicao['cliente_cpf'])
                    if 'cliente_email' in dados_edicao: cli_updates['email'] = dados_edicao['cliente_email']
                    
                    if cli_updates:
                        for k, v in cli_updates.items(): setattr(venda.cliente, k, v)
                        venda.cliente.save()

                    if 'nome_mae' in dados_edicao: venda.nome_mae = (dados_edicao['nome_mae'] or '').upper()
                    if 'data_nascimento' in dados_edicao: 
                        dt = dados_edicao['data_nascimento']
                        venda.data_nascimento = None if dt == "" else dt
                    if 'telefone1' in dados_edicao: venda.telefone1 = dados_edicao['telefone1']
                    if 'telefone2' in dados_edicao: venda.telefone2 = dados_edicao['telefone2']
                    if 'cep' in dados_edicao: venda.cep = str(dados_edicao['cep'])[:9]
                    if 'logradouro' in dados_edicao: venda.logradouro = (dados_edicao['logradouro'] or '').upper()
                    if 'numero' in dados_edicao: venda.numero_residencia = dados_edicao['numero']
                    if 'complemento' in dados_edicao: venda.complemento = (dados_edicao['complemento'] or '').upper()
                    if 'bairro' in dados_edicao: venda.bairro = (dados_edicao['bairro'] or '').upper()
                    if 'cidade' in dados_edicao: venda.cidade = (dados_edicao['cidade'] or '').upper()
                    if 'estado' in dados_edicao: venda.estado = str(dados_edicao['estado'] or '').upper()[:2]
                    if 'referencia' in dados_edicao: venda.ponto_referencia = (dados_edicao['referencia'] or '').upper()
                    if 'plano' in dados_edicao and dados_edicao['plano']: venda.plano_id = dados_edicao['plano']
                    if 'forma_pagamento' in dados_edicao and dados_edicao['forma_pagamento']: venda.forma_pagamento_id = dados_edicao['forma_pagamento']
                    if 'data_agendamento' in dados_edicao: 
                        dt_ag = dados_edicao['data_agendamento']
                        venda.data_agendamento = None if dt_ag == "" else dt_ag
                    if 'periodo_agendamento' in dados_edicao: venda.periodo_agendamento = dados_edicao['periodo_agendamento']

                venda.status_tratamento = status_obj
                if observacoes: venda.observacoes = observacoes
                venda.auditor_atual = None
                
                # --- BLOCO CORRIGIDO ---
                if status_obj.nome.upper() == 'CADASTRADA':
                    # Esta linha e as abaixo devem estar alinhadas (identadas)
                    venda.data_abertura = timezone.now()
                    
                    if not venda.status_esteira:
                        st_agendado = StatusCRM.objects.filter(nome__iexact='AGENDADO', tipo='Esteira').first()
                        if st_agendado: 
                            venda.status_esteira = st_agendado

                venda.save()
                
                HistoricoAlteracaoVenda.objects.create(
                    venda=venda,
                    usuario=request.user,
                    alteracoes={'status_tratamento': f"Auditoria finalizada: {status_obj.nome}", 'dados_editados': bool(dados_edicao)}
                )

                nm_st = status_obj.nome.upper()
                STATUS_SUCESSO = ['AUDITADA', 'CADASTRADA', 'APROVADA', 'INSTALADA', 'AGENDADO', 'CONCLUIDA', 'CONCLUÍDA']
                eh_repro = not any(s in nm_st for s in STATUS_SUCESSO)
                
                if eh_repro and venda.vendedor and venda.vendedor.tel_whatsapp:
                    try:
                        svc = WhatsAppService()
                        end_parts = []
                        if venda.logradouro: end_parts.append(venda.logradouro)
                        if venda.numero_residencia: end_parts.append(venda.numero_residencia)
                        if venda.bairro: end_parts.append(venda.bairro)
                        end_str = ", ".join(end_parts) if end_parts else "Endereço não informado"

                        msg_text = (
                            f"*Nome Completo:* {venda.cliente.nome_razao_social}\n"
                            f"*CPF/CNPJ:* {venda.cliente.cpf_cnpj}\n"
                            f"*Endereço de Instalação:* {end_str}\n"
                            f"*Status de Auditoria:* {status_obj.nome}\n"
                            f"*Observações:* {observacoes or 'Verificar no sistema.'}"
                        )
                        svc.enviar_mensagem_texto(venda.vendedor.tel_whatsapp, msg_text)
                        logger.info(f"Zap de reprovação enviado para {venda.vendedor.username}")
                    except Exception as e_zap:
                        logger.error(f"Erro ao enviar Zap Reprovação: {e_zap}")

            return Response({"status": "Auditoria finalizada com sucesso."})

        except Exception as e:
            logger.error(f"Erro crítico auditoria: {str(e)}", exc_info=True)
            return Response({"detail": f"Erro ao salvar dados: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    def perform_create(self, serializer):
        raw_cpf = serializer.validated_data.pop('cliente_cpf_cnpj')
        cpf_limpo = re.sub(r'\D', '', raw_cpf)
        
        nome = serializer.validated_data.pop('cliente_nome_razao_social')
        email = serializer.validated_data.pop('cliente_email', None)
        
        cliente, created = Cliente.objects.get_or_create(
            cpf_cnpj=cpf_limpo,
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

        cliente_data = serializer.validated_data.get('cliente')
        if cliente_data and 'cpf_cnpj' in cliente_data:
             cliente_data['cpf_cnpj'] = re.sub(r'\D', '', cliente_data['cpf_cnpj'])

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

        # --- 2. NOVA LÓGICA DE NOTIFICAÇÃO WHATSAPP (ESTEIRA) ---
        if venda_atualizada.status_esteira and venda_atualizada.status_esteira != status_esteira_antes:
            novo_status_nome = venda_atualizada.status_esteira.nome.upper()
            
            if ('PENDEN' in novo_status_nome or 'AGENDADO' in novo_status_nome or 'INSTALADA' in novo_status_nome) and 'CANCEL' not in novo_status_nome:
                
                if venda_atualizada.vendedor and venda_atualizada.vendedor.tel_whatsapp:
                    try:
                        svc = WhatsAppService()
                        msg = ""
                        
                        cliente_nome = venda_atualizada.cliente.nome_razao_social
                        os_num = venda_atualizada.ordem_servico or "Não informada"
                        status_label = venda_atualizada.status_esteira.nome
                        obs = venda_atualizada.observacoes or "Sem observações"

                        if 'PENDEN' in novo_status_nome:
                            motivo = venda_atualizada.motivo_pendencia.nome if venda_atualizada.motivo_pendencia else "Não informado"
                            msg = (
                                f"⚠️ *VENDA PENDENCIADA*\n\n"
                                f"*Nome do cliente:* {cliente_nome}\n"
                                f"*O.S:* {os_num}\n"
                                f"*Status:* {status_label}\n"
                                f"*Motivo pendência:* {motivo}\n"
                                f"*Observação:* {obs}"
                            )

                        elif 'AGENDADO' in novo_status_nome:
                            data_ag = venda_atualizada.data_agendamento.strftime('%d/%m/%Y') if venda_atualizada.data_agendamento else "Não informada"
                            turno = venda_atualizada.get_periodo_agendamento_display() if venda_atualizada.periodo_agendamento else "Não informado"
                            msg = (
                                f"📅 *VENDA AGENDADA*\n\n"
                                f"*Nome do cliente:* {cliente_nome}\n"
                                f"*O.S:* {os_num}\n"
                                f"*Status:* {status_label}\n"
                                f"*Data e turno agendado:* {data_ag} - {turno}\n"
                                f"*Observação:* {obs}\n\n"
                                f"Lembrete: Peça ao seu cliente que salve o número 21 4040-1810, o técnico toda vez que coloca uma pendência o CO Digital faz uma ligação automática ao cliente para confirmar. Salvando o número ele atende e evita pendências indevidas!"
                            )

                        elif 'INSTALADA' in novo_status_nome:
                            data_inst = venda_atualizada.data_instalacao.strftime('%d/%m/%Y') if venda_atualizada.data_instalacao else date.today().strftime('%d/%m/%Y')
                            msg = (
                                f"✅ *VENDA INSTALADA*\n\n"
                                f"*Nome do cliente:* {cliente_nome}\n"
                                f"*O.S:* {os_num}\n"
                                f"*Status:* {status_label}\n"
                                f"*Data instalada:* {data_inst}\n"
                                f"*Observação:* {obs}"
                            )
                        
                        if msg:
                            svc.enviar_mensagem_texto(venda_atualizada.vendedor.tel_whatsapp, msg)
                            logger.info(f"Zap Esteira ({novo_status_nome}) enviado para {venda_atualizada.vendedor.username}")

                    except Exception as e:
                        logger.error(f"Erro ao enviar Zap Esteira: {e}")

        return venda_atualizada

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

    # --- NOVA AÇÃO: EXPORTAR EXCEL ---
    @action(detail=False, methods=['get'], url_path='exportar-excel')
    def exportar_excel(self, request):
        user = request.user
        # Apenas Diretoria, Admin e BackOffice podem exportar
        if not is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            return Response({"detail": "Acesso negado."}, status=status.HTTP_403_FORBIDDEN)

        # Pega todos os dados (sem paginação) aplicando os filtros atuais da tela
        vendas = self.filter_queryset(self.get_queryset())
        
        # Criação do Workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Base Completa"

        # 1. Definição dos Cabeçalhos (Colunas)
        headers = [
            'ID', 'Data Criação', 'Data Abertura (OS)', 'Vendedor', 'Supervisor', 'Canal',
            'Cliente', 'CPF/CNPJ', 'Telefone 1', 'Telefone 2', 'Email',
            'Plano', 'Valor', 'Forma Pagamento', 
            'Status Esteira', 'Status Tratamento', 'Status Comissionamento',
            'OS', 'Data Agendamento', 'Turno', 'Data Instalação', 
            'Motivo Pendência', 'Observações',
            'CEP', 'Logradouro', 'Número', 'Complemento', 'Bairro', 'Cidade', 'UF', 'Ponto Ref.'
        ]
        ws.append(headers)
        
        # 2. Estilização do Cabeçalho (Fundo Azul, Fonte Branca e Negrito)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")

        # 3. Preenchimento das Linhas
        for v in vendas:
            # Tratamento de campos nulos para evitar erro
            sup_nome = v.vendedor.supervisor.username if v.vendedor and v.vendedor.supervisor else '-'
            canal_venda = getattr(v.vendedor, 'canal', '-') if v.vendedor else '-'
            
            # Formatação de Datas
            dt_criacao = v.data_criacao.strftime('%d/%m/%Y %H:%M') if v.data_criacao else '-'
            dt_abertura = v.data_abertura.strftime('%d/%m/%Y %H:%M') if v.data_abertura else '-'
            dt_agendamento = v.data_agendamento.strftime('%d/%m/%Y') if v.data_agendamento else '-'
            dt_instalacao = v.data_instalacao.strftime('%d/%m/%Y') if v.data_instalacao else '-'
            
            ws.append([
                v.id,
                dt_criacao,
                dt_abertura,
                v.vendedor.username if v.vendedor else '-',
                sup_nome,
                canal_venda,
                v.cliente.nome_razao_social if v.cliente else '-',
                v.cliente.cpf_cnpj if v.cliente else '-',
                v.telefone1 or '-',
                v.telefone2 or '-',
                v.cliente.email if v.cliente else '-',
                v.plano.nome if v.plano else '-',
                v.plano.valor if v.plano else 0.00,
                v.forma_pagamento.nome if v.forma_pagamento else '-',
                v.status_esteira.nome if v.status_esteira else '-',
                v.status_tratamento.nome if v.status_tratamento else '-',
                v.status_comissionamento.nome if v.status_comissionamento else '-',
                v.ordem_servico or '-',
                dt_agendamento,
                v.get_periodo_agendamento_display() or '-',
                dt_instalacao,
                v.motivo_pendencia.nome if v.motivo_pendencia else '-',
                v.observacoes or '-',
                v.cep or '-',
                v.logradouro or '-',
                v.numero_residencia or '-',
                v.complemento or '-',
                v.bairro or '-',
                v.cidade or '-',
                v.estado or '-',
                v.ponto_referencia or '-'
            ])

        # Ajuste automático de largura das colunas
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter 
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = (max_length + 2)
            if adjusted_width > 50: adjusted_width = 50
            ws.column_dimensions[column].width = adjusted_width

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        filename = f"Base_Vendas_Completa_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        wb.save(response)
        return response

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
        
        data_inicio_str = request.query_params.get('data_inicio')
        data_fim_str = request.query_params.get('data_fim')
        
        hoje = now()
        hoje_date = hoje.date()
        
        if data_inicio_str and data_fim_str:
            try:
                data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d')
                data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d')
                data_fim_ajustada = data_fim + timedelta(days=1)
                data_fim_date = data_fim.date()
            except ValueError:
                data_inicio = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                data_fim_ajustada = (data_inicio + timedelta(days=32)).replace(day=1)
                data_fim_date = (data_fim_ajustada - timedelta(days=1)).date()
        else:
            data_inicio = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            data_fim_ajustada = (data_inicio + timedelta(days=32)).replace(day=1)
            data_fim_date = (data_fim_ajustada - timedelta(days=1)).date()

        last_day_of_month = calendar.monthrange(data_inicio.year, data_inicio.month)[1]
        data_fim_mes_projetado = data_inicio.replace(day=last_day_of_month).date()

        dias_fiscais_db = DiaFiscal.objects.filter(
            data__range=(data_inicio.date(), data_fim_mes_projetado)
        )
        mapa_fiscais = {d.data: d for d in dias_fiscais_db}

        peso_total_mes_venda = 0.0
        peso_realizado_venda = 0.0
        peso_total_mes_inst = 0.0
        peso_realizado_inst = 0.0
        
        limite_realizado = min(hoje_date, data_fim_date)

        data_iter = data_inicio.date()
        while data_iter <= data_fim_mes_projetado:
            if data_iter in mapa_fiscais:
                p_venda = float(mapa_fiscais[data_iter].peso_venda)
                p_inst = float(mapa_fiscais[data_iter].peso_instalacao)
            else:
                weekday = data_iter.weekday()
                if weekday == 6: p_venda = 0.0; p_inst = 0.0
                elif weekday == 5: p_venda = 0.5; p_inst = 0.5
                else: p_venda = 1.0; p_inst = 1.0
            
            peso_total_mes_venda += p_venda
            peso_total_mes_inst += p_inst
            
            if data_iter <= limite_realizado:
                peso_realizado_venda += p_venda
                peso_realizado_inst += p_inst
            
            data_iter += timedelta(days=1)

        def calcular_projecao(valor_atual, peso_realizado, peso_total):
            if not peso_realizado or float(peso_realizado) == 0:
                return 0
            return (float(valor_atual) / float(peso_realizado)) * float(peso_total)

        consultor_filtro_id = request.query_params.get('consultor_id')
        if consultor_filtro_id:
            usuarios_para_calcular = User.objects.filter(id=consultor_filtro_id)
        elif is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            usuarios_para_calcular = User.objects.filter(is_active=True)
        elif is_member(user, ['Supervisor']):
            usuarios_para_calcular = [user]
        else:
            usuarios_para_calcular = [user]

        if is_member(user, ['Diretoria', 'Admin']): exibir_comissao = True
        elif is_member(user, ['BackOffice']): exibir_comissao = False
        else: exibir_comissao = True
        
        is_diretoria = is_member(user, ['Diretoria'])
        mapa_comissao_operadora = {}
        if is_diretoria:
            configs = ComissaoOperadora.objects.all()
            for c in configs:
                mapa_comissao_operadora[c.plano_id] = {
                    'base': float(c.valor_base),
                    'bonus': float(c.bonus_transicao),
                    'fim_bonus': c.data_fim_bonus
                }

        total_registradas_geral = 0
        total_instaladas_geral = 0
        comissao_total_geral = 0.0
        status_counts_geral = defaultdict(int)
        meta_display = 0
        detalhes_listas = defaultdict(list)

        faturamento_operadora_real = 0.0
        mix_velocidade = defaultdict(int)
        mix_pagamento = defaultdict(int)

        for vendedor in usuarios_para_calcular:
            meta_individual = getattr(vendedor, 'meta_comissao', 0) or 0
            meta_display += float(meta_individual)

            vendas_registro = Venda.objects.filter(
                vendedor=vendedor, ativo=True,
                data_criacao__gte=data_inicio, data_criacao__lt=data_fim_ajustada
            ).select_related('cliente', 'status_esteira')
            
            qtd_registradas = vendas_registro.count()
            bateu_meta = qtd_registradas >= float(meta_individual)

            for v in vendas_registro:
                nome_status = v.status_esteira.nome.upper() if v.status_esteira else 'AGUARDANDO'
                if nome_status != 'INSTALADA':
                    status_counts_geral[nome_status] += 1
                
                obj_venda = {
                    'id': v.id, 'cliente': v.cliente.nome_razao_social if v.cliente else 'S/C',
                    'status': nome_status, 'data_iso': v.data_criacao.isoformat(), 'vendedor': vendedor.username
                }
                detalhes_listas['TOTAL_REGISTRADAS'].append(obj_venda)
                if nome_status != 'INSTALADA': detalhes_listas[nome_status].append(obj_venda)

            vendas_instaladas = Venda.objects.filter(
                vendedor=vendedor, ativo=True,
                status_esteira__nome__iexact='INSTALADA',
                data_instalacao__gte=data_inicio, data_instalacao__lt=data_fim_ajustada
            ).select_related('plano', 'cliente', 'forma_pagamento')

            qtd_instaladas = vendas_instaladas.count()
            status_counts_geral['INSTALADA'] += qtd_instaladas

            for vi in vendas_instaladas:
                obj_inst = {
                    'id': vi.id, 'cliente': vi.cliente.nome_razao_social if vi.cliente else 'S/C',
                    'status': 'INSTALADA', 'data_iso': vi.data_instalacao.isoformat() if vi.data_instalacao else None,
                    'vendedor': vendedor.username
                }
                detalhes_listas['TOTAL_INSTALADAS'].append(obj_inst)
                detalhes_listas['INSTALADA'].append(obj_inst)

                if is_diretoria:
                    nome_plano = vi.plano.nome if vi.plano else "Outros"
                    mix_velocidade[nome_plano] += 1
                    nome_pgto = vi.forma_pagamento.nome if vi.forma_pagamento else "Não Informado"
                    mix_pagamento[nome_pgto] += 1

                    if vi.plano_id in mapa_comissao_operadora:
                        cfg = mapa_comissao_operadora[vi.plano_id]
                        valor_venda = cfg['base']
                        if cfg['bonus'] > 0:
                            if not cfg['fim_bonus'] or (vi.data_instalacao and vi.data_instalacao <= cfg['fim_bonus']):
                                valor_venda += cfg['bonus']
                        faturamento_operadora_real += valor_venda

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

        projecao_vendas = calcular_projecao(total_registradas_geral, peso_realizado_venda, peso_total_mes_venda)
        projecao_instaladas = calcular_projecao(total_instaladas_geral, peso_realizado_inst, peso_total_mes_inst)
        projecao_comissao = calcular_projecao(valor_comissao_final, peso_realizado_inst, peso_total_mes_inst)

        periodo_str = f"{data_inicio.strftime('%d/%m')} a {data_fim_date.strftime('%d/%m')}"

        dados = {
            "periodo": periodo_str,
            "meta": meta_display,
            "total_vendas": total_registradas_geral,
            "total_instaladas": total_instaladas_geral,
            "comissao_estimada": valor_comissao_final,
            "projecao_vendas": round(projecao_vendas, 1),
            "projecao_instaladas": round(projecao_instaladas, 1),
            "projecao_comissao": round(projecao_comissao, 2),
            "percentual_meta": round((total_registradas_geral / meta_display * 100), 1) if meta_display > 0 else 0,
            "percentual_aproveitamento": round(percentual_aproveitamento, 1),
            "status_bateu_meta": (total_registradas_geral >= meta_display) if meta_display > 0 else False,
            "exibir_comissao": exibir_comissao, 
            "status_detalhado": status_counts_geral,
            "detalhes_listas": detalhes_listas
        }

        if is_diretoria:
            fat_projetado = calcular_projecao(faturamento_operadora_real, peso_realizado_inst, peso_total_mes_inst)
            dados['diretoria_data'] = {
                'faturamento_real': round(faturamento_operadora_real, 2),
                'faturamento_projetado': round(fat_projetado, 2),
                'mix_velocidade': mix_velocidade,
                'mix_pagamento': mix_pagamento
            }

        return Response(dados)

class ClienteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Cliente.objects.all()
    serializer_class = ClienteSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'cliente'

    def get_queryset(self):
        queryset = Cliente.objects.annotate(
            vendas_count=Count('vendas', filter=Q(vendas__ativo=True))
        ).order_by('nome_razao_social')
        
        search = self.request.query_params.get('search')
        if search:
            filters = Q(nome_razao_social__icontains=search) | Q(cpf_cnpj__icontains=search)
            
            clean_search = ''.join(filter(str.isdigit, search))
            if len(clean_search) == 11:
                cpf_fmt = f"{clean_search[:3]}.{clean_search[3:6]}.{clean_search[6:9]}-{clean_search[9:]}"
                filters |= Q(cpf_cnpj__icontains=cpf_fmt)
            elif len(clean_search) == 14:
                cnpj_fmt = f"{clean_search[:2]}.{clean_search[2:5]}.{clean_search[5:8]}/{clean_search[8:12]}-{clean_search[12:]}"
                filters |= Q(cpf_cnpj__icontains=cnpj_fmt)
            
            queryset = queryset.filter(filters)
            
        return queryset

class ListaVendedoresView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        User = get_user_model()
        vendedores = User.objects.filter(is_active=True).values('id', 'username').order_by('username')
        return Response(list(vendedores))

# Em site-record/crm_app/views.py

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
        
        # Define o intervalo do mês
        data_inicio = datetime(ano, mes, 1)
        if mes == 12:
            data_fim = datetime(ano + 1, 1, 1)
        else:
            data_fim = datetime(ano, mes + 1, 1)

        User = get_user_model()
        consultores = User.objects.filter(is_active=True).order_by('username')
        relatorio = []
        todas_regras = list(RegraComissao.objects.select_related('plano', 'consultor').all())
        
        # --- 1. BUSCAR ADIANTAMENTOS E DESCONTOS JÁ PROCESSADOS (Lançamentos Financeiros) ---
        lancamentos_mes = LancamentoFinanceiro.objects.filter(
            data__gte=data_inicio,
            data__lt=data_fim
        )
        mapa_lancamentos = defaultdict(list)
        for l in lancamentos_mes:
            mapa_lancamentos[l.usuario_id].append(l)

        # --- 2. BUSCAR CAMPANHAS VÁLIDAS NO MÊS ---
        campanhas_mes = Campanha.objects.filter(
            ativo=True,
            data_fim__year=ano,
            data_fim__month=mes
        ).prefetch_related('planos_elegiveis', 'formas_pagamento_elegiveis')

        for consultor in consultores:
            # Vendas do Mês (Instaladas)
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
            
            stats_planos = defaultdict(lambda: {'qtd': 0, 'total': 0.0})
            stats_descontos = defaultdict(float)
            stats_bonus = defaultdict(float)
            
            # --- LOOP PRINCIPAL DE VENDAS ---
            for v in vendas:
                # Dados para regra
                doc = v.cliente.cpf_cnpj if v.cliente else ''
                doc_limpo = ''.join(filter(str.isdigit, doc))
                tipo_cliente = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
                canal_vendedor = getattr(consultor, 'canal', 'PAP') or 'PAP'
                
                # Encontrar Regra de Comissão
                regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor_id == consultor.id), None)
                if not regra:
                    regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor is None), None)
                
                valor_item = float(regra.valor_acelerado if bateu_meta else regra.valor_base) if regra else 0.0
                comissao_bruta += valor_item

                # Estatísticas por Plano
                key_plano = (v.plano.nome, valor_item)
                stats_planos[key_plano]['qtd'] += 1
                stats_planos[key_plano]['total'] += valor_item

                # --- DESCONTOS AUTOMÁTICOS (PREVISTOS) ---
                # Só calcula se a flag de processado for False.
                # Se for True, o valor virá via LancamentoFinanceiro (no loop mais abaixo).

                # 1. Boleto
                if v.forma_pagamento and 'BOLETO' in v.forma_pagamento.nome.upper():
                    if not v.flag_desc_boleto:
                        val = float(consultor.desconto_boleto or 0)
                        if val > 0: stats_descontos['Desc. Boleto (Previsto)'] += val

                # 2. Inclusão/Viabilidade
                if v.inclusao:
                    if not v.flag_desc_viabilidade:
                        val = float(consultor.desconto_inclusao_viabilidade or 0)
                        if val > 0: stats_descontos['Desc. Inclusão (Previsto)'] += val

                # 3. Antecipação
                if v.antecipou_instalacao:
                    if not v.flag_desc_antecipacao:
                        val = float(consultor.desconto_instalacao_antecipada or 0)
                        if val > 0: stats_descontos['Desc. Antecipação (Previsto)'] += val

                # 4. Adiantamento CNPJ
                if len(doc_limpo) > 11:
                    if not v.flag_adiant_cnpj:
                        val = float(consultor.adiantamento_cnpj or 0)
                        if val > 0: stats_descontos['Adiant. CNPJ (Previsto)'] += val

            # --- DESCONTOS FIXOS (Perfil) ---
            if consultor.desconto_inss_fixo and float(consultor.desconto_inss_fixo) > 0:
                 stats_descontos['INSS / Encargos (Fixo)'] += float(consultor.desconto_inss_fixo)

            # --- LANÇAMENTOS FINANCEIROS PROCESSADOS (Manuais ou Confirmados) ---
            lancamentos = mapa_lancamentos.get(consultor.id, [])
            for l in lancamentos:
                # Formatação do nome para exibição
                tipo_display = "Outro"
                if l.tipo == 'ADIANTAMENTO_CNPJ': tipo_display = "Adiant. CNPJ"
                elif l.tipo == 'ADIANTAMENTO_COMISSAO': tipo_display = "Adiantamento"
                elif l.tipo == 'DESCONTO': tipo_display = "Desconto"
                
                descricao_item = l.descricao or ""
                chave_exibicao = f"{tipo_display}: {descricao_item}" if descricao_item else tipo_display
                
                stats_descontos[chave_exibicao] += float(l.valor)

            # --- 3. CÁLCULO DE CAMPANHAS (BÔNUS) ---
            for camp in campanhas_mes:
                q_camp = Q(vendedor=consultor, ativo=True)
                
                # Regras da Campanha
                q_camp &= Q(data_criacao__date__gte=camp.data_inicio, data_criacao__date__lte=camp.data_fim)
                
                if camp.tipo_meta == 'LIQUIDA':
                    q_camp &= Q(status_esteira__nome__iexact='INSTALADA')
                
                if camp.canal_alvo != 'TODOS':
                    q_camp &= Q(vendedor__canal=camp.canal_alvo)
                
                planos_ids = [p.id for p in camp.planos_elegiveis.all()]
                if planos_ids:
                    q_camp &= Q(plano_id__in=planos_ids)
                
                pgto_ids = [fp.id for fp in camp.formas_pagamento_elegiveis.all()]
                if pgto_ids:
                    q_camp &= Q(forma_pagamento_id__in=pgto_ids)
                
                total_atingido = Venda.objects.filter(q_camp).count()
                
                if total_atingido >= camp.meta_vendas:
                    stats_bonus[f"Prêmio: {camp.nome}"] += float(camp.valor_premio)
            
            # --- TOTAIS FINAIS ---
            total_descontos = sum(stats_descontos.values())
            total_bonus = sum(stats_bonus.values())
            
            valor_liquido = (comissao_bruta + total_bonus) - total_descontos

            # --- FORMATAÇÃO PARA O FRONTEND ---
            
            # 1. Planos
            lista_planos_detalhe = []
            for (nome_plano, unitario), dados in stats_planos.items():
                lista_planos_detalhe.append({
                    'plano': nome_plano, 'unitario': unitario,
                    'qtd': dados['qtd'], 'total': dados['total']
                })
            lista_planos_detalhe.sort(key=lambda x: x['total'], reverse=True)

            # 2. Descontos (Ordenados por valor)
            lista_descontos_detalhe = [{'motivo': k, 'valor': v} for k, v in stats_descontos.items()]
            lista_descontos_detalhe.sort(key=lambda x: x['valor'], reverse=True)

            # 3. Bônus (Ordenados por valor)
            lista_bonus_detalhe = [{'motivo': k, 'valor': v} for k, v in stats_bonus.items()]
            lista_bonus_detalhe.sort(key=lambda x: x['valor'], reverse=True)

            relatorio.append({
                'consultor_id': consultor.id,
                'consultor_nome': consultor.username.upper(),
                'qtd_instaladas': qtd_instaladas,
                'meta': meta,
                'atingimento_pct': round(atingimento, 1),
                'comissao_bruta': comissao_bruta,
                'total_descontos': total_descontos,
                'total_bonus': total_bonus,
                'valor_liquido': valor_liquido,
                'detalhes_planos': lista_planos_detalhe,
                'detalhes_descontos': lista_descontos_detalhe,
                'detalhes_bonus': lista_bonus_detalhe
            })

        # --- HISTÓRICO (Últimos 6 meses) ---
        historico = []
        for i in range(6):
            d = hoje - timedelta(days=10*i)
            mes_iter = d.month
            ano_iter = d.year
            
            total_ciclo = CicloPagamento.objects.filter(
                ano=ano_iter, mes=str(mes_iter)
            ).aggregate(Sum('valor_comissao_final'))['valor_comissao_final__sum'] or 0
            
            fechamento = PagamentoComissao.objects.filter(
                referencia_ano=ano_iter, referencia_mes=mes_iter
            ).first()
            
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

# Adicione este import no topo do arquivo se não tiver
import threading

class ImportacaoOsabView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_osab'
    parser_classes = [MultiPartParser, FormParser]

    def _clean_key(self, key):
        if pd.isna(key) or key is None: return None
        return str(key).replace('.0', '').strip()

    def _normalize_text(self, text):
        if not text: return ""
        text = str(text).upper().strip()
        import unicodedata
        return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

    def _enviar_mensagens_background(self, lista_mensagens):
        svc = WhatsAppService()
        for telefone, texto in lista_mensagens:
            try:
                svc.enviar_mensagem_texto(telefone, texto)
            except Exception as e:
                print(f"Erro envio background thread: {e}")

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Nenhum arquivo enviado.'}, status=400)
        
        opcao_front = str(request.data.get('enviar_whatsapp', 'true')).lower() == 'true'
        usuario = request.user
        pode_decidir = is_member(usuario, ['Diretoria', 'Admin'])
        flag_enviar_whatsapp = opcao_front if pode_decidir else True
        
        if not flag_enviar_whatsapp:
            print(f"--- Importação OSAB SILENCIOSA iniciada por: {usuario.username} ---")

        try:
            df = None
            if file_obj.name.endswith('.xlsb'): 
                df = pd.read_excel(file_obj, engine='pyxlsb')
            elif file_obj.name.endswith(('.xlsx', '.xls')): 
                df = pd.read_excel(file_obj)
            else: 
                return Response({'error': 'Formato inválido.'}, status=400)
        except Exception as e: return Response({'error': f'Erro leitura arquivo: {str(e)}'}, status=400)
        
        # 1. Normalização dos nomes das colunas
        df.columns = [str(col).strip().upper().replace(' ', '_') for col in df.columns]
        
        # ==============================================================================
        # 2. PARSER DE DATA "INTELIGENTE" (Versão Corrigida para Conflito de Imports)
        # ==============================================================================
        def smart_date_parser(val):
            # Importação local com alias para evitar conflito com 'from datetime import datetime'
            import datetime as dt_sys 
            import pandas as pd # Garantir pandas aqui também

            # Se for nulo ou vazio
            if val is None or pd.isna(val) or val == '':
                return None
            
            # Caso A: O Pandas/Engine já leu como objeto de data (datetime)
            # Verifica se é instância de datetime.datetime, datetime.date ou pd.Timestamp
            if isinstance(val, (dt_sys.datetime, dt_sys.date, pd.Timestamp)):
                return val.date() if hasattr(val, 'date') else val

            # Caso B: É um número (Serial do Excel - ex: 45279.54)
            if isinstance(val, (float, int)):
                try:
                    # Excel começa em 30/12/1899
                    return (dt_sys.datetime(1899, 12, 30) + dt_sys.timedelta(days=float(val))).date()
                except:
                    return None

            # Caso C: É Texto (String) - Onde mora o perigo "04/12/2025  13:00:00"
            s_val = str(val).strip()
            
            # Tenta encontrar padrão DD/MM/AAAA via Regex (ignora o resto da string)
            # Usa 're' que deve estar importado no topo ou aqui
            import re 
            match_br = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', s_val)
            if match_br:
                d, m, y = match_br.groups()
                try:
                    return dt_sys.date(int(y), int(m), int(d))
                except ValueError:
                    pass # Data inválida matematicamente (ex: 30/02)

            # Tenta encontrar padrão AAAA-MM-DD
            match_iso = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', s_val)
            if match_iso:
                y, m, d = match_iso.groups()
                try:
                    return dt_sys.date(int(y), int(m), int(d))
                except ValueError:
                    pass

            return None
        # ==============================================================================

        # Aplica a função linha a linha nas colunas de data
        cols_data = ['DT_REF', 'DATA_ABERTURA', 'DATA_FECHAMENTO', 'DATA_AGENDAMENTO']
        for col in cols_data:
            if col in df.columns:
                # O .apply é mais lento que vetorização, mas muito mais seguro para dados sujos
                df[col] = df[col].apply(smart_date_parser)
        
        df = df.replace({np.nan: None, pd.NaT: None})

        # --- PREPARAÇÃO DO BANCO DE DADOS ---
        status_esteira_map = {s.nome.upper(): s for s in StatusCRM.objects.filter(tipo='Esteira')}
        status_tratamento_map = {s.nome.upper(): s for s in StatusCRM.objects.filter(tipo='Tratamento')}
        
        mapa_pagamentos = {}
        for fp in FormaPagamento.objects.filter(ativo=True):
            mapa_pagamentos[self._normalize_text(fp.nome)] = fp
        
        motivo_pendencia_map = {}
        for m in MotivoPendencia.objects.all():
            match = re.match(r'^(\d+)', m.nome.strip())
            if match: motivo_pendencia_map[match.group(1)] = m
        
        motivo_padrao_osab, _ = MotivoPendencia.objects.get_or_create(nome="VALIDAR OSAB", defaults={'tipo_pendencia': 'Operacional'})
        motivo_sem_agenda, _ = MotivoPendencia.objects.get_or_create(nome="APROVISIONAMENTO S/ DATA", defaults={'tipo_pendencia': 'Sistêmica'})

        lista_pedidos_raw = df['PEDIDO'].dropna().astype(str).tolist() if 'PEDIDO' in df.columns else []
        lista_pedidos_limpos = set(p.replace('.0', '').strip() for p in lista_pedidos_raw)

        vendas_filtradas = Venda.objects.filter(
            ativo=True, 
            ordem_servico__in=lista_pedidos_limpos
        ).select_related('vendedor', 'status_esteira', 'status_tratamento')
        
        vendas_map = {self._clean_key(v.ordem_servico): v for v in vendas_filtradas}
        osab_bot = get_osab_bot_user()

        osab_existentes = {
            obj.documento: obj for obj in ImportacaoOsab.objects.filter(documento__in=lista_pedidos_limpos)
        }

        osab_criar, osab_atualizar, vendas_atualizar, historicos_criar = [], [], [], []
        fila_mensagens_whatsapp = [] 

        coluna_map = {
            'PRODUTO': 'produto', 'UF': 'uf', 'DT_REF': 'dt_ref', 'PEDIDO': 'documento',
            'SEGMENTO': 'segmento', 'LOCALIDADE': 'localidade', 'CELULA': 'celula',
            'ID_BUNDLE': 'id_bundle', 'TELEFONE': 'telefone', 'VELOCIDADE': 'velocidade',
            'MATRICULA_VENDEDOR': 'matricula_vendedor', 'CLASSE_PRODUTO': 'classe_produto',
            'NOME_CNAL': 'nome_canal', 'PDV_SAP': 'pdv_sap', 'DESCRICAO': 'descricao',
            'DATA_ABERTURA': 'data_abertura', 'DATA_FECHAMENTO': 'data_fechamento',
            'SITUACAO': 'situacao', 'CLASSIFICACAO': 'classificacao',
            'DATA_AGENDAMENTO': 'data_agendamento', 'COD_PENDENCIA': 'cod_pendencia',
            'DESC_PENDENCIA': 'desc_pendencia', 'NUMERO_BA': 'numero_ba',
            'FG_VENDA_VALIDA': 'fg_venda_valida', 'DESC_MOTIVO_ORDEM': 'desc_motivo_ordem',
            'DESC_SUB_MOTIVO_ORDEM': 'desc_sub_motivo_ordem', 'MEIO_PAGAMENTO': 'meio_pagamento',
            'CAMPANHA': 'campanha', 'FLG_MEI': 'flg_mei', 'NM_DIRETORIA': 'nm_diretoria',
            'NM_REGIONAL': 'nm_regional', 'CD_REDE': 'cd_rede', 'GP_CANAL': 'gp_canal',
            'GERENCIA': 'gerencia', 'NM_GC': 'gc',
        }

        STATUS_MAP = {
            'CONCLUÍDO': 'INSTALADA', 'CONCLUIDO': 'INSTALADA', 'EXECUTADO': 'INSTALADA',
            'PENDÊNCIA CLIENTE': 'PENDENCIADA', 'PENDENCIA CLIENTE': 'PENDENCIADA',
            'PENDÊNCIA TÉCNICA': 'PENDENCIADA', 'PENDENCIA TECNICA': 'PENDENCIADA',
            'CANCELADO': 'CANCELADA', 'EM CANCELAMENTO': 'CANCELADA',
            'AGENDADO': 'AGENDADO', 'DRAFT': 'DRAFT', 
            'AGUARDANDO PAGAMENTO': 'AGUARDANDO PAGAMENTO'
        }
        
        report = {
            "status": "sucesso", "total_registros": len(df), "criados": 0, "atualizados": 0, 
            "vendas_encontradas": 0, "ja_corretos": 0, "erros": [], "logs_detalhados": [], "arquivo_excel_b64": None
        }

        # --- LOOP PRINCIPAL ---
        records = df.to_dict('records')

        for index, row in enumerate(records):
            log_item = {"linha": index + 2, "pedido": str(row.get('PEDIDO')), "status_osab": str(row.get('SITUACAO')), "resultado": "", "detalhe": ""}
            try:
                # A. ImportacaoOsab
                dados_model = {}
                for col_planilha, campo_model in coluna_map.items():
                    val = row.get(col_planilha)
                    if col_planilha == 'PEDIDO': val = self._clean_key(val)
                    dados_model[campo_model] = val
                
                doc_chave = dados_model.get('documento')
                if not doc_chave: 
                    log_item["resultado"] = "IGNORADO"; report["logs_detalhados"].append(log_item); continue

                if doc_chave in osab_existentes:
                    obj = osab_existentes[doc_chave]
                    mudou = False
                    for k, v in dados_model.items():
                        if getattr(obj, k) != v:
                            setattr(obj, k, v)
                            mudou = True
                    if mudou: osab_atualizar.append(obj)
                else:
                    osab_criar.append(ImportacaoOsab(**dados_model))

                # B. Venda CRM
                venda = vendas_map.get(doc_chave)
                if not venda:
                    log_item["resultado"] = "NAO_ENCONTRADO CRM"; report["logs_detalhados"].append(log_item); continue
                
                report["vendas_encontradas"] += 1
                sit_osab_raw = str(row.get('SITUACAO', '')).strip().upper()
                if sit_osab_raw in ["NONE", "NAN"]: sit_osab_raw = ""

                target_status_esteira = None
                target_status_tratamento = None
                target_data_agenda = None
                target_motivo_pendencia = None
                
                houve_alteracao = False
                detalhes_hist = {}
                msg_whatsapp_desta_venda = None

                # --- 1. DATA DE ABERTURA ---
                # Como usamos o parser inteligente, aqui já é date ou None
                nova_data_abertura = row.get('DATA_ABERTURA')
                if nova_data_abertura:
                    data_sistema = venda.data_abertura.date() if venda.data_abertura else None
                    if data_sistema != nova_data_abertura:
                        detalhes_hist['data_abertura'] = f"De '{data_sistema}' para '{nova_data_abertura}'"
                        venda.data_abertura = nova_data_abertura
                        houve_alteracao = True

                # --- 2. STATUS ---
                is_fraude = "PAYMENT_NOT_AUTHORIZED" in sit_osab_raw
                if not sit_osab_raw or is_fraude:
                    pgto_raw = self._normalize_text(row.get('MEIO_PAGAMENTO'))
                    if "CARTAO" in pgto_raw:
                        st_reprovado = status_tratamento_map.get("REPROVADO CARTÃO DE CRÉDITO")
                        if st_reprovado: target_status_tratamento = st_reprovado
                
                elif sit_osab_raw == "EM APROVISIONAMENTO":
                    # Aqui usamos a data já limpa pelo parser inteligente
                    dt_ag = row.get('DATA_AGENDAMENTO') 
                    
                    # Validação simples: se existe, o parser já garantiu que é uma data válida
                    if dt_ag and dt_ag.year >= 2000:
                        target_status_esteira = status_esteira_map.get("AGENDADO")
                        target_data_agenda = dt_ag
                    else:
                        target_status_esteira = status_esteira_map.get("PENDENCIADA")
                        target_motivo_pendencia = motivo_sem_agenda
                
                else:
                    nome_est = STATUS_MAP.get(sit_osab_raw)
                    if not nome_est:
                        if sit_osab_raw.startswith("DRAFT"): nome_est = "DRAFT"
                        elif "AGUARDANDO PAGAMENTO" in sit_osab_raw: nome_est = "AGUARDANDO PAGAMENTO"
                        elif "REPROVADO" in sit_osab_raw: nome_est = "REPROVADO CARTÃO DE CRÉDITO"
                    if nome_est: target_status_esteira = status_esteira_map.get(nome_est)

                # Aplica Alterações Status Tratamento
                if target_status_tratamento and venda.status_tratamento != target_status_tratamento:
                    detalhes_hist['status_tratamento'] = f"De '{venda.status_tratamento}' para '{target_status_tratamento.nome}'"
                    venda.status_tratamento = target_status_tratamento
                    houve_alteracao = True

                # Aplica Alterações Status Esteira
                if target_status_esteira:
                    if venda.status_esteira != target_status_esteira:
                        detalhes_hist['status_esteira'] = f"De '{venda.status_esteira}' para '{target_status_esteira.nome}'"
                        venda.status_esteira = target_status_esteira
                        houve_alteracao = True
                        if 'PENDEN' not in target_status_esteira.nome.upper(): venda.motivo_pendencia = None
                    
                    nome_est_upper = target_status_esteira.nome.upper()

                    if 'INSTALADA' in nome_est_upper:
                        nova_dt = row.get('DATA_FECHAMENTO')
                        if nova_dt and nova_dt.year >= 2000:
                            data_inst_atual = venda.data_instalacao
                            if not data_inst_atual or data_inst_atual != nova_dt:
                                detalhes_hist['data_instalacao'] = f"Nova: {nova_dt}"
                                venda.data_instalacao = nova_dt
                                houve_alteracao = True
                        
                        if houve_alteracao and venda.vendedor and venda.vendedor.tel_whatsapp:
                            dt_fmt = venda.data_instalacao.strftime('%d/%m') if venda.data_instalacao else "Hoje"
                            msg_whatsapp_desta_venda = (venda.vendedor.tel_whatsapp, f"✅ *VENDA INSTALADA (OSAB)*\n\n*Cliente:* {venda.cliente.nome_razao_social}\n*OS:* {venda.ordem_servico}\n*Data:* {dt_fmt}")

                    elif 'AGENDADO' in nome_est_upper:
                        nova_dt_ag = target_data_agenda or row.get('DATA_AGENDAMENTO')
                        if nova_dt_ag and nova_dt_ag.year >= 2000:
                            data_ag_atual = venda.data_agendamento
                            if not data_ag_atual or data_ag_atual != nova_dt_ag:
                                detalhes_hist['data_agendamento'] = f"Nova: {nova_dt_ag}"
                                venda.data_agendamento = nova_dt_ag
                                houve_alteracao = True
                        
                        if houve_alteracao and venda.vendedor and venda.vendedor.tel_whatsapp:
                            dt_fmt = venda.data_agendamento.strftime('%d/%m') if venda.data_agendamento else "S/D"
                            msg_whatsapp_desta_venda = (venda.vendedor.tel_whatsapp, f"📅 *VENDA AGENDADA (OSAB)*\n\n*Cliente:* {venda.cliente.nome_razao_social}\n*OS:* {venda.ordem_servico}\n*Data:* {dt_fmt}")

                    elif 'PENDEN' in nome_est_upper:
                        novo_motivo = target_motivo_pendencia
                        if not novo_motivo:
                            cod_full = str(row.get('COD_PENDENCIA', '')).replace('.0', '').strip()
                            novo_motivo = motivo_pendencia_map.get(cod_full) or motivo_pendencia_map.get(cod_full[:2]) or motivo_padrao_osab
                        
                        if venda.motivo_pendencia_id != novo_motivo.id:
                            detalhes_hist['motivo_pendencia'] = f"Novo: {novo_motivo.nome}"
                            venda.motivo_pendencia = novo_motivo
                            houve_alteracao = True
                        
                        if houve_alteracao and venda.vendedor and venda.vendedor.tel_whatsapp:
                            msg_whatsapp_desta_venda = (venda.vendedor.tel_whatsapp, f"⚠️ *VENDA PENDENCIADA (OSAB)*\n\n*Cliente:* {venda.cliente.nome_razao_social}\n*OS:* {venda.ordem_servico}\n*Motivo:* {novo_motivo.nome}")

                # Pagamento
                pgto_osab_raw = row.get('MEIO_PAGAMENTO')
                if pgto_osab_raw:
                    pgto_norm = self._normalize_text(pgto_osab_raw)
                    novo_fp = mapa_pagamentos.get(pgto_norm)
                    if not novo_fp:
                        for k, v in mapa_pagamentos.items():
                            if pgto_norm in k or k in pgto_norm: novo_fp = v; break
                    if novo_fp and (not venda.forma_pagamento or venda.forma_pagamento.id != novo_fp.id):
                        detalhes_hist['forma_pagamento'] = f"Novo: {novo_fp.nome}"
                        venda.forma_pagamento = novo_fp
                        houve_alteracao = True

                # Conclusão
                if houve_alteracao:
                    log_item["resultado"] = "ATUALIZAR"
                    vendas_atualizar.append(venda)
                    historicos_criar.append(HistoricoAlteracaoVenda(venda=venda, usuario=osab_bot, alteracoes=detalhes_hist))
                    if msg_whatsapp_desta_venda and flag_enviar_whatsapp:
                        fila_mensagens_whatsapp.append(msg_whatsapp_desta_venda)
                else:
                    log_item["resultado"] = "SEM_MUDANCA"
                    report["ja_corretos"] += 1
                
                report["logs_detalhados"].append(log_item)

            except Exception as ex:
                log_item["resultado"] = "ERRO"
                report["erros"].append(f"L{index}: {ex}")

        # --- 3. PERSISTÊNCIA ---
        with transaction.atomic():
            if osab_criar: ImportacaoOsab.objects.bulk_create(osab_criar, batch_size=2000)
            if osab_atualizar:
                campos_osab = [f.name for f in ImportacaoOsab._meta.fields if f.name != 'id']
                ImportacaoOsab.objects.bulk_update(osab_atualizar, campos_osab, batch_size=2000)
            if vendas_atualizar:
                campos_venda = ['status_esteira', 'status_tratamento', 'data_instalacao', 'data_agendamento', 'forma_pagamento', 'motivo_pendencia', 'data_abertura']
                Venda.objects.bulk_update(vendas_atualizar, campos_venda, batch_size=2000)
            if historicos_criar:
                HistoricoAlteracaoVenda.objects.bulk_create(historicos_criar, batch_size=2000)

        report["atualizados"] = len(vendas_atualizar)

        # --- 4. ENVIO WHATSAPP ---
        if fila_mensagens_whatsapp:
            import threading
            t = threading.Thread(target=self._enviar_mensagens_background, args=(fila_mensagens_whatsapp,))
            t.start()
            print(f"Iniciado envio de {len(fila_mensagens_whatsapp)} mensagens em background.")
        
        # Gera Excel de Log
        try:
            if report["logs_detalhados"]:
                from io import BytesIO
                import base64
                output = BytesIO()
                pd.DataFrame(report["logs_detalhados"]).to_excel(output, index=False)
                report['arquivo_excel_b64'] = base64.b64encode(output.getvalue()).decode('utf-8')
        except: pass

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
            if file_obj.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_obj)
            elif file_obj.name.endswith('.xlsb'):
                df = pd.read_excel(file_obj, engine='pyxlsb')
            elif file_obj.name.endswith('.csv'):
                df = pd.read_csv(file_obj)
            else:
                return Response({'error': 'Formato inválido. Use .xlsx, .xls, .xlsb ou .csv'}, status=400)
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

        # --- 1. DEFINIR QUEM VAI APARECER NO PAINEL ---
        # Filtra apenas usuários ativos e remove robôs/admins que não vendem
        base_users = User.objects.filter(is_active=True).exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])

        if is_member(current_user, ['Diretoria', 'BackOffice', 'Admin', 'Auditoria', 'Qualidade']):
            users_to_process = base_users.select_related('supervisor')
        elif is_member(current_user, ['Supervisor']):
            # Supervisor vê a si mesmo e seus liderados
            users_to_process = base_users.filter(Q(id=current_user.id) | Q(supervisor=current_user)).select_related('supervisor')
        else:
            # Vendedor vê apenas a si mesmo (ou sua equipe, dependendo da regra. Aqui deixei restrito)
            users_to_process = base_users.filter(id=current_user.id).select_related('supervisor')

        # --- 2. AGREGAR VENDAS ---
        # Filtros: Vendas ativas, COM tratamento definido, SEM cancelamento na esteira
        base_filters = (
            Q(ativo=True) & 
            Q(status_tratamento__isnull=False) & 
            (Q(status_esteira__isnull=True) | ~Q(status_esteira__nome__iexact='CANCELADA'))
        )

        vendas = Venda.objects.filter(base_filters).values('vendedor_id').annotate(
            total_dia=Count('id', filter=Q(data_pedido__date=hoje)),
            total_mes=Count('id', filter=Q(data_pedido__date__gte=start_of_month)),
            total_mes_instalado=Count('id', filter=Q(data_pedido__date__gte=start_of_month, status_esteira__nome__iexact='Instalada')),
            # Semanal
            vendas_segunda=Count('id', filter=Q(data_pedido__date=start_of_week)),
            vendas_terca=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=1))),
            vendas_quarta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=2))),
            vendas_quinta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=3))),
            vendas_sexta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=4))),
            vendas_sabado=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=5))),
        )
        
        vendas_por_vendedor = {v['vendedor_id']: v for v in vendas}

        # --- 3. MONTAR ESTRUTURA DOS TIMES ---
        teams = defaultdict(lambda: {
            'supervisor_name': 'Sem Supervisor', 
            'members': [], 
            'totals': {
                'daily': 0, 
                'weekly_breakdown': {'seg':0,'ter':0,'qua':0,'qui':0,'sex':0,'sab':0},
                'weekly_total': 0,
                'monthly': {'total': 0, 'instalados': 0}
            }
        })

        for user in users_to_process:
            supervisor_id = user.supervisor.id if user.supervisor else 'none'
            
            if supervisor_id != 'none' and user.supervisor:
                teams[supervisor_id]['supervisor_name'] = user.supervisor.username
            
            # Pega dados de vendas (ou 0 se não tiver)
            v_data = vendas_por_vendedor.get(user.id, {})
            
            dia_atual = v_data.get('total_dia', 0)
            weekly_total = sum([
                v_data.get('vendas_segunda', 0), v_data.get('vendas_terca', 0),
                v_data.get('vendas_quarta', 0), v_data.get('vendas_quinta', 0),
                v_data.get('vendas_sexta', 0), v_data.get('vendas_sabado', 0)
            ])
            total_mes = v_data.get('total_mes', 0)
            instalados_mes = v_data.get('total_mes_instalado', 0)
            
            aproveitamento_str = f"{(instalados_mes / total_mes * 100):.0f}%" if total_mes > 0 else "-"

            # Adiciona membro (MESMO SE TIVER 0 VENDAS)
            teams[supervisor_id]['members'].append({
                'name': user.username,
                'full_name': f"{user.first_name} {user.last_name}".strip() or user.username,
                'daily': dia_atual,
                'weekly_breakdown': {
                    'seg': v_data.get('vendas_segunda', 0),
                    'ter': v_data.get('vendas_terca', 0),
                    'qua': v_data.get('vendas_quarta', 0),
                    'qui': v_data.get('vendas_quinta', 0),
                    'sex': v_data.get('vendas_sexta', 0),
                    'sab': v_data.get('vendas_sabado', 0)
                },
                'weekly_total': weekly_total,
                'monthly': {
                    'total': total_mes,
                    'instalados': instalados_mes,
                    'aproveitamento': aproveitamento_str
                }
            })

        # --- 4. CALCULAR TOTAIS E ORDENAR ---
        final_result = []
        
        for supervisor_id, team_data in teams.items():
            if not team_data['members']: continue

            # ORDENAÇÃO IMPORTANTE: Quem vendeu mais no dia fica em cima. Zeros em baixo.
            # Se empate no dia, desempata pelo mensal.
            team_data['members'] = sorted(
                team_data['members'], 
                key=lambda x: (x['daily'], x['monthly']['total']), 
                reverse=True
            )

            # Somar totais do time
            for member in team_data['members']:
                team_data['totals']['daily'] += member['daily']
                for day, count in member['weekly_breakdown'].items():
                    team_data['totals']['weekly_breakdown'][day] += count
                team_data['totals']['weekly_total'] += member['weekly_total']
                team_data['totals']['monthly']['total'] += member['monthly']['total']
                team_data['totals']['monthly']['instalados'] += member['monthly']['instalados']
            
            # Aproveitamento do Time
            t_total = team_data['totals']['monthly']['total']
            t_inst = team_data['totals']['monthly']['instalados']
            team_data['totals']['monthly']['aproveitamento'] = f"{(t_inst / t_total * 100):.0f}%" if t_total > 0 else "-"

            final_result.append(team_data)

        # Ordena as equipes pelo total de vendas do dia (Equipe que mais vendeu aparece primeiro)
        final_result = sorted(final_result, key=lambda x: x['totals']['daily'], reverse=True)
        
        return Response(final_result)

class ImportarKMLView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'Nenhum arquivo enviado.'}, status=400)

        if not file_obj.name.endswith('.kml'):
             return Response({'error': 'Por favor, envie um arquivo .kml (se for .kmz, descompacte antes).'}, status=400)

        try:
            tree = ET.parse(file_obj)
            root = tree.getroot()
            ns = {'kml': 'http://www.opengis.net/kml/2.2'}
            
            placemarks = root.findall('.//kml:Placemark', ns)
            if not placemarks:
                placemarks = root.findall('.//Placemark')

            areas_para_criar = []
            erros = 0
            
            # Compilar regex fora do loop para performance
            regex_cache = {}

            def extrair_rapido(chave, texto):
                if chave not in regex_cache:
                    regex_cache[chave] = re.compile(rf'<strong>{chave}:\s*</strong>(.*?)(?:<br>|$)', re.IGNORECASE)
                match = regex_cache[chave].search(texto)
                return match.group(1).strip() if match else None

            # Limpar tabela antes? Opcional. Se quiser limpar, descomente:
            # AreaVenda.objects.all().delete()

            for pm in placemarks:
                try:
                    def find_text(elem, tag):
                        res = elem.find(f'kml:{tag}', ns)
                        if res is None: res = elem.find(tag)
                        return res.text if res is not None else ""

                    nome = find_text(pm, 'name')
                    description = find_text(pm, 'description')
                    
                    coords_text = ""
                    poly = pm.find('.//kml:Polygon//kml:coordinates', ns)
                    if poly is None: poly = pm.find('.//Polygon//coordinates')
                    if poly is not None:
                        coords_text = poly.text.strip()
                    
                    # Pular se não tiver coordenadas (economiza tempo)
                    if not coords_text:
                        continue

                    obj = AreaVenda(
                        nome_kml=nome or "Sem Nome",
                        coordenadas=coords_text,
                        celula=extrair_rapido('Célula', description),
                        uf=extrair_rapido('UF', description),
                        municipio=extrair_rapido('Município', description),
                        estacao=extrair_rapido('Estação', description),
                        cluster=extrair_rapido('Cluster Célula', description),
                        status_venda=extrair_rapido('Status Venda Célula', description),
                        ocupacao=extrair_rapido(r'Ocup \(%\)', description),
                        atingimento_meta=extrair_rapido(r'Atingimento/Meta \(%\)', description)
                    )
                    
                    # Inteiros
                    for campo, chave in [('prioridade','Prioridade'), ('aging','Aging'), ('hc','HC'), ('hp','HP'), ('hp_viavel','HP Viável'), ('hp_viavel_total','HP Viável Total')]:
                        val = extrair_rapido(chave, description)
                        try: setattr(obj, campo, int(val) if val else 0)
                        except: setattr(obj, campo, 0)
                    
                    # Float
                    val_hc = extrair_rapido('HC Esperado', description)
                    if val_hc:
                        try: obj.hc_esperado = float(val_hc.replace(',', '.'))
                        except: obj.hc_esperado = 0.0
                    
                    areas_para_criar.append(obj)
                    
                except Exception as e:
                    # Não logar erro individual para não spammar log e atrasar
                    erros += 1

            # SALVAMENTO EM LOTE (BULK INSERT) - AQUI ESTÁ O GANHO DE PERFORMANCE
            # Divide em lotes de 1000 para não estourar memória do banco
            batch_size = 1000
            for i in range(0, len(areas_para_criar), batch_size):
                AreaVenda.objects.bulk_create(areas_para_criar[i:i + batch_size])

            return Response({
                'status': 'sucesso',
                'mensagem': f'Importação concluída! {len(areas_para_criar)} áreas importadas.',
            })

        except Exception as e:
            return Response({'error': f'Erro crítico KML: {str(e)}'}, status=500)
        
# --- NOVA VIEW: IMPORTAÇÃO DFV (CSV) ---
class ImportarDFVView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Arquivo CSV não enviado.'}, status=400)
        
        try:
            # Lê o CSV (delimitador ; conforme seu arquivo)
            df = pd.read_csv(file_obj, sep=';', dtype=str, encoding='utf-8') 
            df = df.replace({np.nan: None})
            
            # Normaliza nomes de colunas (remove espaços e poe maiusculo)
            df.columns = [c.strip().upper() for c in df.columns]
            
            objs = []
            for _, row in df.iterrows():
                # Tratamento do CEP
                cep_raw = str(row.get('CEP', '')).strip()
                cep_limpo = "".join(filter(str.isdigit, cep_raw))
                
                # Tratamento da Fachada (Número)
                fachada_raw = str(row.get('NUM_FACHADA', '')).strip()
                
                objs.append(DFV(
                    uf=row.get('UF'),
                    municipio=row.get('MUNICIPIO'),
                    logradouro=row.get('LOGRADOURO'),
                    num_fachada=fachada_raw,
                    complemento=row.get('COMPLEMENTO'),
                    cep=cep_limpo,
                    bairro=row.get('BAIRRO'),
                    tipo_viabilidade=row.get('TIPO_VIABILIDADE'),
                    tipo_rede=row.get('TIPO_REDE'),
                    celula=row.get('CELULA')
                ))
            
            # Opcional: Descomente para apagar a base antiga antes de importar a nova
            # DFV.objects.all().delete()
            
            DFV.objects.bulk_create(objs, batch_size=1000)
            
            return Response({'status': 'sucesso', 'mensagem': f'{len(objs)} registros importados na DFV.'})
            
        except Exception as e:
            return Response({'error': f"Erro ao processar CSV: {str(e)}"}, status=500)

class WebhookWhatsAppView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            data = request.data
            # print(">>> WEBHOOK:", json.dumps(data, default=str)) 

            if isinstance(data, list): data = data[0] if len(data) > 0 else {}
            if not isinstance(data, dict): return Response({'status': 'ignored_format'})

            raw_phone = data.get('phone') or data.get('sender')
            if not raw_phone: return Response({'status': 'ignored_no_phone'})

            phone = str(raw_phone).split('@')[0].strip()[:45]

            text = ""
            if 'text' in data and isinstance(data['text'], dict):
                text = data['text'].get('message', '').strip()
            elif 'text' in data and isinstance(data['text'], str):
                text = data['text'].strip()
            
            if not text: return Response({'status': 'ignored_no_text'})

            service = WhatsAppService()

            # --- GESTÃO DE SESSÃO ---
            try:
                sessao, created = SessaoWhatsapp.objects.get_or_create(
                    telefone=phone, 
                    defaults={'etapa': 'MENU', 'dados_temp': {}}
                )
            except IntegrityError:
                sessao = SessaoWhatsapp.objects.get(telefone=phone)

            msg_upper = text.upper().strip()

            # =========================================================
            # GATILHOS INICIAIS (MENU PRINCIPAL)
            # =========================================================
            
            # 1. GATILHO: FACHADA
            if "FACHADA" in msg_upper:
                sessao.etapa = 'FACHADA_AGUARDANDO_CEP'
                sessao.save()
                service.enviar_mensagem_texto(phone, "🏢 *CONSULTA MASSIVA (DFV)*\n\nEu vou listar todos os números viáveis de uma rua.\nPor favor, digite o *CEP* (somente números):")
                return Response({'status': 'fachada_start'})

            # 2. GATILHO: VIABILIDADE
            elif "VIABILIDADE" in msg_upper:
                sessao.etapa = 'VIABILIDADE_AGUARDANDO_CEP'
                sessao.save()
                service.enviar_mensagem_texto(phone, "🗺️ *CONSULTA VIABILIDADE (KMZ)*\n\nIdentifiquei que você quer consultar a mancha.\nPor favor, digite o *CEP*:")
                return Response({'status': 'viabilidade_start'})

            # 3. GATILHO: STATUS (NOVA FUNÇÃO)
            elif "STATUS" in msg_upper:
                sessao.etapa = 'STATUS_MENU_ESCOLHA'
                sessao.dados_temp = {} # Limpa dados
                sessao.save()
                service.enviar_mensagem_texto(phone, "📋 *CONSULTA DE STATUS*\n\nComo deseja pesquisar o pedido?\n\n1️⃣ Por *CPF*\n2️⃣ Por *O.S* (Ordem de Serviço)\n\nDigite o número da opção (1 ou 2):")
                return Response({'status': 'status_start'})

            # =========================================================
            # FLUXOS EM ANDAMENTO
            # =========================================================

            # --- FLUXO STATUS: ESCOLHA (1 ou 2) ---
            elif sessao.etapa == 'STATUS_MENU_ESCOLHA':
                if text == '1' or 'CPF' in msg_upper:
                    sessao.etapa = 'STATUS_AGUARDANDO_DADO'
                    sessao.dados_temp = {'tipo_busca': 'CPF'}
                    sessao.save()
                    service.enviar_mensagem_texto(phone, "Ok, digite o *CPF* do cliente (apenas números):")
                elif text == '2' or 'OS' in msg_upper or 'ORDEM' in msg_upper:
                    sessao.etapa = 'STATUS_AGUARDANDO_DADO'
                    sessao.dados_temp = {'tipo_busca': 'OS'}
                    sessao.save()
                    service.enviar_mensagem_texto(phone, "Ok, digite o número da *O.S* (Ordem de Serviço):")
                else:
                    service.enviar_mensagem_texto(phone, "⚠️ Opção inválida. Digite *1* para CPF ou *2* para O.S:")
                return Response({'status': 'status_choice'})

            # --- FLUXO STATUS: EXECUÇÃO (Recebe o CPF ou OS) ---
            elif sessao.etapa == 'STATUS_AGUARDANDO_DADO':
                tipo = sessao.dados_temp.get('tipo_busca')
                valor = text

                service.enviar_mensagem_texto(phone, f"🔎 Buscando pedido por {tipo}...")
                
                # Importa a função nova do utils
                from .utils import consultar_status_venda
                resp_msg = consultar_status_venda(tipo, valor)
                
                service.enviar_mensagem_texto(phone, resp_msg)
                sessao.delete() # Encerra
                return Response({'status': 'status_end'})


            # --- FLUXO FACHADA (Antigo) ---
            elif sessao.etapa == 'FACHADA_AGUARDANDO_CEP':
                cep_limpo = "".join(filter(str.isdigit, text))
                if len(cep_limpo) == 8:
                    service.enviar_mensagem_texto(phone, "🔎 Buscando todas as fachadas no DFV...")
                    from .utils import listar_fachadas_dfv
                    resp_msg = listar_fachadas_dfv(cep_limpo)
                    service.enviar_mensagem_texto(phone, resp_msg)
                    sessao.delete() 
                else:
                    service.enviar_mensagem_texto(phone, "⚠️ CEP inválido. Digite 8 números:")
                return Response({'status': 'fachada_end'})

            # --- FLUXO VIABILIDADE (Antigo) ---
            elif sessao.etapa == 'VIABILIDADE_AGUARDANDO_CEP':
                cep_limpo = "".join(filter(str.isdigit, text))
                if len(cep_limpo) == 8:
                    sessao.dados_temp['cep'] = cep_limpo
                    sessao.etapa = 'VIABILIDADE_AGUARDANDO_NUMERO'
                    sessao.save()
                    service.enviar_mensagem_texto(phone, "Ok (Modo Mapa)! Agora digite o *NÚMERO* da fachada para localizarmos no mapa:")
                else:
                    service.enviar_mensagem_texto(phone, "⚠️ CEP inválido. Digite 8 números:")
                return Response({'status': 'viabilidade_cep_ok'})

            elif sessao.etapa == 'VIABILIDADE_AGUARDANDO_NUMERO':
                cep = sessao.dados_temp.get('cep')
                numero = text
                service.enviar_mensagem_texto(phone, "🛰️ Geolocalizando e analisando mancha (KMZ)...")
                from .utils import consultar_viabilidade_kmz
                resp_msg = consultar_viabilidade_kmz(cep, numero)
                service.enviar_mensagem_texto(phone, resp_msg)
                sessao.delete()
                return Response({'status': 'viabilidade_end'})

            # Caso não entenda
            return Response({'status': 'no_action'})

        except Exception as e:
            logger.error(f"Webhook Error: {e}", exc_info=True)
            return Response({'status': 'error', 'detail': str(e)}, status=500)  

# No arquivo crm_app/views.py

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_verificar_whatsapp(request, telefone=None):
    """
    Verifica se um número possui WhatsApp válido.
    Aceita o telefone via URL (rota antiga) ou Query Param (rota nova).
    """
    try:
        # CORREÇÃO: O parâmetro 'telefone' agora é opcional na assinatura (telefone=None)
        # Se não vier na URL, tenta pegar do Query Param ?numero=
        if not telefone:
            telefone = request.query_params.get('numero') or request.query_params.get('telefone')
        
        if not telefone:
            return Response({"error": "Número não informado."}, status=400)
        
        # Limpa o número para garantir apenas dígitos (remove parenteses, traços, etc)
        telefone_limpo = re.sub(r'\D', '', str(telefone))
        
        svc = WhatsAppService()
        existe = svc.verificar_numero_existe(telefone_limpo)
        
        return Response({
            "telefone": telefone_limpo,
            "exists": existe,
            "possui_whatsapp": existe 
        })
    except Exception as e:
        logger.error(f"Erro view verificar zap: {e}")
        return Response({"error": str(e)}, status=500)

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def enviar_comissao_whatsapp(request):
    """
    Calcula o resumo da comissão e envia um card (imagem) via WhatsApp para o consultor.
    """
    try:
        ano = int(request.data.get('ano'))
        mes = int(request.data.get('mes'))
        consultores_ids = request.data.get('consultores', [])

        if not consultores_ids:
            return Response({"error": "Nenhum consultor selecionado."}, status=status.HTTP_400_BAD_REQUEST)

        User = get_user_model()
        
        # Define datas de início e fim do mês
        data_inicio = datetime(ano, mes, 1)
        if mes == 12:
            data_fim = datetime(ano + 1, 1, 1)
        else:
            data_fim = datetime(ano, mes + 1, 1)
        
        svc = WhatsAppService()
        todas_regras = list(RegraComissao.objects.select_related('plano', 'consultor').all())
        
        sucessos = 0
        erros = []

        for c_id in consultores_ids:
            try:
                consultor = User.objects.get(id=c_id)
                telefone = consultor.tel_whatsapp
                
                if not telefone:
                    erros.append(f"{consultor.username}: Sem WhatsApp cadastrado.")
                    continue

                # --- 1. Calcular Comissão (Versão simplificada para o Card) ---
                vendas = Venda.objects.filter(
                    vendedor=consultor,
                    ativo=True,
                    status_esteira__nome__iexact='INSTALADA',
                    data_instalacao__gte=data_inicio,
                    data_instalacao__lt=data_fim
                ).select_related('plano', 'forma_pagamento', 'cliente')

                qtd_instaladas = vendas.count()
                meta = consultor.meta_comissao or 0
                bateu_meta = qtd_instaladas >= meta

                stats_planos = defaultdict(lambda: {'qtd': 0, 'valor_unit': 0.0, 'total': 0.0})
                stats_descontos = defaultdict(float)
                comissao_bruta = 0.0

                for v in vendas:
                    # Encontrar regra
                    doc = v.cliente.cpf_cnpj if v.cliente else ''
                    doc_limpo = ''.join(filter(str.isdigit, doc))
                    tipo_cliente = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
                    canal_vendedor = getattr(consultor, 'canal', 'PAP') or 'PAP'
                    
                    regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor_id == consultor.id), None)
                    if not regra:
                        regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor is None), None)
                    
                    valor_item = float(regra.valor_acelerado if bateu_meta else regra.valor_base) if regra else 0.0
                    comissao_bruta += valor_item
                    
                    # Agrupar por Plano
                    nm_plano = v.plano.nome
                    stats_planos[nm_plano]['qtd'] += 1
                    stats_planos[nm_plano]['total'] += valor_item

                    # Calcular Descontos
                    if v.forma_pagamento and 'BOLETO' in v.forma_pagamento.nome.upper():
                        val = float(consultor.desconto_boleto or 0)
                        if val > 0: stats_descontos['Boleto'] += val
                    
                    if v.inclusao:
                        val = float(consultor.desconto_inclusao_viabilidade or 0)
                        if val > 0: stats_descontos['Inclusão'] += val

                    if v.antecipou_instalacao:
                        val = float(consultor.desconto_instalacao_antecipada or 0)
                        if val > 0: stats_descontos['Antecipação'] += val
                    
                    if len(doc_limpo) > 11:
                        val = float(consultor.adiantamento_cnpj or 0)
                        if val > 0: stats_descontos['Adiant. CNPJ'] += val

                total_descontos = sum(stats_descontos.values())
                liquido = comissao_bruta - total_descontos

                # --- 2. Preparar Dados para a Imagem ---
                detalhes_planos = []
                for p_nome, dados in stats_planos.items():
                    detalhes_planos.append({
                        'nome': p_nome, 
                        'qtd': dados['qtd'], 
                        'valor': f"R$ {dados['total']:.2f}".replace('.', ',')
                    })
                
                detalhes_descontos = []
                for motivo, val in stats_descontos.items():
                     detalhes_descontos.append({
                        'motivo': motivo, 
                        'valor': f"-R$ {val:.2f}".replace('.', ',')
                      })

                dados_img = {
                    'titulo': 'Resumo Comissionamento',
                    'vendedor': consultor.username.upper(),
                    'periodo': f"{mes}/{ano}",
                    'total': f"R$ {liquido:.2f}".replace('.', ','),
                    'detalhes_planos': detalhes_planos,
                    'detalhes_descontos': detalhes_descontos
                }

                # --- 3. Enviar ---
                if svc.enviar_resumo_comissao(telefone, dados_img):
                    sucessos += 1
                else:
                    erros.append(f"{consultor.username}: Falha no envio (Z-API).")

            except Exception as e:
                logger.error(f"Erro ao processar envio para {c_id}: {e}")
                erros.append(f"ID {c_id}: Erro interno.")

        return Response({
            "mensagem": f"Processamento concluído. Sucessos: {sucessos}. Falhas: {len(erros)}",
            "detalhes_erro": erros
        })

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Em site-record/crm_app/views.py

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def enviar_resultado_campanha_whatsapp(request):
    try:
        campanha_id = request.data.get('campanha_id')
        vendedores_dados = request.data.get('vendedores_dados', [])
        
        if not campanha_id or not vendedores_dados:
            return Response({"error": "Dados incompletos."}, status=400)

        campanha = Campanha.objects.get(id=campanha_id)
        User = get_user_model()
        svc = WhatsAppService() 
        
        # 1. Carregar TODAS as regras da campanha ordenadas (Menor -> Maior)
        # Exemplo: [Meta 20, Meta 40, Meta 60]
        regras_ordenadas = list(campanha.regras_meta.all().order_by('meta'))
        
        # Define a meta máxima absoluta da campanha
        meta_maxima_absoluta = regras_ordenadas[-1].meta if regras_ordenadas else campanha.meta_vendas

        sucessos = 0
        erros = []
        periodo_str = f"{campanha.data_inicio.strftime('%d/%m')} até {campanha.data_fim.strftime('%d/%m')}"
        
        for item in vendedores_dados:
            vendedor_id = item.get('vendedor_id')
            try:
                vendedor = User.objects.get(id=vendedor_id)
                if not vendedor.tel_whatsapp:
                    erros.append(f"{vendedor.username}: Sem Zap.")
                    continue

                vendas_validas = int(item.get('vendas_validas', 0))
                
                # --- LÓGICA DE RECALCULO DE FAIXAS (Backend Source of Truth) ---
                meta_atual = 0
                premio_atual = 0.0
                proxima_meta_obj = None
                
                if regras_ordenadas:
                    # Percorre a escada para descobrir onde o vendedor está
                    for regra in regras_ordenadas:
                        if vendas_validas >= regra.meta:
                            # Bateu essa faixa, atualiza o status atual
                            meta_atual = regra.meta
                            premio_atual = float(regra.valor_premio)
                        else:
                            # Se as vendas são menores que esta regra, esta é a PRÓXIMA meta
                            proxima_meta_obj = regra
                            break # Encontramos o próximo degrau, paramos de procurar
                else:
                    # Fallback para campanhas legadas (sem faixas múltiplas)
                    if vendas_validas >= campanha.meta_vendas:
                        meta_atual = campanha.meta_vendas
                        premio_atual = float(campanha.valor_premio)
                    else:
                        # Se não bateu a única meta, ela vira a próxima
                        proxima_meta_obj = type('obj', (object,), {'meta': campanha.meta_vendas, 'valor_premio': campanha.valor_premio})

                # Formatador de Moeda
                def fmt_real(val): return f"R$ {float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                # --- CONSTRUÇÃO DO TEXTO INCENTIVADOR ---
                primeiro_nome = vendedor.first_name.split()[0].title() if vendedor.first_name else "Campeão(a)"
                
                msg = f"🚀 *PERFORMANCE: {campanha.nome}*\n"
                msg += f"🗓️ {periodo_str}\n\n"
                msg += f"Olá, *{primeiro_nome}*! Aqui está sua parcial:\n\n"
                msg += f"📊 *Vendas Válidas:* {vendas_validas}\n"

                # CENÁRIO 1: ESTÁ NO MEIO DA JORNADA (Bateu uma, falta outra)
                if premio_atual > 0 and proxima_meta_obj:
                    faltam = int(proxima_meta_obj.meta) - vendas_validas
                    diferenca_grana = float(proxima_meta_obj.valor_premio) - premio_atual
                    
                    msg += f"✅ *Meta Batida:* {meta_atual} vendas\n"
                    msg += f"💰 *JÁ GARANTIDO:* {fmt_real(premio_atual)}\n\n"
                    msg += f"🔥 *VOCÊ ESTÁ QUASE LÁ!*\n"
                    msg += f"Faltam só *{faltam} vendas* para o próximo nível ({proxima_meta_obj.meta})!\n"
                    msg += f"🚀 *Acelera!* Se bater essa meta, seu prêmio sobe para *{fmt_real(proxima_meta_obj.valor_premio)}*.\n"
                    msg += f"(Isso é *{fmt_real(diferenca_grana)} a mais* no seu bolso! 💵)"

                # CENÁRIO 2: LENDÁRIO (Bateu a última faixa disponível)
                elif premio_atual > 0 and not proxima_meta_obj:
                    msg += f"🏆 *LENDÁRIO! VOCÊ ZEROU A CAMPANHA!*\n"
                    msg += f"✅ Atingiu o topo máximo de {meta_atual} vendas.\n"
                    msg += f"💰 *PRÊMIO MÁXIMO:* {fmt_real(premio_atual)}\n\n"
                    msg += f"⭐ Parabéns pela performance incrível! Você é referência."

                # CENÁRIO 3: INICIANTE (Não bateu a primeira faixa ainda)
                else:
                    # A próxima meta é a primeira de todas
                    meta_alvo = proxima_meta_obj.meta if proxima_meta_obj else meta_maxima_absoluta
                    valor_alvo = proxima_meta_obj.valor_premio if proxima_meta_obj else 0.0
                    faltam = int(meta_alvo) - vendas_validas
                    
                    msg += f"⚠️ *Status:* Em busca da primeira meta!\n"
                    msg += f"🎯 *Alvo:* {meta_alvo} vendas\n"
                    msg += f"⚡ *FALTAM APENAS {faltam} VENDAS!*\n\n"
                    msg += f"💰 Bata essa meta e garanta *{fmt_real(valor_alvo)}*.\n"
                    msg += f"💪 *É totalmente possível!* Foque nos clientes pendentes e vamos buscar esse resultado!"

                msg += "\n\n_Atualizado em: " + timezone.localtime().strftime('%d/%m às %H:%M') + "_"

                # --- GERAÇÃO DA IMAGEM ---
                # Prepara os dados limpos para o gerador de imagem
                dados_card = {
                    'vendedor': primeiro_nome,
                    'vendas': vendas_validas,
                    'premio_atual': premio_atual,
                    'meta_atual': meta_atual,
                    'prox_meta': proxima_meta_obj.meta if proxima_meta_obj else None,
                    'prox_premio': proxima_meta_obj.valor_premio if proxima_meta_obj else None,
                    'campanha': campanha.nome
                }
                
                img_b64 = svc.gerar_card_campanha_b64(dados_card)

                # --- ENVIO ---
                if img_b64:
                    svc.enviar_imagem_b64(vendedor.tel_whatsapp, img_b64, caption=msg)
                else:
                    svc.enviar_mensagem_texto(vendedor.tel_whatsapp, msg)
                
                sucessos += 1
                
            except Exception as e:
                erros.append(f"Erro ID {vendedor_id}: {e}")
                logger.error(f"Erro envio campanha: {e}")

        return Response({"mensagem": f"Enviados: {sucessos}. Erros: {len(erros)}", "erros": erros})

    except Exception as e:
        return Response({"error": str(e)}, status=500)

# --- NOVA API DE PAINEL DE PERFORMANCE ---
# crm_app/views.py (Substitua a classe PainelPerformanceView inteira)

# Em crm_app/views.py

# Em crm_app/views.py

class PainelPerformanceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        User = get_user_model()
        user = request.user
        
        # 1. Datas
        agora_local = timezone.localtime(timezone.now())
        hoje = agora_local.date()
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        dias_semana = [inicio_semana + timedelta(days=i) for i in range(6)]
        inicio_mes = hoje.replace(day=1)

        # 2. Base de Usuários (TODOS OS ATIVOS, exceto bots)
        users = User.objects.filter(is_active=True).exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])

        # 3. Filtros de Permissão
        grupos_gestao = ['Diretoria', 'Admin', 'BackOffice', 'Auditoria', 'Qualidade']
        if is_member(user, grupos_gestao):
            pass 
        elif is_member(user, ['Supervisor']):
            users = users.filter(Q(supervisor=user) | Q(id=user.id))
        else:
            users = users.filter(id=user.id)

        # 4. Filtro de Canal (Query Param)
        filtro_canal = request.query_params.get('canal')
        if filtro_canal:
            users = users.filter(canal__iexact=filtro_canal)

        # 5. Filtros de Venda
        # IMPORTANTE: filtro_os_valida já garante que tem OS, mas agora filtramos pela DATA DE ABERTURA
        filtro_os_valida = Q(vendas__ativo=True) & ~Q(vendas__ordem_servico='') & Q(vendas__ordem_servico__isnull=False)
        
        # Filtro CC (Cartão)
        filtro_cc = (
            Q(vendas__forma_pagamento__nome__icontains='CREDIT') | 
            Q(vendas__forma_pagamento__nome__icontains='CRÉDIT') |
            (Q(vendas__forma_pagamento__nome__icontains='CARTA') & ~Q(vendas__forma_pagamento__nome__icontains='DEBIT'))
        )
        
        # Filtro Instalada
        filtro_inst = Q(vendas__status_esteira__nome__iexact='INSTALADA')

        # --- A. DADOS DE HOJE ---
        qs_hoje = users.annotate(
            vendas_total=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=hoje)),
            vendas_cc=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=hoje) & filtro_cc)
        ).values('username', 'canal', 'vendas_total', 'vendas_cc').order_by('-vendas_total', 'username')

        lista_hoje = []
        for u in qs_hoje:
            total = u['vendas_total']
            cc = u['vendas_cc']
            pct = (cc / total * 100) if total > 0 else 0
            
            nome_display = u['username']
            
            lista_hoje.append({
                'vendedor': nome_display.upper(),
                'canal': u['canal'],
                'total': total,
                'cc': cc,
                'pct_cc': round(pct, 2)
            })

        # --- B. DADOS DA SEMANA ---
        qs_semana = users.annotate(
            seg=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[0])),
            ter=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[1])),
            qua=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[2])),
            qui=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[3])),
            sex=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[4])),
            sab=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[5])),
            total_semana=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_semana)),
            total_cc=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_semana) & filtro_cc)
        ).values('username', 'seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'total_semana', 'total_cc').order_by('-total_semana', 'username')

        lista_semana = []
        for u in qs_semana:
            total = u['total_semana']
            pct = (u['total_cc'] / total * 100) if total > 0 else 0
            nome_display = u['username']

            lista_semana.append({
                'vendedor': nome_display.upper(),
                'dias': [u['seg'], u['ter'], u['qua'], u['qui'], u['sex'], u['sab']],
                'total': total,
                'cc': u['total_cc'],
                'pct_cc': round(pct, 2)
            })

        # --- C. DADOS DO MÊS (CORRIGIDO) ---
        # "total_vendas": Mantém data_abertura (Vendas Novas no mês)
        # "instaladas": Muda para data_instalacao (Instalações no mês, independente de quando vendeu)
        
        qs_mes = users.annotate(
            total_vendas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes)),
            
            # CORREÇÃO AQUI: Trocado data_abertura por data_instalacao
            instaladas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_instalacao__gte=inicio_mes) & filtro_inst),
            
            total_cc=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes) & filtro_cc),
            
            # CORREÇÃO AQUI TAMBÉM: Instaladas com cartão (olha a data da instalação)
            instaladas_cc=Count('vendas', filter=filtro_os_valida & Q(vendas__data_instalacao__gte=inicio_mes) & filtro_inst & filtro_cc),
            
            pendenciadas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes, vendas__status_esteira__nome__icontains='PENDEN')),
            agendadas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes, vendas__status_esteira__nome__iexact='AGENDADO')),
            canceladas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes, vendas__status_esteira__nome__icontains='CANCELAD'))
        ).values(
            'username', 'total_vendas', 'instaladas', 'total_cc', 'instaladas_cc', 'pendenciadas', 'agendadas', 'canceladas'
        ).order_by('-total_vendas', 'username')

        lista_mes = []
        for u in qs_mes:
            tot = u['total_vendas']
            inst = u['instaladas']
            
            pct_cc_total = (u['total_cc'] / tot * 100) if tot > 0 else 0
            
            # Porcentagem sobre instaladas reais
            pct_cc_inst = (u['instaladas_cc'] / inst * 100) if inst > 0 else 0
            
            # Aproveitamento: (Instaladas no Mês / Vendidas no Mês) 
            # Nota: Isso pode passar de 100% se instalar vendas do mês passado, mas é o cálculo de "Conversão Operacional".
            aproveitamento = (inst / tot * 100) if tot > 0 else 0
            
            nome_display = u['username']

            lista_mes.append({
                'vendedor': nome_display.upper(),
                'total': tot,
                'instaladas': inst,
                'cc_total': u['total_cc'],
                'cc_inst': u['instaladas_cc'],
                'pct_cc_total': round(pct_cc_total, 2),
                'pct_cc_inst': round(pct_cc_inst, 2),
                'aproveitamento': round(aproveitamento, 2),
                'pend': u['pendenciadas'],
                'agend': u['agendadas'],
                'canc': u['canceladas']
            })

        # Totais Gerais
        total_hoje = sum(i['total'] for i in lista_hoje)
        total_semana = sum(i['total'] for i in lista_semana)
        total_mes = sum(i['total'] for i in lista_mes)

        return Response({
            "hoje": lista_hoje,
            "semana": lista_semana,
            "mes": lista_mes,
            "totais": {
                "hoje": total_hoje,
                "semana": total_semana,
                "mes": total_mes
            }
        })

        # --- B. DADOS DA SEMANA ---
        qs_semana = users.annotate(
            seg=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[0])),
            ter=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[1])),
            qua=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[2])),
            qui=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[3])),
            sex=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[4])),
            sab=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date=dias_semana[5])),
            total_semana=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_semana)),
            total_cc=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_semana) & filtro_cc)
        ).values('username', 'seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'total_semana', 'total_cc').order_by('-total_semana', 'username')

        lista_semana = []
        for u in qs_semana:
            total = u['total_semana']
            pct = (u['total_cc'] / total * 100) if total > 0 else 0
            
            # ALTERAÇÃO 2: Username
            nome_display = u['username']

            lista_semana.append({
                'vendedor': nome_display.upper(),
                'dias': [u['seg'], u['ter'], u['qua'], u['qui'], u['sex'], u['sab']],
                'total': total,
                'cc': u['total_cc'],
                'pct_cc': round(pct, 2)
            })

        # --- C. DADOS DO MÊS ---
        qs_mes = users.annotate(
            total_vendas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes)),
            
            # A regra de instaladas continua a mesma (Safra): Vendas que tiveram OS aberta neste mês e já instalaram
            instaladas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes) & filtro_inst),
            
            total_cc=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes) & filtro_cc),
            instaladas_cc=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes) & filtro_inst & filtro_cc),
            
            pendenciadas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes, vendas__status_esteira__nome__icontains='PENDEN')),
            agendadas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes, vendas__status_esteira__nome__iexact='AGENDADO')),
            canceladas=Count('vendas', filter=filtro_os_valida & Q(vendas__data_abertura__date__gte=inicio_mes, vendas__status_esteira__nome__icontains='CANCELAD'))
        ).values(
            'username', 'total_vendas', 'instaladas', 'total_cc', 'instaladas_cc', 'pendenciadas', 'agendadas', 'canceladas'
        ).order_by('-total_vendas', 'username')

        lista_mes = []
        for u in qs_mes:
            tot = u['total_vendas']
            inst = u['instaladas']
            pct_cc_total = (u['total_cc'] / tot * 100) if tot > 0 else 0
            pct_cc_inst = (u['instaladas_cc'] / inst * 100) if inst > 0 else 0
            aproveitamento = (inst / tot * 100) if tot > 0 else 0
            
            # ALTERAÇÃO 2: Username
            nome_display = u['username']

            lista_mes.append({
                'vendedor': nome_display.upper(),
                'total': tot,
                'instaladas': inst,
                'cc_total': u['total_cc'],
                'cc_inst': u['instaladas_cc'],
                'pct_cc_total': round(pct_cc_total, 2),
                'pct_cc_inst': round(pct_cc_inst, 2),
                'aproveitamento': round(aproveitamento, 2),
                'pend': u['pendenciadas'],
                'agend': u['agendadas'],
                'canc': u['canceladas']
            })

        # Totais Gerais
        total_hoje = sum(i['total'] for i in lista_hoje)
        total_semana = sum(i['total'] for i in lista_semana)
        total_mes = sum(i['total'] for i in lista_mes)

        return Response({
            "hoje": lista_hoje,
            "semana": lista_semana,
            "mes": lista_mes,
            "totais": {
                "hoje": total_hoje,
                "semana": total_semana,
                "mes": total_mes
            }
        })

# --- CORREÇÃO APLICADA: VIEW DE PÁGINA NORMAL (SEM API_VIEW) ---
def page_painel_performance(request):
    return render(request, 'painel_performance.html')
class ExportarPerformanceExcelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        User = get_user_model()
        user = request.user
        
        # 1. Definição de Datas (Mesma lógica da View principal)
        agora_local = timezone.localtime(timezone.now())
        hoje = agora_local.date()
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        inicio_mes = hoje.replace(day=1)
        
        # 2. Base de Vendas (Filtragem por permissão)
        vendas = Venda.objects.filter(ativo=True).select_related('vendedor', 'cliente', 'plano', 'forma_pagamento', 'status_esteira')
        
        grupos_gestao = ['Diretoria', 'Admin', 'BackOffice', 'Auditoria', 'Qualidade']
        if not is_member(user, grupos_gestao):
            if is_member(user, ['Supervisor']):
                liderados = list(user.liderados.values_list('id', flat=True)) + [user.id]
                vendas = vendas.filter(vendedor_id__in=liderados)
            else:
                vendas = vendas.filter(vendedor=user)

        # Filtro de Canal
        filtro_canal = request.query_params.get('canal')
        if filtro_canal:
            vendas = vendas.filter(vendedor__canal__iexact=filtro_canal)

        # 3. Preparar os 3 DataFrames
        
        # --- ABA 1: HOJE ---
        vendas_hoje = vendas.filter(data_criacao__date=hoje)
        dados_hoje = self._montar_dados(vendas_hoje)
        
        # --- ABA 2: SEMANA ---
        vendas_semana = vendas.filter(data_criacao__date__gte=inicio_semana)
        dados_semana = self._montar_dados(vendas_semana)
        
        # --- ABA 3: MÊS ---
        vendas_mes = vendas.filter(data_criacao__date__gte=inicio_mes)
        dados_mes = self._montar_dados(vendas_mes)

        # 4. Gerar o Excel
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pd.DataFrame(dados_hoje).to_excel(writer, sheet_name='Hoje', index=False)
            pd.DataFrame(dados_semana).to_excel(writer, sheet_name='Semana Atual', index=False)
            pd.DataFrame(dados_mes).to_excel(writer, sheet_name='Mês Atual', index=False)
            
        output.seek(0)
        
        # 5. Retornar Arquivo
        response = HttpResponse(output, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        filename = f"Performance_Analitica_{hoje}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    def _montar_dados(self, queryset):
        dados = []
        for v in queryset:
            # Converter para horário local para validação visual
            dt_criacao_local = timezone.localtime(v.data_criacao).strftime('%d/%m/%Y %H:%M:%S') if v.data_criacao else '-'
            
            dados.append({
                'ID Venda': v.id,
                'Data Criação (Local)': dt_criacao_local,
                'Vendedor': v.vendedor.username.upper() if v.vendedor else '-',
                'Canal': v.vendedor.canal if v.vendedor else '-',
                'Cliente': v.cliente.nome_razao_social if v.cliente else '-',
                'CPF/CNPJ': v.cliente.cpf_cnpj if v.cliente else '-',
                'Plano': v.plano.nome if v.plano else '-',
                'Forma Pagamento': v.forma_pagamento.nome if v.forma_pagamento else '-',
                'Status Esteira': v.status_esteira.nome if v.status_esteira else '-',
                'Data Instalação': v.data_instalacao.strftime('%d/%m/%Y') if v.data_instalacao else '-',
                'OS': v.ordem_servico or '-'
            })
        if not dados:
            return [{'Status': 'Sem vendas neste período'}]
        return dados
    
# 1. API para listar/criar grupos na tela
class GrupoDisparoViewSet(viewsets.ModelViewSet):
    queryset = GrupoDisparo.objects.filter(ativo=True)
    serializer_class = GrupoDisparoSerializer
    permission_classes = [permissions.IsAuthenticated]

# 2. API que recebe a Imagem (Base64) e manda pro Z-API
class EnviarImagemPerformanceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        chat_id = request.data.get('chat_id')
        imagem_b64 = request.data.get('imagem_b64') # String Base64 vinda do HTML2Canvas
        titulo = request.data.get('titulo', 'Performance')

        if not chat_id or not imagem_b64:
            return Response({'error': 'Dados incompletos.'}, status=400)

        # Remove o cabeçalho do base64 se vier (data:image/png;base64,...)
        if "base64," in imagem_b64:
            imagem_b64 = imagem_b64.split("base64,")[1]

        try:
            svc = WhatsAppService()
            # Envia para a Z-API (presumindo que seu service tenha enviar_imagem_b64 ou similar)
            # Se não tiver, vamos usar a enviar_mensagem_imagem genérica
            
            # Ajuste conforme seu whatsapp_service.py:
            # Geralmente Z-API aceita o base64 direto no campo 'image'
            payload = {
                "phone": chat_id,
                "image": imagem_b64,
                "caption": f"📊 *{titulo}* \nGerado em: {timezone.localtime().strftime('%d/%m/%Y %H:%M')}"
            }
            # Aqui chamamos o método interno do seu serviço ou request direto
            # Vou simular usando o seu svc existente:
            resp = svc.enviar_imagem_base64_direto(chat_id, imagem_b64, payload['caption'])
            
            return Response({'status': 'sucesso', 'zapi_response': resp})

        except Exception as e:
            return Response({'error': str(e)}, status=500)
        
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def listar_grupos_whatsapp_api(request):
    """
    Consulta a Z-API e retorna os grupos para seleção.
    """
    try:
        svc = WhatsAppService()
        grupos_zapi = svc.listar_grupos()
        
        # Filtra e formata para o front
        lista_formatada = []
        
        # Garante que seja uma lista (algumas versoes retornam {response: [...]})
        if isinstance(grupos_zapi, dict) and 'response' in grupos_zapi:
            grupos_zapi = grupos_zapi['response']
        
        if isinstance(grupos_zapi, list):
            for g in grupos_zapi:
                if isinstance(g, dict):
                    # Tenta capturar o ID de várias formas possíveis
                    g_id = g.get('id') or g.get('chatId') or g.get('phone')
                    
                    # Tenta capturar o Nome
                    g_name = g.get('name') or g.get('subject') or g.get('contactName') or 'Sem Nome'

                    # Só adiciona se tiver ID válido
                    if g_id:
                        lista_formatada.append({
                            'id': g_id,
                            'name': g_name
                        })
        
        return Response(lista_formatada)
    except Exception as e:
        logger.error(f"Erro view listar grupos: {e}")
        return Response({'error': str(e)}, status=500)
    

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def relatorio_resultado_campanha(request, campanha_id):
    try:
        campanha = Campanha.objects.get(id=campanha_id)
        # Ordena faixas da MAIOR para a MENOR para achar a atingida mais fácil
        faixas_premiacao = campanha.regras_meta.all().order_by('-meta') 
        
        # --- CORREÇÃO DE LÓGICA DE DATAS ---
        if campanha.tipo_meta == 'LIQUIDA':
            # REGRA NOVA: Se a meta é INSTALADA (Líquida), olhamos a Data de Instalação.
            # Não importa se vendeu mês passado, se instalou dentro da campanha, conta.
            filtros = Q(
                data_instalacao__gte=campanha.data_inicio,
                data_instalacao__lte=campanha.data_fim,
                status_esteira__nome__iexact='INSTALADA',
                ativo=True
            )
        else:
            # REGRA PADRÃO: Se a meta é VENDA (Bruta), olhamos a Data de Criação.
            filtros = Q(
                data_criacao__date__gte=campanha.data_inicio,
                data_criacao__date__lte=campanha.data_fim,
                ativo=True
            )
        # -----------------------------------

        if campanha.canal_alvo != 'TODOS':
            filtros &= Q(vendedor__canal=campanha.canal_alvo)

        planos_validos = campanha.planos_elegiveis.all()
        if planos_validos.exists(): filtros &= Q(plano__in=planos_validos)
        
        pgtos_validos = campanha.formas_pagamento_elegiveis.all()
        if pgtos_validos.exists(): filtros &= Q(forma_pagamento__in=pgtos_validos)

        vendas = Venda.objects.filter(filtros).values(
            'vendedor__id', 'vendedor__first_name', 'vendedor__last_name', 'vendedor__username'
        ).annotate(total_vendas=Count('id')).order_by('-total_vendas')

        resultado = []
        ranking = 1
        # Meta máxima apenas para desenhar a barra de progresso visual
        meta_maxima_visual = campanha.meta_vendas if campanha.meta_vendas > 0 else 1

        for v in vendas:
            nome_vendedor = f"{v['vendedor__first_name']} {v['vendedor__last_name']}".strip() or v['vendedor__username']
            qtd = v['total_vendas']
            
            premio_receber = 0.0
            meta_alcancada = 0 
            
            # 1. Lógica de Faixas (Escalonada)
            if faixas_premiacao.exists():
                for faixa in faixas_premiacao:
                    if qtd >= faixa.meta:
                        premio_receber = float(faixa.valor_premio)
                        meta_alcancada = faixa.meta 
                        break 
            # 2. Lógica Simples (Legado)
            else:
                if qtd >= campanha.meta_vendas:
                    premio_receber = float(campanha.valor_premio)
                    meta_alcancada = campanha.meta_vendas

            percentual = round((qtd / meta_maxima_visual) * 100, 1)
            
            resultado.append({
                'ranking': ranking,
                'vendedor_id': v['vendedor__id'],
                'vendedor': nome_vendedor,
                'vendas_validas': qtd,
                'meta': meta_maxima_visual, 
                'meta_alcancada': meta_alcancada, 
                'percentual': percentual,
                'atingiu_meta': premio_receber > 0,
                'premio_receber': premio_receber
            })
            ranking += 1

        return Response({
            'campanha': campanha.nome,
            'periodo': f"{campanha.data_inicio.strftime('%d/%m/%Y')} a {campanha.data_fim.strftime('%d/%m/%Y')}",
            'tipo': campanha.get_tipo_meta_display(),
            'ranking': resultado
        })

    except Campanha.DoesNotExist: return Response({'error': 'Campanha não encontrada'}, status=404)
    except Exception as e: return Response({'error': str(e)}, status=500)
    
class LancamentoFinanceiroViewSet(viewsets.ModelViewSet):
    queryset = LancamentoFinanceiro.objects.all()
    serializer_class = LancamentoFinanceiroSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        # Salva automaticamente quem criou o registro (segurança/auditoria)
        serializer.save(criado_por=self.request.user)
# --- NOVAS VIEWS PARA CONFIRMAÇÃO DE DESCONTOS ---

class PendenciasDescontoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Lista todas as vendas instaladas que geram desconto mas ainda não foram processadas
        vendas = Venda.objects.filter(
            ativo=True,
            status_esteira__nome__iexact='INSTALADA'
        ).select_related('vendedor', 'forma_pagamento', 'cliente')

        pendencias = []

        for v in vendas:
            consultor = v.vendedor
            if not consultor: continue

            doc = v.cliente.cpf_cnpj if v.cliente else ''
            doc_limpo = ''.join(filter(str.isdigit, doc))
            eh_cnpj = len(doc_limpo) > 11

            # 1. Adiantamento CNPJ
            if eh_cnpj and not v.flag_adiant_cnpj:
                val = float(consultor.adiantamento_cnpj or 0)
                if val > 0:
                    pendencias.append(self._montar_obj(v, 'CNPJ', val, 'Adiantamento CNPJ'))

            # 2. Boleto
            if v.forma_pagamento and 'BOLETO' in v.forma_pagamento.nome.upper() and not v.flag_desc_boleto:
                val = float(consultor.desconto_boleto or 0)
                if val > 0:
                    pendencias.append(self._montar_obj(v, 'BOLETO', val, 'Desconto Boleto'))

            # 3. Viabilidade
            if v.inclusao and not v.flag_desc_viabilidade:
                val = float(consultor.desconto_inclusao_viabilidade or 0)
                if val > 0:
                    pendencias.append(self._montar_obj(v, 'VIABILIDADE', val, 'Desconto Viabilidade'))

            # 4. Antecipação
            if v.antecipou_instalacao and not v.flag_desc_antecipacao:
                val = float(consultor.desconto_instalacao_antecipada or 0)
                if val > 0:
                    pendencias.append(self._montar_obj(v, 'ANTECIPACAO', val, 'Desconto Antecipação'))

        return Response(pendencias)

    def _montar_obj(self, venda, tipo_codigo, valor, titulo):
        return {
            'venda_id': venda.id,
            'data_instalacao': venda.data_instalacao,
            'cliente': venda.cliente.nome_razao_social,
            'cliente_cpf': venda.cliente.cpf_cnpj,
            'os': venda.ordem_servico or "",
            'vendedor_id': venda.vendedor.id,
            'vendedor_nome': venda.vendedor.username,
            'tipo_codigo': tipo_codigo,
            'titulo': titulo,
            'valor': valor
        }

# --- VIEWS PARA CONFIRMAÇÃO E REVERSÃO DE DESCONTOS ---

class PendenciasDescontoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        vendas = Venda.objects.filter(
            ativo=True,
            status_esteira__nome__iexact='INSTALADA'
        ).select_related('vendedor', 'forma_pagamento', 'cliente')

        pendencias = []

        for v in vendas:
            consultor = v.vendedor
            if not consultor: continue

            doc = v.cliente.cpf_cnpj if v.cliente else ''
            doc_limpo = ''.join(filter(str.isdigit, doc))
            eh_cnpj = len(doc_limpo) > 11

            if eh_cnpj and not v.flag_adiant_cnpj:
                val = float(consultor.adiantamento_cnpj or 0)
                if val > 0: pendencias.append(self._montar_obj(v, 'CNPJ', val, 'Adiantamento CNPJ'))

            if v.forma_pagamento and 'BOLETO' in v.forma_pagamento.nome.upper() and not v.flag_desc_boleto:
                val = float(consultor.desconto_boleto or 0)
                if val > 0: pendencias.append(self._montar_obj(v, 'BOLETO', val, 'Desconto Boleto'))

            if v.inclusao and not v.flag_desc_viabilidade:
                val = float(consultor.desconto_inclusao_viabilidade or 0)
                if val > 0: pendencias.append(self._montar_obj(v, 'VIABILIDADE', val, 'Desconto Viabilidade'))

            if v.antecipou_instalacao and not v.flag_desc_antecipacao:
                val = float(consultor.desconto_instalacao_antecipada or 0)
                if val > 0: pendencias.append(self._montar_obj(v, 'ANTECIPACAO', val, 'Desconto Antecipação'))

        return Response(pendencias)

    def _montar_obj(self, venda, tipo_codigo, valor, titulo):
        return {
            'venda_id': venda.id,
            'data_instalacao': venda.data_instalacao,
            'cliente': venda.cliente.nome_razao_social,
            'cliente_cpf': venda.cliente.cpf_cnpj,
            'os': venda.ordem_servico or "",
            'vendedor_id': venda.vendedor.id,
            'vendedor_nome': venda.vendedor.username,
            'tipo_codigo': tipo_codigo,
            'titulo': titulo,
            'valor': valor
        }

class ConfirmarDescontosEmMassaView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data_lancamento = request.data.get('data')
        itens = request.data.get('itens', []) 

        if not data_lancamento or not itens:
            return Response({'error': 'Dados inválidos.'}, status=400)

        agrupado = defaultdict(lambda: {'total': 0.0, 'ids_vendas': [], 'tipos': set()})
        updates_flags = {'CNPJ': [], 'BOLETO': [], 'VIABILIDADE': [], 'ANTECIPACAO': []}

        for item in itens:
            v_id = item['venda_id']
            tipo = item['tipo_codigo']
            valor = float(item['valor'])
            vend_id = item['vendedor_id']

            agrupado[vend_id]['total'] += valor
            agrupado[vend_id]['ids_vendas'].append(v_id) # Guarda ID como int
            agrupado[vend_id]['tipos'].add(tipo)
            
            if tipo in updates_flags: updates_flags[tipo].append(v_id)

        try:
            with transaction.atomic():
                lancamentos_criados = []
                for vend_id, dados in agrupado.items():
                    tipos_lista = list(dados['tipos'])
                    tipos_str = ", ".join(tipos_lista)
                    qtd = len(dados['ids_vendas'])
                    
                    categ = 'ADIANTAMENTO_CNPJ' if 'CNPJ' in dados['tipos'] and len(dados['tipos']) == 1 else 'DESCONTO'
                    
                    # SALVA OS IDs NO JSON 'METADADOS' PARA PERMITIR REVERSÃO
                    metadados = {
                        "origem": "automatico",
                        "ids_vendas": dados['ids_vendas'],
                        "tipos_processados": tipos_lista
                    }

                    lancamentos_criados.append(LancamentoFinanceiro(
                        usuario_id=vend_id,
                        tipo=categ,
                        data=data_lancamento,
                        valor=dados['total'],
                        quantidade_vendas=qtd,
                        descricao=f"Processamento Auto: {tipos_str}",
                        metadados=metadados,
                        criado_por=request.user
                    ))
                
                if lancamentos_criados:
                    LancamentoFinanceiro.objects.bulk_create(lancamentos_criados)

                if updates_flags['CNPJ']: Venda.objects.filter(id__in=updates_flags['CNPJ']).update(flag_adiant_cnpj=True)
                if updates_flags['BOLETO']: Venda.objects.filter(id__in=updates_flags['BOLETO']).update(flag_desc_boleto=True)
                if updates_flags['VIABILIDADE']: Venda.objects.filter(id__in=updates_flags['VIABILIDADE']).update(flag_desc_viabilidade=True)
                if updates_flags['ANTECIPACAO']: Venda.objects.filter(id__in=updates_flags['ANTECIPACAO']).update(flag_desc_antecipacao=True)

            return Response({'mensagem': f'{len(itens)} descontos processados com sucesso!'})

        except Exception as e:
            return Response({'error': str(e)}, status=500)

class HistoricoDescontosAutoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Lista lançamentos financeiros automáticos recentes
        # Filtra onde metadados contém "origem": "automatico"
        # SQLite não suporta filtro JSON nativo complexo em Django antigo, então filtramos na descrição ou trazemos tudo
        lancamentos = LancamentoFinanceiro.objects.filter(
            descricao__startswith="Processamento Auto"
        ).select_related('usuario', 'criado_por').order_by('-data_criacao')[:50] # Últimos 50

        data = []
        for l in lancamentos:
            data.append({
                'id': l.id,
                'data_lancamento': l.data,
                'vendedor': l.usuario.username,
                'tipo': l.tipo,
                'descricao': l.descricao,
                'valor': l.valor,
                'criado_por': l.criado_por.username if l.criado_por else 'Sistema',
                'criado_em': l.data_criacao
            })
        return Response(data)

class ReverterDescontoMassaView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        lancamento_id = request.data.get('id')
        if not lancamento_id:
            return Response({'error': 'ID inválido.'}, status=400)

        try:
            lancamento = LancamentoFinanceiro.objects.get(id=lancamento_id)
            
            # Verifica se é um lançamento automático
            if not lancamento.descricao.startswith("Processamento Auto"):
                 return Response({'error': 'Apenas lançamentos automáticos podem ser revertidos por aqui.'}, status=400)

            # --- CORREÇÃO PARA REGISTROS ANTIGOS ---
            # Se não tiver metadados (registros criados durante os testes anteriores),
            # permitimos excluir apenas o financeiro para limpar a tela.
            if not lancamento.metadados:
                lancamento.delete()
                return Response({'mensagem': 'Registro antigo excluído do financeiro! Nota: As flags nas vendas NÃO foram revertidas (dados de vínculo ausentes).'})
            # ---------------------------------------

            meta = lancamento.metadados
            ids_vendas = meta.get('ids_vendas', [])
            tipos = meta.get('tipos_processados', [])

            with transaction.atomic():
                if ids_vendas:
                    # Reverte as flags nas vendas originais
                    vendas_afetadas = Venda.objects.filter(id__in=ids_vendas)
                    updates = {}
                    
                    if 'CNPJ' in tipos: updates['flag_adiant_cnpj'] = False
                    if 'BOLETO' in tipos: updates['flag_desc_boleto'] = False
                    if 'VIABILIDADE' in tipos: updates['flag_desc_viabilidade'] = False
                    if 'ANTECIPACAO' in tipos: updates['flag_desc_antecipacao'] = False
                    
                    if updates:
                        vendas_afetadas.update(**updates)

                # Apaga o lançamento financeiro
                lancamento.delete()

            return Response({'mensagem': 'Reversão concluída com sucesso! As vendas voltaram para a lista de pendências.'})

        except LancamentoFinanceiro.DoesNotExist:
            return Response({'error': 'Lançamento não encontrado.'}, status=404)
        except Exception as e:
            return Response({'error': str(e)}, status=500)
class VerificarPermissaoGestaoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Reutiliza sua função is_member
        eh_gestao = is_member(request.user, ['Diretoria', 'Admin'])
        return Response({'eh_gestao': eh_gestao})

# Em site-record/crm_app/views.py

class ImportacaoLegadoView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    # --- 1. DOWNLOAD DO MODELO (GET) ---
    def get(self, request):
        """
        Gera e baixa a planilha modelo atualizada (V4).
        """
        headers = {
            # DADOS DA VENDA
            'DATA_VENDA': ['01/01/2024'],
            'DATA_INSTALACAO': ['05/01/2024'],
            'LOGIN_VENDEDOR': ['joao.silva'],
            'NOME_PLANO': ['Internet 600 Mega'],
            'FORMA_PAGAMENTO': ['Boleto'],
            'OS': ['0123456'], # Exemplo com zero à esquerda
            
            # TRÂMITE / STATUS
            'STATUS_ESTEIRA': ['Instalada'], 
            'STATUS_TRATAMENTO': ['Fechado'], 
            'MOTIVO_PENDENCIA': [''], 
            'DATA_AGENDAMENTO': [''], 
            'PERIODO_AGENDAMENTO': [''], 
            
            # DADOS DO CLIENTE
            'CPF_CNPJ_CLIENTE': ['12345678900'],
            'NOME_CLIENTE': ['Fulano de Tal'],
            'DATA_NASCIMENTO': ['15/05/1990'],
            'NOME_MAE': ['Maria da Silva'],
            
            # CONTATO
            'TELEFONE_1': ['31999998888'],
            'TELEFONE_2': [''],
            'EMAIL_CLIENTE': ['cliente@email.com'],

            # ENDEREÇO
            'CEP': ['30000000'],
            'NUMERO': ['123'],
            'COMPLEMENTO': ['Apto 101'],
            'PONTO_REFERENCIA': ['Próximo ao Mercado'],
            'LOGRADOURO': [''], 
            'BAIRRO': [''],     
            'CIDADE': [''],     
            'UF': [''],         
            
            'OBSERVACOES': ['Importação Histórico']
        }
        
        df = pd.DataFrame(headers)
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Modelo Legado')
            worksheet = writer.sheets['Modelo Legado']
            
            for idx, col in enumerate(df.columns):
                col_letter = get_column_letter(idx + 1)
                worksheet.column_dimensions[col_letter].width = 20

        output.seek(0)
        response = HttpResponse(output, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="modelo_legado_v4.xlsx"'
        return response

    # --- 2. IMPORTAÇÃO E PROCESSAMENTO (POST) ---
    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Nenhum arquivo enviado.'}, status=400)

        try:
            # --- CORREÇÃO PRINCIPAL: dtype=str ---
            # Lê todas as colunas como TEXTO para preservar zeros (OS, CPF, CEP)
            df = pd.read_excel(file_obj, dtype=str)
        except Exception as e:
            return Response({'error': f'Erro ao ler Excel: {str(e)}'}, status=400)

        # Normaliza nomes das colunas
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        # Limpeza de valores vazios/nulos que vêm como string "nan"
        df = df.replace({np.nan: None, 'nan': None, 'NaN': None, 'None': None})

        # --- CACHES PARA PERFORMANCE ---
        users_map = {u.username.upper(): u for u in get_user_model().objects.all()}
        for u in get_user_model().objects.all():
            if u.email: users_map[u.email.upper()] = u

        planos_map = {p.nome.upper(): p for p in Plano.objects.all()}
        pgto_map = {fp.nome.upper(): fp for fp in FormaPagamento.objects.all()}
        
        status_esteira_map = {s.nome.upper(): s for s in StatusCRM.objects.filter(tipo='Esteira')}
        status_tratamento_map = {s.nome.upper(): s for s in StatusCRM.objects.filter(tipo='Tratamento')}
        
        motivo_map = {}
        for m in MotivoPendencia.objects.all():
            motivo_map[m.nome.upper().strip()] = m
            parts = m.nome.split('-')
            if len(parts) > 1: motivo_map[parts[0].strip()] = m

        cache_viacep = {}
        vendas_para_criar = []
        logs_erro = []
        sucessos = 0

        # --- FUNÇÕES AUXILIARES ---
        def parse_dt(val):
            if not val: return None
            # Como tudo é string agora, pd.to_datetime lida bem
            try: return pd.to_datetime(val, dayfirst=True, errors='coerce').date()
            except: return None

        def parse_periodo(val):
            if not val: return None
            v = str(val).upper()
            if 'MANH' in v: return 'MANHA'
            if 'TARDE' in v: return 'TARDE'
            if 'NOITE' in v: return 'NOITE'
            return None
        
        def consultar_cep_otimizado(cep_input):
            if not cep_input: return {}
            cep_limpo = str(cep_input).replace('-', '').replace('.', '').strip()
            if len(cep_limpo) != 8: return {}
            
            if cep_limpo in cache_viacep: return cache_viacep[cep_limpo]
            
            try:
                resp = requests.get(f"https://viacep.com.br/ws/{cep_limpo}/json/", timeout=2)
                if resp.status_code == 200:
                    dados = resp.json()
                    if 'erro' not in dados:
                        res = {
                            'logradouro': dados.get('logradouro', '').upper(),
                            'bairro': dados.get('bairro', '').upper(),
                            'cidade': dados.get('localidade', '').upper(),
                            'uf': dados.get('uf', '').upper()
                        }
                        cache_viacep[cep_limpo] = res
                        return res
            except: pass
            
            cache_viacep[cep_limpo] = {}
            return {}

        # --- LOOP DE PROCESSAMENTO ---
        for index, row in df.iterrows():
            linha = index + 2
            try:
                # 1. CLIENTE & CPF
                cpf_raw = str(row.get('CPF_CNPJ_CLIENTE', ''))
                cpf_limpo = ''.join(filter(str.isdigit, cpf_raw))
                
                if cpf_limpo and len(cpf_limpo) < 11:
                    cpf_limpo = cpf_limpo.zfill(11)
                
                if not cpf_limpo or len(cpf_limpo) < 11:
                    logs_erro.append(f"Linha {linha}: CPF inválido ou vazio ({cpf_raw}).")
                    continue

                nome_cli = str(row.get('NOME_CLIENTE', 'Cliente Importado')).upper()
                
                cliente, _ = Cliente.objects.get_or_create(
                    cpf_cnpj=cpf_limpo, defaults={'nome_razao_social': nome_cli}
                )
                
                mudou_cliente = False
                if row.get('TELEFONE_1'): 
                    cliente.telefone1 = str(row.get('TELEFONE_1'))
                    mudou_cliente = True
                if row.get('TELEFONE_2'): 
                    cliente.telefone2 = str(row.get('TELEFONE_2'))
                    mudou_cliente = True
                if row.get('EMAIL_CLIENTE'): 
                    cliente.email = str(row.get('EMAIL_CLIENTE'))
                    mudou_cliente = True
                if row.get('DATA_NASCIMENTO'): 
                    cliente.data_nascimento = parse_dt(row.get('DATA_NASCIMENTO'))
                    mudou_cliente = True
                if row.get('NOME_MAE'): 
                    cliente.nome_mae = str(row.get('NOME_MAE')).upper()
                    mudou_cliente = True
                
                if mudou_cliente:
                    cliente.save()

                # 2. VENDEDOR
                login_vend = str(row.get('LOGIN_VENDEDOR', '')).upper().strip()
                vendedor = users_map.get(login_vend)

                # 3. PLANO & PAGAMENTO
                nome_plano = str(row.get('NOME_PLANO', '')).upper().strip()
                plano = planos_map.get(nome_plano)
                
                nome_pgto = str(row.get('FORMA_PAGAMENTO', '')).upper().strip()
                pgto = pgto_map.get(nome_pgto)

                # 4. STATUS
                nome_est = str(row.get('STATUS_ESTEIRA', '')).upper().strip()
                status_esteira = status_esteira_map.get(nome_est)
                
                if not status_esteira and nome_est:
                    if 'INSTAL' in nome_est or 'CONCLU' in nome_est: 
                        status_esteira = status_esteira_map.get('INSTALADA')
                    elif 'PENDEN' in nome_est: 
                        status_esteira = status_esteira_map.get('PENDENCIADA')
                    elif 'AGEND' in nome_est: 
                        status_esteira = status_esteira_map.get('AGENDADO')
                    elif 'CANCEL' in nome_est: 
                        status_esteira = status_esteira_map.get('CANCELADA')

                motivo_pend = None
                if row.get('MOTIVO_PENDENCIA'):
                    motivo_pend = motivo_map.get(str(row.get('MOTIVO_PENDENCIA')).upper().strip())

                status_tratamento = status_tratamento_map.get(str(row.get('STATUS_TRATAMENTO', '')).upper().strip())
                if not status_tratamento:
                    if status_esteira and status_esteira.nome.upper() in ['INSTALADA', 'CANCELADA']:
                        status_tratamento = status_tratamento_map.get('FECHADO')
                    else:
                        status_tratamento = status_tratamento_map.get('SEM TRATAMENTO')

                # 5. DATAS
                dt_venda = parse_dt(row.get('DATA_VENDA'))
                if not dt_venda: dt_venda = timezone.now().date()

                dt_inst = parse_dt(row.get('DATA_INSTALACAO'))
                dt_agend = parse_dt(row.get('DATA_AGENDAMENTO'))

                if status_esteira and status_esteira.nome.upper() == 'INSTALADA' and not dt_inst:
                    dt_inst = dt_venda

                # 6. ENDEREÇO
                cep_raw = str(row.get('CEP', '')).replace('-', '').replace('.', '').strip()
                cep_final = cep_raw[:9]
                
                logradouro = str(row.get('LOGRADOURO', '')).upper()
                bairro = str(row.get('BAIRRO', '')).upper()
                cidade = str(row.get('CIDADE', '')).upper()
                uf = str(row.get('UF', '')).upper()
                
                if cep_final and (not logradouro or not bairro):
                    dados_api = consultar_cep_otimizado(cep_final)
                    if dados_api:
                        logradouro = dados_api.get('logradouro', '')
                        bairro = dados_api.get('bairro', '')
                        cidade = dados_api.get('cidade', '')
                        uf = dados_api.get('uf', '')

                # 7. O.S. (Preservando Zero à Esquerda)
                os_raw = str(row.get('OS', '')).strip()
                # Remove .0 se por acaso o Excel mandou "0123.0"
                if os_raw.endswith('.0'): os_raw = os_raw[:-2]

                # --- INSTANCIAÇÃO ---
                venda = Venda(
                    cliente=cliente,
                    vendedor=vendedor,
                    plano=plano,
                    forma_pagamento=pgto,
                    
                    status_esteira=status_esteira,
                    status_tratamento=status_tratamento,
                    motivo_pendencia=motivo_pend,
                    
                    data_pedido=dt_venda,
                    data_instalacao=dt_inst,
                    data_agendamento=dt_agend,
                    periodo_agendamento=parse_periodo(row.get('PERIODO_AGENDAMENTO')),
                    
                    # DATA DE CRIAÇÃO = DATA DA VENDA (Para relatório retroativo funcionar)
                    data_criacao=dt_venda, 
                    
                    # Endereço
                    cep=cep_final,
                    logradouro=logradouro[:255],
                    numero_residencia=str(row.get('NUMERO', ''))[:20],
                    complemento=str(row.get('COMPLEMENTO', '')).upper()[:100],
                    bairro=bairro[:100],
                    cidade=cidade[:100],
                    estado=uf[:2],
                    ponto_referencia=str(row.get('PONTO_REFERENCIA', '')).upper()[:255],

                    # O.S. Preservada
                    ordem_servico=os_raw,
                    
                    # SEM campo VALOR (Vem do plano)
                    observacoes=str(row.get('OBSERVACOES', 'Importação Legado'))[:500],
                    ativo=True
                )
                
                vendas_para_criar.append(venda)
                sucessos += 1

            except Exception as e:
                logs_erro.append(f"Linha {linha}: {str(e)}")

        # --- GRAVAÇÃO EM LOTE ---
        if vendas_para_criar:
            with transaction.atomic():
                Venda.objects.bulk_create(vendas_para_criar, batch_size=1000)

        return Response({
            'mensagem': f'Importação concluída! {sucessos} vendas processadas.',
            'total_erros': len(logs_erro),
            'erros': logs_erro
        })
# Adicione ou certifique-se que esta classe existe
class ConfigurarAutomacaoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not is_member(request.user, ['Diretoria', 'Admin']):
            return Response({"error": "Sem permissão"}, status=403)

        acao = request.data.get('acao')
        
        if acao == 'listar':
            regras = AgendamentoDisparo.objects.all().values()
            return Response(list(regras))
            
        elif acao == 'salvar':
            d = request.data.get('dados')
            defaults = {
                'nome': d['nome'], 'tipo': d['tipo'], 
                'canal_alvo': d['canal_alvo'], 
                'destinatarios': d['destinatarios'], 
                'ativo': d['ativo']
            }
            if d.get('id'):
                AgendamentoDisparo.objects.filter(id=d['id']).update(**defaults)
            else:
                AgendamentoDisparo.objects.create(**defaults)
            return Response({'ok': True})
            
        elif acao == 'excluir':
            AgendamentoDisparo.objects.filter(id=request.data.get('id')).delete()
            return Response({'ok': True})
            
        return Response({'error': 'Ação inválida'}, status=400)
class CdoiCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        try:
            data = request.POST
            files = request.FILES
            
            nome_condominio = data.get('nome_condominio') or data.get('cliente')
            if not nome_condominio:
                 return Response({"error": "Nome do condomínio é obrigatório."}, status=400)

            # Upload OneDrive (Mantido igual)
            uploader = OneDriveUploader()
            clean_name = str(nome_condominio).replace('/', '-').strip()
            folder_name = f"{clean_name}_{data.get('cep', '')}"
            
            link_carta = None
            if 'arquivo_carta' in files:
                f = files['arquivo_carta']
                link_carta = uploader.upload_file(f, folder_name, f"CARTA_{f.name}")

            link_fachada = None
            if 'arquivo_fachada' in files:
                f = files['arquivo_fachada']
                link_fachada = uploader.upload_file(f, folder_name, f"FACHADA_{f.name}")

            cdoi = CdoiSolicitacao.objects.create(
                nome_condominio=nome_condominio,
                nome_sindico=data.get('nome_sindico'),
                contato_sindico=data.get('contato'),
                cep=data.get('cep'),
                logradouro=data.get('logradouro'),
                numero=data.get('numero'),
                bairro=data.get('bairro'),
                cidade=data.get('cidade'),
                uf=data.get('uf'),
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                infraestrutura_tipo=data.get('infraestrutura'),
                possui_shaft_dg=(data.get('possui_shaft') == 'on'),
                total_hps=data.get('total_hps_final') or 0,
                pre_venda_minima=data.get('prevenda_final') or 0,
                link_carta_sindico=link_carta,
                link_fotos_fachada=link_fachada,
                criado_por=request.user,
                status="SEM_TRATAMENTO" # Status inicial novo
            )

            # Salvar Blocos (Mantido igual)
            blocos_json = data.get('dados_blocos_json')
            if blocos_json:
                try:
                    blocos = json.loads(blocos_json)
                    for b in blocos:
                        CdoiBloco.objects.create(
                            solicitacao=cdoi,
                            nome_bloco=b['nome'],
                            andares=int(b['andares']),
                            unidades_por_andar=int(b['aptos']),
                            total_hps_bloco=int(b['total'])
                        )
                except Exception as e_blocos:
                    print(f"Erro ao salvar blocos: {e_blocos}")

            # --- ITEM 4: WHATSAPP DESCOMENTADO ---
            try:
                if cdoi.contato_sindico:
                     # Instancia o serviço (certifique-se que as credenciais no .env estão ok)
                     svc = WhatsAppService()
                     msg_text = f"Olá, sua solicitação de CDOI para *{cdoi.nome_condominio}* foi recebida com sucesso! ID: {cdoi.id}. Status: Sem Tratamento."
                     # Removemos o # para ativar
                     svc.enviar_mensagem_texto(cdoi.contato_sindico, msg_text)
            except Exception as e_zap:
                print(f"Erro ao enviar Zap CDOI: {e_zap}")

            return Response({'mensagem': f'Solicitação enviada! ID: {cdoi.id}'}, status=200)

        except Exception as e:
            print(f"Erro CDOI: {e}")
            return Response({'error': f"Erro ao processar: {str(e)}"}, status=500)

# --- 2. LISTAGEM (Meus Acionamentos) ---
class CdoiListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        # Perfis que veem tudo
        grupos_gestao = ['Diretoria', 'Admin', 'BackOffice']
        eh_gestao = is_member(user, grupos_gestao)

        if eh_gestao:
            queryset = CdoiSolicitacao.objects.all().order_by('-data_criacao')
        else:
            # Usuário comum vê apenas os seus
            queryset = CdoiSolicitacao.objects.filter(criado_por=user).order_by('-data_criacao')

        data = []
        for item in queryset:
            data.append({
                'id': item.id,
                'nome': item.nome_condominio,
                'cidade': f"{item.cidade}-{item.uf}",
                'logradouro': item.logradouro,
                'numero': item.numero,
                'bairro': item.bairro,
                'nome_sindico': item.nome_sindico,
                'contato': item.contato_sindico,
                'total_hps': item.total_hps,
                'prevenda': item.pre_venda_minima,
                'status': item.get_status_display(),
                'status_cod': item.status,
                'observacao': item.observacao or "",
                'data': item.data_criacao.strftime('%d/%m/%Y'),
                'link_fotos_fachada': item.link_fotos_fachada or "",
                'can_edit': eh_gestao # Flag para o frontend saber se libera edição
            })
        
        return Response(data)

# --- 3. EDIÇÃO DE STATUS (Apenas Gestão) ---
class CdoiUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        user = request.user
        if not is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            return Response({"error": "Acesso negado."}, status=403)

        try:
            cdoi = CdoiSolicitacao.objects.get(pk=pk)
            blocos = [
                {
                    'nome': b.nome_bloco,
                    'andares': b.andares,
                    'aptos': b.unidades_por_andar,
                    'total': b.total_hps_bloco,
                }
                for b in cdoi.blocos.all()
            ]

            data = {
                'id': cdoi.id,
                'nome_condominio': cdoi.nome_condominio,
                'cep': cdoi.cep,
                'numero': cdoi.numero,
                'nome_sindico': cdoi.nome_sindico,
                'contato': cdoi.contato_sindico,
                'infraestrutura': cdoi.infraestrutura_tipo,
                'possui_shaft': cdoi.possui_shaft_dg,
                'latitude': cdoi.latitude or '',
                'longitude': cdoi.longitude or '',
                'blocos': blocos,
            }
            return Response(data)
        except CdoiSolicitacao.DoesNotExist:
            return Response({"error": "Solicitação não encontrada."}, status=404)

    def patch(self, request, pk):
        user = request.user
        if not is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            return Response({"error": "Acesso negado."}, status=403)

        try:
            cdoi = CdoiSolicitacao.objects.get(pk=pk)
            data = request.data

            # Campos pontuais
            if data.get('status'):
                cdoi.status = data.get('status')
            if 'observacao' in data:
                cdoi.observacao = data.get('observacao')
            if data.get('nome_condominio'):
                cdoi.nome_condominio = data.get('nome_condominio')
            if data.get('cep'):
                cdoi.cep = data.get('cep')
            if data.get('numero'):
                cdoi.numero = data.get('numero')
            if data.get('nome_sindico'):
                cdoi.nome_sindico = data.get('nome_sindico')
            if data.get('contato'):
                cdoi.contato_sindico = data.get('contato')
            if data.get('infraestrutura'):
                cdoi.infraestrutura_tipo = data.get('infraestrutura')
            if 'possui_shaft' in data:
                val = data.get('possui_shaft')
                if isinstance(val, str):
                    cdoi.possui_shaft_dg = val.lower() in ['on', 'true', '1']
                else:
                    cdoi.possui_shaft_dg = bool(val)
            if data.get('latitude'):
                cdoi.latitude = data.get('latitude')
            if data.get('longitude'):
                cdoi.longitude = data.get('longitude')

            # Atualiza blocos apenas se fornecido
            blocos_json = data.get('dados_blocos_json') or data.get('input_blocos_json')
            if blocos_json:
                import json as _json
                try:
                    blocos = _json.loads(blocos_json)
                    cdoi.blocos.all().delete()
                    for b in blocos:
                        CdoiBloco.objects.create(
                            solicitacao=cdoi,
                            nome_bloco=b.get('nome'),
                            andares=int(b.get('andares') or 0),
                            unidades_por_andar=int(b.get('aptos') or 0),
                            total_hps_bloco=int(b.get('total') or 0)
                        )
                except Exception as e:
                    return Response({"error": f"Erro ao atualizar blocos: {e}"}, status=400)
            
            cdoi.save()
            return Response({"mensagem": "Atualizado com sucesso!"})
        except CdoiSolicitacao.DoesNotExist:
            return Response({"error": "Solicitação não encontrada."}, status=404)

    def put(self, request, pk):
        user = request.user
        if not is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            return Response({"error": "Acesso negado."}, status=403)

        try:
            cdoi = CdoiSolicitacao.objects.get(pk=pk)
            data = request.data

            # Atualiza campos principais
            cdoi.nome_condominio = data.get('nome_condominio', cdoi.nome_condominio)
            cdoi.nome_sindico = data.get('nome_sindico', cdoi.nome_sindico)
            cdoi.contato_sindico = data.get('contato', cdoi.contato_sindico)
            cdoi.cep = data.get('cep', cdoi.cep)
            cdoi.logradouro = data.get('logradouro', cdoi.logradouro)
            cdoi.numero = data.get('numero', cdoi.numero)
            cdoi.bairro = data.get('bairro', cdoi.bairro)
            cdoi.cidade = data.get('cidade', cdoi.cidade)
            cdoi.uf = data.get('uf', cdoi.uf)
            cdoi.latitude = data.get('latitude', cdoi.latitude)
            cdoi.longitude = data.get('longitude', cdoi.longitude)
            cdoi.infraestrutura_tipo = data.get('infraestrutura', cdoi.infraestrutura_tipo)
            # checkbox pode vir como 'on' ou 'true'
            possui_shaft_val = data.get('possui_shaft', None)
            if isinstance(possui_shaft_val, str):
                cdoi.possui_shaft_dg = possui_shaft_val.lower() in ['on', 'true', '1']
            elif isinstance(possui_shaft_val, bool):
                cdoi.possui_shaft_dg = possui_shaft_val

            # Totais
            try:
                cdoi.total_hps = int(data.get('total_hps_final') or data.get('input_total_hps') or cdoi.total_hps or 0)
            except Exception:
                pass
            try:
                cdoi.pre_venda_minima = int(data.get('prevenda_final') or data.get('input_prevenda') or cdoi.pre_venda_minima or 0)
            except Exception:
                pass

            cdoi.save()

            # Atualiza blocos se enviados
            blocos_json = data.get('dados_blocos_json') or data.get('input_blocos_json')
            if blocos_json:
                try:
                    import json as _json
                    blocos = _json.loads(blocos_json)
                    # Remove blocos existentes e recria
                    cdoi.blocos.all().delete()
                    for b in blocos:
                        CdoiBloco.objects.create(
                            solicitacao=cdoi,
                            nome_bloco=b.get('nome'),
                            andares=int(b.get('andares') or 0),
                            unidades_por_andar=int(b.get('aptos') or 0),
                            total_hps_bloco=int(b.get('total') or 0)
                        )
                except Exception as e:
                    return Response({"error": f"Erro ao atualizar blocos: {e}"}, status=400)

            return Response({"mensagem": "Solicitação atualizada com sucesso!"})
        except CdoiSolicitacao.DoesNotExist:
            return Response({"error": "Solicitação não encontrada."}, status=404)

    def delete(self, request, pk):
        user = request.user
        if not is_member(user, ['Diretoria', 'Admin']):
            return Response({"error": "Acesso negado."}, status=403)

        try:
            cdoi = CdoiSolicitacao.objects.get(pk=pk)
            # Exclusão lógica: marca como CANCELADA
            cdoi.status = 'CANCELADA'
            cdoi.save()
            return Response({"mensagem": "Solicitação marcada como cancelada."}, status=200)
        except CdoiSolicitacao.DoesNotExist:
            return Response({"error": "Solicitação não encontrada."}, status=404)

# --- AQUI ESTÁ A CORREÇÃO: A FUNÇÃO DEVE FICAR FORA DA CLASSE ---
# Note que não tem espaço antes do 'def'

def page_cdoi_novo(request):
    """View simples para abrir a página no navegador"""
    return render(request, 'cdoi_form.html')


# =============================================================================
# BÔNUS M-10 & FPD - VIEWS
# =============================================================================

from django.db.models import Q, Count, Sum, Avg
from django.http import HttpResponse
import pandas as pd
from datetime import datetime
from .models import SafraM10, ContratoM10, FaturaM10


def page_bonus_m10(request):
    """View para renderizar a página HTML"""
    return render(request, 'bonus_m10.html')


class SafraM10ListView(APIView):
    """Lista todas as safras disponíveis"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        safras = SafraM10.objects.all().order_by('-mes_referencia')
        data = []
        for s in safras:
            data.append({
                'id': s.id,
                'mes_referencia': s.mes_referencia.isoformat(),
                'mes_referencia_formatado': s.mes_referencia.strftime('%B/%Y'),
                'total_instalados': s.total_instalados,
                'total_ativos': s.total_ativos,
                'total_elegivel_bonus': s.total_elegivel_bonus,
                'valor_bonus_total': float(s.valor_bonus_total),
            })
        return Response(data)


class DashboardM10View(APIView):
    """Dashboard com estatísticas M-10"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        safra_id = request.GET.get('safra')
        if not safra_id:
            return Response({'error': 'Safra não informada'}, status=400)

        try:
            safra = SafraM10.objects.get(id=safra_id)
        except SafraM10.DoesNotExist:
            return Response({'error': 'Safra não encontrada'}, status=404)

        # Filtros
        queryset = ContratoM10.objects.filter(safra=safra)
        
        vendedor = request.GET.get('vendedor')
        if vendedor:
            queryset = queryset.filter(vendedor_id=vendedor)
        
        status = request.GET.get('status')
        if status:
            queryset = queryset.filter(status_contrato=status)
        
        elegivel = request.GET.get('elegivel')
        if elegivel:
            queryset = queryset.filter(elegivel_bonus=(elegivel == 'true'))

        # Estatísticas
        total = queryset.count()
        ativos = queryset.filter(status_contrato='ATIVO').count()
        elegiveis = queryset.filter(elegivel_bonus=True).count()
        valor_total = elegiveis * 150  # R$ 150 por contrato elegível

        taxa_permanencia = round((ativos / total * 100) if total > 0 else 0, 1)

        # Paginação - Limita a 100 registros por página
        page = int(request.GET.get('page', 1))
        page_size = 100
        start = (page - 1) * page_size
        end = start + page_size

        # Contratos para tabela (apenas dados essenciais)
        contratos_data = []
        for c in queryset.select_related('vendedor')[start:end]:
            faturas_pagas = c.faturas.filter(status='PAGO').count()
            contratos_data.append({
                'id': c.id,
                'numero_contrato': c.numero_contrato,
                'cliente_nome': c.cliente_nome,
                'vendedor_nome': c.vendedor.get_full_name() if c.vendedor else '-',
                'data_instalacao': c.data_instalacao.strftime('%d/%m/%Y'),
                'plano_atual': c.plano_atual,
                'status': c.status_contrato,
                'status_display': c.get_status_contrato_display(),
                'faturas_pagas': faturas_pagas,
                'elegivel': c.elegivel_bonus,
            })

        total_pages = (total + page_size - 1) // page_size

        return Response({
            'total': total,
            'ativos': ativos,
            'elegiveis': elegiveis,
            'valor_total': valor_total,
            'taxa_permanencia': taxa_permanencia,
            'contratos': contratos_data,
            'page': page,
            'total_pages': total_pages,
            'page_size': page_size,
        })


class DashboardFPDView(APIView):
    """Dashboard com estatísticas FPD"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        mes_str = request.GET.get('mes')  # formato: 2025-07
        
        # Filtrar faturas número 1 (primeira fatura)
        queryset = FaturaM10.objects.filter(numero_fatura=1)
        
        if mes_str:
            ano, mes = mes_str.split('-')
            queryset = queryset.filter(data_vencimento__year=ano, data_vencimento__month=mes)
        
        status_filtro = request.GET.get('status')
        if status_filtro:
            queryset = queryset.filter(status=status_filtro)
        
        vendedor = request.GET.get('vendedor')
        if vendedor:
            queryset = queryset.filter(contrato__vendedor_id=vendedor)

        # Estatísticas
        total_geradas = queryset.count()
        total_pagas = queryset.filter(status='PAGO').count()
        total_aberto = queryset.filter(status__in=['NAO_PAGO', 'AGUARDANDO']).count()
        taxa_fpd = round((total_pagas / total_geradas * 100) if total_geradas > 0 else 0, 1)

        # Faturas para tabela
        faturas_data = []
        for f in queryset.select_related('contrato', 'contrato__vendedor'):
            faturas_data.append({
                'id': f.id,
                'contrato_id': f.contrato.id,
                'numero_contrato': f.contrato.numero_contrato,
                'cliente_nome': f.contrato.cliente_nome,
                'vendedor_nome': f.contrato.vendedor.get_full_name() if f.contrato.vendedor else '-',
                'data_vencimento': f.data_vencimento.strftime('%d/%m/%Y'),
                'valor': float(f.valor),
                'data_pagamento': f.data_pagamento.strftime('%d/%m/%Y') if f.data_pagamento else None,
                'status': f.status,
                'status_display': f.get_status_display(),
            })

        return Response({
            'total_geradas': total_geradas,
            'total_pagas': total_pagas,
            'total_aberto': total_aberto,
            'taxa_fpd': taxa_fpd,
            'faturas': faturas_data,
        })


class PopularSafraM10View(APIView):
    """Popula SafraM10 e ContratoM10 a partir da tabela Venda baseado em data_instalacao"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not is_member(request.user, ['Admin', 'BackOffice', 'Diretoria']):
            return Response({'error': 'Sem permissão'}, status=403)

        mes_referencia = request.data.get('mes_referencia')  # Formato: '2025-07'
        
        if not mes_referencia:
            return Response({'error': 'mes_referencia é obrigatório (formato: YYYY-MM)'}, status=400)

        try:
            # Converte para data (primeiro dia do mês)
            ano, mes = mes_referencia.split('-')
            data_inicio = datetime(int(ano), int(mes), 1).date()
            # Próximo mês para o range
            if mes == '12':
                data_fim = datetime(int(ano) + 1, 1, 1).date()
            else:
                data_fim = datetime(int(ano), int(mes) + 1, 1).date()
            
            # Busca ou cria a Safra M-10
            safra, safra_criada = SafraM10.objects.get_or_create(
                mes_referencia=data_inicio,
                defaults={
                    'total_instalados': 0,
                    'total_ativos': 0,
                    'total_elegivel_bonus': 0,
                    'valor_bonus_total': 0,
                }
            )

            # Busca Vendas com data_instalacao no mês de referência
            vendas = Venda.objects.filter(
                data_instalacao__gte=data_inicio,
                data_instalacao__lt=data_fim,
                data_instalacao__isnull=False,
                ativo=True
            ).select_related('cliente', 'vendedor')

            contratos_criados = 0
            contratos_duplicados = 0

            for venda in vendas:
                # Usa ordem_servico como número de contrato único
                numero_contrato = venda.ordem_servico or f"VENDA_{venda.id}"
                
                # Verifica se já existe contrato com este O.S
                contrato_existe = ContratoM10.objects.filter(
                    ordem_servico=venda.ordem_servico
                ).exists() if venda.ordem_servico else False

                if contrato_existe:
                    contratos_duplicados += 1
                    continue

                # Cria novo ContratoM10
                contrato = ContratoM10.objects.create(
                    safra=safra,
                    venda=venda,
                    numero_contrato=numero_contrato,
                    ordem_servico=venda.ordem_servico,
                    cliente_nome=venda.cliente.nome_razao_social,
                    cpf_cliente=venda.cliente.cpf_cnpj,
                    vendedor=venda.vendedor,
                    data_instalacao=venda.data_instalacao,
                    plano_original=venda.plano.nome if venda.plano else 'N/D',
                    plano_atual=venda.plano.nome if venda.plano else 'N/D',
                    valor_plano=venda.plano.valor if venda.plano else 0,
                    status_contrato='ATIVO',
                    observacao=f"Importado de Venda #{venda.id}"
                )
                contratos_criados += 1

            # Atualiza contagens na Safra
            safra.total_instalados = safra.contratos.count()
            safra.total_ativos = safra.contratos.filter(status_contrato='ATIVO').count()
            safra.save()

            return Response({
                'message': f'Safra {mes_referencia} populada com sucesso!',
                'safra_id': safra.id,
                'contratos_criados': contratos_criados,
                'contratos_duplicados': contratos_duplicados,
                'total_contratos_safra': safra.total_instalados,
            })

        except ValueError as e:
            return Response({'error': f'Formato de data inválido: {str(e)}'}, status=400)
        except Exception as e:
            return Response({'error': f'Erro ao popular safra: {str(e)}'}, status=500)


class ContratoM10DetailView(APIView):
    """Detalhes de um contrato com suas faturas"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        try:
            contrato = ContratoM10.objects.get(pk=pk)
            faturas = []
            for f in contrato.faturas.all().order_by('numero_fatura'):
                faturas.append({
                    'id': f.id,
                    'numero_fatura': f.numero_fatura,
                    'numero_fatura_operadora': f.numero_fatura_operadora or '',
                    'valor': float(f.valor),
                    'data_vencimento': f.data_vencimento.isoformat(),
                    'data_pagamento': f.data_pagamento.isoformat() if f.data_pagamento else '',
                    'status': f.status,
                })
            
            return Response({
                'id': contrato.id,
                'numero_contrato': contrato.numero_contrato,
                'cliente_nome': contrato.cliente_nome,
                'faturas': faturas,
            })
        except ContratoM10.DoesNotExist:
            return Response({'error': 'Contrato não encontrado'}, status=404)


class ImportarFPDView(APIView):
    """Importa planilha FPD da operadora e faz crossover com ContratoM10 por O.S"""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)
    
    def post(self, request):
        if not is_member(request.user, ['Admin', 'BackOffice', 'Diretoria']):
            return Response({'error': 'Sem permissão'}, status=403)

        arquivo = request.FILES.get('file')
        if not arquivo:
            return Response({'error': 'Arquivo não enviado'}, status=400)

        try:
            # Lê arquivo Excel/CSV
            if arquivo.name.endswith('.csv'):
                df = pd.read_csv(arquivo)
            elif arquivo.name.endswith('.xlsb'):
                try:
                    df = pd.read_excel(arquivo, engine='pyxlsb')
                except Exception:
                    return Response({
                        'error': 'Formato .xlsb não suportado. Use .xlsx, .xls ou .csv'
                    }, status=400)
            else:
                df = pd.read_excel(arquivo)

            registros_atualizados = 0
            registros_nao_encontrados = 0

            for _, row in df.iterrows():
                # Busca por O.S (NR_ORDEM na planilha)
                nr_ordem = str(row.get('NR_ORDEM', '')).strip()
                if not nr_ordem:
                    continue

                # Tenta encontrar contrato por ordem_servico
                try:
                    contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
                    
                    # Atualiza/cria primeira fatura (Safra FPD por mês de vencimento)
                    dt_venc = row.get('DT_VENC_ORIG')
                    dt_pgto = row.get('DT_PAGAMENTO')
                    status_str = str(row.get('DS_STATUS_FATURA', 'NAO_PAGO')).upper()
                    
                    # Mapeia status
                    status_map = {
                        'PAGO': 'PAGO',
                        'QUITADO': 'PAGO',
                        'ABERTO': 'NAO_PAGO',
                        'VENCIDO': 'ATRASADO',
                        'AGUARDANDO': 'AGUARDANDO',
                    }
                    status = status_map.get(status_str, 'NAO_PAGO')

                    # Se houver data de vencimento, define safra de FPD por mês de vencimento
                    if pd.notna(dt_venc):
                        dt_venc_obj = pd.to_datetime(dt_venc).date()
                        safra_fpd_mes = dt_venc_obj.replace(day=1)
                        safra_fpd, _ = SafraM10.objects.get_or_create(
                            mes_referencia=safra_fpd_mes,
                            defaults={'total_instalados': 0, 'total_ativos': 0}
                        )
                        # Se o contrato estava em safra M-10, pode estar em safra FPD agora
                        # (Safra FPD é complementar)

                    fatura, created_fatura = FaturaM10.objects.update_or_create(
                        contrato=contrato,
                        numero_fatura=1,
                        defaults={
                            'numero_fatura_operadora': str(row.get('NR_FATURA', '')),
                            'valor': float(row.get('VL_FATURA', 0)) if pd.notna(row.get('VL_FATURA')) else 0,
                            'data_vencimento': pd.to_datetime(dt_venc).date() if pd.notna(dt_venc) else datetime.now().date(),
                            'data_pagamento': pd.to_datetime(dt_pgto).date() if pd.notna(dt_pgto) else None,
                            'dias_atraso': int(row.get('NR_DIAS_ATRASO', 0)) if pd.notna(row.get('NR_DIAS_ATRASO')) else 0,
                            'status': status,
                        }
                    )

                    registros_atualizados += 1

                except ContratoM10.DoesNotExist:
                    registros_nao_encontrados += 1
                    continue

            return Response({
                'message': f'Importação FPD concluída! {registros_atualizados} contratos atualizados, {registros_nao_encontrados} não encontrados.',
                'atualizados': registros_atualizados,
                'nao_encontrados': registros_nao_encontrados,
            })

        except Exception as e:
            return Response({'error': f'Erro ao processar arquivo: {str(e)}'}, status=500)


class ImportarChurnView(APIView):
    """Importa base de churn (cancelamentos) e faz crossover com ContratoM10 por O.S"""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        if not is_member(request.user, ['Admin', 'BackOffice', 'Diretoria']):
            return Response({'error': 'Sem permissão'}, status=403)

        arquivo = request.FILES.get('file')
        if not arquivo:
            return Response({'error': 'Arquivo não enviado'}, status=400)

        try:
            if arquivo.name.endswith('.csv'):
                df = pd.read_csv(arquivo)
            elif arquivo.name.endswith('.xlsb'):
                try:
                    df = pd.read_excel(arquivo, engine='pyxlsb')
                except Exception:
                    return Response({
                        'error': 'Formato .xlsb não suportado. Use .xlsx, .xls ou .csv'
                    }, status=400)
            else:
                df = pd.read_excel(arquivo)

            cancelados = 0
            nao_encontrados = 0

            for _, row in df.iterrows():
                # Busca por O.S (NR_ORDEM na planilha de churn)
                nr_ordem = str(row.get('NR_ORDEM', '')).strip()
                if not nr_ordem:
                    continue

                try:
                    # Tenta encontrar contrato por ordem_servico
                    contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
                    
                    # Marca como cancelado se aplicável
                    status_str = str(row.get('STATUS', '')).upper() if pd.notna(row.get('STATUS')) else ''
                    
                    if 'CANCELADO' in status_str or 'INATIVO' in status_str or 'CHURN' in status_str:
                        contrato.status_contrato = 'CANCELADO'
                        contrato.data_cancelamento = pd.to_datetime(row.get('DATA_CANCELAMENTO')).date() if pd.notna(row.get('DATA_CANCELAMENTO')) else datetime.now().date()
                        contrato.motivo_cancelamento = str(row.get('MOTIVO', '')) or str(row.get('MOTIVO_CANCELAMENTO', ''))
                        contrato.elegivel_bonus = False
                        contrato.save()
                        cancelados += 1
                    
                except ContratoM10.DoesNotExist:
                    nao_encontrados += 1
                    continue

            return Response({
                'message': f'Base churn processada! {cancelados} contratos marcados como cancelados, {nao_encontrados} não encontrados.',
                'cancelados': cancelados,
                'nao_encontrados': nao_encontrados,
            })

        except Exception as e:
            return Response({'error': f'Erro ao processar arquivo: {str(e)}'}, status=500)


class AtualizarFaturasView(APIView):
    """Atualiza múltiplas faturas de uma vez"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not is_member(request.user, ['Admin', 'BackOffice', 'Diretoria']):
            return Response({'error': 'Sem permissão'}, status=403)

        updates = request.data.get('updates', [])
        
        for update in updates:
            fatura_id = update.get('id')
            field = update.get('field')
            value = update.get('value')

            try:
                fatura = FaturaM10.objects.get(id=fatura_id)
                
                if field == 'status':
                    fatura.status = value
                elif field == 'valor':
                    fatura.valor = float(value) if value else 0
                elif field == 'data_vencimento':
                    fatura.data_vencimento = datetime.strptime(value, '%Y-%m-%d').date() if value else None
                elif field == 'data_pagamento':
                    fatura.data_pagamento = datetime.strptime(value, '%Y-%m-%d').date() if value else None
                elif field == 'numero_fatura_operadora':
                    fatura.numero_fatura_operadora = value

                fatura.save()
                
                # Recalcula elegibilidade do contrato
                fatura.contrato.calcular_elegibilidade()

            except FaturaM10.DoesNotExist:
                continue

        return Response({'message': 'Faturas atualizadas com sucesso!'})


class ExportarM10View(APIView):
    """Exporta dados para Excel"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Cria workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Bônus M-10"

        # Cabeçalhos
        headers = ['Contrato', 'Cliente', 'Vendedor', 'Instalação', 'Plano', 'Status', 'Faturas Pagas', 'Elegível', 'Bônus']
        ws.append(headers)

        # Estilo cabeçalho
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            cell.alignment = Alignment(horizontal="center")

        # Dados
        contratos = ContratoM10.objects.all().select_related('vendedor', 'safra')
        for c in contratos:
            faturas_pagas = c.faturas.filter(status='PAGO').count()
            bonus = 150 if c.elegivel_bonus else 0
            ws.append([
                c.numero_contrato,
                c.cliente_nome,
                c.vendedor.get_full_name() if c.vendedor else '-',
                c.data_instalacao.strftime('%d/%m/%Y'),
                c.plano_atual,
                c.get_status_contrato_display(),
                f"{faturas_pagas}/10",
                'Sim' if c.elegivel_bonus else 'Não',
                f"R$ {bonus:.2f}",
            ])

        # Ajusta largura das colunas
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = (max_length + 2)
            ws.column_dimensions[column_letter].width = adjusted_width

        # Retorna arquivo
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=bonus_m10_{datetime.now().strftime("%Y%m%d")}.xlsx'
        wb.save(response)
        return response