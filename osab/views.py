# osab/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
import pandas as pd
import numpy as np

# --- 1. Importe a nova classe de permissão ---
from usuarios.permissions import CheckAPIPermission

from .models import Osab
from crm_app.models import Venda, StatusCRM


class UploadOsabView(APIView):
    # --- 2. Aplique a permissão dinâmica e defina o nome do recurso ---
    permission_classes = [CheckAPIPermission]
    resource_name = 'osab' # O nome para cadastrar na tela de Governança

    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "Nenhum arquivo enviado."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # --- LEITURA E LIMPEZA DOS DADOS DA PLANILHA ---
            df = pd.read_excel(file_obj, engine='pyxlsb')
            df.columns = [str(col).strip().upper() for col in df.columns]
            
            if 'DOCUMENTO' not in df.columns or 'SITUACAO' not in df.columns:
                return Response({"error": "O arquivo precisa conter as colunas 'DOCUMENTO' e 'SITUACAO'."}, status=status.HTTP_400_BAD_REQUEST)

            df = df.replace({np.nan: None})
            
            # --- PREPARAÇÃO DOS DADOS DO SISTEMA ---
            STATUS_MAP = {
                'CONCLUÍDO': 'INSTALADA',
                'CANCELADO': 'CANCELADA',
                'CANCELADO - SEM APROVISIONAMENTO': 'CANCELADA',
                'PENDÊNCIA CLIENTE': 'PENDENCIADA',
                'PENDÊNCIA TÉCNICA': 'PENDENCIADA',
                'EM APROVISIONAMENTO': 'EM ANDAMENTO',
                'AGUARDANDO PAGAMENTO': 'AGUARDANDO PAGAMENTO',
                'REPROVADO ANALISE DE FRAUDE': 'REPROVADO CARTÃO DE CRÉDITO',
                'DRAFT': 'DRAFT',
                'DRAFT - PRAZO CC EXPIRADO': 'DRAFT',
            }

            status_esteira_objects = StatusCRM.objects.filter(tipo='Esteira')
            status_esteira_map = {status.nome.upper(): status for status in status_esteira_objects}

            vendas_com_os = Venda.objects.filter(ordem_servico__isnull=False).exclude(ordem_servico__exact='')
            vendas_map = {venda.ordem_servico: venda for venda in vendas_com_os}

            # --- PROCESSAMENTO E ATUALIZAÇÃO ---
            report = {
                "total_records": len(df),
                "found_sales": 0,
                "updated_sales": 0,
                "already_correct": 0,
                "unmapped_status": 0,
                "not_found_docs": []
            }
            
            vendas_para_atualizar = []

            for index, row in df.iterrows():
                documento = row.get('DOCUMENTO')
                situacao_osab = row.get('SITUACAO')

                if not documento:
                    continue

                venda = vendas_map.get(str(documento))

                if not venda:
                    report["not_found_docs"].append(str(documento))
                    continue
                
                report["found_sales"] += 1
                
                if not situacao_osab:
                    continue

                target_status_name = STATUS_MAP.get(str(situacao_osab).upper())

                if not target_status_name:
                    report["unmapped_status"] += 1
                    continue

                target_status_obj = status_esteira_map.get(target_status_name.upper())

                if not target_status_obj:
                    print(f"Alerta: O status '{target_status_name}' mapeado não foi encontrado no banco de dados.")
                    report["unmapped_status"] += 1
                    continue

                if venda.status_esteira_id == target_status_obj.id:
                    report["already_correct"] += 1
                else:
                    venda.status_esteira = target_status_obj
                    vendas_para_atualizar.append(venda)
                    report["updated_sales"] += 1

            if vendas_para_atualizar:
                Venda.objects.bulk_update(vendas_para_atualizar, ['status_esteira'])

            return Response(report, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": f"Ocorreu um erro inesperado: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)