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

# --- CORREÇÃO CRÍTICA: Importar transaction e IntegrityError ---
from django.db import transaction, IntegrityError

from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.decorators import api_view, permission_classes, action

# --- IMPORTS EXTRAS DO PROJETO ---
from core.models import DiaFiscal
from .whatsapp_service import WhatsAppService
from xhtml2pdf import pisa
from usuarios.permissions import CheckAPIPermission, VendaPermission
import openpyxl 
from openpyxl.styles import Font, PatternFill


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
    SessaoWhatsapp, DFV
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
                
                if status_obj.nome.upper() == 'CADASTRADA' and not venda.status_esteira:
                    st_agendado = StatusCRM.objects.filter(nome__iexact='AGENDADO', tipo='Esteira').first()
                    if st_agendado: venda.status_esteira = st_agendado

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

        # Pega todos os dados (sem paginação)
        vendas = self.filter_queryset(self.get_queryset())
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Base de Vendas"

        headers = ['ID', 'Data Venda', 'Vendedor', 'Supervisor', 'Cliente', 'CPF/CNPJ', 'Plano', 'Status Esteira', 'Data Instalação', 'Status Pagamento', 'OS', 'Motivo Pendência']
        ws.append(headers)
        
        # Estilo Cabeçalho
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")

        for v in vendas:
            sup_nome = v.vendedor.supervisor.username if v.vendedor and v.vendedor.supervisor else '-'
            ws.append([
                v.id,
                v.data_criacao.strftime('%d/%m/%Y') if v.data_criacao else '-',
                v.vendedor.username if v.vendedor else '-',
                sup_nome,
                v.cliente.nome_razao_social if v.cliente else '-',
                v.cliente.cpf_cnpj if v.cliente else '-',
                v.plano.nome if v.plano else '-',
                v.status_esteira.nome if v.status_esteira else '-',
                v.data_instalacao.strftime('%d/%m/%Y') if v.data_instalacao else '-',
                v.status_comissionamento.nome if v.status_comissionamento else '-',
                v.ordem_servico or '-',
                v.motivo_pendencia.nome if v.motivo_pendencia else '-'
            ])

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=base_vendas_{datetime.now().strftime("%Y%m%d")}.xlsx'
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
            
            stats_planos = defaultdict(lambda: {'qtd': 0, 'total': 0.0})
            stats_descontos = defaultdict(float)
            
            for v in vendas:
                doc = v.cliente.cpf_cnpj if v.cliente else ''
                doc_limpo = ''.join(filter(str.isdigit, doc))
                tipo_cliente = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
                canal_vendedor = getattr(consultor, 'canal', 'PAP') or 'PAP'
                
                regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor_id == consultor.id), None)
                if not regra:
                    regra = next((r for r in todas_regras if r.plano_id == v.plano_id and r.tipo_cliente == tipo_cliente and r.tipo_venda == canal_vendedor and r.consultor is None), None)
                
                valor_item = float(regra.valor_acelerado if bateu_meta else regra.valor_base) if regra else 0.0
                comissao_bruta += valor_item

                key_plano = (v.plano.nome, valor_item)
                stats_planos[key_plano]['qtd'] += 1
                stats_planos[key_plano]['total'] += valor_item

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

            total_descontos = sum(stats_descontos.values())
            premiacao = 0.0 
            bonus = 0.0
            valor_liquido = (comissao_bruta + premiacao + bonus) - total_descontos

            lista_planos_detalhe = []
            for (nome_plano, unitario), dados in stats_planos.items():
                lista_planos_detalhe.append({
                    'plano': nome_plano,
                    'unitario': unitario,
                    'qtd': dados['qtd'],
                    'total': dados['total']
                })
            lista_planos_detalhe.sort(key=lambda x: x['total'], reverse=True)

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

    def _normalize_text(self, text):
        if not text: return ""
        text = str(text).upper().strip()
        import unicodedata
        return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Nenhum arquivo enviado.'}, status=400)
        
        # --- FUNÇÃO DATA SEGURA ---
        def safe_date_convert(val):
            try:
                if pd.isna(val) or val == "" or val is None: return None
                if isinstance(val, (datetime, date, pd.Timestamp)):
                    return val.date() if isinstance(val, (datetime, pd.Timestamp)) else val
                if isinstance(val, (float, int)):
                    if val < 100: return None 
                    return (datetime(1899, 12, 30) + timedelta(days=float(val))).date()
                if isinstance(val, str):
                    val = val.strip()
                    return pd.to_datetime(val, dayfirst=True, errors='coerce').date()
            except: return None
            return None

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

        # Status básicos (Esteira)
        STATUS_MAP = {
            'CONCLUÍDO': 'INSTALADA', 'CONCLUIDO': 'INSTALADA', 'EXECUTADO': 'INSTALADA',
            'PENDÊNCIA CLIENTE': 'PENDENCIADA', 'PENDENCIA CLIENTE': 'PENDENCIADA',
            'PENDÊNCIA TÉCNICA': 'PENDENCIADA', 'PENDENCIA TECNICA': 'PENDENCIADA',
            'CANCELADO': 'CANCELADA', 'EM CANCELAMENTO': 'CANCELADA',
            'AGENDADO': 'AGENDADO', 'DRAFT': 'DRAFT', 
            'AGUARDANDO PAGAMENTO': 'AGUARDANDO PAGAMENTO'
        }

        try:
            df = None
            if file_obj.name.endswith('.xlsb'): df = pd.read_excel(file_obj, engine='pyxlsb')
            elif file_obj.name.endswith(('.xlsx', '.xls')): df = pd.read_excel(file_obj)
            else: return Response({'error': 'Formato inválido.'}, status=400)
        except Exception as e: return Response({'error': f'Erro leitura arquivo: {str(e)}'}, status=400)
        
        df.columns = [str(col).strip().upper() for col in df.columns]
        df = df.replace({np.nan: None, pd.NaT: None})

        # --- CACHES (Agora carregamos Esteira E Tratamento) ---
        status_esteira_map = {s.nome.upper(): s for s in StatusCRM.objects.filter(tipo='Esteira')}
        status_tratamento_map = {s.nome.upper(): s for s in StatusCRM.objects.filter(tipo='Tratamento')} # <--- NOVO
        
        mapa_pagamentos = {}
        for fp in FormaPagamento.objects.filter(ativo=True):
            mapa_pagamentos[self._normalize_text(fp.nome)] = fp
        
        motivo_pendencia_map = {}
        import re
        for m in MotivoPendencia.objects.all():
            match = re.match(r'^(\d+)', m.nome.strip())
            if match:
                codigo_full = match.group(1)
                motivo_pendencia_map[codigo_full] = m
        
        motivo_padrao_osab, _ = MotivoPendencia.objects.get_or_create(nome="VALIDAR OSAB", defaults={'tipo_pendencia': 'Operacional'})
        motivo_sem_agenda, _ = MotivoPendencia.objects.get_or_create(nome="APROVISIONAMENTO S/ DATA", defaults={'tipo_pendencia': 'Sistêmica'})

        vendas_com_os = Venda.objects.filter(ativo=True).exclude(ordem_servico__isnull=True).exclude(ordem_servico='')
        vendas_map = {self._clean_key(v.ordem_servico): v for v in vendas_com_os}
        osab_bot = get_osab_bot_user()

        report = {
            "status": "sucesso", "total_registros": len(df), "criados": 0, "atualizados": 0, 
            "vendas_encontradas": 0, "ja_corretos": 0, "erros": [], "logs_detalhados": [], "arquivo_excel_b64": None
        }
        
        vendas_para_atualizar_db = []
        historicos_para_criar = []

        for index, row in df.iterrows():
            log_item = {"linha": index + 2, "pedido": str(row.get('PEDIDO')), "status_osab": str(row.get('SITUACAO')), "resultado": "", "detalhe": ""}
            try:
                # Salvar Bruto
                colunas_validas = {k: v for k, v in coluna_map.items() if k in df.columns}
                dados_model = {}
                for col_planilha, campo_model in colunas_validas.items():
                    val = row.get(col_planilha)
                    if col_planilha == 'PEDIDO': val = self._clean_key(val)
                    if campo_model in ['dt_ref', 'data_abertura', 'data_fechamento', 'data_agendamento']: val = safe_date_convert(val)
                    dados_model[campo_model] = val
                
                doc_chave = dados_model.get('documento')
                if doc_chave: ImportacaoOsab.objects.update_or_create(documento=doc_chave, defaults=dados_model)

                # Processar Venda
                if not doc_chave: 
                    log_item["resultado"] = "IGNORADO"; log_item["detalhe"] = "Sem pedido"; report["logs_detalhados"].append(log_item); continue

                venda = vendas_map.get(doc_chave)
                if not venda:
                    log_item["resultado"] = "NAO_ENCONTRADO"; log_item["detalhe"] = "OS não existe no CRM"; report["logs_detalhados"].append(log_item); continue
                
                report["vendas_encontradas"] += 1
                sit_osab_raw = str(row.get('SITUACAO', '')).strip().upper()
                if sit_osab_raw == "NONE" or sit_osab_raw == "NAN": sit_osab_raw = ""

                # --- VARIÁVEIS DE CONTROLE ---
                target_status_esteira = None
                target_status_tratamento = None # <--- Para lidar com Reprovado
                target_data_agenda = None
                target_motivo_pendencia = None
                
                houve_alteracao = False
                detalhes_hist = {}
                motivos_ignorados = []

                # --- 1. LÓGICA DE DECISÃO ---
                
                # CASO: Vazio ou Fraude (Regra do Cartão - TRATAMENTO)
                is_fraude = "PAYMENT_NOT_AUTHORIZED" in sit_osab_raw
                if not sit_osab_raw or is_fraude:
                    pgto_raw = self._normalize_text(row.get('MEIO_PAGAMENTO'))
                    if "CARTAO" in pgto_raw:
                        # Busca no mapa de TRATAMENTO, não Esteira
                        st_reprovado = status_tratamento_map.get("REPROVADO CARTÃO DE CRÉDITO")
                        if st_reprovado:
                            target_status_tratamento = st_reprovado
                        else:
                            motivos_ignorados.append("Status 'REPROVADO CARTÃO DE CRÉDITO' não achado em Tratamento")
                    else:
                        pass # Mantém o que está

                # CASO: Em Aprovisionamento (Esteira)
                elif sit_osab_raw == "EM APROVISIONAMENTO":
                    dt_ag_raw = row.get('DATA_AGENDAMENTO')
                    dt_ag = safe_date_convert(dt_ag_raw)
                    if dt_ag and dt_ag.year >= 2000:
                        target_status_esteira = status_esteira_map.get("AGENDADO")
                        target_data_agenda = dt_ag
                    else:
                        target_status_esteira = status_esteira_map.get("PENDENCIADA")
                        target_motivo_pendencia = motivo_sem_agenda

                # DEMAIS CASOS (Esteira Padrão)
                else:
                    nome_est = STATUS_MAP.get(sit_osab_raw)
                    if not nome_est:
                        if sit_osab_raw.startswith("DRAFT"): nome_est = "DRAFT"
                        elif "AGUARDANDO PAGAMENTO" in sit_osab_raw: nome_est = "AGUARDANDO PAGAMENTO"
                        elif "REPROVADO" in sit_osab_raw: 
                            # Se for reprovado e não caiu na regra acima, talvez seja esteira
                             nome_est = "REPROVADO CARTÃO DE CRÉDITO"
                    
                    if nome_est:
                         # Tenta achar na Esteira
                         target_status_esteira = status_esteira_map.get(nome_est)

                # --- APLICAÇÃO ---

                # A. Atualizar Tratamento (Prioridade para Regra do Cartão)
                if target_status_tratamento:
                    if venda.status_tratamento != target_status_tratamento:
                        detalhes_hist['status_tratamento'] = f"De '{venda.status_tratamento}' para '{target_status_tratamento.nome}'"
                        venda.status_tratamento = target_status_tratamento
                        houve_alteracao = True
                    else:
                        motivos_ignorados.append(f"Tratamento já é {target_status_tratamento.nome}")

                # B. Atualizar Esteira (Se definido)
                if target_status_esteira:
                    if venda.status_esteira != target_status_esteira:
                        detalhes_hist['status_esteira'] = f"De '{venda.status_esteira}' para '{target_status_esteira.nome}'"
                        venda.status_esteira = target_status_esteira
                        houve_alteracao = True
                        if 'PENDEN' not in target_status_esteira.nome.upper(): venda.motivo_pendencia = None
                    else:
                        motivos_ignorados.append(f"Esteira já é {target_status_esteira.nome}")

                    # Regras adicionais de Esteira
                    nome_est_upper = target_status_esteira.nome.upper()

                    # C. Datas
                    if 'INSTALADA' in nome_est_upper:
                        raw_dt = row.get('DATA_FECHAMENTO')
                        nova_dt = safe_date_convert(raw_dt)
                        if nova_dt and nova_dt.year >= 2000:
                            db_valido = (venda.data_instalacao and venda.data_instalacao.year >= 2000)
                            if not db_valido or venda.data_instalacao != nova_dt:
                                detalhes_hist['data_instalacao'] = f"De '{venda.data_instalacao}' para '{nova_dt}'"
                                venda.data_instalacao = nova_dt
                                houve_alteracao = True
                        else:
                             motivos_ignorados.append(f"Sem Data Fechamento válida")

                    elif 'AGENDADO' in nome_est_upper:
                        nova_dt_ag = target_data_agenda
                        if not nova_dt_ag: nova_dt_ag = safe_date_convert(row.get('DATA_AGENDAMENTO'))
                        
                        if nova_dt_ag and nova_dt_ag.year >= 2000:
                            db_ag_valido = (venda.data_agendamento and venda.data_agendamento.year >= 2000)
                            if not db_ag_valido or venda.data_agendamento != nova_dt_ag:
                                detalhes_hist['data_agendamento'] = f"De '{venda.data_agendamento}' para '{nova_dt_ag}'"
                                venda.data_agendamento = nova_dt_ag
                                houve_alteracao = True

                    # D. Pendência
                    elif 'PENDEN' in nome_est_upper:
                        novo_motivo = target_motivo_pendencia
                        if not novo_motivo:
                            cod_full = str(row.get('COD_PENDENCIA', '')).replace('.0', '').strip()
                            novo_motivo = motivo_pendencia_map.get(cod_full)
                            if not novo_motivo and len(cod_full) >= 2:
                                 novo_motivo = motivo_pendencia_map.get(cod_full[:2])
                            if not novo_motivo: novo_motivo = motivo_padrao_osab
                        
                        if venda.motivo_pendencia_id != novo_motivo.id:
                            detalhes_hist['motivo_pendencia'] = f"Atualizado para '{novo_motivo.nome}'"
                            venda.motivo_pendencia = novo_motivo
                            houve_alteracao = True

                # E. Pagamento (Sempre verifica, independente do status)
                pgto_osab_raw = row.get('MEIO_PAGAMENTO')
                if pgto_osab_raw:
                    pgto_norm = self._normalize_text(pgto_osab_raw)
                    novo_fp = None
                    if pgto_norm in mapa_pagamentos: novo_fp = mapa_pagamentos[pgto_norm]
                    else:
                        for k, v in mapa_pagamentos.items():
                            if pgto_norm in k or k in pgto_norm: novo_fp = v; break
                    
                    if novo_fp and (not venda.forma_pagamento or venda.forma_pagamento.id != novo_fp.id):
                        old_fp = venda.forma_pagamento.nome if venda.forma_pagamento else "N/A"
                        detalhes_hist['forma_pagamento'] = f"De '{old_fp}' para '{novo_fp.nome}'"
                        venda.forma_pagamento = novo_fp
                        houve_alteracao = True

                # Commit
                if houve_alteracao:
                    log_item["resultado"] = "ATUALIZAR"; log_item["detalhe"] = " | ".join([f"{k}: {v}" for k,v in detalhes_hist.items()])
                    vendas_para_atualizar_db.append(venda)
                    historicos_para_criar.append(HistoricoAlteracaoVenda(venda=venda, usuario=osab_bot, alteracoes=detalhes_hist))
                else:
                    if not target_status_esteira and not target_status_tratamento:
                         log_item["resultado"] = "SEM_MUDANCA"; log_item["detalhe"] = f"Status '{sit_osab_raw}' não gerou ação."
                    else:
                        log_item["resultado"] = "JA_CORRETO"; log_item["detalhe"] = " | ".join(motivos_ignorados)
                    report["ja_corretos"] += 1
                report["logs_detalhados"].append(log_item)

            except Exception as ex:
                log_item["resultado"] = "ERRO_CRITICO"; log_item["detalhe"] = str(ex)
                report["logs_detalhados"].append(log_item); report['erros'].append(f"Linha {index}: {ex}")

        if vendas_para_atualizar_db:
            report["atualizados"] = len(vendas_para_atualizar_db)
            campos = ['status_esteira', 'status_tratamento', 'data_instalacao', 'data_agendamento', 'forma_pagamento', 'motivo_pendencia']
            Venda.objects.bulk_update(vendas_para_atualizar_db, campos)
            if historicos_para_criar: HistoricoAlteracaoVenda.objects.bulk_create(historicos_para_criar)

        # Gerar Excel
        try:
            if report["logs_detalhados"]:
                df_logs = pd.DataFrame(report["logs_detalhados"])
                output = BytesIO()
                df_logs.to_excel(output, index=False, sheet_name='Log')
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
            if isinstance(data, list): data = data[0] if len(data) > 0 else {}
            if not isinstance(data, dict): return Response({'status': 'ignored'})

            phone = data.get('phone') or data.get('sender')
            if not phone: return Response({'status': 'ignored'})

            # Extrair texto
            text = ""
            if 'text' in data and isinstance(data['text'], dict):
                text = data['text'].get('message', '').strip()
            elif 'text' in data and isinstance(data['text'], str):
                text = data['text'].strip()

            service = WhatsAppService()

            # 1. VERIFICAÇÃO POR LOCALIZAÇÃO (MAPA - CLIPE)
            # Se mandar localização, ignora o fluxo de texto e responde na hora
            if 'location' in data or data.get('type') == 'location':
                loc_data = data.get('location') or data
                if loc_data and 'latitude' in loc_data:
                    lat = float(loc_data['latitude'])
                    lng = float(loc_data['longitude'])
                    res = verificar_viabilidade_por_coordenadas(lat, lng)
                    service.enviar_mensagem_texto(phone, res['msg'])
                    # Limpa sessão se existir
                    try: SessaoWhatsapp.objects.filter(telefone=phone).delete()
                    except: pass
                    return Response({'status': 'loc_processed'})

            # 2. FLUXO DE CONVERSA (TEXTO)
            # Recupera ou cria sessão com proteção contra Race Condition
            try:
                sessao, created = SessaoWhatsapp.objects.get_or_create(
                    telefone=phone, 
                    defaults={'etapa': 'MENU'}
                )
            except IntegrityError:
                # Se der erro de duplicidade (concorrencia), recupera a que foi criada no milissegundo anterior
                sessao = SessaoWhatsapp.objects.get(telefone=phone)

            msg_upper = text.upper()

            # GATILHO INICIAL: "VIABILIDADE"
            if msg_upper == "VIABILIDADE":
                sessao.etapa = 'AGUARDANDO_CEP'
                sessao.dados_temp = {} # Limpa dados anteriores
                sessao.save()
                service.enviar_mensagem_texto(phone, "Olá! 🌍\nPor favor, digite o *CEP* do local (apenas números):")
                return Response({'status': 'step_1_cep'})

            # ETAPA 1: RECEBEU O CEP -> PEDE NÚMERO
            elif sessao.etapa == 'AGUARDANDO_CEP':
                # Validação básica de CEP
                cep_limpo = "".join(filter(str.isdigit, text))
                if len(cep_limpo) == 8:
                    sessao.dados_temp = {'cep': cep_limpo}
                    sessao.etapa = 'AGUARDANDO_NUMERO'
                    sessao.save()
                    service.enviar_mensagem_texto(phone, "Certo! Agora digite o *NÚMERO* da fachada (ou 'SN' se não tiver):")
                else:
                    service.enviar_mensagem_texto(phone, "⚠️ CEP inválido. Por favor, digite um CEP com 8 dígitos:")
                return Response({'status': 'step_2_num'})

            # ETAPA 2: RECEBEU O NÚMERO -> PROCESSA TUDO
            elif sessao.etapa == 'AGUARDANDO_NUMERO':
                cep = sessao.dados_temp.get('cep')
                numero = text
                
                service.enviar_mensagem_texto(phone, "🔎 Buscando no mapa, aguarde um instante...")
                
                # Chama a nova função exata
                resultado = verificar_viabilidade_exata(cep, numero)
                
                service.enviar_mensagem_texto(phone, resultado['msg'])
                
                # Reseta o robô
                sessao.delete()
                return Response({'status': 'finished'})

            return Response({'status': 'no_action'})

        except Exception as e:
            # logger.error(f"Webhook Error: {e}", exc_info=True)
            return Response({'status': 'error'}, status=500)

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_verificar_whatsapp(request, telefone):
    """
    Verifica se um número possui WhatsApp válido usando a API externa (Z-API).
    """
    try:
        svc = WhatsAppService()
        # Chama a API de verdade
        existe = svc.verificar_numero_existe(telefone)
        
        # Retorna com múltiplas chaves para garantir compatibilidade com qualquer versão do seu HTML
        return Response({
            "telefone": telefone,
            "whatsapp_valido": existe,  # Usado em algumas versões
            "possui_whatsapp": existe,  # Usado no seu crm_vendas.html atual
            "exists": existe            # Padrão Z-API
        })
    except Exception as e:
        # Se der erro interno, não trava a venda (retorna erro 500 mas o log registra)
        logger.error(f"Erro view verificar zap: {e}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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