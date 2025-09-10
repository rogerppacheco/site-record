# relatorios/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.db import connection, transaction
from django.db.utils import OperationalError
from datetime import datetime

def get_dias_uteis_no_periodo(data_inicio, data_fim):
    """
    Função auxiliar para calcular dias úteis, compatível com SQLite.
    """
    # --- CORREÇÃO APLICADA AQUI: Sintaxe SQL alterada para SQLite ---
    query = """
        WITH RECURSIVE DateRange(data) AS (
          SELECT %s AS data
          UNION ALL
          SELECT date(data, '+1 day')
          FROM DateRange
          WHERE data < %s
        )
        SELECT COUNT(*)
        FROM DateRange
        WHERE
          strftime('%%w', data) NOT IN ('0', '6') AND -- 0 é Domingo, 6 é Sábado no SQLite
          data NOT IN (SELECT data FROM presenca_dianaoutil)
    """
    with connection.cursor() as cursor:
        cursor.execute(query, [data_inicio.isoformat(), data_fim.isoformat()])
        result = cursor.fetchone()
    return result[0] if result else 0

def validar_datas(request):
    """
    Função auxiliar para validar os parâmetros de data do request.
    """
    data_inicio_str = request.query_params.get('dataInicio')
    data_fim_str = request.query_params.get('dataFim')

    if not data_inicio_str or not data_fim_str:
        return None, None, Response(
            {"msg": "Os parâmetros 'dataInicio' e 'dataFim' são obrigatórios."},
            status=status.HTTP_400_BAD_REQUEST
        )
    try:
        data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
        return data_inicio, data_fim, None
    except ValueError:
        return None, None, Response(
            {"msg": "Formato de data inválido. Use AAAA-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST
        )

# --- VIEW PARA O RELATÓRIO DE PREVISÃO ---
class RelatorioPrevisaoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        data_inicio, data_fim, error_response = validar_datas(request)
        if error_response:
            return error_response
        
        try:
            dias_uteis = get_dias_uteis_no_periodo(data_inicio, data_fim)

            # --- CORREÇÃO APLICADA AQUI: Sintaxe SQL alterada para SQLite ---
            query = """
                SELECT
                    u.first_name || ' ' || u.last_name as nome_completo, -- CONCAT trocado por ||
                    u.valor_almoco,
                    u.valor_passagem
                FROM usuarios_usuario u
                WHERE u.is_active = 1 -- 'true' trocado por 1
            """
            with connection.cursor() as cursor:
                cursor.execute(query)
                usuarios = cursor.fetchall()
            
            dados_relatorio = []
            for user in usuarios:
                nome_completo, valor_almoco, valor_passagem = user
                valor_almoco = valor_almoco or 0
                valor_passagem = valor_passagem or 0
                auxilio_diario = valor_almoco + valor_passagem
                previsao_periodo = dias_uteis * auxilio_diario
                dados_relatorio.append({
                    'nome_completo': nome_completo.strip(),
                    'auxilio_diario': f"{auxilio_diario:.2f}",
                    'previsao_periodo': f"{previsao_periodo:.2f}",
                })
            
            return Response({
                "periodo": {"inicio": data_inicio, "fim": data_fim, "dias_uteis": dias_uteis},
                "dados": dados_relatorio
            })

        except OperationalError as e:
            return Response({"msg": f"Erro no banco de dados: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"msg": f"Ocorreu um erro: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- VIEW PARA O RELATÓRIO DE DESCONTOS ---
class RelatorioDescontosView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        data_inicio, data_fim, error_response = validar_datas(request)
        if error_response:
            return error_response
        
        try:
            # --- CORREÇÃO APLICADA AQUI: Sintaxe SQL alterada para SQLite ---
            query = """
                SELECT
                    u.first_name || ' ' || u.last_name as nome_completo, -- CONCAT trocado por ||
                    pp.data,
                    ma.motivo,
                    (u.valor_almoco + u.valor_passagem) as valor_desconto
                FROM presenca_presenca pp
                JOIN usuarios_usuario u ON pp.colaborador_id = u.id
                LEFT JOIN presenca_motivoausencia ma ON pp.motivo_id = ma.id
                WHERE pp.status = 0
                  AND ma.gera_desconto = 1 -- 'true' trocado por 1
                  AND pp.data BETWEEN %s AND %s
                ORDER BY u.first_name, pp.data
            """
            with connection.cursor() as cursor:
                cursor.execute(query, [data_inicio, data_fim])
                descontos = cursor.fetchall()

            dados_relatorio = []
            for item in descontos:
                nome_completo, data_falta, motivo, valor_desconto = item
                dados_relatorio.append({
                    'nome_completo': nome_completo.strip(),
                    'data': data_falta,
                    'motivo': motivo or "Não especificado",
                    'valor_desconto': f"{(valor_desconto or 0):.2f}"
                })

            return Response({
                "periodo": {"inicio": data_inicio, "fim": data_fim},
                "dados": dados_relatorio
            })
        
        except OperationalError as e:
            return Response({"msg": f"Erro no banco de dados: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"msg": f"Ocorreu um erro: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# --- VIEW PARA O RELATÓRIO FINAL ---
class RelatorioFinalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        data_inicio, data_fim, error_response = validar_datas(request)
        if error_response:
            return error_response
        
        try:
            dias_uteis = get_dias_uteis_no_periodo(data_inicio, data_fim)

            # --- CORREÇÃO APLICADA AQUI: Sintaxe SQL alterada para SQLite ---
            query = """
                SELECT
                    u.id,
                    u.first_name || ' ' || u.last_name as nome_completo, -- CONCAT trocado por ||
                    u.valor_almoco,
                    u.valor_passagem,
                    (SELECT COUNT(*)
                       FROM presenca_presenca pp
                       JOIN presenca_motivoausencia ma ON pp.motivo_id = ma.id
                       WHERE pp.colaborador_id = u.id
                         AND pp.status = 0
                         AND ma.gera_desconto = 1 -- 'true' trocado por 1
                         AND pp.data BETWEEN %s AND %s
                    ) as dias_falta_com_desconto
                FROM usuarios_usuario u
                WHERE u.is_active = 1 -- 'true' trocado por 1
            """
            with connection.cursor() as cursor:
                cursor.execute(query, [data_inicio, data_fim])
                usuarios = cursor.fetchall()

            dados_relatorio = []
            for user in usuarios:
                user_id, nome_completo, valor_almoco, valor_passagem, dias_falta_com_desconto = user
                
                valor_almoco = valor_almoco or 0
                valor_passagem = valor_passagem or 0
                dias_falta_com_desconto = dias_falta_com_desconto or 0

                dias_trabalhados = dias_uteis - dias_falta_com_desconto
                auxilio_diario = valor_almoco + valor_passagem
                
                total_a_receber_bruto = dias_uteis * auxilio_diario
                total_a_descontar = dias_falta_com_desconto * auxilio_diario
                valor_final_liquido = total_a_receber_bruto - total_a_descontar

                dados_relatorio.append({
                    'nome_completo': nome_completo.strip(),
                    'dias_uteis_periodo': dias_uteis,
                    'dias_trabalhados': dias_trabalhados,
                    'dias_falta_com_desconto': dias_falta_com_desconto,
                    'total_a_receber': f"{total_a_receber_bruto:.2f}",
                    'total_a_descontar': f"{total_a_descontar:.2f}",
                    'valor_final': f"{valor_final_liquido:.2f}"
                })

            return Response({
                "periodo": {"inicio": data_inicio, "fim": data_fim, "dias_uteis": dias_uteis},
                "dados": dados_relatorio
            })
        
        except OperationalError as e:
            return Response({"msg": f"Erro no banco de dados: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"msg": f"Ocorreu um erro: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)