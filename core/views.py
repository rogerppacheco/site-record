from django.shortcuts import render, redirect
from django.db.models import Sum
from django.views.generic import TemplateView
from datetime import date, timedelta
import calendar

# DRF Imports
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import IsAuthenticated
# --- IMPORTAÇÃO NECESSÁRIA PARA O JWT ---
from rest_framework_simplejwt.authentication import JWTAuthentication

# Imports dos Modelos Novos
from .models import DiaFiscal, RegraAutomacao
from .serializers import RegraAutomacaoSerializer

# Autenticação para ignorar CSRF na API (Útil se usar Sessão com Ajax, mas o JWT é o principal aqui)
class CsrfExemptSessionAuthentication(SessionAuthentication):
    def enforce_csrf(self, request):
        return 

# --- VIEWSET DA NOVA REGRA DE AUTOMAÇÃO ---
class RegraAutomacaoViewSet(viewsets.ModelViewSet):
    queryset = RegraAutomacao.objects.all()
    serializer_class = RegraAutomacaoSerializer
    # --- CORREÇÃO: Adicionado JWTAuthentication para aceitar o Token do Frontend ---
    authentication_classes = (CsrfExemptSessionAuthentication, BasicAuthentication, JWTAuthentication)
    permission_classes = [IsAuthenticated]

# --- SUAS VIEWS DE TEMPLATE ---
class IndexView(TemplateView):
    template_name = "frontend/public/index.html"

class AreaInternaView(TemplateView):
    template_name = "frontend/public/area-interna.html"

class GovernancaView(TemplateView):
    # Ajustado para o caminho correto se estiver usando a pasta public
    template_name = "public/governanca.html"

class PresencaView(TemplateView):
    template_name = "frontend/public/presenca.html"

class CrmVendasView(TemplateView):
    template_name = "frontend/public/crm_vendas.html"

class ConsultaCpfView(TemplateView):
    template_name = "frontend/public/index.html"

class ConsultaTratamentoView(TemplateView):
    template_name = "frontend/public/area-interna.html"

class AuditoriaView(TemplateView):
    template_name = "frontend/public/auditoria.html"

class SalvarOsabView(TemplateView):
    template_name = "frontend/public/salvar_osab.html"

class SalvarChurnView(TemplateView):
    template_name = "frontend/public/salvar_churn.html"

# --- VIEW DO CALENDÁRIO FISCAL ---
def calendario_fiscal_view(request, ano=None, mes=None):
    hoje = date.today()
    if not ano: ano = hoje.year
    if not mes: mes = hoje.month

    if request.method == 'POST':
        dias_ids = request.POST.getlist('dia_id')
        pesos_venda = request.POST.getlist('peso_venda')
        pesos_inst = request.POST.getlist('peso_instalacao')
        obs_list = request.POST.getlist('observacao')

        for i, d_id in enumerate(dias_ids):
            try:
                dia = DiaFiscal.objects.get(id=d_id)
                p_venda = pesos_venda[i].replace(',', '.') if pesos_venda[i] else 0
                p_inst = pesos_inst[i].replace(',', '.') if pesos_inst[i] else 0
                
                dia.peso_venda = float(p_venda)
                dia.peso_instalacao = float(p_inst)
                dia.observacao = obs_list[i]
                dia.save()
            except (ValueError, DiaFiscal.DoesNotExist):
                continue
        
        redirect_url = f'/calendario/{ano}/{mes}/'
        if request.GET.get('modo') == 'iframe':
            redirect_url += '?modo=iframe'
        return redirect(redirect_url)

    # Lógica de Montagem do Calendário
    cal = calendar.Calendar(firstweekday=6).monthdayscalendar(ano, mes)
    estrutura_calendario = []
    primeiro_dia_mes = date(ano, mes, 1)
    ultimo_dia_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])
    dias_banco = {d.data: d for d in DiaFiscal.objects.filter(data__range=(primeiro_dia_mes, ultimo_dia_mes))}

    for semana in cal:
        semana_processada = []
        for dia_numero in semana:
            if dia_numero == 0:
                semana_processada.append(None) 
            else:
                data_atual = date(ano, mes, dia_numero)
                if data_atual not in dias_banco:
                    weekday = data_atual.weekday()
                    # Regra padrão: Dom=0, Sáb=0.5 (Venda), Sáb/Dom=0 (Instalação)
                    p_venda = 0.0 if weekday == 6 else (0.5 if weekday == 5 else 1.0)
                    p_inst = 0.0 if weekday >= 5 else 1.0 
                    novo_dia = DiaFiscal.objects.create(data=data_atual, peso_venda=p_venda, peso_instalacao=p_inst)
                    dias_banco[data_atual] = novo_dia
                semana_processada.append(dias_banco[data_atual])
        estrutura_calendario.append(semana_processada)

    totais = DiaFiscal.objects.filter(data__range=(primeiro_dia_mes, ultimo_dia_mes)).aggregate(
        total_vb=Sum('peso_venda'), total_gross=Sum('peso_instalacao')
    )
    
    nav_ant = (date(ano, mes, 1) - timedelta(days=1))
    nav_prox = (date(ano, mes, 1) + timedelta(days=32)).replace(day=1)

    context = {
        'calendario': estrutura_calendario, 'mes': mes, 'ano': ano, 'totais': totais,
        'nome_mes': calendar.month_name[mes], 'nav_ant': nav_ant, 'nav_prox': nav_prox,
        'modo_iframe': request.GET.get('modo') == 'iframe'
    }
    
    # --- CORREÇÃO: Caminho do template simplificado (Django já busca dentro de 'templates') ---
    return render(request, 'core/calendario_fiscal.html', context)