from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated 
from django.http import Http404, HttpResponse
from django.db.models import Q
import pandas as pd
from datetime import datetime, timedelta, date

from .models import MotivoAusencia, Presenca, DiaNaoUtil
from .serializers import MotivoAusenciaSerializer, PresencaSerializer, DiaNaoUtilSerializer
from usuarios.models import Usuario
from usuarios.serializers import UsuarioSerializer

class MotivoViewSet(viewsets.ModelViewSet):
    queryset = MotivoAusencia.objects.all().order_by('motivo')
    serializer_class = MotivoAusenciaSerializer
    permission_classes = [IsAuthenticated]

class PresencaViewSet(viewsets.ModelViewSet):
    serializer_class = PresencaSerializer
    permission_classes = [IsAuthenticated]
    resource_name = 'presenca' 

    def get_queryset(self):
        user = self.request.user
        queryset = Presenca.objects.all()
        
        if self.action in ['destroy', 'update', 'partial_update', 'retrieve']:
            return queryset

        if user.is_superuser or user.groups.filter(name__in=['Diretoria', 'Admin', 'BackOffice']).exists():
            pass 
        elif hasattr(user, 'liderados') and user.liderados.exists():
            liderados_ids = list(user.liderados.values_list('id', flat=True))
            all_ids = liderados_ids + [user.id]
            queryset = queryset.filter(colaborador_id__in=all_ids)
        else:
            queryset = queryset.filter(colaborador=user)

        if self.action == 'list':
            data_selecionada = self.request.query_params.get('data')
            if data_selecionada:
                queryset = queryset.filter(data=data_selecionada)
        
        return queryset

    def destroy(self, request, *args, **kwargs):
        try:
            pk = kwargs.get('pk')
            instance = Presenca.objects.get(pk=pk)
            self.perform_destroy(instance)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Presenca.DoesNotExist:
            return Response({"detail": "Registro não encontrado."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def create(self, request, *args, **kwargs):
        from django.db import transaction
        data = request.data.copy()
        colaborador_id = data.get('colaborador')
        data_registro = data.get('data')
        if not colaborador_id or not data_registro:
            return Response({'detail': 'Colaborador e data são obrigatórios.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                obj, created = Presenca.objects.get_or_create(
                    colaborador_id=colaborador_id,
                    data=data_registro,
                    defaults={
                        'status': data.get('status', True),
                        'motivo_id': data.get('motivo'),
                        'observacao': data.get('observacao', ''),
                        'lancado_por': request.user
                    }
                )
                if not created:
                    # Atualiza apenas campos relevantes
                    update_fields = []
                    if 'status' in data:
                        obj.status = data['status']
                        update_fields.append('status')
                    if 'motivo' in data:
                        obj.motivo_id = data['motivo']
                        update_fields.append('motivo')
                    if 'observacao' in data:
                        obj.observacao = data['observacao']
                        update_fields.append('observacao')
                    obj.editado_por = request.user
                    update_fields.append('editado_por')
                    obj.save(update_fields=update_fields)
                serializer = self.get_serializer(obj)
                return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False) 
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save(editado_por=request.user)
        return Response(serializer.data)


class DiaNaoUtilViewSet(viewsets.ModelViewSet):
    queryset = DiaNaoUtil.objects.all().order_by('-data')
    serializer_class = DiaNaoUtilSerializer
    permission_classes = [IsAuthenticated]

class MinhaEquipeListView(generics.ListAPIView):
    serializer_class = UsuarioSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        user = self.request.user
        qs = getattr(user, 'liderados', None)
        if qs is not None:
            result = qs.filter(is_active=True).order_by('first_name')
        else:
            result = Usuario.objects.none()
        print(f"[DEBUG MinhaEquipeListView] queryset type: {type(result)}, count: {result.count()}")
        return result

class TodosUsuariosListView(generics.ListAPIView):
    from .serializers import UsuarioPresencaSerializer
    serializer_class = UsuarioPresencaSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        qs = Usuario.objects.filter(is_active=True, participa_controle_presenca=True)\
            .select_related('perfil', 'supervisor')\
            .order_by('first_name')
        print(f"[DEBUG TodosUsuariosListView] queryset type: {type(qs)}, count: {qs.count()}")
        return qs

# =========================================================================
# RELATÓRIOS FINANCEIROS (CORRIGIDO)
# =========================================================================

def get_dias_uteis_periodo(inicio, fim):
    """Retorna uma lista de datas (dias úteis) entre inicio e fim, excluindo feriados."""
    feriados = set(DiaNaoUtil.objects.filter(data__range=(inicio, fim)).values_list('data', flat=True))
    dias = []
    atual = inicio
    while atual <= fim:
        # 0=Segunda, 4=Sexta. Sábado(5) e Domingo(6) excluídos.
        if atual.weekday() < 5 and atual not in feriados:
            dias.append(atual)
        atual += timedelta(days=1)
    return dias

class RelatorioFinanceiroView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        inicio_str = request.query_params.get('inicio')
        fim_str = request.query_params.get('fim')

        if not inicio_str or not fim_str:
            return Response({"error": "Datas obrigatórias."}, status=400)

        try:
            dt_ini = datetime.strptime(inicio_str, '%Y-%m-%d').date()
            dt_fim = datetime.strptime(fim_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({"error": "Data inválida."}, status=400)

        # 1. Mapeamento de Dias Úteis
        dias_uteis_lista = get_dias_uteis_periodo(dt_ini, dt_fim)
        qtd_dias_uteis = len(dias_uteis_lista)

        # 2. Usuários Participantes
        usuarios = Usuario.objects.filter(participa_controle_presenca=True, is_active=True).order_by('first_name')

        # 3. Presenças no Período
        presencas = Presenca.objects.filter(
            data__range=(dt_ini, dt_fim),
            colaborador__in=usuarios
        ).select_related('motivo')

        # Mapa: { user_id: { data: { status: bool, gera_desconto: bool } } }
        mapa_presencas = {}
        for p in presencas:
            uid = p.colaborador_id
            if uid not in mapa_presencas: mapa_presencas[uid] = {}
            
            gera_desconto = False
            if not p.status and p.motivo and p.motivo.gera_desconto:
                gera_desconto = True
            
            mapa_presencas[uid][p.data] = {
                'status': p.status,
                'gera_desconto': gera_desconto
            }

        dados_previsao = []
        dados_descontos = []

        for user in usuarios:
            # CORREÇÃO: Usar get_full_name() pois o objeto Model não tem 'nome_completo'
            nome_display = user.get_full_name()
            if not nome_display:
                nome_display = user.username.upper()
            else:
                nome_display = nome_display.upper()

            # Valor Diário = Almoço + Passagem (Campos do modelo Usuario)
            val_almoco = float(user.valor_almoco or 0)
            val_passagem = float(user.valor_passagem or 0)
            valor_diario = val_almoco + val_passagem

            # --- PREVISÃO (Cenário Ideal: Trabalhar todos os dias úteis) ---
            total_previsao = qtd_dias_uteis * valor_diario
            dados_previsao.append({
                'nome': nome_display,
                'dias_uteis': qtd_dias_uteis,
                'valor_diario': valor_diario,
                'total_receber': total_previsao
            })

            # --- APURAÇÃO REAL (Faltas) ---
            user_records = mapa_presencas.get(user.id, {})
            datas_faltas = []

            for dia in dias_uteis_lista:
                rec = user_records.get(dia)
                
                if rec:
                    # Se tem registro
                    # É falta se status=Ausente E gera_desconto=True
                    if rec['status'] == False and rec['gera_desconto'] == True:
                        datas_faltas.append(dia)
                else:
                    # Sem registro no dia útil = Falta (Buraco)
                    datas_faltas.append(dia)

            qtd_faltas = len(datas_faltas)
            valor_desconto = qtd_faltas * valor_diario
            total_liquido = total_previsao - valor_desconto

            dados_descontos.append({
                'nome': nome_display,
                'dias_uteis': qtd_dias_uteis,
                'qtd_faltas': qtd_faltas,
                'datas_faltas': [d.strftime('%d/%m/%Y') for d in datas_faltas], # Lista formatada para o modal
                'valor_diario': valor_diario,
                'valor_desconto': valor_desconto,
                'total_receber': total_liquido
            })

        return Response({
            'previsao': dados_previsao,
            'descontos': dados_descontos
        })

class ExportarRelatorioFinanceiroExcelView(RelatorioFinanceiroView):
    # Herda a lógica acima para não duplicar código
    def get(self, request):
        response_data = super().get(request)
        if response_data.status_code != 200:
            return response_data
        
        dados = response_data.data 
        lista_final = dados['descontos'] # Usa a lista de descontos/realizado

        export_list = []
        for item in lista_final:
            export_list.append({
                'Colaborador': item['nome'],
                'Dias Úteis': item['dias_uteis'],
                'Valor Diário (R$)': item['valor_diario'],
                'Previsão Total (R$)': item['dias_uteis'] * item['valor_diario'],
                'Qtd Faltas': item['qtd_faltas'],
                'Valor Desconto (R$)': item['valor_desconto'],
                'Total a Receber (R$)': item['total_receber'],
                'Datas das Faltas': ", ".join(item['datas_faltas'])
            })

        df = pd.DataFrame(export_list)
        
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        filename = f"Financeiro_{request.query_params.get('inicio')}_{request.query_params.get('fim')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        # Requer openpyxl instalado (pip install openpyxl)
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Financeiro')
        
        return response