# crm_app/views.py

# NOVAS IMPORTAÇÕES ADICIONADAS NO TOPO DO ARQUIVO
import logging
# --------------------------------------------------

from django.db.models import Count, Q
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from django.utils.timezone import now
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import authenticate
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.http import JsonResponse
from collections import defaultdict
from operator import itemgetter


from usuarios.permissions import CheckAPIPermission

from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia,
    RegraComissao, Cliente, Venda, ImportacaoOsab, ImportacaoChurn,
    CicloPagamento, HistoricoAlteracaoVenda
)
from .serializers import (
    OperadoraSerializer, PlanoSerializer, FormaPagamentoSerializer,
    StatusCRMSerializer, MotivoPendenciaSerializer, RegraComissaoSerializer,
    VendaSerializer, VendaCreateSerializer, ClienteSerializer,
    VendaUpdateSerializer, ImportacaoOsabSerializer, ImportacaoChurnSerializer,
    CicloPagamentoSerializer,
    VendaDetailSerializer
)

# NOVO LOGGER ADICIONADO AQUI
logger = logging.getLogger(__name__)

class OperadoraListCreateView(generics.ListCreateAPIView):
    queryset = Operadora.objects.filter(ativo=True)
    serializer_class = OperadoraSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'operadoras'

class OperadoraDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Operadora.objects.all()
    serializer_class = OperadoraSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'operadoras'

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
    resource_name = 'status_crm'

    def get_queryset(self):
        user = self.request.user
        perfil_nome = user.perfil.nome if hasattr(user, 'perfil') and user.perfil else None
        if user.is_superuser or perfil_nome in ['Diretoria', 'BackOffice']:
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
    resource_name = 'status_crm'

class MotivoPendenciaListCreateView(generics.ListCreateAPIView):
    queryset = MotivoPendencia.objects.all()
    serializer_class = MotivoPendenciaSerializer
    permission_classes = [permissions.IsAuthenticated]

class MotivoPendenciaDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = MotivoPendencia.objects.all()
    serializer_class = MotivoPendenciaSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'motivos_pendencia'

class RegraComissaoListCreateView(generics.ListCreateAPIView):
    queryset = RegraComissao.objects.all()
    serializer_class = RegraComissaoSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'regras_comissao'

class RegraComissaoDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = RegraComissao.objects.all()
    serializer_class = RegraComissaoSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'regras_comissao'

class VendaViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, CheckAPIPermission]
    resource_name = 'vendas'
    
    # <<< ALTERAÇÃO 1: QUERYSET PRINCIPAL AGORA FILTRA APENAS VENDAS ATIVAS >>>
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
        # Utiliza o queryset da classe que já está filtrado por 'ativo=True'
        queryset = self.queryset
        user = self.request.user
        perfil_nome = user.perfil.nome if hasattr(user, 'perfil') and user.perfil else None

        queryset = queryset.select_related(
            'vendedor', 'cliente', 'plano', 'forma_pagamento',
            'status_tratamento', 'status_esteira', 'status_comissionamento',
            'motivo_pendencia'
        ).prefetch_related('historico_alteracoes__usuario')

        if not (user.is_superuser or perfil_nome in ['Diretoria', 'BackOffice', 'Admin']):
            if perfil_nome == 'Supervisor':
                liderados_ids = list(user.liderados.values_list('id', flat=True))
                liderados_ids.append(user.id)
                queryset = queryset.filter(vendedor_id__in=liderados_ids)
            else:
                queryset = queryset.filter(vendedor=user)

        if getattr(self, 'action', None) == 'list':
            ordem_servico = self.request.query_params.get('ordem_servico')
            data_inicio_str = self.request.query_params.get('data_inicio')
            data_fim_str = self.request.query_params.get('data_fim')
            consultor_id = self.request.query_params.get('consultor_id')
            view_type = self.request.query_params.get('view', 'minhas_vendas')
            flow = self.request.query_params.get('flow')

            is_management_profile = user.is_superuser or perfil_nome in ['Diretoria', 'BackOffice', 'Admin']
            if is_management_profile and flow:
                view_type = self.request.query_params.get('view', 'geral')

            if is_management_profile:
                if view_type == 'minhas_vendas':
                    queryset = queryset.filter(vendedor=user)
                elif consultor_id:
                    queryset = queryset.filter(vendedor_id=consultor_id)

            if flow == 'auditoria':
                queryset = queryset.filter(status_tratamento__isnull=False, status_esteira__isnull=True)
            elif flow == 'esteira':
                queryset = queryset.filter(status_esteira__isnull=False, status_comissionamento__isnull=True).exclude(status_esteira__nome__iexact='Instalada')
            elif flow == 'comissionamento':
                queryset = queryset.filter(status_esteira__nome__iexact='Instalada').exclude(status_comissionamento__nome__iexact='Pago')

            if ordem_servico:
                queryset = queryset.filter(ordem_servico__icontains=ordem_servico)

            if is_management_profile:
                if data_inicio_str:
                    try:
                        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                        queryset = queryset.filter(data_criacao__gte=data_inicio)
                    except (ValueError, TypeError): pass
                if data_fim_str:
                    try:
                        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
                        data_fim += timedelta(days=1)
                        queryset = queryset.filter(data_criacao__lt=data_fim)
                    except (ValueError, TypeError): pass
            else:
                hoje = now()
                inicio_mes = hoje.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                queryset = queryset.filter(data_criacao__gte=inicio_mes)
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
            if email:
                cliente.email = email
            cliente.save()
        try:
            status_inicial = StatusCRM.objects.get(nome__iexact="SEM TRATAMENTO", tipo__iexact="Tratamento")
        except StatusCRM.DoesNotExist:
            status_inicial = None
            print("ATENÇÃO: O status inicial 'SEM TRATAMENTO' para o Tratamento não foi encontrado.")
        serializer.save(vendedor=self.request.user, cliente=cliente, status_tratamento=status_inicial)

    def perform_update(self, serializer):
        serializer.save(request=self.request)

    # <<< ALTERAÇÃO 2: MÉTODO DESTROY AGORA FAZ A EXCLUSÃO LÓGICA (SOFT DELETE) >>>
    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            
            # Marca a venda como inativa em vez de apagar do banco de dados
            instance.ativo = False
            instance.save()

            # Cria um registro no histórico para auditar quem excluiu a venda
            HistoricoAlteracaoVenda.objects.create(
                venda=instance,
                usuario=request.user,
                alteracoes={
                    "acao": "exclusao_logica",
                    "detalhe": f"Venda marcada como inativa por {request.user.username}."
                }
            )
            
            # Retorna uma resposta de sucesso
            return Response(status=status.HTTP_204_NO_CONTENT)

        except Exception as e:
            # Captura qualquer erro inesperado e o registra
            logger.error(f"Erro inesperado ao realizar soft delete da venda {kwargs.get('pk')}: {e}", exc_info=True)
            return Response(
                {"detail": f"Ocorreu um erro inesperado ao tentar excluir a venda: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

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
        resultado_final = {item['status_esteira__nome']: item['count'] for item in sorted_counts}
        return Response(resultado_final)


class ClienteViewSet(viewsets.ReadOnlyModelViewSet):
    # <<< ALTERAÇÃO 3: FILTRA CLIENTES APENAS DE VENDAS ATIVAS >>>
    queryset = Cliente.objects.filter(vendas__ativo=True).distinct()
    serializer_class = ClienteSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'clientes'

    def get_queryset(self):
        # Garante que a contagem de vendas também considere apenas as ativas
        queryset = super().get_queryset().annotate(vendas_count=Count('vendas', filter=Q(vendas__ativo=True)))
        search_query = self.request.query_params.get('search', None)
        if search_query:
            queryset = queryset.filter(
                Q(cpf_cnpj__icontains=search_query) |
                Q(nome_razao_social__icontains=search_query)
            )
        return queryset

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
            response.set_cookie(
                'access_token', str(refresh.access_token),
                httponly=True, secure=True, samesite='Lax'
            )
            return response
        else:
            return Response(
                {"detail": "Credenciais inválidas"},
                status=status.HTTP_401_UNAUTHORIZED
            )

class ImportacaoOsabView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_osab'
    parser_classes = [MultiPartParser, FormParser]

    def _clean_key(self, key):
        if pd.isna(key) or key is None:
            return None
        return str(key).replace('.0', '').strip()

    def get(self, request):
        queryset = ImportacaoOsab.objects.all().order_by('-id')
        serializer = ImportacaoOsabSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'Nenhum arquivo foi enviado.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            df = None
            if file_obj.name.endswith('.xlsb'):
                df = pd.read_excel(file_obj, engine='pyxlsb')
            elif file_obj.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_obj)
            else:
                return Response({'error': 'Formato de arquivo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Erro ao ler o arquivo: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        
        df.columns = [str(col).strip().upper() for col in df.columns]
        if 'DOCUMENTO' not in df.columns or 'SITUACAO' not in df.columns:
            return Response({"error": "O arquivo precisa conter as colunas 'DOCUMENTO' e 'SITUACAO'."}, status=status.HTTP_400_BAD_REQUEST)
        
        df = df.replace({np.nan: None, pd.NaT: None})
        STATUS_MAP = {
            'CONCLUÍDO': 'INSTALADA', 'CANCELADO': 'CANCELADA', 'CANCELADO - SEM APROVISIONAMENTO': 'CANCELADA', 'PENDÊNCIA CLIENTE': 'PENDENCIADA', 'PENDÊNCIA TÉCNICA': 'PENDENCIADA', 'EM APROVISIONAMENTO': 'EM ANDAMENTO', 'AGUARDANDO PAGAMENTO': 'AGUARDANDO PAGAMENTO', 'REPROVADO ANALISE DE FRAUDE': 'REPROVADO CARTÃO DE CRÉDITO', 'DRAFT': 'DRAFT', 'DRAFT - PRAZO CC EXPIRADO': 'DRAFT',
        }
        status_esteira_objects = StatusCRM.objects.filter(tipo='Esteira')
        status_esteira_map = {status.nome.upper(): status for status in status_esteira_objects}
        
        # Filtra apenas vendas ativas
        vendas_com_os = Venda.objects.filter(ativo=True, ordem_servico__isnull=False).exclude(ordem_servico__exact='')
        vendas_map = {self._clean_key(v.ordem_servico): v for v in vendas_com_os}
        
        report = {"status": "sucesso", "total_registros": len(df), "criados": 0, "atualizados": 0, "vendas_encontradas": 0, "ja_corretos": 0, "status_nao_mapeado": 0, "erros": []}
        vendas_para_atualizar = []
        
        for index, row in df.iterrows():
            documento_limpo = self._clean_key(row.get('DOCUMENTO'))
            situacao_osab = row.get('SITUACAO')
            if not documento_limpo: continue

            venda = vendas_map.get(documento_limpo)
            if not venda:
                report["erros"].append(f"Linha {index + 2}: Documento {documento_limpo} não encontrado no sistema (ou a venda está inativa).")
                continue
            
            report["vendas_encontradas"] += 1
            if not situacao_osab: continue
            
            target_status_name = STATUS_MAP.get(str(situacao_osab).upper())
            if not target_status_name:
                report["status_nao_mapeado"] += 1
                report["erros"].append(f"Linha {index + 2}: Status '{situacao_osab}' do doc {documento_limpo} não mapeado.")
                continue

            target_status_obj = status_esteira_map.get(target_status_name.upper())
            if not target_status_obj:
                report["status_nao_mapeado"] += 1
                report["erros"].append(f"Linha {index + 2}: Status mapeado '{target_status_name}' do doc {documento_limpo} não existe no DB.")
                continue

            if venda.status_esteira and venda.status_esteira.id == target_status_obj.id:
                report["ja_corretos"] += 1
            else:
                venda.status_esteira = target_status_obj
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
        if not file_obj:
            return Response({'error': 'Nenhum arquivo foi enviado.'}, status=status.HTTP_400_BAD_REQUEST)
        coluna_map = {
            'UF': 'uf', 'PRODUTO': 'produto', 'MATRICULA_VENDEDOR': 'matricula_vendedor', 'GV': 'gv', 'SAP_PRINCIPAL_FIM': 'sap_principal_fim', 'GESTAO': 'gestao', 'ST_REGIONAL': 'st_regional', 'GC': 'gc', 'NUMERO_PEDIDO': 'numero_pedido', 'DT_GROSS': 'dt_gross', 'ANOMES_GROSS': 'anomes_gross', 'DT_RETIRADA': 'dt_retirada', 'ANOMES_RETIRADA': 'anomes_retirada', 'GRUPO_UNIDADE': 'grupo_unidade', 'CODIGO_SAP': 'codigo_sap', 'MUNICIPIO': 'municipio', 'TIPO_RETIRADA': 'tipo_retirada', 'MOTIVO_RETIRADA': 'motivo_retirada', 'SUBMOTIVO_RETIRADA': 'submotivo_retirada', 'CLASSIFICACAO': 'classificacao', 'DESC_APELIDO': 'desc_apelido',
        }
        colunas_esperadas = list(coluna_map.keys())
        try:
            df = None
            if file_obj.name.endswith('.xlsb'):
                df = pd.read_excel(file_obj, engine='pyxlsb', usecols=lambda c: c.strip().upper() in colunas_esperadas)
            elif file_obj.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_obj, usecols=lambda c: c.strip().upper() in colunas_esperadas)
            else:
                return Response({'error': 'Formato de arquivo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Erro ao ler o arquivo: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        df.columns = [str(col).strip().upper() for col in df.columns]
        date_fields_churn = ['DT_GROSS', 'DT_RETIRADA']
        for field in date_fields_churn:
            if field in df.columns:
                df[field] = pd.to_datetime(df[field], errors='coerce')
        df = df.replace({np.nan: None, pd.NaT: None})
        df.rename(columns=coluna_map, inplace=True)
        registros_criados, registros_atualizados, erros_importacao = 0, 0, []
        model_fields = {f.name for f in ImportacaoChurn._meta.get_fields()}
        for index, row in df.iterrows():
            row_data = row.to_dict()
            numero_pedido = row_data.get('numero_pedido')
            if not numero_pedido:
                erros_importacao.append(f'Linha {index+2}: Número do pedido ausente.')
                continue
            defaults_data = {key: value for key, value in row_data.items() if key in model_fields}
            try:
                obj, created = ImportacaoChurn.objects.update_or_create(numero_pedido=numero_pedido, defaults=defaults_data)
                if created: registros_criados += 1
                else: registros_atualizados += 1
            except Exception as e:
                erros_importacao.append(f'Linha {index+2}: Erro ao salvar: {str(e)}')
        return Response({'status': 'sucesso', 'total_registros': len(df), 'criados': registros_criados, 'atualizados': registros_atualizados, 'erros': erros_importacao}, status=status.HTTP_200_OK)

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
        if not file_obj:
            return Response({'error': 'Nenhum arquivo enviado.'}, status=status.HTTP_400_BAD_REQUEST)
        coluna_map = {
            'ANO': 'ano', 'MES': 'mes', 'QUINZENA': 'quinzena', 'CICLO': 'ciclo', 'CICLO_COMPLEMENTAR': 'ciclo_complementar', 'EVENTO': 'evento', 'SUB_EVENTO': 'sub_evento', 'CANAL_DETALHADO': 'canal_detalhado', 'CANAL_AGRUPADO': 'canal_agrupado', 'SUB_CANAL': 'sub_canal', 'COD_SAP': 'cod_sap', 'COD_SAP_AGR': 'cod_sap_agr', 'PARCEIRO_AGR': 'parceiro_agr', 'UF_PARCEIRO_AGR': 'uf_parceiro_agr', 'FAMILIA': 'familia', 'PRODUTO': 'produto', 'OFERTA': 'oferta', 'PLANO_DETALHADO': 'plano_detalhado', 'CELULA': 'celula', 'METODO_PAGAMENTO': 'metodo_pagamento', 'CONTRATO': 'contrato', 'NUM_OS_PEDIDO_SIEBEL': 'num_os_pedido_siebel', 'ID_BUNDLE': 'id_bundle', 'DATA_ATV': 'data_atv', 'DATA_RETIRADA': 'data_retirada', 'QTD': 'qtd', 'COMISSAO_BRUTA': 'comissao_bruta', 'FATOR': 'fator', 'IQ': 'iq', 'VALOR_COMISSAO_FINAL': 'valor_comissao_final'
        }
        colunas_esperadas = list(coluna_map.keys())
        try:
            df = None
            if file_obj.name.endswith('.xlsb'):
                df = pd.read_excel(file_obj, engine='pyxlsb', usecols=lambda c: c.strip().upper() in colunas_esperadas)
            elif file_obj.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_obj, usecols=lambda c: c.strip().upper() in colunas_esperadas)
            else:
                return Response({'error': 'Formato de arquivo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Erro ao ler o arquivo: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        df.columns = [str(col).strip().upper() for col in df.columns]
        df.rename(columns=coluna_map, inplace=True)
        date_fields = ['data_atv', 'data_retirada']
        for field in date_fields:
            if field in df.columns:
                df[field] = pd.to_datetime(df[field], errors='coerce')
        numeric_fields = ['comissao_bruta', 'fator', 'iq', 'valor_comissao_final']
        for field in numeric_fields:
            if field in df.columns:
                df[field] = df[field].astype(str).str.replace('R$', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df[field] = pd.to_numeric(df[field], errors='coerce')
        df = df.replace({np.nan: None, pd.NaT: None})
        registros_criados, registros_atualizados, erros = 0, 0, []
        model_fields = {f.name for f in CicloPagamento._meta.get_fields()}
        for index, row in df.iterrows():
            row_data = row.to_dict()
            contrato = row_data.get('contrato')
            if not contrato:
                erros.append(f'Linha {index+2}: O número do contrato é obrigatório.')
                continue
            defaults_data = {key: value for key, value in row_data.items() if key in model_fields}
            try:
                obj, created = CicloPagamento.objects.update_or_create(contrato=contrato, defaults=defaults_data)
                if created: registros_criados += 1
                else: registros_atualizados += 1
            except Exception as e:
                erros.append(f'Linha {index+2}: Erro ao salvar o registro: {str(e)}')
        return Response({'total_registros': len(df), 'criados': registros_criados, 'atualizados': registros_atualizados, 'erros': erros}, status=status.HTTP_200_OK)

class PerformanceVendasView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        User = get_user_model()
        hoje = timezone.now().date()
        
        start_of_week = hoje - timedelta(days=hoje.weekday())
        start_of_month = hoje.replace(day=1)
        
        # Filtra apenas vendas ativas
        base_filters = (
            Q(ativo=True) &
            Q(status_tratamento__isnull=False) & 
            (Q(status_esteira__isnull=True) | ~Q(status_esteira__nome__iexact='CANCELADA'))
        )
        
        current_user = self.request.user
        perfil_nome = current_user.perfil.nome if hasattr(current_user, 'perfil') and current_user.perfil else None
        
        if current_user.is_superuser or perfil_nome in ['Diretoria', 'BackOffice', 'Admin']:
            users_to_process = User.objects.filter(is_active=True).select_related('supervisor')
        elif perfil_nome == 'Supervisor':
            users_to_process = User.objects.filter(Q(id=current_user.id) | Q(supervisor=current_user), is_active=True).select_related('supervisor')
        else:
            users_to_process = User.objects.filter(id=current_user.id, is_active=True).select_related('supervisor')
            
        vendas = Venda.objects.filter(base_filters).values('vendedor_id').annotate(
            total_dia=Count('id', filter=Q(data_pedido__date=hoje)),
            total_mes=Count('id', filter=Q(data_pedido__date__gte=start_of_month)),
            total_mes_instalado=Count('id', filter=Q(data_pedido__date__gte=start_of_month, status_esteira__nome__iexact='Instalada')),
            vendas_segunda=Count('id', filter=Q(data_pedido__date=start_of_week)),
            vendas_terca=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=1))),
            vendas_quarta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=2))),
            vendas_quinta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=3))),
            vendas_sexta=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=4))),
            vendas_sabado=Count('id', filter=Q(data_pedido__date=start_of_week + timedelta(days=5)))
        )
        
        vendas_por_vendedor = {v['vendedor_id']: v for v in vendas}

        teams = defaultdict(lambda: {
            'supervisor_name': 'Sem Supervisor',
            'members': [],
            'totals': {
                'daily': 0,
                'weekly_breakdown': {'seg': 0, 'ter': 0, 'qua': 0, 'qui': 0, 'sex': 0, 'sab': 0},
                'weekly_total': 0,
                'monthly': {'total': 0, 'instalados': 0}
            }
        })

        for user in users_to_process:
            supervisor_id = user.supervisor.id if user.supervisor else 'none'
            if supervisor_id != 'none' and user.supervisor:
                 teams[supervisor_id]['supervisor_name'] = user.supervisor.username

            v_data = vendas_por_vendedor.get(user.id, {})
            
            weekly_total = sum([
                v_data.get('vendas_segunda', 0), v_data.get('vendas_terca', 0), v_data.get('vendas_quarta', 0),
                v_data.get('vendas_quinta', 0), v_data.get('vendas_sexta', 0), v_data.get('vendas_sabado', 0)
            ])
            
            total_mes = v_data.get('total_mes', 0)
            instalados_mes = v_data.get('total_mes_instalado', 0)
            
            aproveitamento_str = f"{(instalados_mes / total_mes * 100):.1f}%" if total_mes > 0 else "0.0%"

            teams[supervisor_id]['members'].append({
                'name': user.username,
                'daily': v_data.get('total_dia', 0),
                'weekly_breakdown': {
                    'seg': v_data.get('vendas_segunda', 0), 'ter': v_data.get('vendas_terca', 0),
                    'qua': v_data.get('vendas_quarta', 0), 'qui': v_data.get('vendas_quinta', 0),
                    'sex': v_data.get('vendas_sexta', 0), 'sab': v_data.get('vendas_sabado', 0)
                },
                'weekly_total': weekly_total,
                'monthly': {
                    'total': total_mes,
                    'instalados': instalados_mes,
                    'aproveitamento': aproveitamento_str
                }
            })

        final_result = []
        for supervisor_id, team_data in teams.items():
            if not team_data['members']:
                continue

            team_data['members'] = sorted(team_data['members'], key=itemgetter('name'))

            for member in team_data['members']:
                team_data['totals']['daily'] += member['daily']
                for day, count in member['weekly_breakdown'].items():
                    team_data['totals']['weekly_breakdown'][day] += count
                team_data['totals']['weekly_total'] += member['weekly_total']
                team_data['totals']['monthly']['total'] += member['monthly']['total']
                team_data['totals']['monthly']['instalados'] += member['monthly']['instalados']
            
            total_geral_mes = team_data['totals']['monthly']['total']
            instalados_geral_mes = team_data['totals']['monthly']['instalados']
            team_data['totals']['monthly']['aproveitamento'] = f"{(instalados_geral_mes / total_geral_mes * 100):.1f}%" if total_geral_mes > 0 else "0.0%"
            
            final_result.append(team_data)
        
        final_result = sorted(final_result, key=itemgetter('supervisor_name'))

        return Response(final_result)