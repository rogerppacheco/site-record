import logging
from django.utils import timezone
from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from .models import Venda, AgendamentoDisparo, LogEnvioPerformance
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

def processar_envio_performance():
    """Lógica principal chamada pelo Scheduler"""
    agora = timezone.localtime(timezone.now())
    hora = agora.hour
    minuto = agora.minute
    dia_sem = agora.weekday() # 0=Seg, 1=Ter, 2=Qua, 3=Qui, 4=Sex, 5=Sáb, 6=Dom
    
    logger.info(f"📊 Verificando envios de Performance - {agora.strftime('%d/%m/%Y %H:%M:%S')} (Dia: {dia_sem}, Hora: {hora:02d}:{minuto:02d})")
    
    regras = AgendamentoDisparo.objects.filter(ativo=True)
    logger.info(f"📋 Encontradas {regras.count()} regra(s) de agendamento ativa(s)")
    
    svc = WhatsAppService()
    User = get_user_model()

    for regra in regras:
        enviar = False
        intervalo_min = getattr(regra, 'intervalo_minutos', 60) or 60

        # --- Respeitar intervalo mínimo desde o último disparo ---
        if regra.ultimo_disparo:
            try:
                diff_minutos = (agora - regra.ultimo_disparo).total_seconds() / 60.0
                if diff_minutos < intervalo_min:
                    logger.info(f"⏳ Regra '{regra.nome}': aguardando intervalo ({diff_minutos:.0f} min < {intervalo_min} min)")
                    continue  # Ainda não passou o intervalo, pula esta regra
            except (TypeError, AttributeError):
                pass

        # --- VERIFICAÇÃO DE HORÁRIO (janela permitida) ---
        # Para HORARIO: janela ampla; o intervalo_minutos controla a frequência (ex: 15 min)
        if regra.tipo == 'HORARIO':
            if dia_sem in [0, 1, 2, 3, 4]:  # Seg-Sex: 8h30 até 17h59
                if (hora == 8 and minuto >= 30) or (9 <= hora <= 17):
                    enviar = True
            elif dia_sem == 5:  # Sábado: 9h até 12h59
                if 9 <= hora <= 12:
                    enviar = True
        elif regra.tipo == 'SEMANAL':
            if dia_sem in [1, 3, 5] and hora == 17 and minuto == 0:
                enviar = True

        if enviar:
            try:
                # 1. Coletar Dados do Banco
                hoje = agora.date()
                users = User.objects.filter(is_active=True).exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])
                
                if regra.canal_alvo != 'TODOS':
                    users = users.filter(canal__iexact=regra.canal_alvo)

                if getattr(regra, 'cluster_alvo', None) and str(regra.cluster_alvo).strip() and str(regra.cluster_alvo).upper() != 'TODOS':
                    users = users.filter(cluster__iexact=regra.cluster_alvo.strip())

                filtro = Q(vendas__ativo=True, vendas__data_abertura__date=hoje)
                qs = users.annotate(
                    total=Count('vendas', filter=filtro),
                    cc=Count('vendas', filter=filtro & (Q(vendas__forma_pagamento__nome__icontains='CREDIT') | Q(vendas__forma_pagamento__nome__icontains='CARTA')))
                ).filter(total__gt=0).order_by('username')  # Ordem alfabética

                if not qs.exists():
                    logger.info(f"Sem vendas para regra {regra.nome} - pulando envio")
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
                    
                    sucessos = 0
                    falhas = 0
                    
                    for dest in destinos:
                        try:
                            resultado = svc.enviar_imagem_b64(dest, img_b64, caption=legenda)
                            if resultado is not None:
                                sucessos += 1
                                logger.info(f"✅ Imagem enviada com sucesso para {dest}")
                            else:
                                falhas += 1
                                logger.error(f"❌ Falha ao enviar imagem para {dest}: resposta None")
                        except Exception as e:
                            falhas += 1
                            logger.error(f"❌ Erro ao enviar imagem para {dest}: {e}")
                    
                    # Só atualizar último_disparo se pelo menos um envio foi bem-sucedido
                    if sucessos > 0:
                        logger.info(f"✅ Enviado regra '{regra.nome}' com imagem para {sucessos}/{len(destinos)} destinatário(s) (falhas: {falhas})")
                        regra.ultimo_disparo = agora
                        regra.save()
                        detalhe = f"{sucessos}/{len(destinos)} enviados"
                    else:
                        logger.error(f"❌ Nenhum envio bem-sucedido para regra '{regra.nome}' ({falhas} falha(s))")
                        detalhe = f"0/{len(destinos)} - todas falhas"
                    # Histórico do dia
                    try:
                        LogEnvioPerformance.objects.create(
                            regra=regra,
                            regra_nome=regra.nome,
                            sucesso=(sucessos > 0),
                            total_destinos=len(destinos),
                            sucessos=sucessos,
                            falhas=falhas,
                            detalhe=detalhe,
                        )
                    except Exception:
                        pass
                else:
                    logger.error(f"❌ Erro ao gerar imagem (Pillow) para regra '{regra.nome}'")
                    try:
                        LogEnvioPerformance.objects.create(
                            regra=regra,
                            regra_nome=regra.nome,
                            sucesso=False,
                            total_destinos=0,
                            sucessos=0,
                            falhas=0,
                            detalhe="Erro ao gerar imagem",
                        )
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"❌ Erro no disparo da regra '{regra.nome}': {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                try:
                    LogEnvioPerformance.objects.create(
                        regra=regra,
                        regra_nome=regra.nome,
                        sucesso=False,
                        total_destinos=0,
                        sucessos=0,
                        falhas=0,
                        detalhe=str(e)[:500],
                    )
                except Exception:
                    pass