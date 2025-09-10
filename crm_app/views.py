from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from django.db.models import Count, Q
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
import pandas as pd
import numpy as np
from datetime import datetime

from usuarios.permissions import CheckAPIPermission

from .models import (
    Operadora, Plano, FormaPagamento, StatusCRM, MotivoPendencia,
    RegraComissao, Cliente, Venda, ImportacaoOsab, ImportacaoChurn,
    CicloPagamento
)
from .serializers import (
    OperadoraSerializer, PlanoSerializer, FormaPagamentoSerializer,
    StatusCRMSerializer, MotivoPendenciaSerializer, RegraComissaoSerializer,
    VendaSerializer, VendaCreateSerializer, ClienteSerializer,
    VendaUpdateSerializer, ImportacaoOsabSerializer, ImportacaoChurnSerializer,
    CicloPagamentoSerializer
)

# --- VIEWS DE CADASTROS GERAIS ---

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
    permission_classes = [CheckAPIPermission]
    resource_name = 'motivos_pendencia'

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
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return VendaCreateSerializer
        if self.action in ['update', 'partial_update']:
            return VendaUpdateSerializer
        return VendaSerializer

    def get_queryset(self):
        user = self.request.user
        ordem_servico = self.request.query_params.get('ordem_servico')
        
        if ordem_servico:
            return Venda.objects.filter(ordem_servico__iexact=ordem_servico)

        flow = self.request.query_params.get('flow', None)
        
        queryset = Venda.objects.select_related(
            'vendedor', 'cliente', 'plano', 'forma_pagamento', 
            'status_tratamento', 'status_esteira', 'status_comissionamento'
        ).order_by('-data_criacao')

        perfil_nome = user.perfil.nome if hasattr(user, 'perfil') and user.perfil else None
        
        try:
            status_cadastrada = StatusCRM.objects.get(nome__iexact='CADASTRADA', tipo__iexact='Tratamento')
            status_instalada = StatusCRM.objects.get(nome__iexact='INSTALADA', tipo__iexact='Esteira')
            
            if flow == 'esteira':
                queryset = queryset.filter(
                    status_tratamento=status_cadastrada
                ).exclude(status_esteira=status_instalada)
            elif flow == 'comissionamento':
                queryset = queryset.filter(status_esteira=status_instalada)
            elif flow == 'auditoria':
                queryset = queryset.exclude(
                    Q(status_tratamento=status_cadastrada)
                    | Q(status_esteira=status_instalada)
                )
        except StatusCRM.DoesNotExist:
            queryset = Venda.objects.none()

        if user.is_superuser or perfil_nome in ['Diretoria', 'BackOffice']:
            return queryset

        if hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = user.liderados.values_list('id', flat=True)
            all_ids = list(liderados_ids) + [user.id]
            return queryset.filter(vendedor_id__in=all_ids)
        
        return queryset.filter(vendedor=user)

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

        serializer.save(
            vendedor=self.request.user,
            cliente=cliente,
            status_tratamento=status_inicial
        )

    def perform_update(self, serializer):
        old_venda = self.get_object()
        serializer.save()
        updated_venda = serializer.instance

        if updated_venda.status_tratamento and updated_venda.status_tratamento.nome.upper() == 'CADASTRADA' and not updated_venda.status_esteira:
            try:
                status_agendado = StatusCRM.objects.get(nome__iexact="AGENDADO", tipo__iexact="Esteira")
                updated_venda.status_esteira = status_agendado
                updated_venda.save(update_fields=['status_esteira'])
                print(f"Venda {updated_venda.id} movida para a Esteira com status 'AGENDADO'.")
            except StatusCRM.DoesNotExist:
                print("ERRO: O status 'AGENDADO' para a Esteira não foi encontrado.")

class ClienteViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ClienteSerializer
    permission_classes = [CheckAPIPermission]
    resource_name = 'clientes'

    def get_queryset(self):
        queryset = Cliente.objects.all().annotate(vendas_count=Count('vendas'))
        
        search_query = self.request.query_params.get('search', None)
        if search_query:
            queryset = queryset.filter(
                Q(cpf_cnpj__icontains=search_query) | 
                Q(nome_razao_social__icontains=search_query)
            )
        return queryset

# --- VIEW DE IMPORTAÇÃO OSAB (VERSÃO FINAL) ---
class ImportacaoOsabView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_osab'
    parser_classes = [MultiPartParser, FormParser]

    def _clean_key(self, key):
        if pd.isna(key) or key is None:
            return None
        return str(key).replace('.0', '').strip()

    def post(self, request, *args, **kwargs):
        print("\n--- [LOG] INÍCIO DA ATUALIZAÇÃO DE VENDAS VIA OSAB ---")
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'Nenhum arquivo foi enviado.'}, status=status.HTTP_400_BAD_REQUEST)

        print(f"--- [LOG] Arquivo recebido: {file_obj.name}")

        try:
            df = None
            if file_obj.name.endswith('.xlsb'):
                df = pd.read_excel(file_obj, engine='pyxlsb')
            elif file_obj.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_obj)
            else:
                return Response({'error': 'Formato de arquivo inválido.'}, status=status.HTTP_400_BAD_REQUEST)
            print("--- [LOG] Leitura do arquivo concluída com sucesso.")
        except Exception as e:
            return Response({'error': f'Erro ao ler o arquivo: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        
        df.columns = [str(col).strip().upper() for col in df.columns]
        
        if 'DOCUMENTO' not in df.columns or 'SITUACAO' not in df.columns:
            return Response({"error": "O arquivo precisa conter as colunas 'DOCUMENTO' e 'SITUACAO'."}, status=status.HTTP_400_BAD_REQUEST)

        df = df.replace({np.nan: None, pd.NaT: None})

        print("--- [LOG] Mapeando status e buscando vendas no sistema...")
        STATUS_MAP = {
            'CONCLUÍDO': 'INSTALADA', 'CANCELADO': 'CANCELADA',
            'CANCELADO - SEM APROVISIONAMENTO': 'CANCELADA', 'PENDÊNCIA CLIENTE': 'PENDENCIADA',
            'PENDÊNCIA TÉCNICA': 'PENDENCIADA', 'EM APROVISIONAMENTO': 'EM ANDAMENTO',
            'AGUARDANDO PAGAMENTO': 'AGUARDANDO PAGAMENTO', 'REPROVADO ANALISE DE FRAUDE': 'REPROVADO CARTÃO DE CRÉDITO',
            'DRAFT': 'DRAFT', 'DRAFT - PRAZO CC EXPIRADO': 'DRAFT',
        }
        
        status_esteira_objects = StatusCRM.objects.filter(tipo='Esteira')
        status_esteira_map = {status.nome.upper(): status for status in status_esteira_objects}

        vendas_com_os = Venda.objects.filter(ordem_servico__isnull=False).exclude(ordem_servico__exact='')
        vendas_map = {self._clean_key(v.ordem_servico): v for v in vendas_com_os}
        
        print("\n--- [DIAGNÓSTICO] ---")
        print(f"Total de Vendas com OS no sistema: {len(vendas_map)}")
        print(f"Amostra de 5 chaves do BANCO DE DADOS: {[key for key in list(vendas_map.keys())[:5]]}")
        
        docs_from_file = [self._clean_key(doc) for doc in df['DOCUMENTO'].dropna().unique()]
        print(f"Total de Documentos únicos no ARQUIVO: {len(docs_from_file)}")
        print(f"Amostra de 5 chaves do ARQUIVO: {docs_from_file[:5]}\n")
        
        # --- RESPOSTA PADRONIZADA PARA O FRONTEND ---
        report = {
            "status": "sucesso",
            "total_registros": len(df),
            "criados": 0, # Esta lógica não cria, então sempre será 0.
            "atualizados": 0,
            "vendas_encontradas": 0,
            "ja_corretos": 0,
            "status_nao_mapeado": 0,
            "erros": []
        }
        vendas_para_atualizar = []
        
        print(f"--- [LOG] Iniciando processamento de {len(df)} linhas...")
        for index, row in df.iterrows():
            documento_bruto = row.get('DOCUMENTO')
            documento_limpo = self._clean_key(documento_bruto)
            situacao_osab = row.get('SITUACAO')

            if not documento_limpo:
                continue

            venda = vendas_map.get(documento_limpo)

            if not venda:
                report["erros"].append(f"Linha {index + 2}: Documento {documento_limpo} não encontrado no sistema.")
                continue
            
            report["vendas_encontradas"] += 1
            
            if not situacao_osab:
                continue

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
            print(f"--- [LOG] Atualizando {len(vendas_para_atualizar)} vendas em lote...")
            Venda.objects.bulk_update(vendas_para_atualizar, ['status_esteira'])
            print("--- [LOG] Atualização em lote concluída.")

        print("--- [LOG] Processamento finalizado.")
        return Response(report, status=status.HTTP_200_OK)


# --- VIEW DE IMPORTAÇÃO CHURN ---
class ImportacaoChurnView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_churn'
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'Nenhum arquivo foi enviado.'}, status=status.HTTP_400_BAD_REQUEST)

        coluna_map = {
            'UF': 'uf', 'PRODUTO': 'produto', 'MATRICULA_VENDEDOR': 'matricula_vendedor',
            'GV': 'gv', 'SAP_PRINCIPAL_FIM': 'sap_principal_fim', 'GESTAO': 'gestao',
            'ST_REGIONAL': 'st_regional', 'GC': 'gc', 'NUMERO_PEDIDO': 'numero_pedido',
            'DT_GROSS': 'dt_gross', 'ANOMES_GROSS': 'anomes_gross', 'DT_RETIRADA': 'dt_retirada',
            'ANOMES_RETIRADA': 'anomes_retirada', 'GRUPO_UNIDADE': 'grupo_unidade',
            'CODIGO_SAP': 'codigo_sap', 'MUNICIPIO': 'municipio', 'TIPO_RETIRADA': 'tipo_retirada',
            'MOTIVO_RETIRADA': 'motivo_retirada', 'SUBMOTIVO_RETIRADA': 'submotivo_retirada',
            'CLASSIFICACAO': 'classificacao', 'DESC_APELIDO': 'desc_apelido',
        }
        
        colunas_esperadas = list(coluna_map.keys())

        try:
            df = None
            if file_obj.name.endswith('.xlsb'):
                df = pd.read_excel(file_obj, engine='pyxlsb', usecols=lambda c: c.strip().upper() in colunas_esperadas)
            elif file_obj.name.endswith(('.xlsx', '.xls')):
                df = pd.read_excel(file_obj, usecols=lambda c: c.strip().upper() in colunas_esperadas)
            else:
                return Response({'error': 'Formato de arquivo inválido. Apenas .xlsb, .xlsx, .xls são aceitos.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Erro ao ler o arquivo. Verifique se todas as colunas esperadas existem: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

        df.columns = [str(col).strip().upper() for col in df.columns]
        
        date_fields_churn = ['DT_GROSS', 'DT_RETIRADA']
        for field in date_fields_churn:
            if field in df.columns:
                df[field] = pd.to_datetime(df[field], errors='coerce')

        df = df.replace({np.nan: None, pd.NaT: None})
            
        df.rename(columns=coluna_map, inplace=True)
        
        registros_criados = 0
        registros_atualizados = 0
        erros_importacao = []

        model_fields = {f.name for f in ImportacaoChurn._meta.get_fields()}

        for index, row in df.iterrows():
            row_data = row.to_dict()
            numero_pedido = row_data.get('numero_pedido')
            if not numero_pedido:
                erros_importacao.append(f'Linha {index+2}: Número do pedido ausente.')
                continue

            defaults_data = {key: value for key, value in row_data.items() if key in model_fields}

            try:
                obj, created = ImportacaoChurn.objects.update_or_create(
                    numero_pedido=numero_pedido,
                    defaults=defaults_data
                )
                if created:
                    registros_criados += 1
                else:
                    registros_atualizados += 1
            except Exception as e:
                erros_importacao.append(f'Linha {index+2}: Erro ao salvar registro: {str(e)}')

        return Response({
            'status': 'sucesso',
            'total_registros': len(df),
            'criados': registros_criados,
            'atualizados': registros_atualizados,
            'erros': erros_importacao
        }, status=status.HTTP_200_OK)

# =======================================================================================
# NOVA VIEW PARA IMPORTAÇÃO DO CICLO DE PAGAMENTO
# =======================================================================================
class ImportacaoCicloPagamentoView(APIView):
    permission_classes = [CheckAPIPermission]
    resource_name = 'importacao_ciclo_pagamento'
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'Nenhum arquivo enviado.'}, status=status.HTTP_400_BAD_REQUEST)

        coluna_map = {
            'ANO': 'ano', 'MES': 'mes', 'QUINZENA': 'quinzena', 'CICLO': 'ciclo',
            'CICLO_COMPLEMENTAR': 'ciclo_complementar', 'EVENTO': 'evento', 'SUB_EVENTO': 'sub_evento',
            'CANAL_DETALHADO': 'canal_detalhado', 'CANAL_AGRUPADO': 'canal_agrupado',
            'SUB_CANAL': 'sub_canal', 'COD_SAP': 'cod_sap', 'COD_SAP_AGR': 'cod_sap_agr',
            'PARCEIRO_AGR': 'parceiro_agr', 'UF_PARCEIRO_AGR': 'uf_parceiro_agr', 'FAMILIA': 'familia',
            'PRODUTO': 'produto', 'OFERTA': 'oferta', 'PLANO_DETALHADO': 'plano_detalhado',
            'CELULA': 'celula', 'METODO_PAGAMENTO': 'metodo_pagamento', 'CONTRATO': 'contrato',
            'NUM_OS_PEDIDO_SIEBEL': 'num_os_pedido_siebel', 'ID_BUNDLE': 'id_bundle',
            'DATA_ATV': 'data_atv', 'DATA_RETIRADA': 'data_retirada', 'QTD': 'qtd',
            'COMISSAO_BRUTA': 'comissao_bruta', 'FATOR': 'fator', 'IQ': 'iq',
            'VALOR_COMISSAO_FINAL': 'valor_comissao_final'
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
            return Response({'error': f'Erro ao ler o arquivo. Verifique se as colunas estão corretas: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

        df.columns = [str(col).strip().upper() for col in df.columns]
        df.rename(columns=coluna_map, inplace=True)
        
        date_fields = ['data_atv', 'data_retirada']
        for field in date_fields:
            if field in df.columns:
                df[field] = pd.to_datetime(df[field], errors='coerce')

        # Limpeza de campos numéricos
        numeric_fields = ['comissao_bruta', 'fator', 'iq', 'valor_comissao_final']
        for field in numeric_fields:
            if field in df.columns:
                # Remove R$, pontos de milhar e substitui vírgula por ponto
                df[field] = df[field].astype(str).str.replace('R$', '', regex=False).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df[field] = pd.to_numeric(df[field], errors='coerce')

        df = df.replace({np.nan: None, pd.NaT: None})

        registros_criados = 0
        registros_atualizados = 0
        erros = []

        model_fields = {f.name for f in CicloPagamento._meta.get_fields()}
        
        for index, row in df.iterrows():
            row_data = row.to_dict()
            contrato = row_data.get('contrato')
            
            if not contrato:
                erros.append(f'Linha {index+2}: O número do contrato é obrigatório.')
                continue

            defaults_data = {key: value for key, value in row_data.items() if key in model_fields}

            try:
                obj, created = CicloPagamento.objects.update_or_create(
                    contrato=contrato,
                    defaults=defaults_data
                )
                if created:
                    registros_criados += 1
                else:
                    registros_atualizados += 1
            except Exception as e:
                erros.append(f'Linha {index+2}: Erro ao salvar o registro: {str(e)}')

        return Response({
            'total_registros': len(df),
            'criados': registros_criados,
            'atualizados': registros_atualizados,
            'erros': erros
        }, status=status.HTTP_200_OK)