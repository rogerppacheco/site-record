from django.shortcuts import render
from rest_framework.decorators import api_view, permission_classes
from rest_framework import permissions
from rest_framework.response import Response

# Endpoint de teste (e-mail)
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_verificar_email(request, email=None):
    return Response({"status": "ok", "email": email})

# Endpoint de validação WhatsApp
@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def api_verificar_whatsapp(request, telefone=None):
    """
    Valida se um número possui WhatsApp ativo via Z-API.
    Aceita telefone como parâmetro de URL ou query string.
    """
    # Pega telefone da URL ou query string
    if not telefone:
        telefone = request.GET.get('numero') or request.GET.get('telefone')
    
    if not telefone:
        return Response({
            "exists": False,
            "whatsapp_valido": False,
            "possui_whatsapp": False,
            "erro": "Número não informado"
        }, status=400)
    
    # Limpa o telefone (remove caracteres não numéricos)
    import re
    telefone_limpo = re.sub(r'\D', '', str(telefone))
    
    if len(telefone_limpo) < 10:
        return Response({
            "exists": False,
            "whatsapp_valido": False,
            "possui_whatsapp": False,
            "erro": "Número inválido (mínimo 10 dígitos)"
        }, status=400)
    
    try:
        from crm_app.whatsapp_service import WhatsAppService
        
        service = WhatsAppService()
        
        # Verifica se a API está configurada
        if not service.instance_id or not service.token:
            return Response({
                "exists": True,  # Retorna True para não bloquear o cadastro
                "whatsapp_valido": True,
                "possui_whatsapp": True,
                "aviso": "API WhatsApp não configurada. Validação ignorada."
            }, status=200)
        
        # Formata telefone para a API (adiciona 55 se necessário)
        if len(telefone_limpo) <= 11:
            telefone_api = f"55{telefone_limpo}"
        else:
            telefone_api = telefone_limpo
        
        # Verifica se o número existe no WhatsApp
        try:
            existe = service.verificar_numero_existe(telefone_api)
            
            # Se a API retornou None (erro), trata como se não existisse mas permite salvar
            if existe is None:
                return Response({
                    "exists": True,  # Permite salvar mesmo se não conseguir verificar
                    "whatsapp_valido": True,
                    "possui_whatsapp": True,
                    "aviso": "Não foi possível verificar WhatsApp (API offline). Você pode salvar mesmo assim."
                }, status=200)
            
            return Response({
                "exists": existe,
                "whatsapp_valido": existe,
                "possui_whatsapp": existe,
                "telefone": telefone_limpo
            }, status=200)
        except Exception as e_inner:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception(f"Erro ao chamar verificar_numero_existe: {e_inner}")
            # Em caso de erro na verificação, permite salvar mas avisa
            return Response({
                "exists": True,
                "whatsapp_valido": True,
                "possui_whatsapp": True,
                "aviso": f"Erro ao verificar: {str(e_inner)}. Você pode salvar mesmo assim."
            }, status=200)
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception(f"Erro ao verificar WhatsApp: {e}")
        
        # Retorna True com aviso para não bloquear o cadastro em caso de erro
        return Response({
            "exists": True,
            "whatsapp_valido": True,
            "possui_whatsapp": True,
            "aviso": f"Erro ao verificar WhatsApp: {str(e)}. Validação ignorada."
        }, status=200)
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework import status

# --- RESTAURAÇÃO: WebhookWhatsAppView ---
# URL de produção: https://www.recordpap.com.br/api/crm/webhook-whatsapp/
# URL alternativa: https://site-record-production.up.railway.app/api/crm/webhook-whatsapp/
# Configurar no Z-API: Método POST, Eventos: Mensagens recebidas
class WebhookWhatsAppView(APIView):
    permission_classes = [AllowAny]  # Permite acesso sem autenticação para webhooks

    def post(self, request, *args, **kwargs):
        """
        Endpoint para receber eventos do WhatsApp e processar fluxos:
        - Fachada: Consulta fachadas por CEP (DFV)
        - Viabilidade: Consulta viabilidade por CEP e número (KMZ)
        - Fatura: Consulta fatura por CPF (Nio API)
        - Status: Consulta status de venda por CPF ou OS
        """
        import logging
        logger_webhook = logging.getLogger(__name__)
        
        from crm_app.whatsapp_webhook_handler import processar_webhook_whatsapp
        
        data = request.data
        logger_webhook.info(f"[WebhookWhatsAppView] Recebido POST com dados: {data}")
        
        try:
            resultado = processar_webhook_whatsapp(data)
            logger_webhook.info(f"[WebhookWhatsAppView] Resultado do processamento: {resultado}")
            return Response(resultado, status=200 if resultado.get('status') == 'ok' else 500)
        except Exception as e:
            import logging
            logger_webhook = logging.getLogger(__name__)
            logger_webhook.exception(f"[WebhookWhatsAppView] Erro: {e}")
            return Response({'status': 'erro', 'mensagem': str(e)}, status=500)
# Endpoint para duplicar venda (Reemissão)
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Venda

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def duplicar_venda(request):
    """
    Duplica uma venda (reemissão).
    Cria uma NOVA venda com TODOS os dados iguais (incluindo data_criacao), exceto:
    - data_abertura (OS): atual (timezone.now())
    - ordem_servico: nova OS informada
    - data_agendamento: nova data informada
    - periodo_agendamento: novo turno informado
    - status_esteira: AGENDADO
    - reemissao: True
    - observacoes: copiada da venda original (não muda)
    """
    id_venda = request.data.get('id_venda')
    nova_os = request.data.get('nova_os') or request.data.get('ordem_servico')
    nova_data = request.data.get('nova_data_agendamento') or request.data.get('data_agendamento')
    novo_turno = request.data.get('novo_turno') or request.data.get('periodo_agendamento')
    # observacoes não é usado - copia da venda original
    
    if not (id_venda and nova_os and nova_data and novo_turno):
        return Response({'detail': 'Dados obrigatórios faltando: id_venda, ordem_servico, data_agendamento, periodo_agendamento.'}, status=400)
    
    try:
        from django.utils import timezone
        from crm_app.whatsapp_service import WhatsAppService
        from .models import StatusCRM
        
        venda_original = Venda.objects.get(id=id_venda)
        
        # Duplicar venda (criar nova)
        # Método correto: copiar a instância usando pk=None diretamente da instância
        venda_nova = Venda()
        
        # Copiar TODOS os campos da venda original (incluindo data_criacao)
        # ForeignKeys e relacionamentos são copiados como objetos (não IDs)
        data_criacao_original = venda_original.data_criacao  # Preservar data_criacao
        
        for field in venda_original._meta.get_fields():
            if field.auto_created or field.name in ['id', 'pk']:
                continue
            if hasattr(venda_original, field.name):
                value = getattr(venda_original, field.name)
                setattr(venda_nova, field.name, value)
        
        # APENAS estes campos mudam (vêm do formulário):
        venda_nova.ordem_servico = nova_os
        venda_nova.data_abertura = timezone.now()  # Data de abertura da OS = agora
        venda_nova.data_agendamento = nova_data
        venda_nova.periodo_agendamento = novo_turno
        # observacoes: copiada da venda original (não usar nova_observacao)
        
        # Marcar como reemissão
        venda_nova.reemissao = True
        
        # Status esteira = AGENDADO
        try:
            status_agendado = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
            venda_nova.status_esteira = status_agendado
        except StatusCRM.DoesNotExist:
            return Response({'detail': 'Status AGENDADO (Esteira) não encontrado.'}, status=400)
        
        # Salvar nova venda primeiro (para gerar o ID)
        venda_nova.save()
        
        # Preservar data_criacao da venda original (usar update para evitar auto_now_add)
        if data_criacao_original:
            Venda.objects.filter(id=venda_nova.id).update(data_criacao=data_criacao_original)
            venda_nova.data_criacao = data_criacao_original  # Atualizar em memória também

        # Enviar WhatsApp para o vendedor
        if venda_nova.vendedor and venda_nova.telefone1:
            try:
                ws = WhatsAppService()
                ws.enviar_mensagem_cadastrada(venda_nova)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Erro ao enviar WhatsApp para reemissão: {e}")

        return Response({'success': True, 'nova_venda_id': venda_nova.id, 'message': 'Reemissão criada com sucesso!'})
    except Venda.DoesNotExist:
        return Response({'detail': 'Venda não encontrada.'}, status=404)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception(f"Erro ao duplicar venda: {e}")
        return Response({'detail': str(e)}, status=500)
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
# --- NOVO ENDPOINT: Buscar Fatura NIO para Bonus M-10 ---
@api_view(["POST"])
@permission_classes([AllowAny])
def buscar_fatura_nio_bonus_m10(request):
    cpf = request.data.get("cpf")
    if not cpf:
        return Response({"error": "CPF não informado."}, status=400)
    try:
        from crm_app.services_nio import buscar_fatura_nio_por_cpf
        resultado = buscar_fatura_nio_por_cpf(cpf, incluir_pdf=True)
        if resultado and resultado.get('valor'):
            return Response({
                "success": True,
                "valor": resultado.get('valor'),
                "codigo_pix": resultado.get('codigo_pix'),
                "codigo_barras": resultado.get('codigo_barras'),
                "data_vencimento": resultado.get('data_vencimento'),
                "pdf_url": resultado.get('pdf_url'),
                "pdf_salvo": resultado.get('pdf_salvo')
            })
        else:
            return Response({"success": False, "message": "Não foi possível buscar a fatura. Verifique o CPF ou tente novamente."}, status=404)
    except Exception as e:
        return Response({"success": False, "message": str(e)}, status=500)
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
from email_validator import validate_email, EmailNotValidError


# --- CORREÇÃO CRÍTICA: Importar transaction e IntegrityError ---
from django.db import transaction, IntegrityError
from django.db.models import Count, Q, Sum, F
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

# Importar mapeamento de status FPD
from .fpd_status_mapping import normalizar_status_fpd

from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.decorators import api_view, permission_classes, action
from openpyxl.utils import get_column_letter


# --- IMPORTS EXTRAS DO PROJETO ---
from core.models import DiaFiscal, RegraAutomacao
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
from .nio_api import consultar_dividas_nio


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
    AgendamentoDisparo, ImportacaoAgendamento, ImportacaoRecompra,
    LogImportacaoAgendamento
)

# Serializers do App
from .serializers import (
    OperadoraSerializer, PlanoSerializer, FormaPagamentoSerializer,
    StatusCRMSerializer, MotivoPendenciaSerializer, RegraComissaoSerializer,
    VendaSerializer, VendaCreateSerializer, ClienteSerializer,
    VendaUpdateSerializer, ImportacaoOsabSerializer, ImportacaoChurnSerializer,
    CicloPagamentoSerializer, VendaDetailSerializer,
    CampanhaSerializer, ComissaoOperadoraSerializer, ComunicadoSerializer,
    FaturaM10Serializer
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
            'motivo_pendencia', 'auditor_atual', 'editado_por'
        )
        
        # ✅ OTIMIZAÇÃO: Carrega histórico APENAS quando recuperando detalhes (retrieve)
        if self.action == 'retrieve':
            queryset = queryset.prefetch_related('historico_alteracoes__usuario')
        
        queryset = queryset.order_by('-data_criacao')
        
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
        print("[CRM DEBUG] Dados recebidos no POST /crm/vendas/:", dict(request.data))
        # Validar CPF/CNPJ antes de processar
        if 'cliente_cpf_cnpj' in request.data:
            try:
                validar_cpf_ou_cnpj(request.data['cliente_cpf_cnpj'])
            except ValidationError as e:
                print("[CRM DEBUG] Erro de validação CPF/CNPJ:", e)
                return Response({"cliente_cpf_cnpj": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
        # Validar CPF do Representante Legal se fornecido
        if 'cpf_representante_legal' in request.data and request.data['cpf_representante_legal']:
            try:
                validar_cpf(request.data['cpf_representante_legal'])
            except ValidationError as e:
                print("[CRM DEBUG] Erro de validação CPF Rep. Legal:", e)
                return Response({"cpf_representante_legal": [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print("[CRM DEBUG] Erros de validação do serializer:", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        print("[CRM DEBUG] Venda criada com sucesso! Dados:", serializer.data)
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
        qs = qs.exclude(status_tratamento__estado__iexact='FECHADO').order_by('-id')
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
        
        # Capturar valores antes da atualização para detectar mudanças nos dados
        data_agendamento_antes = venda_antes.data_agendamento
        periodo_agendamento_antes = venda_antes.periodo_agendamento
        data_instalacao_antes = venda_antes.data_instalacao
        motivo_pendencia_antes = venda_antes.motivo_pendencia
        
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
        # Verifica se status mudou OU se dados importantes foram alterados
        status_mudou = venda_atualizada.status_esteira and venda_atualizada.status_esteira != status_esteira_antes
        dados_mudaram = (
            (data_agendamento_antes != venda_atualizada.data_agendamento) or
            (periodo_agendamento_antes != venda_atualizada.periodo_agendamento) or
            (data_instalacao_antes != venda_atualizada.data_instalacao) or
            (motivo_pendencia_antes != venda_atualizada.motivo_pendencia)
        )

        enviar_whatsapp = self.request.data.get('enviar_whatsapp', True)
        if isinstance(enviar_whatsapp, str):
            enviar_whatsapp = enviar_whatsapp.lower() not in ['false', '0', 'no', 'nao', 'off']
        
        if enviar_whatsapp and venda_atualizada.status_esteira and (status_mudou or dados_mudaram):
            novo_status_nome = venda_atualizada.status_esteira.nome.upper()
            
            if ('PENDEN' in novo_status_nome or 'AGENDADO' in novo_status_nome or 'INSTALADA' in novo_status_nome) and 'CANCEL' not in novo_status_nome:
                
                if venda_atualizada.vendedor and venda_atualizada.vendedor.tel_whatsapp:
                    try:
                        svc = WhatsAppService()
                        msg = ""
                        
                        # Determina se é alteração de dados ou mudança de status
                        prefixo = "🔄 *ATUALIZAÇÃO - " if (dados_mudaram and not status_mudou) else ""
                        
                        cliente_nome = venda_atualizada.cliente.nome_razao_social
                        os_num = venda_atualizada.ordem_servico or "Não informada"
                        status_label = venda_atualizada.status_esteira.nome
                        obs = venda_atualizada.observacoes or "Sem observações"

                        if 'PENDEN' in novo_status_nome:
                            motivo = venda_atualizada.motivo_pendencia.nome if venda_atualizada.motivo_pendencia else "Não informado"
                            titulo = f"{prefixo}VENDA PENDENCIADA*" if prefixo else "⚠️ *VENDA PENDENCIADA*"
                            msg = (
                                f"{titulo}\n\n"
                                f"*Nome do cliente:* {cliente_nome}\n"
                                f"*O.S:* {os_num}\n"
                                f"*Status:* {status_label}\n"
                                f"*Motivo pendência:* {motivo}\n"
                                f"*Observação:* {obs}"
                            )

                        elif 'AGENDADO' in novo_status_nome:
                            data_ag = venda_atualizada.data_agendamento.strftime('%d/%m/%Y') if venda_atualizada.data_agendamento else "Não informada"
                            turno = venda_atualizada.get_periodo_agendamento_display() if venda_atualizada.periodo_agendamento else "Não informado"
                            titulo = f"{prefixo}VENDA AGENDADA*" if prefixo else "📅 *VENDA AGENDADA*"
                            msg = (
                                f"{titulo}\n\n"
                                f"*Nome do cliente:* {cliente_nome}\n"
                                f"*O.S:* {os_num}\n"
                                f"*Status:* {status_label}\n"
                                f"*Data e turno agendado:* {data_ag} - {turno}\n"
                                f"*Observação:* {obs}\n\n"
                                f"Lembrete: Peça ao seu cliente que salve o número 21 4040-1810, o técnico toda vez que coloca uma pendência o CO Digital faz uma ligação automática ao cliente para confirmar. Salvando o número ele atende e evita pendências indevidas!"
                            )

                        elif 'INSTALADA' in novo_status_nome:
                            data_inst = venda_atualizada.data_instalacao.strftime('%d/%m/%Y') if venda_atualizada.data_instalacao else date.today().strftime('%d/%m/%Y')
                            titulo = f"{prefixo}VENDA INSTALADA*" if prefixo else "✅ *VENDA INSTALADA*"
                            msg = (
                                f"{titulo}\n\n"
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
        import time
        import pandas as pd
        from django.http import HttpResponse
        from io import BytesIO
        start_time = time.time()
        print(f"[EXPORTAR_EXCEL] Início: {start_time}")

        user = request.user
        if not is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            return Response({"detail": "Acesso negado."}, status=status.HTTP_403_FORBIDDEN)

        vendas = self.filter_queryset(self.get_queryset())


        headers = [
            'ID', 'Reemissão', 'Data Criação', 'Data Abertura (OS)', 'Vendedor', 'Supervisor', 'Canal',
            'Cliente', 'CPF/CNPJ', 'Telefone 1', 'Telefone 2', 'Email',
            'Plano', 'Valor', 'Forma Pagamento', 
            'Status Esteira', 'Status Tratamento', 'Status Comissionamento',
            'OS', 'Data Agendamento', 'Turno', 'Data Instalação', 
            'Motivo Pendência', 'Observações',
            'CEP', 'Logradouro', 'Número', 'Complemento', 'Bairro', 'Cidade', 'UF', 'Ponto Ref.'
        ]

        data = []
        for v in vendas.iterator():
            sup_nome = v.vendedor.supervisor.username if v.vendedor and v.vendedor.supervisor else '-'
            canal_venda = getattr(v.vendedor, 'canal', '-') if v.vendedor else '-'
            from django.utils import timezone
            dt_criacao = timezone.localtime(v.data_criacao).strftime('%d/%m/%Y %H:%M') if v.data_criacao else '-'
            dt_abertura = timezone.localtime(v.data_abertura).strftime('%d/%m/%Y %H:%M') if v.data_abertura else '-'
            dt_agendamento = v.data_agendamento.strftime('%d/%m/%Y') if v.data_agendamento else '-'
            dt_instalacao = v.data_instalacao.strftime('%d/%m/%Y') if v.data_instalacao else '-'
            data.append([
                v.id,
                'Sim' if getattr(v, 'reemissao', False) else 'Não',
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

        df = pd.DataFrame(data, columns=headers)
        output = BytesIO()
        df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)

        filename = f"Base_Vendas_Completa_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        response = HttpResponse(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        end_time = time.time()
        print(f"[EXPORTAR_EXCEL] Fim: {end_time} | Duração: {end_time - start_time:.2f} segundos")
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

    def _sincronizar_seq_historico(self):
        """Garante que a sequence do histórico não esteja atrasada (evita PK duplicada)."""
        try:
            from django.db import connection
            from django.db.models import Max

            max_id = HistoricoAlteracaoVenda.objects.aggregate(max_id=Max('id')).get('max_id') or 0
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true);",
                    ['crm_historico_alteracao_venda', max_id]
                )
        except Exception as e:
            print(f"Aviso: não foi possível sincronizar sequence do histórico: {e}")

    def _sincronizar_seq_osab(self):
        """Garante que a sequence da importação OSAB não esteja atrasada (evita PK duplicada)."""
        try:
            from django.db import connection
            from django.db.models import Max

            max_id = ImportacaoOsab.objects.aggregate(max_id=Max('id')).get('max_id') or 0
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true);",
                    ['crm_importacao_osab', max_id]
                )
        except Exception as e:
            print(f"Aviso: não foi possível sincronizar sequence da OSAB: {e}")

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj: return Response({'error': 'Nenhum arquivo enviado.'}, status=400)
        
        opcao_front = str(request.data.get('enviar_whatsapp', 'true')).lower() == 'true'
        usuario = request.user
        pode_decidir = is_member(usuario, ['Diretoria', 'Admin'])
        flag_enviar_whatsapp = opcao_front if pode_decidir else True
        
        if not flag_enviar_whatsapp:
            print(f"--- Importação OSAB SILENCIOSA iniciada por: {usuario.username} ---")

        # Criar log antes de processar
        from crm_app.models import LogImportacaoOSAB
        log = LogImportacaoOSAB.objects.create(
            usuario=usuario,
            nome_arquivo=file_obj.name,
            status='PROCESSANDO',
            tamanho_arquivo=file_obj.size,
            enviar_whatsapp=flag_enviar_whatsapp
        )

        # Ler arquivo para memória ANTES de spawnar thread
        try:
            file_content = file_obj.read()
            file_name = file_obj.name
        except Exception as e:
            log.status = 'ERRO'
            log.mensagem_erro = f'Erro ao ler arquivo: {str(e)}'
            log.finalizado_em = timezone.now()
            log.calcular_duracao()
            log.save()
            return Response({'error': f'Erro leitura arquivo: {str(e)}'}, status=400)

        # Processar em background
        import threading
        thread = threading.Thread(
            target=self._processar_osab_interno,
            args=(log.id, file_content, file_name, flag_enviar_whatsapp)
        )
        thread.daemon = True
        thread.start()

        return Response({
            'success': True,
            'message': 'Importação OSAB iniciada! Processamento em andamento...',
            'log_id': log.id,
            'detalhes': 'O processamento está sendo executado em background. Atualize a página em alguns minutos para ver o resultado.',
        }, status=200)

    def _processar_osab_interno(self, log_id, file_content, file_name, flag_enviar_whatsapp):
        """Processamento OSAB em background thread"""
        from io import BytesIO
        from django.utils import timezone
        from crm_app.models import LogImportacaoOSAB
        
        try:
            log = LogImportacaoOSAB.objects.get(id=log_id)
            LogImportacaoOSAB.objects.filter(id=log_id).update(
                mensagem='Lendo arquivo OSAB...'
            )
            
            # Ler DataFrame do conteúdo
            try:
                file_buffer = BytesIO(file_content)
                if file_name.endswith('.xlsb'): 
                    df = pd.read_excel(file_buffer, engine='pyxlsb')
                elif file_name.endswith(('.xlsx', '.xls')): 
                    df = pd.read_excel(file_buffer)
                else: 
                    raise ValueError('Formato inválido')
            except Exception as e:
                log.status = 'ERRO'
                log.mensagem_erro = f'Erro leitura arquivo: {str(e)}'
                log.finalizado_em = timezone.now()
                log.calcular_duracao()
                log.save()
                return

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

            total_registros = len(df)
            LogImportacaoOSAB.objects.filter(id=log_id).update(
                total_registros=total_registros,
                total_processadas=0,
                mensagem=f'Preparando dados... 0/{total_registros}'
            )

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
                "vendas_encontradas": 0, "ja_corretos": 0, "erros": [], "logs_detalhados": [],
                "ignorados_dt_ref": 0, "arquivo_excel_b64": None
            }

            def _normalize_dt_ref(val):
                import datetime as dt_sys
                if val is None:
                    return None
                if isinstance(val, dt_sys.datetime):
                    return val.date()
                if isinstance(val, dt_sys.date):
                    return val
                return None

            # --- LOOP PRINCIPAL ---
            records = df.to_dict('records')
            progress_step = 5000

            for index, row in enumerate(records):
                log_item = {
                    "linha": index + 2,
                    "pedido": str(row.get('PEDIDO')),
                    "status_osab": str(row.get('SITUACAO')),
                    "dt_ref_planilha": row.get('DT_REF'),
                    "dt_ref_crm": None,
                    "consta_osab": "NAO",
                    "consta_crm": "NAO",
                    "resultado_osab": "",
                    "resultado_crm": "",
                    "detalhe": ""
                }
                try:
                    # A. ImportacaoOsab
                    dados_model = {}
                    for col_planilha, campo_model in coluna_map.items():
                        val = row.get(col_planilha)
                        if col_planilha == 'PEDIDO': val = self._clean_key(val)
                        dados_model[campo_model] = val
                    
                    doc_chave = dados_model.get('documento')
                    if not doc_chave: 
                        log_item["resultado_osab"] = "IGNORADO"
                        log_item["resultado_crm"] = "IGNORADO"
                        report["logs_detalhados"].append(log_item)
                        continue

                    if doc_chave in osab_existentes:
                        obj = osab_existentes[doc_chave]
                        dt_ref_nova = _normalize_dt_ref(dados_model.get('dt_ref'))
                        dt_ref_atual = _normalize_dt_ref(getattr(obj, 'dt_ref', None))
                        log_item["consta_osab"] = "SIM"
                        log_item["dt_ref_crm"] = dt_ref_atual
                        # Se a DT_REF nova não for mais recente, não atualiza nem altera a venda
                        if dt_ref_atual and (dt_ref_nova is None or dt_ref_nova <= dt_ref_atual):
                            log_item["resultado_osab"] = "IGNORADO_DT_REF_ANTIGA"
                            log_item["resultado_crm"] = "IGNORADO_DT_REF_ANTIGA"
                            log_item["detalhe"] = f"DT_REF planilha ({dt_ref_nova}) <= DT_REF CRM ({dt_ref_atual})"
                            report["ignorados_dt_ref"] += 1
                            report["logs_detalhados"].append(log_item)
                            continue

                        mudou = False
                        for k, v in dados_model.items():
                            if getattr(obj, k) != v:
                                setattr(obj, k, v)
                                mudou = True
                        if mudou:
                            osab_atualizar.append(obj)
                            log_item["resultado_osab"] = "ATUALIZADO_OSAB"
                        else:
                            log_item["resultado_osab"] = "SEM_MUDANCA_OSAB"
                    else:
                        osab_criar.append(ImportacaoOsab(**dados_model))
                        log_item["resultado_osab"] = "CRIADO_OSAB"

                    # B. Venda CRM
                    venda = vendas_map.get(doc_chave)
                    if not venda:
                        log_item["resultado_crm"] = "NAO_ENCONTRADO_CRM"
                        log_item["consta_crm"] = "NAO"
                        report["logs_detalhados"].append(log_item)
                        continue
                    
                    log_item["consta_crm"] = "SIM"
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
                        log_item["resultado_crm"] = "ATUALIZADO_CRM"
                        log_item["detalhe"] = "; ".join([f"{k}: {v}" for k, v in detalhes_hist.items()])
                        vendas_atualizar.append(venda)
                        historicos_criar.append(HistoricoAlteracaoVenda(venda=venda, usuario=osab_bot, alteracoes=detalhes_hist))
                        if msg_whatsapp_desta_venda and flag_enviar_whatsapp:
                            fila_mensagens_whatsapp.append(msg_whatsapp_desta_venda)
                    else:
                        log_item["resultado_crm"] = "SEM_MUDANCA_CRM"
                        report["ja_corretos"] += 1
                    
                    report["logs_detalhados"].append(log_item)

                except Exception as ex:
                    log_item["resultado_osab"] = log_item["resultado_osab"] or "ERRO"
                    log_item["resultado_crm"] = log_item["resultado_crm"] or "ERRO"
                    log_item["detalhe"] = str(ex)
                    report["erros"].append(f"L{index}: {ex}")
                    report["logs_detalhados"].append(log_item)

                # Atualizar progresso periodicamente
                if (index + 1) % progress_step == 0:
                    LogImportacaoOSAB.objects.filter(id=log_id).update(
                        total_processadas=index + 1,
                        mensagem=f'Processando registros... {index + 1}/{total_registros}'
                    )

            # --- 3. PERSISTÊNCIA ---
            LogImportacaoOSAB.objects.filter(id=log_id).update(
                total_processadas=total_registros,
                mensagem='Salvando resultados no banco...'
            )

            # Salvar em etapas para facilitar debug e evitar travar tudo num único transaction
            try:
                from django.db import connection
                if osab_criar:
                    LogImportacaoOSAB.objects.filter(id=log_id).update(
                        mensagem=f'Salvando OSAB: {len(osab_criar)} novos registros...'
                    )
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL statement_timeout = '120000ms'")
                        self._sincronizar_seq_osab()
                        ImportacaoOsab.objects.bulk_create(osab_criar, batch_size=2000)

                if osab_atualizar:
                    LogImportacaoOSAB.objects.filter(id=log_id).update(
                        mensagem=f'Atualizando OSAB: {len(osab_atualizar)} registros...'
                    )
                    campos_osab = [f.name for f in ImportacaoOsab._meta.fields if f.name != 'id']
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL statement_timeout = '120000ms'")
                        ImportacaoOsab.objects.bulk_update(osab_atualizar, campos_osab, batch_size=2000)

                if vendas_atualizar:
                    LogImportacaoOSAB.objects.filter(id=log_id).update(
                        mensagem=f'Atualizando vendas CRM: {len(vendas_atualizar)} registros...'
                    )
                    campos_venda = ['status_esteira', 'status_tratamento', 'data_instalacao', 'data_agendamento', 'forma_pagamento', 'motivo_pendencia', 'data_abertura']
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL statement_timeout = '120000ms'")
                        Venda.objects.bulk_update(vendas_atualizar, campos_venda, batch_size=2000)

                if historicos_criar:
                    LogImportacaoOSAB.objects.filter(id=log_id).update(
                        mensagem=f'Salvando histórico: {len(historicos_criar)} registros...'
                    )
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL statement_timeout = '120000ms'")
                        self._sincronizar_seq_historico()
                        HistoricoAlteracaoVenda.objects.bulk_create(historicos_criar, batch_size=2000)
            except Exception as e:
                log.status = 'ERRO'
                log.mensagem_erro = f'Erro ao salvar no banco: {str(e)}'
                log.finalizado_em = timezone.now()
                log.calcular_duracao()
                log.save()
                return

            report["atualizados"] = len(vendas_atualizar)
            report["criados"] = len(osab_criar)

            # --- 4. ENVIO WHATSAPP ---
            if fila_mensagens_whatsapp and flag_enviar_whatsapp:
                import threading
                t = threading.Thread(target=self._enviar_mensagens_background, args=(fila_mensagens_whatsapp,))
                t.start()
                print(f"Iniciado envio de {len(fila_mensagens_whatsapp)} mensagens em background.")
            
            # Atualizar log com sucesso
            log.status = 'SUCESSO'
            log.total_registros = report['total_registros']
            log.total_processadas = report['vendas_encontradas']
            log.criados = report['criados']
            log.atualizados = report['atualizados']
            log.vendas_encontradas = report['vendas_encontradas']
            log.ja_corretos = report['ja_corretos']
            log.erros_count = len(report['erros'])
            log.mensagem = f"Processados {report['total_registros']} registros. {report['atualizados']} atualizados."
            log.detalhes_json = report
            log.finalizado_em = timezone.now()
            log.calcular_duracao()
            log.save()
            
            print(f"✅ OSAB processado com sucesso - {report['atualizados']} vendas atualizadas")

        except Exception as e:
            # Atualizar log com erro
            print(f"❌ Erro no processamento OSAB: {str(e)}")
            import traceback
            traceback.print_exc()
            
            try:
                log.status = 'ERRO'
                log.mensagem_erro = str(e)
                log.finalizado_em = timezone.now()
                log.calcular_duracao()
                log.save()
            except:
                print("Erro ao salvar log de erro")


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
        
        # Bulk operations optimization
        criados, atualizados, erros = 0, 0, []
        fields = {f.name for f in ImportacaoChurn._meta.get_fields() if f.name != 'id'}
        
        # Separar registros para criar e atualizar
        pedidos_df = [row.get('numero_pedido') for _, row in df.iterrows() if row.get('numero_pedido')]
        existentes = {obj.numero_pedido: obj for obj in ImportacaoChurn.objects.filter(numero_pedido__in=pedidos_df)}
        
        to_create = []
        to_update = []
        
        for idx, row in df.iterrows():
            data = row.to_dict()
            pedido = data.get('numero_pedido')
            if not pedido: continue
            
            filtered_data = {k: v for k, v in data.items() if k in fields}
            
            try:
                if pedido in existentes:
                    obj = existentes[pedido]
                    for k, v in filtered_data.items():
                        setattr(obj, k, v)
                    to_update.append(obj)
                else:
                    to_create.append(ImportacaoChurn(**filtered_data))
            except Exception as e:
                erros.append(f"Linha {idx+2}: {e}")
        
        # Executar bulk operations
        with transaction.atomic():
            if to_create:
                ImportacaoChurn.objects.bulk_create(to_create, batch_size=1000)
                criados = len(to_create)
            if to_update:
                ImportacaoChurn.objects.bulk_update(to_update, list(fields), batch_size=1000)
                atualizados = len(to_update)
        
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
        
        # Bulk operations optimization
        criados, atualizados, erros = 0, 0, []
        fields = {f.name for f in CicloPagamento._meta.get_fields() if f.name != 'contrato'}
        
        # Separar registros para criar e atualizar
        contratos_df = [row.get('contrato') for _, row in df.iterrows() if row.get('contrato')]
        existentes = {obj.contrato: obj for obj in CicloPagamento.objects.filter(contrato__in=contratos_df)}
        
        to_create = []
        to_update = []
        
        for idx, row in df.iterrows():
            data = row.to_dict()
            contrato = data.get('contrato')
            if not contrato: continue
            
            filtered_data = {k: v for k, v in data.items() if k in fields or k == 'contrato'}
            
            try:
                if contrato in existentes:
                    obj = existentes[contrato]
                    for k, v in filtered_data.items():
                        if k != 'contrato':
                            setattr(obj, k, v)
                    to_update.append(obj)
                else:
                    to_create.append(CicloPagamento(**filtered_data))
            except Exception as e:
                erros.append(f"Linha {idx+2}: {e}")
        
        # Executar bulk operations
        with transaction.atomic():
            if to_create:
                CicloPagamento.objects.bulk_create(to_create, batch_size=1000, ignore_conflicts=True)
                criados = len(to_create)
            if to_update:
                CicloPagamento.objects.bulk_update(to_update, list(fields), batch_size=1000)
                atualizados = len(to_update)
        
        return Response({'total': len(df), 'criados': criados, 'atualizados': atualizados, 'erros': erros}, status=200)
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

            # Limpa tabela para evitar PK duplicada em reimportações
            AreaVenda.objects.all().delete()
            try:
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT setval(pg_get_serial_sequence('crm_app_areavenda', 'id'), COALESCE((SELECT MAX(id) FROM crm_app_areavenda), 1), false)"
                    )
            except Exception:
                pass  # Se não for Postgres ou falhar, segue com sequence atual

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
        
# --- IMPORTAÇÃO DFV (CSV) - VERSÃO PROFISSIONAL ---
class ImportarDFVView(APIView):
    """
    View para importação de arquivos DFV (Dados do Faturamento de Vendas).
    
    Esta view segue as melhores práticas:
    - Separação de responsabilidades (usa Service Layer)
    - Processamento assíncrono em background
    - Resposta imediata ao cliente
    - Tratamento robusto de erros
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        """
        Endpoint para upload e processamento de arquivo DFV.
        
        Returns:
            Response com log_id e status da importação iniciada
        """
        import logging
        import threading
        import tempfile
        import os
        
        logger = logging.getLogger(__name__)
        
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response(
                {'error': 'Arquivo CSV não enviado.'}, 
                status=400
            )
        
        try:
            from .models import LogImportacaoDFV
            from django.utils import timezone
            
            # Evitar múltiplas importações simultâneas (reduz lock e travamentos)
            log_em_andamento = LogImportacaoDFV.objects.filter(status='PROCESSANDO').order_by('-iniciado_em').first()
            if log_em_andamento:
                return Response(
                    {
                        'error': 'Já existe uma importação DFV em andamento. Aguarde finalizar para enviar outro arquivo.',
                        'log_id': log_em_andamento.id,
                        'status': 'PROCESSANDO'
                    },
                    status=409
                )
            
            # Criar log de importação ANTES de ler o arquivo
            log = LogImportacaoDFV.objects.create(
                nome_arquivo=file_obj.name,
                usuario=request.user,
                status='PROCESSANDO',
                tamanho_arquivo=0  # Será atualizado durante o processamento
            )
            
            logger.info(
                f"[DFV] Nova importação iniciada - Log ID: {log.id}, "
                f"Arquivo: {file_obj.name}, Usuário: {request.user.username}"
            )
            
            # Salvar arquivo em disco temporário para evitar uso excessivo de memória
            chunk_size = 1024 * 1024  # 1MB por chunk
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
            temp_path = temp_file.name
            total_bytes = 0

            logger.debug(f"[DFV] Salvando arquivo {file_obj.name} em disco temporário...")
            for chunk in file_obj.chunks(chunk_size):
                temp_file.write(chunk)
                total_bytes += len(chunk)
            temp_file.close()

            logger.info(
                f"[DFV] Arquivo salvo em disco: {file_obj.name} "
                f"({total_bytes / (1024*1024):.2f} MB)"
            )

            # Atualizar tamanho do arquivo no log
            LogImportacaoDFV.objects.filter(id=log.id).update(tamanho_arquivo=total_bytes)
            
            # Iniciar processamento em thread background
            def processar_dfv_async():
                """Wrapper para processamento assíncrono"""
                try:
                    from .services.dfv_import_service import DFVImportService
                    
                    service = DFVImportService(log_id=log.id)
                    service.process(None, file_obj.name, arquivo_path=temp_path)
                except Exception as e:
                    logger.error(
                        f"[DFV] Erro crítico no processamento assíncrono: {e}",
                        exc_info=True
                    )
                    # O serviço já atualiza o log em caso de erro
                finally:
                    try:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    except Exception as e:
                        logger.warning(f"[DFV] Não foi possível remover arquivo temporário: {e}")
            
            thread = threading.Thread(target=processar_dfv_async, daemon=True)
            thread.start()
            
            # Retornar imediatamente ao cliente
            return Response({
                'success': True,
                'log_id': log.id,
                'message': 'Importação DFV iniciada! O processamento continuará em segundo plano.',
                'status': 'PROCESSANDO',
                'background': True
            })
            
        except Exception as e:
            logger.error(
                f"[DFV] Erro ao iniciar importação: {e}",
                exc_info=True
            )
            return Response(
                {'error': f'Erro ao iniciar importação: {str(e)}'}, 
                status=500
            )

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

        # 4b. Filtro de Cluster (Query Param)
        filtro_cluster = request.query_params.get('cluster')
        if filtro_cluster:
            users = users.filter(cluster=filtro_cluster)

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
        ).values('username', 'canal', 'cluster', 'vendas_total', 'vendas_cc').order_by('username')  # Ordem alfabética

        lista_hoje = []
        for u in qs_hoje:
            total = u['vendas_total']
            cc = u['vendas_cc']
            pct = (cc / total * 100) if total > 0 else 0
            
            nome_display = u['username']
            
            lista_hoje.append({
                'vendedor': nome_display.upper(),
                'canal': u['canal'],
                'cluster': u.get('cluster', '-'),
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
        ).values('username', 'cluster', 'seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'total_semana', 'total_cc').order_by('username')  # Ordem alfabética

        lista_semana = []
        for u in qs_semana:
            total = u['total_semana']
            pct = (u['total_cc'] / total * 100) if total > 0 else 0
            nome_display = u['username']

            lista_semana.append({
                'vendedor': nome_display.upper(),
                'cluster': u.get('cluster', '-'),
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
            'username', 'cluster', 'total_vendas', 'instaladas', 'total_cc', 'instaladas_cc', 'pendenciadas', 'agendadas', 'canceladas'
        ).order_by('username')  # Ordem alfabética

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
                'cluster': u.get('cluster', '-'),
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
        ).values('username', 'seg', 'ter', 'qua', 'qui', 'sex', 'sab', 'total_semana', 'total_cc').order_by('username')  # Ordem alfab�tica

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
        ).order_by('username')  # Ordem alfab�tica

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


class ViaCepProxyView(APIView):
    """Proxy para consulta de CEP evitando CORS no frontend."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, cep):
        cep_limpo = re.sub(r'\D', '', str(cep or ''))
        if len(cep_limpo) != 8:
            return Response({'error': 'CEP inválido.'}, status=400)

        try:
            import json
            import urllib.request

            url = f"https://viacep.com.br/ws/{cep_limpo}/json/"
            with urllib.request.urlopen(url, timeout=8) as response:
                data = json.loads(response.read().decode('utf-8'))
            return Response(data)
        except Exception as e:
            return Response({'error': f'Erro ao consultar CEP: {str(e)}'}, status=502)


class NominatimProxyView(APIView):
    """Proxy para consulta Nominatim evitando CORS no frontend."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            import json
            import urllib.parse
            import urllib.request

            q = request.query_params.get('q')
            postalcode = request.query_params.get('postalcode')
            if not q and not postalcode:
                return Response({'error': 'Parâmetro ausente.'}, status=400)

            params = {
                'format': 'json',
                'limit': '1',
                'countrycodes': 'br',
            }
            if q:
                params['q'] = q
            if postalcode:
                params['postalcode'] = postalcode

            url = f"https://nominatim.openstreetmap.org/search?{urllib.parse.urlencode(params)}"
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'RecordPap/1.0'}
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                data = json.loads(response.read().decode('utf-8'))
            return Response(data)
        except Exception as e:
            return Response({'error': f'Erro ao consultar Nominatim: {str(e)}'}, status=502)
    

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

    # --- 2. IMPORTAÇÃO E PROCESSAMENTO (POST) - ASYNC ---
    def post(self, request):
        """
        Recebe arquivo Excel e inicia processamento assíncrono.
        Retorna imediatamente com log_id para acompanhamento.
        """
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'Arquivo não enviado'}, status=400)

        # 1. Criar log inicial
        log = LogImportacaoLegado.objects.create(
            usuario=request.user,
            nome_arquivo=file_obj.name,
            status='PROCESSANDO'
        )

        # 2. Ler arquivo para memória
        try:
            file_content = file_obj.read()
            file_name = file_obj.name
        except Exception as e:
            log.status = 'ERRO'
            log.mensagem_erro = f'Erro ao ler arquivo: {str(e)}'
            log.finalizado_em = timezone.now()
            log.save()
            return Response({'error': f'Erro ao ler arquivo: {str(e)}'}, status=400)

        # 3. Iniciar thread de processamento
        thread = threading.Thread(
            target=self._processar_legado_interno,
            args=(log.id, file_content, file_name)
        )
        thread.daemon = True
        thread.start()

        # 4. Retornar imediatamente
        # Mantém padrão dos outros imports: retorna sucesso imediato + log_id
        return Response({
            'success': True,
            'message': 'Processamento iniciado! Acompanhe o progresso na aba Histórico.',
            'status': 'PROCESSANDO',
            'background': True,
            'log_id': log.id
        }, status=200)

    def _processar_legado_interno(self, log_id, file_content, file_name):
        """Processa importação em background"""
        try:
            log = LogImportacaoLegado.objects.get(id=log_id)
            
            # Ler Excel em memória com dtype=str para preservar zeros
            try:
                df = pd.read_excel(io.BytesIO(file_content), dtype=str)
            except Exception as e:
                log.status = 'ERRO'
                log.mensagem_erro = f'Erro ao ler Excel: {str(e)}'
                log.finalizado_em = timezone.now()
                log.save()
                return

            # Normaliza colunas
            df.columns = [str(c).strip().upper() for c in df.columns]
            df = df.replace({np.nan: None, 'nan': None, 'NaN': None, 'None': None})
            
            log.total_linhas = len(df)
            log.save()
            
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
            vendas_criadas = 0
            clientes_criados = 0

            # --- FUNÇÕES AUXILIARES ---
            def parse_dt(val):
                if not val: return None
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
                    
                    cliente, criou_cliente = Cliente.objects.get_or_create(
                        cpf_cnpj=cpf_limpo, defaults={'nome_razao_social': nome_cli}
                    )
                    if criou_cliente:
                        clientes_criados += 1
                    
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
                        
                        data_criacao=dt_venda, 
                        
                        cep=cep_final,
                        logradouro=logradouro[:255],
                        numero_residencia=str(row.get('NUMERO', ''))[:20],
                        complemento=str(row.get('COMPLEMENTO', '')).upper()[:100],
                        bairro=bairro[:100],
                        cidade=cidade[:100],
                        estado=uf[:2],
                        ponto_referencia=str(row.get('PONTO_REFERENCIA', '')).upper()[:255],

                        ordem_servico=os_raw,
                        observacoes=str(row.get('OBSERVACOES', 'Importação Legado'))[:500],
                        ativo=True
                    )
                    
                    vendas_para_criar.append(venda)
                    vendas_criadas += 1

                except Exception as e:
                    logs_erro.append(f"Linha {linha}: {str(e)}")

            # --- GRAVAÇÃO EM LOTE ---
            if vendas_para_criar:
                with transaction.atomic():
                    Venda.objects.bulk_create(vendas_para_criar, batch_size=1000)

            # Atualizar log
            log.total_processadas = vendas_criadas
            log.vendas_criadas = vendas_criadas
            log.clientes_criados = clientes_criados
            log.erros_count = len(logs_erro)
            log.finalizado_em = timezone.now()
            
            if logs_erro:
                log.status = 'PARCIAL' if vendas_criadas > 0 else 'ERRO'
                log.mensagem_erro = '\n'.join(logs_erro[:50])
                log.mensagem = f'{vendas_criadas} vendas importadas, {len(logs_erro)} erros'
            else:
                log.status = 'SUCESSO'
                log.mensagem = f'{vendas_criadas} vendas importadas com sucesso!'
            
            log.detalhes_json = {
                'clientes_criados': clientes_criados,
                'vendas_criadas': vendas_criadas,
                'erros': logs_erro[:100]
            }
            log.save()

        except Exception as e:
            try:
                log = LogImportacaoLegado.objects.get(id=log_id)
                log.status = 'ERRO'
                log.mensagem_erro = str(e)
                log.finalizado_em = timezone.now()
                log.save()
            except:
                pass
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
            resumo_msg = None
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

            destinatarios_config = []
            try:
                regra = RegraAutomacao.objects.filter(evento_gatilho='NOVO_CDOI').first()
                if regra and isinstance(regra.destinos_numeros, list):
                    destinatarios_config = [str(x).strip() for x in regra.destinos_numeros if str(x).strip()]
            except Exception:
                destinatarios_config = []

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
                destinatarios_resumo=",".join(destinatarios_config) if destinatarios_config else None,
                criado_por=request.user,
                status="SEM_TRATAMENTO" # Status inicial novo
            )

            # Salvar Blocos (Melhorado com logs e tratamento de erro)
            blocos_json = data.get('dados_blocos_json')
            import logging
            logger = logging.getLogger(__name__)
            
            if blocos_json:
                try:
                    blocos = json.loads(blocos_json)
                    logger.info(f"[CDOI] Salvando {len(blocos)} blocos para {cdoi.nome_condominio} (ID: {cdoi.id})")
                    
                    blocos_criados = 0
                    for b in blocos:
                        try:
                            CdoiBloco.objects.create(
                                solicitacao=cdoi,
                                nome_bloco=b.get('nome', ''),
                                andares=int(b.get('andares', 0)),
                                unidades_por_andar=int(b.get('aptos', 0)),
                                total_hps_bloco=int(b.get('total', 0))
                            )
                            blocos_criados += 1
                            logger.debug(f"[CDOI] Bloco criado: {b.get('nome')} - {b.get('andares')} andares, {b.get('aptos')} aptos")
                        except Exception as e_bloco_individual:
                            logger.error(f"[CDOI] Erro ao criar bloco individual {b}: {e_bloco_individual}", exc_info=True)
                    
                    logger.info(f"[CDOI] {blocos_criados}/{len(blocos)} blocos salvos com sucesso para {cdoi.nome_condominio}")
                    
                    # Verifica se todos foram salvos
                    if blocos_criados != len(blocos):
                        logger.warning(f"[CDOI] ATENCAO: Apenas {blocos_criados} de {len(blocos)} blocos foram salvos!")
                    
                except json.JSONDecodeError as e_json:
                    logger.error(f"[CDOI] Erro ao decodificar JSON de blocos: {e_json}")
                    logger.error(f"[CDOI] JSON recebido: {blocos_json}")
                except Exception as e_blocos:
                    logger.error(f"[CDOI] Erro ao salvar blocos: {e_blocos}", exc_info=True)
            else:
                logger.warning(f"[CDOI] Nenhum dado de blocos recebido para {cdoi.nome_condominio} (ID: {cdoi.id})")

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

            # Enviar resumo para acionador e destinatários extras
            try:
                def _limpar_tel(tel):
                    tel_limpo = re.sub(r'\D', '', str(tel or ''))
                    return tel_limpo if tel_limpo else None

                blocos_data = []
                if blocos_json:
                    try:
                        blocos_data = json.loads(blocos_json)
                    except Exception:
                        blocos_data = []

                blocos_txt = "\n".join(
                    [f"- {b.get('nome','')} | {b.get('andares','')} andares | {b.get('aptos','')} aptos/andar | {b.get('total','')} HPs"
                     for b in blocos_data]
                ) or "- (não informado)"

                resumo = (
                    f"✅ *Resumo CDOI*\n"
                    f"ID: {cdoi.id}\n"
                    f"Condomínio: {cdoi.nome_condominio}\n"
                    f"CEP: {cdoi.cep}\n"
                    f"Endereço: {cdoi.logradouro}, {cdoi.numero} - {cdoi.bairro}\n"
                    f"Cidade/UF: {cdoi.cidade}-{cdoi.uf}\n"
                    f"Infraestrutura: {cdoi.infraestrutura_tipo}\n"
                    f"Shaft/DG: {'Sim' if cdoi.possui_shaft_dg else 'Não'}\n"
                    f"Total HPs: {cdoi.total_hps}\n"
                    f"Pré-venda (10%): {cdoi.pre_venda_minima}\n"
                    f"Síndico: {cdoi.nome_sindico}\n"
                    f"Contato: {cdoi.contato_sindico}\n"
                    f"Latitude: {cdoi.latitude or '-'}\n"
                    f"Longitude: {cdoi.longitude or '-'}\n"
                    f"Blocos:\n{blocos_txt}"
                )
                resumo_msg = resumo

                destinatarios = []
                tel_user = getattr(request.user, 'tel_whatsapp', None)
                tel_user = _limpar_tel(tel_user)
                if tel_user:
                    destinatarios.append(tel_user)

                extras = []
                if destinatarios_config:
                    extras.extend(destinatarios_config)
                extras_raw = data.get('destinatarios_resumo') or ''
                extras.extend([t.strip() for t in re.split(r'[;,\\n]', str(extras_raw)) if t.strip()])
                for t in extras:
                    tel_extra = _limpar_tel(t)
                    if tel_extra and tel_extra not in destinatarios:
                        destinatarios.append(tel_extra)

                if destinatarios:
                    svc = WhatsAppService()
                    for tel in destinatarios:
                        svc.enviar_mensagem_texto(tel, resumo)
            except Exception as e_zap_resumo:
                print(f"Erro ao enviar resumo CDOI: {e_zap_resumo}")

            return Response({'mensagem': f'Solicitação enviada! ID: {cdoi.id}', 'resumo': resumo_msg}, status=200)

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
        for item in queryset.select_related('criado_por'):
            # Usa username ao invés do nome completo
            criado_por_nome = item.criado_por.username if item.criado_por else '-'
            
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
                'can_edit': eh_gestao, # Flag para o frontend saber se libera edição
                'criado_por_id': item.criado_por.id if item.criado_por else None,
                'criado_por_nome': criado_por_nome
            })
        
        return Response(data)


class CdoiDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum

        queryset = CdoiSolicitacao.objects.all()
        total_acionamentos = queryset.count()
        total_hps = queryset.aggregate(total=Sum('total_hps')).get('total') or 0
        total_prevenda = queryset.aggregate(total=Sum('pre_venda_minima')).get('total') or 0

        por_status = (
            queryset.values('status')
            .annotate(qtd=Count('id'))
            .order_by('-qtd')
        )

        # Cruzar CEP + fachada (numero) com vendas
        pares = []
        for item in queryset.values('cep', 'numero'):
            cep_limpo = re.sub(r'\D', '', str(item.get('cep') or ''))
            numero = str(item.get('numero') or '').strip()
            if cep_limpo and numero:
                pares.append((cep_limpo, numero))

        vendas_realizadas = 0
        if pares:
            ceps = list({p[0] for p in pares})
            pares_set = set(pares)
            vendas = Venda.objects.filter(cep__in=ceps).values('cep', 'numero_residencia')
            for v in vendas:
                cep_limpo = re.sub(r'\D', '', str(v.get('cep') or ''))
                numero = str(v.get('numero_residencia') or '').strip()
                if (cep_limpo, numero) in pares_set:
                    vendas_realizadas += 1

        return Response({
            'success': True,
            'total_acionamentos': total_acionamentos,
            'total_hps': total_hps,
            'total_prevenda': total_prevenda,
            'vendas_realizadas': vendas_realizadas,
            'por_status': list(por_status),
        })

# --- 3. EDIÇÃO DE STATUS (Apenas Gestão) ---
class CdoiUpdateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        user = request.user
        if not is_member(user, ['Diretoria', 'Admin', 'BackOffice']):
            return Response({"error": "Acesso negado."}, status=403)

        try:
            cdoi = CdoiSolicitacao.objects.get(pk=pk)
            # Usa select_related/prefetch_related para otimizar a consulta
            blocos_queryset = cdoi.blocos.all().order_by('nome_bloco')
            blocos = [
                {
                    'nome': b.nome_bloco,
                    'andares': b.andares,
                    'aptos': b.unidades_por_andar,
                    'total': b.total_hps_bloco,
                }
                for b in blocos_queryset
            ]
            
            # Log para debug detalhado
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[CDOI] Editando {cdoi.nome_condominio} (ID: {pk}) - {len(blocos)} blocos encontrados")
            
            # Log detalhado se não houver blocos mas houver total_hps
            if len(blocos) == 0 and cdoi.total_hps > 0:
                logger.warning(
                    f"[CDOI] ATENCAO: Condominio {cdoi.nome_condominio} (ID: {pk}) "
                    f"tem total_hps={cdoi.total_hps} mas nenhum bloco cadastrado!"
                )
                logger.warning(f"[CDOI] Isso indica que os blocos nao foram salvos durante a criacao.")

            # Monta nome do criador
            criado_por_nome = '-'
            if cdoi.criado_por:
                if cdoi.criado_por.first_name or cdoi.criado_por.last_name:
                    criado_por_nome = f"{cdoi.criado_por.first_name or ''} {cdoi.criado_por.last_name or ''}".strip()
                else:
                    criado_por_nome = cdoi.criado_por.username or '-'
            
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
                'criado_por_id': cdoi.criado_por.id if cdoi.criado_por else None,
                'criado_por_nome': criado_por_nome,
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
            import logging
            logger = logging.getLogger(__name__)

            # Campos pontuais
            if data.get('status'):
                cdoi.status = data.get('status')
            if 'observacao' in data:
                cdoi.observacao = data.get('observacao')
            if data.get('nome_condominio'):
                cdoi.nome_condominio = data.get('nome_condominio')
            
            # Atualizar blocos se fornecidos
            if 'dados_blocos_json' in data:
                blocos_json = data.get('dados_blocos_json')
                if blocos_json:
                    try:
                        # Remove blocos antigos
                        cdoi.blocos.all().delete()
                        logger.info(f"[CDOI] Blocos antigos removidos para {cdoi.nome_condominio} (ID: {pk})")
                        
                        # Cria novos blocos
                        blocos = json.loads(blocos_json)
                        blocos_criados = 0
                        for b in blocos:
                            try:
                                CdoiBloco.objects.create(
                                    solicitacao=cdoi,
                                    nome_bloco=b.get('nome', ''),
                                    andares=int(b.get('andares', 0)),
                                    unidades_por_andar=int(b.get('aptos', 0)),
                                    total_hps_bloco=int(b.get('total', 0))
                                )
                                blocos_criados += 1
                            except Exception as e_bloco:
                                logger.error(f"[CDOI] Erro ao criar bloco na edicao: {e_bloco}")
                        
                        logger.info(f"[CDOI] {blocos_criados} blocos atualizados para {cdoi.nome_condominio} (ID: {pk})")
                        
                        # Atualiza total_hps e pre_venda se fornecidos
                        if 'total_hps_final' in data:
                            cdoi.total_hps = int(data.get('total_hps_final', 0))
                        if 'prevenda_final' in data:
                            cdoi.pre_venda_minima = int(data.get('prevenda_final', 0))
                    except json.JSONDecodeError as e_json:
                        logger.error(f"[CDOI] Erro ao decodificar JSON de blocos na edicao: {e_json}")
                    except Exception as e_blocos:
                        logger.error(f"[CDOI] Erro ao atualizar blocos: {e_blocos}", exc_info=True)
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
            
            # Permite alterar quem acionou (criado_por)
            if 'criado_por_id' in data and data.get('criado_por_id'):
                try:
                    from usuarios.models import Usuario
                    novo_criador = Usuario.objects.get(id=data.get('criado_por_id'))
                    cdoi.criado_por = novo_criador
                except Usuario.DoesNotExist:
                    pass  # Ignora se usuário não existir

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
# IMPORTAÇÃO DE AGENDAMENTOS E TAREFAS
# =============================================================================

class ImportacaoAgendamentoView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_agendamento'
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        """
        Recebe arquivo Excel/XLSB e inicia processamento assíncrono.
        Retorna imediatamente com log_id para acompanhamento.
        """
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'Nenhum arquivo enviado.'}, status=400)

        # 1. Criar log inicial
        log = LogImportacaoAgendamento.objects.create(
            usuario=request.user,
            nome_arquivo=file_obj.name,
            status='PROCESSANDO'
        )

        # 2. Ler arquivo para memória
        try:
            file_content = file_obj.read()
            file_name = file_obj.name
        except Exception as e:
            log.status = 'ERRO'
            log.mensagem_erro = f'Erro ao ler arquivo: {str(e)}'
            log.finalizado_em = timezone.now()
            log.save()
            return Response({'error': f'Erro ao ler arquivo: {str(e)}'}, status=400)

        # 3. Iniciar thread de processamento
        thread = threading.Thread(
            target=self._processar_agendamento_interno,
            args=(log.id, file_content, file_name)
        )
        thread.daemon = True
        thread.start()

        # 4. Retornar imediatamente
        return Response({
            'success': True,
            'status': 'PROCESSANDO',
            'background': True,
            'log_id': log.id,
            'message': 'Processamento iniciado! Acompanhe o progresso na aba Histórico.'
        }, status=200)

    def _processar_agendamento_interno(self, log_id, file_content, file_name):
        """Processa importação em background"""
        try:
            log = LogImportacaoAgendamento.objects.get(id=log_id)
            
            # Ler Excel/XLSB em memória
            try:
                if file_name.endswith('.xlsb'):
                    df = pd.read_excel(io.BytesIO(file_content), engine='pyxlsb')
                elif file_name.endswith(('.xlsx', '.xls')):
                    df = pd.read_excel(io.BytesIO(file_content))
                else:
                    log.status = 'ERRO'
                    log.mensagem_erro = 'Formato inválido. Envie .xlsx, .xls ou .xlsb'
                    log.finalizado_em = timezone.now()
                    log.save()
                    return
            except Exception as e:
                log.status = 'ERRO'
                log.mensagem_erro = f'Erro ao ler arquivo: {str(e)}'
                log.finalizado_em = timezone.now()
                log.save()
                return

            # Normaliza nomes das colunas
            df.columns = [str(col).strip().lower() for col in df.columns]

            log.total_linhas = len(df)
            log.save()

            # Converte datas
            campos_data = ['dt_abertura_ba', 'dt_execucao_particao', 'dt_agendamento']
            campos_datetime = ['dt_inicio_agendamento', 'dt_fim_agendamento', 'dt_inicio_execucao_real', 'dt_fim_execucao_real']

            for campo in campos_data:
                if campo in df.columns:
                    df[campo] = pd.to_datetime(df[campo], errors='coerce')

            for campo in campos_datetime:
                if campo in df.columns:
                    df[campo] = pd.to_datetime(df[campo], errors='coerce')

            # Processa linhas
            registros_criados = 0
            registros_atualizados = 0
            nao_encontrados = 0
            erros = []

            for idx, row in df.iterrows():
                try:
                    dados = {
                        'sg_uf': str(row.get('sg_uf')) if pd.notna(row.get('sg_uf')) else None,
                        'nm_municipio': str(row.get('nm_municipio')) if pd.notna(row.get('nm_municipio')) else None,
                        'indicador': str(row.get('indicador')) if pd.notna(row.get('indicador')) else None,
                        'cd_nrba': str(row.get('cd_nrba')) if pd.notna(row.get('cd_nrba')) else None,
                        'st_ba': str(row.get('st_ba')) if pd.notna(row.get('st_ba')) else None,
                        'cd_encerramento': str(row.get('cd_encerramento')) if pd.notna(row.get('cd_encerramento')) else None,
                        'desc_observacao': str(row.get('desc_observacao')) if pd.notna(row.get('desc_observacao')) else None,
                        'desc_macro_atividade': str(row.get('desc_macro_atividade')) if pd.notna(row.get('desc_macro_atividade')) else None,
                        'ds_atividade': str(row.get('ds_atividade')) if pd.notna(row.get('ds_atividade')) else None,
                        'nr_ordem': str(row.get('nr_ordem')) if pd.notna(row.get('nr_ordem')) else None,
                        'nr_ordem_venda': str(row.get('nr_ordem_venda')) if pd.notna(row.get('nr_ordem_venda')) else None,
                        'anomes': str(row.get('anomes')) if pd.notna(row.get('anomes')) else None,
                        'cd_sap_original': str(row.get('cd_sap_original')) if pd.notna(row.get('cd_sap_original')) else None,
                        'cd_rede': str(row.get('cd_rede')) if pd.notna(row.get('cd_rede')) else None,
                        'nm_pdv_rel': str(row.get('nm_pdv_rel')) if pd.notna(row.get('nm_pdv_rel')) else None,
                        'rede': str(row.get('rede')) if pd.notna(row.get('rede')) else None,
                        'gp_canal': str(row.get('gp_canal')) if pd.notna(row.get('gp_canal')) else None,
                        'sg_gerencia': str(row.get('sg_gerencia')) if pd.notna(row.get('sg_gerencia')) else None,
                        'nm_gc': str(row.get('nm_gc')) if pd.notna(row.get('nm_gc')) else None,
                    }

                    # Campos de data
                    for campo in campos_data:
                        if campo in df.columns and pd.notna(row[campo]):
                            dados[campo] = row[campo].date() if isinstance(row[campo], pd.Timestamp) else None

                    # Campos de datetime
                    for campo in campos_datetime:
                        if campo in df.columns and pd.notna(row[campo]):
                            dados[campo] = row[campo].to_pydatetime() if isinstance(row[campo], pd.Timestamp) else None

                    # Cria registro
                    ImportacaoAgendamento.objects.create(**dados)
                    registros_criados += 1

                except Exception as e:
                    erros.append(f"Linha {idx + 2}: {str(e)}")

            # Atualizar log
            log.total_processadas = registros_criados
            log.agendamentos_criados = registros_criados
            log.agendamentos_atualizados = registros_atualizados
            log.nao_encontrados = nao_encontrados
            log.erros_count = len(erros)
            log.finalizado_em = timezone.now()
            
            if erros:
                log.status = 'PARCIAL' if registros_criados > 0 else 'ERRO'
                log.mensagem_erro = '\n'.join(erros[:50])
                log.mensagem = f'{registros_criados} registros importados, {len(erros)} erros'
            else:
                log.status = 'SUCESSO'
                log.mensagem = f'{registros_criados} agendamentos importados com sucesso!'
            
            log.detalhes_json = {
                'registros_criados': registros_criados,
                'erros': erros[:100]
            }
            log.save()

        except Exception as e:
            try:
                log = LogImportacaoAgendamento.objects.get(id=log_id)
                log.status = 'ERRO'
                log.mensagem_erro = str(e)
                log.finalizado_em = timezone.now()
                log.save()
            except:
                pass


class ImportacaoRecompraView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_recompra'
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('arquivo')
        if not file_obj:
            return Response({'success': False, 'error': 'Arquivo não enviado'}, status=400)

        try:
            # Leitura do arquivo
            if file_obj.name.endswith('.xlsb'):
                df = pd.read_excel(file_obj, engine='pyxlsb')
            elif file_obj.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_obj)
            else:
                return Response({'success': False, 'error': 'Formato inválido. Envie .xlsx, .xls ou .xlsb'}, status=400)
        except Exception as e:
            return Response({'success': False, 'error': f'Erro ao ler arquivo: {str(e)}'}, status=400)

        # Normaliza nomes das colunas
        df.columns = [str(col).strip() for col in df.columns]

        # Converte datas
        campos_data = ['dt_venda_particao', 'dt_encerramento', 'dt_inicio_ativo']

        for campo in campos_data:
            if campo in df.columns:
                df[campo] = pd.to_datetime(df[campo], errors='coerce')

        # Mapa de colunas esperadas
        coluna_map = {
            'ds_anomes': 'ds_anomes',
            'dt_venda_particao': 'dt_venda_particao',
            'dt_encerramento': 'dt_encerramento',
            'nr_ordem': 'nr_ordem',
            'st_ordem': 'st_ordem',
            'nm_seg': 'nm_seg',
            'sg_uf': 'sg_uf',
            'cd_sap_pdv': 'cd_sap_pdv',
            'cd_tr_vdd': 'cd_tr_vdd',
            'nr_cep': 'nr_cep',
            'nm_municipio': 'nm_municipio',
            'nm_bairro': 'nm_bairro',
            'resultado': 'resultado',
            'dt_inicio_ativo': 'dt_inicio_ativo',
            'nr_cep_base': 'nr_cep_base',
            'nr_complemento1_base': 'nr_complemento1_base',
            'nr_complemento2_base': 'nr_complemento2_base',
            'nr_complemento3_base': 'nr_complemento3_base',
            'nm_diretoria': 'nm_diretoria',
            'nm_regional': 'nm_regional',
            'cd_rede': 'cd_rede',
            'gp_canal': 'gp_canal',
            'nm_pdv_rel': 'nm_pdv_rel',
            'GERENCIA': 'GERENCIA',
            'nm_gc': 'nm_gc',
            'REDE': 'REDE',
        }

        # Processa linhas
        registros_criados = 0
        erros = []

        for idx, row in df.iterrows():
            try:
                dados = {}
                for col_arquivo, col_model in coluna_map.items():
                    if col_arquivo in df.columns:
                        valor = row.get(col_arquivo)
                        
                        # Tratar valores vazios
                        if pd.isna(valor) or valor == '':
                            dados[col_model] = None
                        else:
                            # Converter datas
                            if col_model in campos_data:
                                try:
                                    dados[col_model] = pd.to_datetime(valor).date()
                                except:
                                    dados[col_model] = None
                            else:
                                dados[col_model] = str(valor).strip()
                    else:
                        dados[col_model] = None

                # Cria registro
                ImportacaoRecompra.objects.create(**dados)
                registros_criados += 1

            except Exception as e:
                erros.append(f"Linha {idx + 2}: {str(e)}")

        return Response({
            'success': True,
            'registros_criados': registros_criados,
            'total_linhas': len(df),
            'erros': erros[:10] if erros else [],
            'arquivo': file_obj.name,
            'data_importacao': timezone.now().strftime('%d/%m/%Y, %H:%M:%S')
        }, status=200)


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


def page_validacao_fpd(request):
    """View para renderizar a página de validação de importações FPD"""
    return render(request, 'validacao-fpd.html')


def page_validacao_churn(request):
    """View para renderizar a página de validação de importações CHURN"""
    return render(request, 'validacao-churn.html')


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


def _map_status_fpd(status_raw: str) -> str:
    """Mapeia status do FPD para rótulos amigáveis segundo mapeamento do usuário:
    - Paga → Paga
    - Paga_aguardando_repasse → Paga
    - Aguardando_arrecadacao → Não Pago
    - Ajustada → Paga
    - Erro_nao_recobravel → Não Pago
    """
    if not status_raw:
        return '-'
    mapping = {
        'paga': 'Paga',
        'paga_aguardando_repasse': 'Paga',
        'aguardando_arrecadacao': 'Não Pago',
        'ajustada': 'Paga',
        'erro_nao_recobravel': 'Não Pago',
    }
    key = status_raw.lower()
    return mapping.get(key, status_raw.replace('_', ' '))


class VendedoresM10View(APIView):
    """Lista vendedores que têm contratos na M-10 (opcionalmente filtrado por safra)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        safra = request.GET.get('safra')
        queryset = ContratoM10.objects.select_related('vendedor').filter(vendedor__isnull=False)
        if safra:
            # safra pode ser ID do SafraM10 ou string YYYY-MM
            # Tenta primeiro como string diretamente
            queryset = queryset.filter(safra=safra)

        # Deduplica por vendedor_id para evitar repetição na lista
        vistos = {}
        for v in queryset.values('vendedor_id', 'vendedor__username', 'vendedor__first_name', 'vendedor__last_name'):
            vid = v['vendedor_id']
            if vid not in vistos and vid is not None:
                nome = f"{v.get('vendedor__first_name', '')} {v.get('vendedor__last_name', '')}".strip()
                vistos[vid] = {
                    'id': vid,
                    'username': v.get('vendedor__username') or '-',
                    'nome': nome or v.get('vendedor__username') or '-',
                }

        data = sorted(vistos.values(), key=lambda x: (x['username'] or '').lower())
        return Response(data)


class DashboardM10View(APIView):
    """Dashboard com estatísticas M-10"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            safra_id = request.GET.get('safra')
            if not safra_id:
                return Response({'error': 'Safra não informada'}, status=400)

            try:
                safra = SafraM10.objects.get(id=safra_id)
            except SafraM10.DoesNotExist:
                return Response({'error': 'Safra não encontrada'}, status=404)

            # Converte safra_id para string YYYY-MM para filtro
            safra_str = safra.mes_referencia.strftime('%Y-%m')
            
            # Filtros - agora safra é CharField YYYY-MM
            queryset = ContratoM10.objects.filter(safra=safra_str).select_related('vendedor')
            
            vendedor = request.GET.get('vendedor')
            if vendedor:
                queryset = queryset.filter(vendedor_id=vendedor)
            
            status = request.GET.get('status')
            if status:
                queryset = queryset.filter(status_contrato=status)
            
            elegivel = request.GET.get('elegivel')
            if elegivel:
                queryset = queryset.filter(elegivel_bonus=(elegivel == 'true'))

            busca = request.GET.get('q')
            if busca:
                busca_digits = re.sub(r'\D', '', busca)
                filtros_busca = (
                    Q(numero_contrato__icontains=busca)
                    | Q(numero_contrato_definitivo__icontains=busca)
                    | Q(cliente_nome__icontains=busca)
                    | Q(ordem_servico__icontains=busca)
                )
                if busca_digits:
                    filtros_busca |= Q(cpf_cliente__icontains=busca_digits)
                queryset = queryset.filter(filtros_busca)

            # Anotações de faturas para calcular elegibilidade dinâmica
            queryset = queryset.annotate(
                total_faturas=Count('faturas', distinct=True),
                faturas_pagas=Count('faturas', filter=Q(faturas__status='PAGO'), distinct=True),
            )

            # Aplica fallback: se não houver faturas cadastradas mas status FPD for Paga, conta como 1/1
            contratos_list = list(queryset)
            for c in contratos_list:
                if c.total_faturas == 0 and c.status_fatura_fpd and str(c.status_fatura_fpd).lower().startswith('paga'):
                    c.total_faturas = 1
                    c.faturas_pagas = 1

            # Mapa da fatura 1 por contrato (prioridade para exibir vencimento/status na lista)
            ids_contratos = [c.id for c in contratos_list]
            faturas1_map = {
                f.contrato_id: f
                for f in FaturaM10.objects.filter(contrato_id__in=ids_contratos, numero_fatura=1)
            }
            status_display_map = dict(FaturaM10.STATUS_CHOICES)

            # Estatísticas
            total = len(contratos_list)
            ativos = len([c for c in contratos_list if c.status_contrato == 'ATIVO'])
            elegiveis = len([
                c for c in contratos_list
                if c.status_contrato == 'ATIVO'
                and not c.teve_downgrade
                and (c.total_faturas or 0) > 0
                and c.total_faturas == c.faturas_pagas
            ])
            valor_total = elegiveis * 150  # R$ 150 por contrato elegível

            taxa_permanencia = round((ativos / total * 100) if total > 0 else 0, 1)

            # Paginação - Limita a 100 registros por página
            page = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 100))
            start = (page - 1) * page_size
            end = start + page_size

            # Contratos para tabela (apenas dados essenciais)
            contratos_data = []
            for c in contratos_list[start:end]:
                is_elegivel = (
                    c.status_contrato == 'ATIVO'
                    and (c.total_faturas or 0) > 0
                    and c.faturas_pagas == c.total_faturas
                    and not c.teve_downgrade
                )
                data_instalacao_fmt = c.data_instalacao.strftime('%d/%m/%Y') if c.data_instalacao else '-'
                f1 = faturas1_map.get(c.id)
                venc_fatura1 = f1.data_vencimento.strftime('%d/%m/%Y') if f1 and f1.data_vencimento else None
                pagto_fatura1 = f1.data_pagamento.strftime('%d/%m/%Y') if f1 and f1.data_pagamento else None
                status_fatura1 = f1.status if f1 else None
                status_fatura1_display = status_display_map.get(status_fatura1, '-') if status_fatura1 else None
                # FPD permanece fallback se não houver fatura 1
                venc_exib = venc_fatura1 or (c.data_vencimento_fpd.strftime('%d/%m/%Y') if c.data_vencimento_fpd else '-')
                pagto_exib = pagto_fatura1 or (c.data_pagamento_fpd.strftime('%d/%m/%Y') if c.data_pagamento_fpd else '-')
                # Sempre mostrar status da fatura 1 se existir, senão FPD
                status_fpd_exib = status_fatura1 or (c.status_fatura_fpd or '-')
                # Aplicar mapeamento em ambos os casos (fatura 1 ou FPD)
                if status_fatura1_display:
                    status_fpd_display = status_fatura1_display
                else:
                    status_fpd_display = _map_status_fpd(c.status_fatura_fpd)
                contratos_data.append({
                    'id': c.id,
                    'numero_contrato': c.numero_contrato,
                    'numero_contrato_definitivo': c.numero_contrato_definitivo or '-',
                    'cliente_nome': c.cliente_nome,
                    'cpf_cliente': c.cpf_cliente,
                    'vendedor_nome': c.vendedor.username if c.vendedor else '-',
                    'data_instalacao': data_instalacao_fmt,
                    'plano_atual': c.plano_atual,
                    'status': c.status_contrato,
                    'status_display': c.get_status_contrato_display(),
                    'faturas_pagas': c.faturas_pagas,
                    'total_faturas': c.total_faturas,
                    'elegivel': is_elegivel,
                    # Dados de fatura 1 (prioritário) ou FPD como fallback
                    'status_fatura_fpd': status_fpd_exib,
                    'status_fatura_fpd_display': status_fpd_display,
                    'data_vencimento_fpd': venc_exib,
                    'data_pagamento_fpd': pagto_exib,
                    'valor_fatura_fpd': float(c.valor_fatura_fpd) if c.valor_fatura_fpd else 0,
                    'nr_dias_atraso_fpd': c.nr_dias_atraso_fpd or 0,
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

        except Exception as e:
            logger.exception('Erro ao gerar dashboard M-10')
            return Response({'error': 'Erro ao carregar dashboard M-10', 'detail': str(e)}, status=500)


class DashboardFPDView(APIView):
    """Dashboard com estatísticas FPD"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            mes_str = request.GET.get('mes')  # formato: 2025-07
            
            # Filtrar faturas número 1 (primeira fatura)
            queryset = FaturaM10.objects.filter(numero_fatura=1)
            
            if mes_str:
                try:
                    ano, mes = mes_str.split('-')
                    queryset = queryset.filter(data_vencimento__year=ano, data_vencimento__month=mes)
                except ValueError:
                    return Response({'error': 'Parâmetro mes inválido. Use YYYY-MM.'}, status=400)
            
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
                data_venc = f.data_vencimento.strftime('%d/%m/%Y') if f.data_vencimento else '-'
                data_pag = f.data_pagamento.strftime('%d/%m/%Y') if f.data_pagamento else None
                faturas_data.append({
                    'id': f.id,
                    'contrato_id': f.contrato.id,
                    'numero_contrato': f.contrato.numero_contrato,
                    'cliente_nome': f.contrato.cliente_nome,
                    'vendedor_nome': f.contrato.vendedor.username if f.contrato.vendedor else '-',
                    'data_vencimento': data_venc,
                    'valor': float(f.valor) if f.valor is not None else 0,
                    'data_pagamento': data_pag,
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

        except Exception as e:
            logger.exception('Erro ao gerar dashboard FPD')
            return Response({'error': 'Erro ao carregar dashboard FPD', 'detail': str(e)}, status=500)


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

                # Calcula safra como string YYYY-MM
                safra_str = venda.data_instalacao.strftime('%Y-%m')

                # Cria novo ContratoM10
                contrato = ContratoM10.objects.create(
                    safra=safra_str,
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

            # Conta total de contratos criados nesta safra (usando CharField safra)
            total_contratos_safra = ContratoM10.objects.filter(safra=safra_str).count()
            
            # Atualiza contagens na Safra M10 (tabela histórica)
            safra.total_instalados = total_contratos_safra
            safra.total_ativos = ContratoM10.objects.filter(safra=safra_str, status_contrato='ATIVO').count()
            safra.save()

            return Response({
                'message': f'Safra {mes_referencia} populada com sucesso!',
                'safra_id': safra.id,
                'contratos_criados': contratos_criados,
                'contratos_duplicados': contratos_duplicados,
                'total_contratos_safra': total_contratos_safra,
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
                data_venc = f.data_vencimento.isoformat() if f.data_vencimento else None
                data_pag = f.data_pagamento.isoformat() if f.data_pagamento else None
                faturas.append({
                    'id': f.id,
                    'numero_fatura': f.numero_fatura,
                    'numero_fatura_operadora': f.numero_fatura_operadora or '',
                    'valor': float(f.valor) if f.valor is not None else 0,
                    'data_vencimento': data_venc,
                    'data_pagamento': data_pag or '',
                    'status': f.status,
                })
            
            return Response({
                'id': contrato.id,
                'numero_contrato': contrato.numero_contrato,
                'cliente_nome': contrato.cliente_nome,
                'cpf_cliente': contrato.cpf_cliente,
                'data_vencimento_fpd': contrato.data_vencimento_fpd.isoformat() if contrato.data_vencimento_fpd else None,
                'data_pagamento_fpd': contrato.data_pagamento_fpd.isoformat() if contrato.data_pagamento_fpd else None,
                'status_fatura_fpd': contrato.status_fatura_fpd or '',
                'valor_fatura_fpd': float(contrato.valor_fatura_fpd) if contrato.valor_fatura_fpd else 0,
                'faturas': faturas,
            })
        except ContratoM10.DoesNotExist:
            return Response({'error': 'Contrato não encontrado'}, status=404)
        except Exception as e:
            logger.exception('Erro ao recuperar contrato M-10')
            return Response({'error': 'Erro ao carregar contrato', 'detail': str(e)}, status=500)


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

        from .models import ImportacaoFPD, LogImportacaoFPD
        from django.utils import timezone
        from django.db import transaction
        
        # Criar log de importação
        log = LogImportacaoFPD.objects.create(
            nome_arquivo=arquivo.name,
            usuario=request.user,
            status='PROCESSANDO'
        )
        
        # Ler arquivo em memória para passar para thread
        arquivo_bytes = arquivo.read()
        arquivo_nome = arquivo.name
        user_id = request.user.id
        
        # Iniciar processamento em thread background
        def processar_fpd_async():
            self._processar_fpd_interno(log.id, arquivo_bytes, arquivo_nome, user_id)
        
        thread = threading.Thread(target=processar_fpd_async, daemon=True)
        thread.start()
        
        # Retornar imediatamente ao cliente
        return Response({
            'success': True,
            'log_id': log.id,
            'message': 'Importação FPD iniciada! O processamento continuará em segundo plano. Atualize a página em alguns minutos para ver o resultado.',
            'status': 'PROCESSANDO',
            'background': True
        })
    
    def _processar_fpd_interno(self, log_id, arquivo_bytes, arquivo_nome, user_id):
        """Processa FPD em background thread"""
        from .models import ImportacaoFPD, LogImportacaoFPD
        from django.utils import timezone
        from django.db import transaction
        from io import BytesIO
        
        # Recuperar log e usuário
        log = LogImportacaoFPD.objects.get(id=log_id)
        User = get_user_model()
        usuario = User.objects.get(id=user_id)
        # Recuperar log e usuário
        log = LogImportacaoFPD.objects.get(id=log_id)
        User = get_user_model()
        usuario = User.objects.get(id=user_id)
        
        inicio = timezone.now()
        os_nao_encontradas = []
        erros_detalhados = []

        try:
            # Criar objeto BytesIO do arquivo
            arquivo_io = BytesIO(arquivo_bytes)
            
            # Lê arquivo Excel/CSV
            # IMPORTANTE: Ler colunas numéricas como STRING para preservar leading zeros
            dtype_spec = {
                'ID_CONTRATO': str,      # Força leitura como texto
                'NR_FATURA': str,        # Força leitura como texto  
                'NR_ORDEM': str,         # Força leitura como texto
            }
            
            if arquivo_nome.endswith('.csv'):
                df = pd.read_csv(arquivo_io, dtype=dtype_spec)
            elif arquivo_nome.endswith('.xlsb'):
                try:
                    df = pd.read_excel(arquivo_io, engine='pyxlsb', dtype=dtype_spec)
                except Exception as e:
                    log.status = 'ERRO'
                    log.mensagem_erro = f'Formato .xlsb não suportado: {str(e)}'
                    log.finalizado_em = timezone.now()
                    log.calcular_duracao()
                    log.save()
                    return
            else:
                df = pd.read_excel(arquivo_io, dtype=dtype_spec)

            # Normalizar nomes de colunas para minúsculas E remover espaços extras
            df.columns = df.columns.str.lower().str.strip().str.replace(' ', '_')
            
            log.total_linhas = len(df)
            log.save(update_fields=['total_linhas'])
            registros_nao_encontrados = 0
            registros_importacoes_fpd = 0
            registros_atualizados = 0
            registros_pulados = 0
            valor_total = 0
            data_importacao_agora = timezone.now()
            
            # Otimização: pre-carregar contratos em memória para evitar N queries
            contratos_dict = {c.ordem_servico: c for c in ContratoM10.objects.all()}
            
            # Otimização: pre-carregar ImportacaoFPD em memória também
            importacoes_dict = {(imp.nr_ordem, imp.nr_fatura): imp for imp in ImportacaoFPD.objects.all()}
            
            # Listas para bulk operations (reduz queries drasticamente)
            faturas_para_criar = []
            faturas_para_atualizar = []
            importacoes_para_criar = []
            importacoes_para_atualizar = []

            with transaction.atomic():  # Garantir atomicidade
                for idx, row in df.iterrows():
                    try:
                        # Busca por O.S (nr_ordem - com coluna normalizada para minúsculas)
                        nr_ordem_raw = row.get('nr_ordem', '')
                        
                        # Converter para string mas MANTER ZEROS à esquerda
                        if pd.isna(nr_ordem_raw):
                            registros_pulados += 1
                            continue
                        
                        nr_ordem = str(nr_ordem_raw).strip()
                        
                        # Se for número, adicionar zero à esquerda para padronizar em 8 dígitos
                        if nr_ordem.replace('.', '').replace('-', '').isdigit():
                            # Remover ".0" se existir (vem do pandas quando lê números do Excel)
                            nr_ordem = nr_ordem.split('.')[0]
                            nr_ordem = nr_ordem.zfill(8)  # Preenche com zeros à esquerda até 8 dígitos
                        
                        if not nr_ordem or nr_ordem == 'nan':
                            registros_pulados += 1
                            continue

                        # Tenta encontrar contrato por ordem_servico (lookup em memória)
                        contrato = contratos_dict.get(nr_ordem)
                        if contrato:
                            
                            # ID_CONTRATO e NR_FATURA já vêm como STRING do pandas (dtype=str)
                            nr_contrato = str(row.get('id_contrato', '')).strip()
                            if nr_contrato and nr_contrato != 'nan':
                                contrato.numero_contrato_definitivo = nr_contrato
                                # Save será feito em bulk ao final
                            
                            # Extrai dados FPD
                            # Já vêm como STRING do pandas, preservando zeros
                            id_contrato = str(row.get('id_contrato', '')).strip()
                            dt_venc = row.get('dt_venc_orig')
                            dt_pgto = row.get('dt_pagamento')
                            status_str = str(row.get('ds_status_fatura', 'NAO_PAGO')).upper()
                            nr_fatura = str(row.get('nr_fatura', '')).strip()
                            vl_fatura = row.get('vl_fatura', 0)
                            nr_dias_atraso = row.get('nr_dias_atraso', 0)
                            
                            # Normalizar status usando mapeamento padronizado
                            status = normalizar_status_fpd(status_str)

                            # Extrair e converter datas - Excel armazena como números serial
                            dt_venc = row.get('dt_venc_orig')
                            if pd.notna(dt_venc):
                                # Se for número, converter de serial Excel
                                if isinstance(dt_venc, (int, float)):
                                    dt_venc_date = (pd.Timestamp("1900-01-01") + pd.Timedelta(days=dt_venc - 2)).date()
                                else:
                                    dt_venc_date = pd.to_datetime(dt_venc).date()
                            else:
                                dt_venc_date = timezone.now().date()

                            dt_pgto = row.get('dt_pagamento')
                            if pd.notna(dt_pgto):
                                # Se for número, converter de serial Excel
                                if isinstance(dt_pgto, (int, float)):
                                    dt_pgto_date = (pd.Timestamp("1900-01-01") + pd.Timedelta(days=dt_pgto - 2)).date()
                                else:
                                    dt_pgto_date = pd.to_datetime(dt_pgto).date()
                            else:
                                dt_pgto_date = None

                            # Se houver data de vencimento, define safra de FPD por mês de vencimento
                            if dt_venc_date:
                                safra_fpd_mes = dt_venc_date.replace(day=1)
                                safra_fpd, _ = SafraM10.objects.get_or_create(
                                    mes_referencia=safra_fpd_mes,
                                    defaults={'total_instalados': 0, 'total_ativos': 0}
                                )

                            # Preparar fatura para bulk update/create
                            vl_fatura_float = float(vl_fatura) if pd.notna(vl_fatura) else 0
                            nr_dias_atraso_int = int(nr_dias_atraso) if pd.notna(nr_dias_atraso) else 0
                        
                            # Verificar se fatura já existe (lookup em memória via contrato)
                            fatura_existente = None
                            for f in contrato.faturas.all():
                                if f.numero_fatura == 1:
                                    fatura_existente = f
                                    break
                            
                            if fatura_existente:
                                fatura_existente.numero_fatura_operadora = nr_fatura
                                fatura_existente.valor = vl_fatura_float
                                fatura_existente.data_vencimento = dt_venc_date
                                fatura_existente.data_pagamento = dt_pgto_date
                                fatura_existente.dias_atraso = nr_dias_atraso_int
                                fatura_existente.status = status
                                fatura_existente.id_contrato_fpd = id_contrato
                                fatura_existente.dt_pagamento_fpd = dt_pgto_date
                                fatura_existente.ds_status_fatura_fpd = status_str
                                fatura_existente.data_importacao_fpd = data_importacao_agora
                                faturas_para_atualizar.append(fatura_existente)
                            else:
                                faturas_para_criar.append(FaturaM10(
                                    contrato=contrato,
                                    numero_fatura=1,
                                    numero_fatura_operadora=nr_fatura,
                                    valor=vl_fatura_float,
                                    data_vencimento=dt_venc_date,
                                    data_pagamento=dt_pgto_date,
                                    dias_atraso=nr_dias_atraso_int,
                                    status=status,
                                    id_contrato_fpd=id_contrato,
                                    dt_pagamento_fpd=dt_pgto_date,
                                    ds_status_fatura_fpd=status_str,
                                    data_importacao_fpd=data_importacao_agora
                                ))

                            # Preparar ImportacaoFPD para bulk
                            chave = (nr_ordem, nr_fatura)
                            importacao_existente = importacoes_dict.get(chave)
                            
                            if importacao_existente:
                                importacao_existente.id_contrato = id_contrato
                                importacao_existente.dt_venc_orig = dt_venc_date
                                importacao_existente.dt_pagamento = dt_pgto_date
                                importacao_existente.nr_dias_atraso = nr_dias_atraso_int
                                importacao_existente.ds_status_fatura = status_str
                                importacao_existente.vl_fatura = vl_fatura_float
                                importacao_existente.contrato_m10 = contrato
                                importacoes_para_atualizar.append(importacao_existente)
                                registros_atualizados += 1
                            else:
                                importacoes_para_criar.append(ImportacaoFPD(
                                    nr_ordem=nr_ordem,
                                    nr_fatura=nr_fatura,
                                    id_contrato=id_contrato,
                                    dt_venc_orig=dt_venc_date,
                                    dt_pagamento=dt_pgto_date,
                                    nr_dias_atraso=nr_dias_atraso_int,
                                    ds_status_fatura=status_str,
                                    vl_fatura=vl_fatura_float,
                                    contrato_m10=contrato
                                ))
                                registros_importacoes_fpd += 1
                            
                            valor_total += vl_fatura_float
                        else:  # Contrato não encontrado
                            # Se não encontrou contrato M10, salva mesmo assim sem vínculo
                            # O usuário pode fazer matching depois
                            
                            # Extrai dados FPD mesmo sem contrato
                            # Já vêm como STRING do pandas, preservando zeros
                            id_contrato = str(row.get('id_contrato', '')).strip()
                            dt_venc = row.get('dt_venc_orig')
                            dt_pgto = row.get('dt_pagamento')
                            status_str = str(row.get('ds_status_fatura', 'NAO_PAGO')).upper()
                            nr_fatura = str(row.get('nr_fatura', '')).strip()
                            vl_fatura = row.get('vl_fatura', 0)
                            nr_dias_atraso = row.get('nr_dias_atraso', 0)
                            
                            # Normalizar status usando mapeamento padronizado
                            status = normalizar_status_fpd(status_str)

                            # Extrair e converter datas - Excel armazena como números serial
                            if pd.notna(dt_venc):
                                # Se for número, converter de serial Excel
                                if isinstance(dt_venc, (int, float)):
                                    dt_venc_date = (pd.Timestamp("1900-01-01") + pd.Timedelta(days=dt_venc - 2)).date()
                                else:
                                    dt_venc_date = pd.to_datetime(dt_venc).date()
                            else:
                                dt_venc_date = timezone.now().date()

                            if pd.notna(dt_pgto):
                                # Se for número, converter de serial Excel
                                if isinstance(dt_pgto, (int, float)):
                                    dt_pgto_date = (pd.Timestamp("1900-01-01") + pd.Timedelta(days=dt_pgto - 2)).date()
                                else:
                                    dt_pgto_date = pd.to_datetime(dt_pgto).date()
                            else:
                                dt_pgto_date = None

                            # Converte valores
                            vl_fatura_float = float(vl_fatura) if pd.notna(vl_fatura) else 0
                            nr_dias_atraso_int = int(nr_dias_atraso) if pd.notna(nr_dias_atraso) else 0
                        
                            # Preparar ImportacaoFPD sem contrato para bulk
                            chave = (nr_ordem, nr_fatura)
                            importacao_sem_contrato = importacoes_dict.get(chave)
                            
                            if importacao_sem_contrato:
                                importacao_sem_contrato.id_contrato = id_contrato
                                importacao_sem_contrato.dt_venc_orig = dt_venc_date
                                importacao_sem_contrato.dt_pagamento = dt_pgto_date
                                importacao_sem_contrato.nr_dias_atraso = nr_dias_atraso_int
                                importacao_sem_contrato.ds_status_fatura = status_str
                                importacao_sem_contrato.vl_fatura = vl_fatura_float
                                importacao_sem_contrato.contrato_m10 = None
                                importacoes_para_atualizar.append(importacao_sem_contrato)
                                registros_nao_encontrados += 1
                            else:
                                importacoes_para_criar.append(ImportacaoFPD(
                                    nr_ordem=nr_ordem,
                                    nr_fatura=nr_fatura,
                                    id_contrato=id_contrato,
                                    dt_venc_orig=dt_venc_date,
                                    dt_pagamento=dt_pgto_date,
                                    nr_dias_atraso=nr_dias_atraso_int,
                                    ds_status_fatura=status_str,
                                    vl_fatura=vl_fatura_float,
                                    contrato_m10=None
                                ))
                                registros_importacoes_fpd += 1
                            
                            valor_total += vl_fatura_float
                            if len(os_nao_encontradas) < 20:
                                os_nao_encontradas.append(f"{nr_ordem} (sem contrato)")
                            continue
                    
                    except Exception as e:
                        erros_detalhados.append(f"Linha {idx+2}: {str(e)}")
                        if len(erros_detalhados) <= 10:
                            log.detalhes_json['erros'] = erros_detalhados
                
                # Executar bulk operations (reduz milhares de queries para dezenas)
                if faturas_para_criar:
                    FaturaM10.objects.bulk_create(faturas_para_criar, batch_size=500)
                if faturas_para_atualizar:
                    FaturaM10.objects.bulk_update(faturas_para_atualizar, [
                        'numero_fatura_operadora', 'valor', 'data_vencimento',
                        'data_pagamento', 'dias_atraso', 'status', 'id_contrato_fpd',
                        'dt_pagamento_fpd', 'ds_status_fatura_fpd', 'data_importacao_fpd'
                    ], batch_size=500)
                
                if importacoes_para_criar:
                    ImportacaoFPD.objects.bulk_create(importacoes_para_criar, batch_size=500)
                if importacoes_para_atualizar:
                    ImportacaoFPD.objects.bulk_update(importacoes_para_atualizar, [
                        'id_contrato', 'dt_venc_orig', 'dt_pagamento', 'nr_dias_atraso',
                        'ds_status_fatura', 'vl_fatura', 'contrato_m10'
                    ], batch_size=500)
                
                # Salvar contratos atualizados em bulk
                contratos_para_atualizar = [c for c in contratos_dict.values() if c.numero_contrato_definitivo]
                if contratos_para_atualizar:
                    ContratoM10.objects.bulk_update(contratos_para_atualizar, ['numero_contrato_definitivo'], batch_size=500)

            # Finalizar log
            log.finalizado_em = timezone.now()
            log.calcular_duracao()
            # Total processadas = novos criados + atualizados + sem contrato criados/atualizados
            log.total_processadas = registros_importacoes_fpd + registros_atualizados
            log.total_erros = len(erros_detalhados)
            log.total_contratos_nao_encontrados = registros_nao_encontrados
            log.total_valor_importado = valor_total
            log.exemplos_nao_encontrados = ', '.join(os_nao_encontradas[:10]) if os_nao_encontradas else None
            
            # Debug log
            print(f"DEBUG Final: Pulados={registros_pulados} | Criados={registros_importacoes_fpd} | Atualizados={registros_atualizados} | Sem M10={registros_nao_encontrados}")
            
            if registros_pulados == log.total_linhas:
                # TODAS as linhas foram puladas!
                log.status = 'ERRO'
                log.mensagem_erro = f'Todas as {registros_pulados} linhas foram puladas (NR_ORDEM vazio ou inválido). Verificar formato do arquivo.'
            elif registros_nao_encontrados > 0 and registros_atualizados == 0:
                # Todos os registros foram salvos sem contrato (sem vincular ao M10)
                log.status = 'PARCIAL'
                log.mensagem_erro = f'{registros_nao_encontrados} registros FPD importados sem vínculo M10 (O.S não encontrados na base ContratoM10). Você pode fazer matching depois.'
            elif registros_nao_encontrados > 0:
                # Alguns registros com contrato, alguns sem
                log.status = 'PARCIAL'
                log.mensagem_erro = f'{registros_atualizados} registros vinculados a contratos M10, {registros_nao_encontrados} importados sem vínculo (O.S não encontradas). Pode fazer matching depois.'
            else:
                log.status = 'SUCESSO'
            
            log.save()

            # FIM DO PROCESSAMENTO - retorno já foi enviado antes via HTTP
            
        except Exception as e:
            log.status = 'ERRO'
            log.mensagem_erro = str(e)
            log.finalizado_em = timezone.now()
            log.calcular_duracao()
            log.save()


class LogsImportacaoFPDView(APIView):
    """Lista logs de importações FPD"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        from .models import LogImportacaoFPD
        
        # Buscar últimos 20 logs do usuário (se não for admin, só seus próprios)
        if is_member(request.user, ['Admin', 'Diretoria']):
            logs = LogImportacaoFPD.objects.all().order_by('-iniciado_em')[:20]
        else:
            logs = LogImportacaoFPD.objects.filter(usuario=request.user).order_by('-iniciado_em')[:20]
        
        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'nome_arquivo': log.nome_arquivo,
                'status': log.status,
                'status_display': log.get_status_display(),
                'iniciado_em': log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S') if log.iniciado_em else None,
                'finalizado_em': log.finalizado_em.strftime('%d/%m/%Y %H:%M:%S') if log.finalizado_em else None,
                'duracao_segundos': log.duracao_segundos,
                'total_linhas': log.total_linhas,
                'total_processadas': log.total_processadas,
                'total_contratos_nao_encontrados': log.total_contratos_nao_encontrados,
                'total_valor_importado': str(log.total_valor_importado) if log.total_valor_importado else '0.00',
                'mensagem_erro': log.mensagem_erro,
                'usuario_nome': log.usuario.get_full_name() if log.usuario else 'Sistema',
                'exemplos_nao_encontrados': log.exemplos_nao_encontrados,
            })
        
        return Response({
            'success': True,
            'logs': logs_data
        })


class LogsImportacaoOSABView(APIView):
    """Lista logs de importações OSAB"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        from .models import LogImportacaoOSAB
        
        # Buscar últimos 20 logs (todos os usuários podem ver todos os logs OSAB)
        if is_member(request.user, ['Admin', 'Diretoria']):
            logs = LogImportacaoOSAB.objects.all().order_by('-iniciado_em')[:20]
        else:
            logs = LogImportacaoOSAB.objects.filter(usuario=request.user).order_by('-iniciado_em')[:20]
        
        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'nome_arquivo': log.nome_arquivo,
                'status': log.status,
                'status_display': log.get_status_display(),
                'iniciado_em': log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S') if log.iniciado_em else None,
                'finalizado_em': log.finalizado_em.strftime('%d/%m/%Y %H:%M:%S') if log.finalizado_em else None,
                'duracao_segundos': log.duracao_segundos,
                'total_registros': log.total_registros,
                'total_processadas': log.total_processadas,
                'criados': log.criados,
                'atualizados': log.atualizados,
                'vendas_encontradas': log.vendas_encontradas,
                'ja_corretos': log.ja_corretos,
                'erros_count': log.erros_count,
                'mensagem': log.mensagem,
                'mensagem_erro': log.mensagem_erro,
                'usuario_nome': log.usuario.get_full_name() if log.usuario else 'Sistema',
                'enviar_whatsapp': log.enviar_whatsapp,
                'download_url': f"/api/crm/logs-osab/{log.id}/relatorio/",
            })
        
        return Response({
            'success': True,
            'logs': logs_data
        })


class DownloadRelatorioOSABView(APIView):
    """Gera relatório Excel da importação OSAB"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, log_id):
        from io import BytesIO
        from django.http import HttpResponse
        from crm_app.models import LogImportacaoOSAB, ImportacaoOsab

        log = LogImportacaoOSAB.objects.filter(id=log_id).first()
        if not log:
            return Response({'error': 'Log não encontrado.'}, status=404)

        if not is_member(request.user, ['Admin', 'Diretoria']) and log.usuario != request.user:
            return Response({'error': 'Sem permissão para acessar este relatório.'}, status=403)

        report = log.detalhes_json or {}
        logs = report.get('logs_detalhados') or []
        if not logs:
            return Response({'error': 'Relatório ainda não disponível.'}, status=404)

        df = pd.DataFrame(logs)
        colunas = [
            'linha', 'pedido', 'status_osab', 'dt_ref_planilha', 'dt_ref_crm',
            'consta_osab', 'consta_crm', 'resultado_osab', 'resultado_crm', 'detalhe'
        ]
        for col in colunas:
            if col not in df.columns:
                df[col] = ''
        df = df[colunas]

        resumo = [
            {'metrica': 'Total registros planilha', 'valor': report.get('total_registros', len(df))},
            {'metrica': 'Vendas encontradas CRM', 'valor': report.get('vendas_encontradas', 0)},
            {'metrica': 'Atualizados CRM', 'valor': report.get('atualizados', 0)},
            {'metrica': 'Criados OSAB', 'valor': report.get('criados', 0)},
            {'metrica': 'Ignorados DT_REF', 'valor': report.get('ignorados_dt_ref', 0)},
            {'metrica': 'Erros', 'valor': len(report.get('erros', []))},
        ]
        df_resumo = pd.DataFrame(resumo)
        df_contagem_osab = df['resultado_osab'].value_counts().reset_index()
        df_contagem_osab.columns = ['resultado_osab', 'quantidade']
        df_contagem_crm = df['resultado_crm'].value_counts().reset_index()
        df_contagem_crm.columns = ['resultado_crm', 'quantidade']

        df_planilha_nao_crm = df[df['resultado_crm'] == 'NAO_ENCONTRADO_CRM'].copy()

        pedidos_planilha = set(df['pedido'].dropna().astype(str))
        qs_crm = ImportacaoOsab.objects.exclude(documento__in=pedidos_planilha).values(
            'documento', 'dt_ref', 'uf', 'municipio', 'produto'
        )
        df_crm_nao_planilha = pd.DataFrame(list(qs_crm))
        if df_crm_nao_planilha.empty:
            df_crm_nao_planilha = pd.DataFrame(columns=['documento', 'dt_ref', 'uf', 'municipio', 'produto'])

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_resumo.to_excel(writer, sheet_name='Resumo', index=False)
            df_contagem_osab.to_excel(writer, sheet_name='Resumo_OSAB', index=False)
            df_contagem_crm.to_excel(writer, sheet_name='Resumo_CRM', index=False)
            df.to_excel(writer, sheet_name='Planilha_vs_CRM', index=False)
            df_planilha_nao_crm.to_excel(writer, sheet_name='Planilha_nao_CRM', index=False)
            df_crm_nao_planilha.to_excel(writer, sheet_name='CRM_nao_Planilha', index=False)

        output.seek(0)
        filename = f"Relatorio_OSAB_{log.id}_{log.nome_arquivo}".replace(' ', '_')
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
        return response


class CancelarImportacaoOSABView(APIView):
    """Cancela uma importação OSAB em processamento."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, log_id):
        from django.utils import timezone
        from crm_app.models import LogImportacaoOSAB

        log = LogImportacaoOSAB.objects.filter(id=log_id).first()
        if not log:
            return Response({'error': 'Log não encontrado.'}, status=404)

        if not is_member(request.user, ['Admin', 'Diretoria']) and log.usuario != request.user:
            return Response({'error': 'Sem permissão para cancelar este log.'}, status=403)

        if log.status != 'PROCESSANDO':
            return Response({'error': 'A importação já foi finalizada.'}, status=400)

        LogImportacaoOSAB.objects.filter(id=log_id).update(
            status='ERRO',
            mensagem_erro='Cancelado manualmente pelo usuário.',
            finalizado_em=timezone.now()
        )
        log.calcular_duracao()

        return Response({'success': True, 'message': 'Importação cancelada.'})


class LogsImportacaoDFVView(APIView):
    """Lista logs de importações DFV"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        from .models import LogImportacaoDFV
        
        # Buscar últimos 20 logs
        if is_member(request.user, ['Admin', 'Diretoria']):
            logs = LogImportacaoDFV.objects.all().order_by('-iniciado_em')[:20]
        else:
            logs = LogImportacaoDFV.objects.filter(usuario=request.user).order_by('-iniciado_em')[:20]
        
        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'nome_arquivo': log.nome_arquivo,
                'status': log.status,
                'iniciado_em': log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S') if log.iniciado_em else None,
                'finalizado_em': log.finalizado_em.strftime('%d/%m/%Y %H:%M:%S') if log.finalizado_em else None,
                'duracao_segundos': log.duracao_segundos,
                'total_registros': log.total_registros,
                'total_processadas': log.total_processadas,
                'sucesso': log.sucesso,
                'erros': log.erros,
                'total_valor_importado': str(log.total_valor_importado) if log.total_valor_importado else '0.00',
                'mensagem': log.mensagem,
                'mensagem_erro': log.mensagem_erro,
                'usuario_nome': log.usuario.get_full_name() if log.usuario else 'Sistema',
            })
        
        return Response({
            'success': True,
            'logs': logs_data
        })


class LogsImportacaoLegadoView(APIView):
    """Lista logs de importações Legado"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        from .models import LogImportacaoLegado
        
        # Buscar últimos 20 logs
        if is_member(request.user, ['Admin', 'Diretoria']):
            logs = LogImportacaoLegado.objects.all().order_by('-iniciado_em')[:20]
        else:
            logs = LogImportacaoLegado.objects.filter(usuario=request.user).order_by('-iniciado_em')[:20]
        
        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'nome_arquivo': log.nome_arquivo,
                'status': log.status,
                'status_display': log.get_status_display(),
                'iniciado_em': log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S') if log.iniciado_em else None,
                'finalizado_em': log.finalizado_em.strftime('%d/%m/%Y %H:%M:%S') if log.finalizado_em else None,
                'duracao_segundos': log.duracao_segundos,
                'total_linhas': log.total_linhas,
                'total_processadas': log.total_processadas,
                'vendas_criadas': log.vendas_criadas,
                'vendas_atualizadas': log.vendas_atualizadas,
                'clientes_criados': log.clientes_criados,
                'erros_count': log.erros_count,
                'mensagem': log.mensagem,
                'mensagem_erro': log.mensagem_erro,
                'usuario_nome': log.usuario.get_full_name() if log.usuario else 'Sistema',
            })
        
        return Response({
            'success': True,
            'logs': logs_data
        })


class LogsImportacaoAgendamentoView(APIView):
    """Lista logs de importações Agendamento"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        from .models import LogImportacaoAgendamento
        
        # Buscar últimos 20 logs
        if is_member(request.user, ['Admin', 'Diretoria']):
            logs = LogImportacaoAgendamento.objects.all().order_by('-iniciado_em')[:20]
        else:
            logs = LogImportacaoAgendamento.objects.filter(usuario=request.user).order_by('-iniciado_em')[:20]
        
        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'nome_arquivo': log.nome_arquivo,
                'status': log.status,
                'status_display': log.get_status_display(),
                'iniciado_em': log.iniciado_em.strftime('%d/%m/%Y %H:%M:%S') if log.iniciado_em else None,
                'finalizado_em': log.finalizado_em.strftime('%d/%m/%Y %H:%M:%S') if log.finalizado_em else None,
                'duracao_segundos': log.duracao_segundos,
                'total_linhas': log.total_linhas,
                'total_processadas': log.total_processadas,
                'agendamentos_criados': log.agendamentos_criados,
                'agendamentos_atualizados': log.agendamentos_atualizados,
                'nao_encontrados': log.nao_encontrados,
                'erros_count': log.erros_count,
                'mensagem': log.mensagem,
                'mensagem_erro': log.mensagem_erro,
                'usuario_nome': log.usuario.get_full_name() if log.usuario else 'Sistema',
            })
        
        return Response({
            'success': True,
            'logs': logs_data
        })


class ImportarChurnView(APIView):
    """Importa base de churn (cancelamentos) e faz crossover com ContratoM10 por O.S"""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        from .models import ImportacaoChurn, ContratoM10, LogImportacaoChurn
        
        if not is_member(request.user, ['Admin', 'BackOffice', 'Diretoria']):
            return Response({'error': 'Sem permissão'}, status=403)

        arquivo = request.FILES.get('file')
        if not arquivo:
            return Response({'error': 'Arquivo não enviado'}, status=400)

        # Criar log de importação
        log = LogImportacaoChurn.objects.create(
            nome_arquivo=arquivo.name,
            tamanho_arquivo=getattr(arquivo, 'size', 0) or 0,
            usuario=request.user,
            status='PROCESSANDO'
        )
        inicio = datetime.now()

        try:
            if arquivo.name.endswith('.csv'):
                df = pd.read_csv(arquivo, dtype={'NR_ORDEM': str})
            elif arquivo.name.endswith('.xlsb'):
                try:
                    df = pd.read_excel(arquivo, engine='pyxlsb', dtype={'NR_ORDEM': str})
                except Exception:
                    log.status = 'ERRO'
                    log.mensagem_erro = 'Formato .xlsb não suportado. Use .xlsx, .xls ou .csv'
                    log.finalizado_em = datetime.now()
                    log.save()
                    return Response({
                        'error': 'Formato .xlsb não suportado. Use .xlsx, .xls ou .csv'
                    }, status=400)
            else:
                df = pd.read_excel(arquivo, dtype={'NR_ORDEM': str})

            # Normalizar nomes das colunas
            df.columns = df.columns.str.strip().str.upper()
            
            log.total_linhas = len(df)
            log.save()

            cancelados = 0
            salvos_churn = 0
            reativados = 0
            nao_encontrados = 0
            erros = 0
            
            # Coletar todas as O.S que aparecem no CHURN
            ordens_no_churn = set()

            for _, row in df.iterrows():
                try:
                    # Busca por O.S (NR_ORDEM na planilha de churn)
                    nr_ordem_raw = row.get('NR_ORDEM', '')
                    if pd.isna(nr_ordem_raw) or str(nr_ordem_raw).strip() == '':
                        continue
                    
                    nr_ordem = str(nr_ordem_raw).strip().zfill(8)  # Padronizar com 8 dígitos
                    ordens_no_churn.add(nr_ordem)

                    # Salvar registro na ImportacaoChurn
                    try:
                        ImportacaoChurn.objects.update_or_create(
                            numero_pedido=str(row.get('NUMERO_PEDIDO', '')) if pd.notna(row.get('NUMERO_PEDIDO')) else None,
                            defaults={
                                'nr_ordem': nr_ordem,
                                'uf': str(row.get('UF', ''))[:2] if pd.notna(row.get('UF')) else None,
                                'produto': str(row.get('PRODUTO', '')) if pd.notna(row.get('PRODUTO')) else None,
                                'matricula_vendedor': str(row.get('MATRICULA_VENDEDOR', '')) if pd.notna(row.get('MATRICULA_VENDEDOR')) else None,
                                'gv': str(row.get('GV', '')) if pd.notna(row.get('GV')) else None,
                                'sap_principal_fim': str(row.get('SAP_PRINCIPAL_FIM', '')) if pd.notna(row.get('SAP_PRINCIPAL_FIM')) else None,
                                'gestao': str(row.get('GESTAO', '')) if pd.notna(row.get('GESTAO')) else None,
                                'st_regional': str(row.get('ST_REGIONAL', '')) if pd.notna(row.get('ST_REGIONAL')) else None,
                                'gc': str(row.get('GC', '')) if pd.notna(row.get('GC')) else None,
                                'dt_gross': pd.to_datetime(row.get('DT_GROSS')).date() if pd.notna(row.get('DT_GROSS')) else None,
                                'anomes_gross': str(row.get('ANOMES_GROSS', '')) if pd.notna(row.get('ANOMES_GROSS')) else None,
                                'dt_retirada': pd.to_datetime(row.get('DT_RETIRADA')).date() if pd.notna(row.get('DT_RETIRADA')) else None,
                                'anomes_retirada': str(row.get('ANOMES_RETIRADA', '')) if pd.notna(row.get('ANOMES_RETIRADA')) else None,
                                'grupo_unidade': str(row.get('GRUPO_UNIDADE', '')) if pd.notna(row.get('GRUPO_UNIDADE')) else None,
                                'codigo_sap': str(row.get('CODIGO_SAP', '')) if pd.notna(row.get('CODIGO_SAP')) else None,
                                'municipio': str(row.get('MUNICIPIO', '')) if pd.notna(row.get('MUNICIPIO')) else None,
                                'tipo_retirada': str(row.get('TIPO_RETIRADA', '')) if pd.notna(row.get('TIPO_RETIRADA')) else None,
                                'motivo_retirada': str(row.get('MOTIVO_RETIRADA', '')) if pd.notna(row.get('MOTIVO_RETIRADA')) else None,
                                'submotivo_retirada': str(row.get('SUBMOTIVO_RETIRADA', '')) if pd.notna(row.get('SUBMOTIVO_RETIRADA')) else None,
                                'classificacao': str(row.get('CLASSIFICACAO', '')) if pd.notna(row.get('CLASSIFICACAO')) else None,
                                'desc_apelido': str(row.get('DESC_APELIDO', '')) if pd.notna(row.get('DESC_APELIDO')) else None,
                            }
                        )
                        salvos_churn += 1
                    except Exception as e:
                        erros += 1
                        print(f"Erro ao salvar ImportacaoChurn: {e}")

                    # Atualizar status do contrato M10 para CANCELADO
                    try:
                        contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
                        
                        # Marca como cancelado (apareceu no CHURN)
                        if contrato.status_contrato != 'CANCELADO':
                            contrato.status_contrato = 'CANCELADO'
                            contrato.data_cancelamento = pd.to_datetime(row.get('DT_RETIRADA')).date() if pd.notna(row.get('DT_RETIRADA')) else datetime.now().date()
                            contrato.motivo_cancelamento = str(row.get('MOTIVO_RETIRADA', '')) if pd.notna(row.get('MOTIVO_RETIRADA')) else 'CHURN'
                            contrato.elegivel_bonus = False
                            contrato.save()
                            cancelados += 1
                        
                    except ContratoM10.DoesNotExist:
                        nao_encontrados += 1
                
                except Exception as e:
                    erros += 1
                    continue

            # IMPORTANTE: Marcar como ATIVO os contratos que NÃO aparecem no CHURN
            contratos_ativos = ContratoM10.objects.exclude(ordem_servico__in=ordens_no_churn).exclude(status_contrato='ATIVO')
            reativados = contratos_ativos.update(status_contrato='ATIVO', data_cancelamento=None)

            # Atualizar log
            fim = datetime.now()
            log.finalizado_em = fim
            log.duracao_segundos = int((fim - inicio).total_seconds())
            log.total_processadas = salvos_churn
            log.total_erros = erros
            log.total_contratos_cancelados = cancelados
            log.total_contratos_reativados = reativados
            log.total_nao_encontrados = nao_encontrados
            log.status = 'PARCIAL' if (cancelados > 0 and nao_encontrados > 0) else 'SUCESSO'
            log.detalhes_json = {
                'ordens_unicas': len(ordens_no_churn),
                'cancelados': cancelados,
                'reativados': reativados,
                'nao_encontrados': nao_encontrados,
            }
            log.save()

            return Response({
                'message': f'Base CHURN processada! {cancelados} contratos cancelados, {reativados} contratos reativados, {salvos_churn} registros salvos.',
                'cancelados': cancelados,
                'reativados': reativados,
                'salvos_churn': salvos_churn,
                'nao_encontrados': nao_encontrados,
                'log_id': log.id,
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            
            # Atualizar log com erro
            log.status = 'ERRO'
            log.mensagem_erro = str(e)
            log.finalizado_em = datetime.now()
            log.save()
            
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
        headers = ['O.S/PEDIDO', 'Nº Contrato', 'Cliente', 'Vendedor', 'Instalação', 'Plano', 'Status', 'Faturas Pagas', 'Elegível', 'Bônus']
        ws.append(headers)

        # Estilo cabeçalho
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            cell.alignment = Alignment(horizontal="center")

        # Dados
        contratos = (
            ContratoM10.objects.all()
            .select_related('vendedor')
            .annotate(
                total_faturas=Count('faturas', distinct=True),
                faturas_pagas=Count('faturas', filter=Q(faturas__status='PAGO'), distinct=True),
            )
        )
        for c in contratos:
            total_faturas = c.total_faturas
            faturas_pagas = c.faturas_pagas
            if total_faturas == 0 and c.status_fatura_fpd and str(c.status_fatura_fpd).lower().startswith('paga'):
                total_faturas = 1
                faturas_pagas = 1
            elegivel = (
                c.status_contrato == 'ATIVO'
                and not c.teve_downgrade
                and (total_faturas or 0) > 0
                and faturas_pagas == total_faturas
            )
            bonus = 150 if elegivel else 0
            ws.append([
                c.numero_contrato,
                c.numero_contrato_definitivo or '-',
                c.cliente_nome,
                c.vendedor.username if c.vendedor else '-',
                c.data_instalacao.strftime('%d/%m/%Y'),
                c.plano_atual,
                c.get_status_contrato_display(),
                f"{faturas_pagas}/{total_faturas}",
                'Sim' if elegivel else 'Não',
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


class DadosFPDView(APIView):
    """Retorna dados FPD de um contrato por O.S (Ordem de Serviço)"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        """GET /api/bonus-m10/dados-fpd/?os=NR_ORDEM"""
        nr_ordem = request.query_params.get('os')
        if not nr_ordem:
            return Response({'error': 'Parâmetro os (Ordem de Serviço) é obrigatório'}, status=400)
        
        try:
            contrato = ContratoM10.objects.get(ordem_servico=nr_ordem)
            
            # Busca registros de importação FPD para esta O.S
            from .models import ImportacaoFPD
            dados_fpd = ImportacaoFPD.objects.filter(nr_ordem=nr_ordem).order_by('-importada_em')
            
            # Dados do contrato
            resultado = {
                'contrato': {
                    'numero_contrato': contrato.numero_contrato,
                    'numero_contrato_definitivo': contrato.numero_contrato_definitivo,
                    'cliente_nome': contrato.cliente_nome,
                    'cpf_cliente': contrato.cpf_cliente,
                    'ordem_servico': contrato.ordem_servico,
                    'vendedor': contrato.vendedor.get_full_name() if contrato.vendedor else None,
                    'data_instalacao': contrato.data_instalacao.isoformat(),
                    'status_contrato': contrato.get_status_contrato_display(),
                },
                'importacoes_fpd': []
            }
            
            # Adiciona dados de cada importação FPD
            for imp in dados_fpd:
                resultado['importacoes_fpd'].append({
                    'id_contrato': imp.id_contrato,
                    'nr_fatura': imp.nr_fatura,
                    'dt_venc_orig': imp.dt_venc_orig.isoformat(),
                    'dt_pagamento': imp.dt_pagamento.isoformat() if imp.dt_pagamento else None,
                    'ds_status_fatura': imp.ds_status_fatura,
                    'vl_fatura': str(imp.vl_fatura),
                    'nr_dias_atraso': imp.nr_dias_atraso,
                    'importada_em': imp.importada_em.isoformat(),
                })
            
            # Dados das faturas M10 vinculadas
            resultado['faturas_m10'] = []
            for fatura in contrato.faturas.all():
                resultado['faturas_m10'].append({
                    'numero_fatura': fatura.numero_fatura,
                    'id_contrato_fpd': fatura.id_contrato_fpd,
                    'dt_pagamento_fpd': fatura.dt_pagamento_fpd.isoformat() if fatura.dt_pagamento_fpd else None,
                    'ds_status_fatura_fpd': fatura.ds_status_fatura_fpd,
                    'status': fatura.status,
                    'valor': str(fatura.valor),
                    'data_vencimento': fatura.data_vencimento.isoformat(),
                    'data_pagamento': fatura.data_pagamento.isoformat() if fatura.data_pagamento else None,
                    'data_importacao_fpd': fatura.data_importacao_fpd.isoformat() if fatura.data_importacao_fpd else None,
                })
            
            return Response(resultado)
            
        except ContratoM10.DoesNotExist:
            return Response({'error': f'Contrato com O.S {nr_ordem} não encontrado'}, status=404)


class BuscarOSFPDView(APIView):
    """Busca por O.S específica na ImportacaoFPD"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        """GET /api/bonus-m10/buscar-os-fpd/?os=07309961"""
        nr_ordem = request.query_params.get('os', '').strip()
        
        if not nr_ordem:
            return Response({'error': 'Parâmetro os é obrigatório'}, status=400)
        
        from .models import ImportacaoFPD
        
        # Buscar registros com a O.S
        registros = ImportacaoFPD.objects.filter(nr_ordem__icontains=nr_ordem).order_by('-importada_em')
        
        dados = []
        valor_total = 0
        
        for imp in registros:
            valor_total += float(imp.vl_fatura or 0)
            dados.append({
                'id': imp.id,
                'nr_ordem': imp.nr_ordem,
                'nr_fatura': imp.nr_fatura,
                'dt_venc_orig': imp.dt_venc_orig.isoformat(),
                'dt_pagamento': imp.dt_pagamento.isoformat() if imp.dt_pagamento else None,
                'ds_status_fatura': imp.ds_status_fatura,
                'vl_fatura': str(imp.vl_fatura),
                'nr_dias_atraso': imp.nr_dias_atraso,
                'contrato_m10': f"{imp.contrato_m10.numero_contrato} - {imp.contrato_m10.cliente_nome}" if imp.contrato_m10 else None,
                'importada_em': imp.importada_em.isoformat(),
            })
        
        return Response({
            'total': len(dados),
            'valor_total': str(valor_total),
            'os': nr_ordem,
            'registros': dados,
        })


class ListarImportacoesFPDView(APIView):
    """Lista todas as importações FPD com filtros"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        """GET /api/bonus-m10/importacoes-fpd/?status=PAGO&mes=2025-01"""
        from .models import ImportacaoFPD
        
        queryset = ImportacaoFPD.objects.all()
        
        # Filtro por status
        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(ds_status_fatura__icontains=status)
        
        # Filtro por mês de vencimento
        mes = request.query_params.get('mes')
        if mes:
            try:
                data_inicio = datetime.strptime(mes, '%Y-%m')
                data_fim = (data_inicio.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                queryset = queryset.filter(dt_venc_orig__range=[data_inicio, data_fim])
            except ValueError:
                return Response({'error': 'Formato de mês inválido (use YYYY-MM)'}, status=400)
        
        # Estatísticas
        total_faturas = queryset.count()
        total_valor = queryset.aggregate(Sum('vl_fatura'))['vl_fatura__sum'] or 0
        
        # Paginação
        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 100))
        start = (page - 1) * limit
        end = start + limit
        
        dados = []
        for imp in queryset.order_by('-importada_em')[start:end]:
            dados.append({
                'nr_ordem': imp.nr_ordem,
                'id_contrato': imp.id_contrato,
                'nr_fatura': imp.nr_fatura,
                'dt_venc_orig': imp.dt_venc_orig.isoformat(),
                'dt_pagamento': imp.dt_pagamento.isoformat() if imp.dt_pagamento else None,
                'ds_status_fatura': imp.ds_status_fatura,
                'vl_fatura': str(imp.vl_fatura),
                'nr_dias_atraso': imp.nr_dias_atraso,
                'contrato_m10': f"{imp.contrato_m10.numero_contrato} - {imp.contrato_m10.cliente_nome}" if imp.contrato_m10 else None,
                'importada_em': imp.importada_em.isoformat(),
            })
        
        return Response({
            'total': total_faturas,
            'total_valor': str(total_valor),
            'pagina': page,
            'limit': limit,
            'dados': dados,
        })


class ListarLogsImportacaoFPDView(APIView):
    """Lista logs de importação FPD para monitoramento e debug"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        """GET /api/bonus-m10/logs-importacao-fpd/?status=ERRO&page=1"""
        from .models import LogImportacaoFPD
        from django.db.models import Sum, Count, Avg, Q
        
        queryset = LogImportacaoFPD.objects.select_related('usuario').all()
        
        # Filtros
        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        usuario_id = request.query_params.get('usuario_id')
        if usuario_id:
            queryset = queryset.filter(usuario_id=usuario_id)
        
        data_inicio = request.query_params.get('data_inicio')
        if data_inicio:
            queryset = queryset.filter(iniciado_em__gte=data_inicio)
        
        data_fim = request.query_params.get('data_fim')
        if data_fim:
            queryset = queryset.filter(iniciado_em__lte=data_fim)
        
        # Paginação
        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 50))
        start = (page - 1) * limit
        end = start + limit
        
        total = queryset.count()
        logs = queryset.order_by('-iniciado_em')[start:end]
        
        # Estatísticas gerais
        try:
            stats_geral = LogImportacaoFPD.objects.aggregate(
                total_importacoes=Count('id'),
                total_linhas_processadas=Sum('total_linhas'),
                total_sucesso=Count('id', filter=Q(status='SUCESSO')),
                total_erro=Count('id', filter=Q(status='ERRO')),
                total_parcial=Count('id', filter=Q(status='PARCIAL')),
                media_duracao=Avg('duracao_segundos'),
                total_valor=Sum('total_valor_importado')
            )
            
            total_importacoes = stats_geral['total_importacoes'] or 0
            total_sucesso = stats_geral['total_sucesso'] or 0
            
            resultado = {
                'total': total,
                'page': page,
                'limit': limit,
                'total_pages': (total + limit - 1) // limit if limit > 0 else 1,
                'estatisticas_gerais': {
                    'total_importacoes': total_importacoes,
                    'total_linhas_processadas': int(stats_geral['total_linhas_processadas'] or 0),
                    'total_sucesso': total_sucesso,
                    'total_erro': stats_geral['total_erro'] or 0,
                    'total_parcial': stats_geral['total_parcial'] or 0,
                    'media_duracao_segundos': float(stats_geral['media_duracao'] or 0),
                    'total_valor_importado': str(stats_geral['total_valor'] or 0),
                    'taxa_sucesso': round((total_sucesso / total_importacoes * 100) if total_importacoes > 0 else 0, 2)
                },
                'logs': []
            }
        except Exception as e:
            # Em caso de erro, retornar estrutura vazia mas válida
            resultado = {
                'total': 0,
                'page': page,
                'limit': limit,
                'total_pages': 1,
                'estatisticas_gerais': {
                    'total_importacoes': 0,
                    'total_linhas_processadas': 0,
                    'total_sucesso': 0,
                    'total_erro': 0,
                    'total_parcial': 0,
                    'media_duracao_segundos': 0.0,
                    'total_valor_importado': '0',
                    'taxa_sucesso': 0.0
                },
                'logs': []
            }
        
        for log in logs:
            try:
                log_data = {
                    'id': log.id,
                    'nome_arquivo': log.nome_arquivo or '',
                    'tamanho_arquivo': log.tamanho_arquivo or 0,
                    'usuario': {
                        'id': log.usuario.id if log.usuario else None,
                        'username': log.usuario.username if log.usuario else 'Sistema',
                        'nome_completo': log.usuario.get_full_name() if log.usuario else 'Sistema',
                    },
                    'status': log.status or 'DESCONHECIDO',
                    'iniciado_em': log.iniciado_em.isoformat() if log.iniciado_em else None,
                    'finalizado_em': log.finalizado_em.isoformat() if log.finalizado_em else None,
                    'duracao_segundos': log.duracao_segundos or 0,
                    'total_linhas': log.total_linhas or 0,
                    'total_processadas': log.total_processadas or 0,
                    'total_erros': log.total_erros or 0,
                    'total_contratos_nao_encontrados': log.total_contratos_nao_encontrados or 0,
                    'total_valor_importado': str(log.total_valor_importado) if log.total_valor_importado else '0',
                    'mensagem_erro': log.mensagem_erro or None,
                    'exemplos_nao_encontrados': log.exemplos_nao_encontrados or None,
                }
                
                # Adicionar detalhes completos se requisitado
                if request.query_params.get('detalhes') == 'true':
                    log_data['detalhes_json'] = log.detalhes_json
                
                resultado['logs'].append(log_data)
            except Exception as e:
                # Se houver erro ao processar um log específico, pular para o próximo
                print(f"Erro ao processar log {log.id}: {str(e)}")
                continue
        
        return Response(resultado)


class ListarLogsImportacaoChurnView(APIView):
    """Lista logs de importação CHURN para monitoramento e debug"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        """GET /api/bonus-m10/logs-importacao-churn/?status=ERRO&page=1"""
        from .models import LogImportacaoChurn
        from django.db.models import Sum, Count, Avg, Q
        
        queryset = LogImportacaoChurn.objects.select_related('usuario').all()
        
        # Filtros
        status = request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        usuario_id = request.query_params.get('usuario_id')
        if usuario_id:
            queryset = queryset.filter(usuario_id=usuario_id)
        
        data_inicio = request.query_params.get('data_inicio')
        if data_inicio:
            queryset = queryset.filter(iniciado_em__gte=data_inicio)
        
        data_fim = request.query_params.get('data_fim')
        if data_fim:
            queryset = queryset.filter(iniciado_em__lte=data_fim)
        
        # Paginação
        page = int(request.query_params.get('page', 1))
        limit = int(request.query_params.get('limit', 50))
        start = (page - 1) * limit
        end = start + limit
        
        total = queryset.count()
        logs = queryset.order_by('-iniciado_em')[start:end]
        
        # Estatísticas gerais
        try:
            stats_geral = LogImportacaoChurn.objects.aggregate(
                total_importacoes=Count('id'),
                total_linhas_processadas=Sum('total_linhas'),
                total_sucesso=Count('id', filter=Q(status='SUCESSO')),
                total_erro=Count('id', filter=Q(status='ERRO')),
                total_parcial=Count('id', filter=Q(status='PARCIAL')),
                media_duracao=Avg('duracao_segundos'),
                total_cancelados=Sum('total_contratos_cancelados'),
                total_reativados=Sum('total_contratos_reativados')
            )
            
            total_importacoes = stats_geral['total_importacoes'] or 0
            total_sucesso = stats_geral['total_sucesso'] or 0
            
            resultado = {
                'total': total,
                'page': page,
                'limit': limit,
                'total_pages': (total + limit - 1) // limit if limit > 0 else 1,
                'estatisticas_gerais': {
                    'total_importacoes': total_importacoes,
                    'total_linhas_processadas': int(stats_geral['total_linhas_processadas'] or 0),
                    'total_sucesso': total_sucesso,
                    'total_erro': stats_geral['total_erro'] or 0,
                    'total_parcial': stats_geral['total_parcial'] or 0,
                    'media_duracao_segundos': float(stats_geral['media_duracao'] or 0),
                    'total_cancelados': int(stats_geral['total_cancelados'] or 0),
                    'total_reativados': int(stats_geral['total_reativados'] or 0),
                    'taxa_sucesso': round((total_sucesso / total_importacoes * 100) if total_importacoes > 0 else 0, 2)
                },
                'logs': []
            }
        except Exception as e:
            # Em caso de erro, retornar estrutura vazia mas válida
            resultado = {
                'total': 0,
                'page': page,
                'limit': limit,
                'total_pages': 1,
                'estatisticas_gerais': {
                    'total_importacoes': 0,
                    'total_linhas_processadas': 0,
                    'total_sucesso': 0,
                    'total_erro': 0,
                    'total_parcial': 0,
                    'media_duracao_segundos': 0.0,
                    'total_cancelados': 0,
                    'total_reativados': 0,
                    'taxa_sucesso': 0.0
                },
                'logs': []
            }
        
        for log in logs:
            try:
                log_data = {
                    'id': log.id,
                    'nome_arquivo': log.nome_arquivo or '',
                    'tamanho_arquivo': log.tamanho_arquivo or 0,
                    'usuario': {
                        'id': log.usuario.id if log.usuario else None,
                        'username': log.usuario.username if log.usuario else 'Sistema',
                        'nome_completo': log.usuario.get_full_name() if log.usuario else 'Sistema',
                    },
                    'status': log.status or 'DESCONHECIDO',
                    'iniciado_em': log.iniciado_em.isoformat() if log.iniciado_em else None,
                    'finalizado_em': log.finalizado_em.isoformat() if log.finalizado_em else None,
                    'duracao_segundos': log.duracao_segundos or 0,
                    'total_linhas': log.total_linhas or 0,
                    'total_processadas': log.total_processadas or 0,
                    'total_erros': log.total_erros or 0,
                    'total_contratos_cancelados': log.total_contratos_cancelados or 0,
                    'total_contratos_reativados': log.total_contratos_reativados or 0,
                    'total_nao_encontrados': log.total_nao_encontrados or 0,
                    'mensagem_erro': log.mensagem_erro or None,
                }
                
                # Adicionar detalhes completos se requisitado
                if request.query_params.get('detalhes') == 'true':
                    log_data['detalhes_json'] = log.detalhes_json
                
                resultado['logs'].append(log_data)
            except Exception as e:
                # Se houver erro ao processar um log específico, pular para o próximo
                print(f"Erro ao processar log {log.id}: {str(e)}")
                continue
        
        return Response(resultado)


class FaturaM10ListView(generics.ListCreateAPIView):
    """Lista e cria faturas de um contrato específico"""
    serializer_class = FaturaM10Serializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    
    def create(self, request, *args, **kwargs):
        """Override create para usar update_or_create e evitar erro de duplicação"""
        contrato_id = request.data.get('contrato')
        numero_fatura = request.data.get('numero_fatura')
        
        if not contrato_id or not numero_fatura:
            return Response({'error': 'contrato e numero_fatura são obrigatórios'}, status=400)
        
        try:
            contrato = ContratoM10.objects.get(id=contrato_id)
        except ContratoM10.DoesNotExist:
            return Response({'error': 'Contrato não encontrado'}, status=404)
        
        # Remove campos que não devem ser passados para update_or_create
        dados_fatura = {k: v for k, v in request.data.items() if k not in ['contrato', 'numero_fatura']}
        dados_fatura['contrato'] = contrato
        
        # Usa update_or_create para evitar duplicação
        fatura, created = FaturaM10.objects.update_or_create(
            contrato=contrato,
            numero_fatura=numero_fatura,
            defaults=dados_fatura
        )
        
        serializer = self.get_serializer(fatura)
        status_code = 201 if created else 200
        return Response(serializer.data, status=status_code)

    def _sincronizar_primeira_fatura_com_fpd(self, contrato_id: int):
        """Garante que a fatura 1 reflita os dados importados do FPD (prioridade)."""
        try:
            contrato = ContratoM10.objects.get(id=contrato_id)
        except ContratoM10.DoesNotExist:
            return

        tem_fpd = any([
            contrato.data_vencimento_fpd,
            contrato.status_fatura_fpd,
            contrato.valor_fatura_fpd,
            contrato.data_pagamento_fpd,
        ])
        if not tem_fpd:
            return

        status_fpd = (contrato.status_fatura_fpd or '').upper()
        if 'PAGA' in status_fpd:
            status_m10 = 'PAGO'
        elif 'AGUARDANDO' in status_fpd:
            status_m10 = 'AGUARDANDO'
        elif 'ATRASAD' in status_fpd or 'VENCID' in status_fpd:
            status_m10 = 'ATRASADO'
        else:
            status_m10 = 'NAO_PAGO'

        defaults = {
            'valor': contrato.valor_fatura_fpd or 0,
            'data_vencimento': contrato.data_vencimento_fpd or date.today(),
            'data_pagamento': contrato.data_pagamento_fpd,
            'status': status_m10,
        }
        fatura, _ = FaturaM10.objects.get_or_create(
            contrato=contrato,
            numero_fatura=1,
            defaults=defaults,
        )

        alterado = False
        if contrato.valor_fatura_fpd and fatura.valor != contrato.valor_fatura_fpd:
            fatura.valor = contrato.valor_fatura_fpd
            alterado = True
        if contrato.data_vencimento_fpd and fatura.data_vencimento != contrato.data_vencimento_fpd:
            fatura.data_vencimento = contrato.data_vencimento_fpd
            alterado = True
        if contrato.data_pagamento_fpd and fatura.data_pagamento != contrato.data_pagamento_fpd:
            fatura.data_pagamento = contrato.data_pagamento_fpd
            alterado = True
        if fatura.status != status_m10:
            fatura.status = status_m10
            alterado = True
        if alterado:
            fatura.save(update_fields=['valor', 'data_vencimento', 'data_pagamento', 'status', 'atualizado_em'])
    
    def get_queryset(self):
        contrato_id = self.request.query_params.get('contrato_id')
        if contrato_id:
            self._sincronizar_primeira_fatura_com_fpd(contrato_id)
            return FaturaM10.objects.filter(contrato_id=contrato_id).order_by('numero_fatura')
        return FaturaM10.objects.none()
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class FaturaM10DetailView(generics.RetrieveUpdateAPIView):
    """Detalhes e atualização de uma fatura específica (suporta link ou upload de PDF)"""
    queryset = FaturaM10.objects.all()
    serializer_class = FaturaM10Serializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class BuscarFaturaNioView(APIView):
    """Busca automática de fatura no site da Nio Internet"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """
        Busca fatura automaticamente e retorna os dados
        
        Body: {
            "cpf": "12345678900",
            "contrato_id": 123,
            "numero_fatura": 1,
            "salvar": false  # Se true, salva automaticamente
        }
        """
        from datetime import date
        
        cpf = request.data.get('cpf')
        contrato_id = request.data.get('contrato_id')
        numero_fatura = request.data.get('numero_fatura')
        salvar = request.data.get('salvar', False)
        
        if not cpf:
            return Response({'error': 'CPF não informado'}, status=400)
        
        # Verificar se a fatura já está disponível
        if contrato_id and numero_fatura:
            try:
                contrato = ContratoM10.objects.get(id=contrato_id)
                fatura = FaturaM10.objects.filter(
                    contrato=contrato,
                    numero_fatura=numero_fatura
                ).first()
                
                if fatura and fatura.data_disponibilidade:
                    hoje = date.today()
                    if fatura.data_disponibilidade > hoje:
                        dias_faltam = (fatura.data_disponibilidade - hoje).days
                        return Response({
                            'error': f'Fatura ainda não disponível. Estará disponível em {dias_faltam} dia(s), a partir de {fatura.data_disponibilidade.strftime("%d/%m/%Y")}.',
                            'data_disponibilidade': fatura.data_disponibilidade,
                            'disponivel': False
                        }, status=400)
            except ContratoM10.DoesNotExist:
                pass
        
        try:
            from crm_app.services_nio import buscar_fatura_nio_por_cpf
            
            # Busca dados no site da Nio (com PDF se solicitado)
            incluir_pdf = request.data.get('incluir_pdf', True)  # Por padrão busca o PDF
            dados = buscar_fatura_nio_por_cpf(cpf, incluir_pdf=incluir_pdf)
            
            if not dados:
                return Response({
                    'error': 'Não foi possível buscar a fatura. Verifique o CPF ou tente novamente.'
                }, status=404)
            
            # Se retornou indicação de CPF sem dívidas
            if dados.get('sem_dividas'):
                return Response({
                    'success': True,
                    'sem_dividas': True,
                    'mensagem': dados.get('mensagem', 'CPF sem dívidas no momento.')
                }, status=200)
            
            # Se não encontrou nenhum dado válido
            if not any([dados.get('valor'), dados.get('codigo_pix'), dados.get('codigo_barras')]):
                return Response({
                    'error': 'Fatura encontrada mas sem dados disponíveis. Preencha manualmente.'
                }, status=404)
            
            # Se deve salvar automaticamente
            if salvar and contrato_id and numero_fatura:
                try:
                    contrato = ContratoM10.objects.get(id=contrato_id)
                    fatura, created = FaturaM10.objects.get_or_create(
                        contrato=contrato,
                        numero_fatura=numero_fatura,
                        defaults={
                            'valor': dados['valor'] or 0,
                            'data_vencimento': dados['data_vencimento'] or datetime.now().date(),
                            'status': 'NAO_PAGO'
                        }
                    )
                    
                    # Atualiza campos
                    if dados['valor']:
                        fatura.valor = dados['valor']
                    if dados['data_vencimento']:
                        fatura.data_vencimento = dados['data_vencimento']
                    if dados['codigo_pix']:
                        fatura.codigo_pix = dados['codigo_pix']
                    if dados['codigo_barras']:
                        fatura.codigo_barras = dados['codigo_barras']
                    if dados['pdf_url']:
                        fatura.pdf_url = dados['pdf_url']
                    
                    fatura.save()
                    
                    return Response({
                        'success': True,
                        'message': '✅ Fatura preenchida automaticamente!',
                        'dados': {
                            'valor': float(fatura.valor),
                            'data_vencimento': fatura.data_vencimento.strftime('%Y-%m-%d'),
                            'codigo_pix': fatura.codigo_pix,
                            'codigo_barras': fatura.codigo_barras,
                            'tem_pdf': bool(fatura.pdf_url or fatura.arquivo_pdf),
                            'pdf_url': fatura.pdf_url,
                        }
                    })
                    
                except ContratoM10.DoesNotExist:
                    return Response({'error': 'Contrato não encontrado'}, status=404)
                except Exception as e:
                    return Response({'error': f'Erro ao salvar: {str(e)}'}, status=500)
            
            # Retorna apenas os dados sem salvar
            return Response({
                'success': True,
                'dados': dados
            })
            
        except ImportError:
            return Response({
                'error': 'Selenium não instalado. Execute: pip install selenium'
            }, status=500)
        except Exception as e:
            return Response({
                'error': f'Erro ao buscar fatura: {str(e)}'
            }, status=500)


class BuscarFaturasSafraView(APIView):
    """Busca automática de todas as faturas disponíveis de uma safra"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """
        Busca faturas de todos os contratos de uma safra
        
        Body: {
            "safra": "2025-12",  # Opcional: formato YYYY-MM
            "safra_id": 1,       # Ou ID da safra
            "numero_fatura": 1   # Opcional: buscar apenas esta fatura
        }
        """
        from datetime import date, timedelta
        from crm_app.services_nio import buscar_todas_faturas_nio_por_cpf
        
        safra_str = request.data.get('safra')
        safra_id = request.data.get('safra_id')
        numero_fatura_filtro = request.data.get('numero_fatura')
        
        if not safra_str and not safra_id:
            return Response({'error': 'Informe a safra (YYYY-MM) ou safra_id'}, status=400)
        
        try:
            # Buscar contratos da safra
            if safra_id:
                try:
                    safra = SafraM10.objects.get(id=safra_id)
                    safra_str = safra.mes_referencia.strftime('%Y-%m')
                except SafraM10.DoesNotExist:
                    return Response({'error': 'Safra não encontrada'}, status=404)
            
            if not safra_str:
                return Response({'error': 'Safra inválida'}, status=400)
            
            # Filtrar por safra (CharField YYYY-MM)
            contratos = ContratoM10.objects.filter(
                safra=safra_str,
                status_contrato='ATIVO'
            )
            
            if not contratos.exists():
                return Response({'error': 'Nenhum contrato encontrado para esta safra'}, status=404)
            
            hoje = date.today()
            resultados = {
                'total_contratos': contratos.count(),
                'processados': 0,
                'sucesso': 0,
                'erros': 0,
                'nao_disponiveis': 0,
                'sem_cpf': 0,
                'detalhes': []
            }
            
            for contrato in contratos:
                if not contrato.cpf_cliente:
                    resultados['sem_cpf'] += 1
                    resultados['detalhes'].append({
                        'contrato': contrato.numero_contrato,
                        'status': 'sem_cpf',
                        'mensagem': 'CPF não cadastrado'
                    })
                    continue
                
                # Busca faturas disponíveis
                from django.db.models import Q
                
                if numero_fatura_filtro:
                    # Busca apenas a fatura especificada
                    fatura = FaturaM10.objects.filter(
                        contrato=contrato,
                        numero_fatura=numero_fatura_filtro
                    ).first()
                    faturas_disponiveis = [fatura] if fatura else []
                else:
                    # Busca apenas faturas não pagas E que já estão disponíveis
                    faturas_disponiveis = FaturaM10.objects.filter(
                        contrato=contrato,
                        status__in=['NAO_PAGO', 'ATRASADO', 'AGUARDANDO']
                    ).filter(
                        Q(data_disponibilidade__isnull=True) | Q(data_disponibilidade__lte=hoje)
                    ).order_by('numero_fatura')
                
                if not faturas_disponiveis:
                    continue
                
                # Busca TODAS as faturas disponíveis no Nio para fazer matching por vencimento
                # incluir_pdf=True força uso do Playwright para capturar o link do PDF
                try:
                    faturas_nio = buscar_todas_faturas_nio_por_cpf(contrato.cpf_cliente, incluir_pdf=True)
                    
                    if not faturas_nio:
                        resultados['detalhes'].append({
                            'contrato': contrato.numero_contrato,
                            'status': 'sem_dividas_nio',
                            'mensagem': 'CPF sem dívidas no Nio no momento'
                        })
                        continue
                    
                    # Faz matching por data de vencimento (com tolerância de ±3 dias)
                    for fatura in faturas_disponiveis:
                        resultados['processados'] += 1
                        match_encontrado = False
                        
                        for fatura_nio in faturas_nio:
                            if not fatura_nio.get('data_vencimento'):
                                continue
                            
                            # Compara datas com tolerância de 3 dias
                            diff_dias = abs((fatura.data_vencimento - fatura_nio['data_vencimento']).days)
                            
                            if diff_dias <= 3:  # Match encontrado!
                                match_encontrado = True
                                
                                # Atualiza a fatura com os dados do Nio
                                alteracoes = []
                                if fatura_nio.get('valor') and fatura.valor != fatura_nio['valor']:
                                    fatura.valor = fatura_nio['valor']
                                    alteracoes.append('valor')
                                
                                if fatura_nio.get('data_vencimento') and fatura.data_vencimento != fatura_nio['data_vencimento']:
                                    fatura.data_vencimento = fatura_nio['data_vencimento']
                                    alteracoes.append('vencimento')
                                
                                if fatura_nio.get('codigo_pix') and fatura.codigo_pix != fatura_nio['codigo_pix']:
                                    fatura.codigo_pix = fatura_nio['codigo_pix']
                                    alteracoes.append('pix')
                                
                                if fatura_nio.get('codigo_barras') and fatura.codigo_barras != fatura_nio['codigo_barras']:
                                    fatura.codigo_barras = fatura_nio['codigo_barras']
                                    alteracoes.append('barcode')
                                
                                if fatura_nio.get('pdf_url') and fatura.pdf_url != fatura_nio['pdf_url']:
                                    fatura.pdf_url = fatura_nio['pdf_url']
                                    alteracoes.append('pdf_url')
                                
                                if alteracoes:
                                    fatura.save()
                                    resultados['sucesso'] += 1
                                    resultados['detalhes'].append({
                                        'contrato': contrato.numero_contrato,
                                        'fatura': fatura.numero_fatura,
                                        'status': 'atualizado',
                                        'mensagem': f'Match por vencimento (diff: {diff_dias} dia(s))',
                                        'alteracoes': alteracoes,
                                        'vencimento_crm': fatura.data_vencimento.strftime('%d/%m/%Y'),
                                        'vencimento_nio': fatura_nio['data_vencimento'].strftime('%d/%m/%Y')
                                    })
                                else:
                                    resultados['detalhes'].append({
                                        'contrato': contrato.numero_contrato,
                                        'fatura': fatura.numero_fatura,
                                        'status': 'sem_alteracao',
                                        'mensagem': 'Match encontrado mas dados já estão atualizados'
                                    })
                                
                                # Remove fatura_nio da lista para não fazer match duplicado
                                faturas_nio.remove(fatura_nio)
                                break
                        
                        if not match_encontrado:
                            resultados['detalhes'].append({
                                'contrato': contrato.numero_contrato,
                                'fatura': fatura.numero_fatura,
                                'status': 'sem_match',
                                'mensagem': f'Fatura vencimento {fatura.data_vencimento.strftime("%d/%m/%Y")} não encontrada no Nio',
                                'vencimento_crm': fatura.data_vencimento.strftime('%d/%m/%Y')
                            })
                    
                except Exception as e:
                    resultados['erros'] += 1
                    resultados['detalhes'].append({
                        'contrato': contrato.numero_contrato,
                        'status': 'erro',
                        'mensagem': str(e)
                    })
            
            return Response({
                'success': True,
                'resumo': resultados
            })
            
        except Exception as e:
            return Response({
                'error': f'Erro ao processar safra: {str(e)}'
            }, status=500)


class NioDividasView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        cpf = (request.query_params.get("cpf") or "").strip()
        offset = int(request.query_params.get("offset", 0))
        limit = int(request.query_params.get("limit", 10))

        if not cpf:
            return Response({"detail": "CPF/CNPJ não informado"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Valida CPF/CNPJ mas trata exceção de validação
        try:
            validar_cpf_ou_cnpj(cpf)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = consultar_dividas_nio(
                cpf=cpf,
                offset=offset,
                limit=limit,
                storage_state=getattr(settings, "NIO_STORAGE_STATE", None),
                headless=True,
            )
        except Exception as exc:
            logger.exception("Erro ao consultar dívidas Nio")
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({
            "invoices": result.get("invoices", []),
            "meta": {
                "api_base": result.get("api_base"),
                "session_id": result.get("session_id"),
                "count": len(result.get("invoices", [])),
            },
        })
