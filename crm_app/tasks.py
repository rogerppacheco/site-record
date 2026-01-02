import logging
from django.utils import timezone
from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from .models import Venda, AgendamentoDisparo
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

def processar_envio_performance():
    """Lógica principal chamada pelo Scheduler"""
    agora = timezone.localtime(timezone.now())
    hora = agora.hour
    minuto = agora.minute
    dia_sem = agora.weekday() # 0=Seg, 1=Ter, 2=Qua, 3=Qui, 4=Sex, 5=Sáb, 6=Dom
    
    regras = AgendamentoDisparo.objects.filter(ativo=True)
    svc = WhatsAppService()
    User = get_user_model()

    for regra in regras:
        enviar = False
        
        # --- VERIFICAÇÃO DE HORÁRIO ---
        if regra.tipo == 'HORARIO': # Hora a hora conforme dia da semana
            # Segunda a Sexta: 8h30 até 17h (verifica se já passou dos 30min da hora 8)
            if dia_sem in [0, 1, 2, 3, 4]:  # Seg-Sex
                if (hora == 8 and minuto >= 30) or (9 <= hora <= 16) or (hora == 17 and minuto == 0):
                    if not regra.ultimo_disparo or regra.ultimo_disparo.hour != hora or regra.ultimo_disparo.date() != agora.date():
                        enviar = True
            
            # Sábado: 9h até 12h
            elif dia_sem == 5:  # Sábado
                if 9 <= hora <= 12:
                    if not regra.ultimo_disparo or regra.ultimo_disparo.hour != hora or regra.ultimo_disparo.date() != agora.date():
                        enviar = True
            
            # Domingo: Não enviar (dia_sem == 6)
        
        elif regra.tipo == 'SEMANAL': # Ter/Qui/Sáb às 17h
            if dia_sem in [1, 3, 5] and hora == 17:
                if not regra.ultimo_disparo or regra.ultimo_disparo.date() != agora.date():
                    enviar = True

        if enviar:
            try:
                # 1. Coletar Dados do Banco
                hoje = agora.date()
                users = User.objects.filter(is_active=True).exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])
                
                if regra.canal_alvo != 'TODOS':
                    users = users.filter(canal__iexact=regra.canal_alvo)

                filtro = Q(vendas__ativo=True, vendas__data_abertura__date=hoje)
                qs = users.annotate(
                    total=Count('vendas', filter=filtro),
                    cc=Count('vendas', filter=filtro & (Q(vendas__forma_pagamento__nome__icontains='CREDIT') | Q(vendas__forma_pagamento__nome__icontains='CARTA')))
                ).filter(total__gt=0).order_by('username')  # Ordem alfabética

                if not qs.exists():
                    print(f"Sem vendas para regra {regra.nome}")
                    continue

                # 2. Formatar para o Gerador de Imagem
                lista_dados = []
                t_total = 0
                t_cc = 0
                
                for u in qs:
                    pct = int((u.cc / u.total * 100)) if u.total > 0 else 0
                    lista_dados.append({
                        'nome': u.username.upper(),
                        'total': u.total,
                        'cc': u.cc,
                        'pct': f"{pct}%"
                    })
                    t_total += u.total
                    t_cc += u.cc
                
                pct_geral = int((t_cc / t_total * 100)) if t_total > 0 else 0
                
                payload_imagem = {
                    'titulo': f"PERFORMANCE {regra.get_canal_alvo_display().upper()}",
                    'data': hoje.strftime('%d/%m/%Y'),
                    'lista': lista_dados,
                    'totais': {'total': t_total, 'cc': t_cc, 'pct': f"{pct_geral}%"}
                }

                # 3. Gerar Imagem no Backend (Pillow)
                img_b64 = svc.gerar_imagem_performance_b64(payload_imagem)

                # 4. Enviar
                if img_b64:
                    destinos = [d.strip() for d in regra.destinatarios.split(',') if d.strip()]
                    legenda = f"📊 *Atualização Automática* \n⏰ {agora.strftime('%H:%M')}"
                    
                    for dest in destinos:
                        svc.enviar_imagem_b64(dest, img_b64, caption=legenda)
                    
                    print(f"✅ Enviado regra '{regra.nome}' com imagem.")
                    regra.ultimo_disparo = agora
                    regra.save()
                else:
                    print("Erro ao gerar imagem (Pillow).")

            except Exception as e:
                logger.error(f"Erro no disparo {regra.nome}: {e}")