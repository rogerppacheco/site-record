from django.shortcuts import render, redirect
from django.db.models import Sum
from django.views.generic import TemplateView
from .models import DiaFiscal
import calendar
from datetime import date, timedelta

# Mantenha suas views existentes aqui (IndexView, AreaInternaView, etc...)
# Vou incluir apenas as necessárias para não apagar as suas, 
# mas certifique-se de manter as outras classes que você já tem.

class IndexView(TemplateView):
    template_name = "frontend/public/index.html"

class AreaInternaView(TemplateView):
    template_name = "frontend/public/area-interna.html"

class GovernancaView(TemplateView):
    template_name = "core/governanca.html"

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

# --- NOVA VIEW DO CALENDÁRIO ---
def calendario_fiscal_view(request, ano=None, mes=None):
    # 1. Definir Mês/Ano atual se não informado
    hoje = date.today()
    if not ano: ano = hoje.year
    if not mes: mes = hoje.month

    # 2. Processar Salvamento (se for POST)
    if request.method == 'POST':
        dias_ids = request.POST.getlist('dia_id')
        pesos_venda = request.POST.getlist('peso_venda')
        pesos_inst = request.POST.getlist('peso_instalacao')
        obs_list = request.POST.getlist('observacao')

        for i, d_id in enumerate(dias_ids):
            try:
                dia = DiaFiscal.objects.get(id=d_id)
                # Tratamento para converter "0,5" em "0.5" se vier com vírgula
                p_venda = pesos_venda[i].replace(',', '.') if pesos_venda[i] else 0
                p_inst = pesos_inst[i].replace(',', '.') if pesos_inst[i] else 0
                
                dia.peso_venda = float(p_venda)
                dia.peso_instalacao = float(p_inst)
                dia.observacao = obs_list[i]
                dia.save()
            except (ValueError, DiaFiscal.DoesNotExist):
                continue
        
        # Redireciona mantendo o modo iframe se estiver ativo
        redirect_url = f'/calendario/{ano}/{mes}/'
        if request.GET.get('modo') == 'iframe':
            redirect_url += '?modo=iframe'
        return redirect(redirect_url)

    # 3. Gerar Calendário Lógico (CORREÇÃO AQUI)
    # Usamos calendar.Calendar(firstweekday=6) para dizer que a semana começa no Domingo (6)
    # Isso alinha perfeitamente com o cabeçalho da sua tabela HTML (Dom, Seg, Ter...)
    cal = calendar.Calendar(firstweekday=6).monthdayscalendar(ano, mes)
    estrutura_calendario = []
    
    primeiro_dia_mes = date(ano, mes, 1)
    ultimo_dia_mes = date(ano, mes, calendar.monthrange(ano, mes)[1])

    # Pegar todos os dias do banco nesse intervalo
    dias_banco = {d.data: d for d in DiaFiscal.objects.filter(data__range=(primeiro_dia_mes, ultimo_dia_mes))}

    for semana in cal:
        semana_processada = []
        for dia_numero in semana:
            if dia_numero == 0:
                semana_processada.append(None) 
            else:
                data_atual = date(ano, mes, dia_numero)
                
                # Se não existe, CRIA O PADRÃO AGORA
                if data_atual not in dias_banco:
                    weekday = data_atual.weekday() # 0=Seg, 6=Dom
                    p_venda = 0.0 if weekday == 6 else (0.5 if weekday == 5 else 1.0)
                    p_inst = 0.0 if weekday >= 5 else 1.0 
                    
                    novo_dia = DiaFiscal.objects.create(
                        data=data_atual,
                        peso_venda=p_venda,
                        peso_instalacao=p_inst
                    )
                    dias_banco[data_atual] = novo_dia
                
                semana_processada.append(dias_banco[data_atual])
        estrutura_calendario.append(semana_processada)

    # 4. Calcular Totais
    totais = DiaFiscal.objects.filter(data__range=(primeiro_dia_mes, ultimo_dia_mes)).aggregate(
        total_vb=Sum('peso_venda'),
        total_gross=Sum('peso_instalacao')
    )

    # Navegação
    data_atual = date(ano, mes, 1)
    nav_ant = (data_atual - timedelta(days=1))
    nav_prox = (data_atual + timedelta(days=32)).replace(day=1)

    context = {
        'calendario': estrutura_calendario,
        'mes': mes,
        'ano': ano,
        'totais': totais,
        'nome_mes': calendar.month_name[mes],
        'nav_ant': nav_ant,
        'nav_prox': nav_prox,
        'modo_iframe': request.GET.get('modo') == 'iframe'
    }
    
    return render(request, 'core/calendario_fiscal.html', context)