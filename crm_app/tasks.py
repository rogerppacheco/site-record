import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from .models import Venda, AgendamentoDisparo, LogEnvioPerformance
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

def _filtro_cc():
    return (
        Q(vendas__forma_pagamento__nome__icontains='CREDIT') |
        Q(vendas__forma_pagamento__nome__icontains='CRÉDIT') |
        (Q(vendas__forma_pagamento__nome__icontains='CARTA') & ~Q(vendas__forma_pagamento__nome__icontains='DEBIT'))
    )

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
        hora_fim = getattr(regra, 'hora_fim', 19) or 19
        if regra.tipo == 'HORARIO':
            if dia_sem in [0, 1, 2, 3, 4]:  # Seg-Sex: 8h30 até hora_fim
                if (hora == 8 and minuto >= 30) or (9 <= hora <= hora_fim):
                    enviar = True
            elif dia_sem == 5:  # Sábado: 9h até 12h59 (ou hora_fim se menor)
                fim_sab = min(12, hora_fim)
                if 9 <= hora <= fim_sab:
                    enviar = True
        elif regra.tipo == 'SEMANAL':
            if dia_sem in [1, 3, 5] and hora == 17 and minuto == 0:
                enviar = True

        if enviar:
            try:
                hoje = agora.date()
                inicio_semana = hoje - timedelta(days=hoje.weekday())
                dias_semana = [inicio_semana + timedelta(days=i) for i in range(6)]
                inicio_mes = hoje.replace(day=1)

                users = User.objects.filter(is_active=True).exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])
                if regra.canal_alvo != 'TODOS':
                    users = users.filter(canal__iexact=regra.canal_alvo)
                if getattr(regra, 'cluster_alvo', None) and str(regra.cluster_alvo).strip() and str(regra.cluster_alvo).upper() != 'TODOS':
                    users = users.filter(cluster__iexact=regra.cluster_alvo.strip())

                filtro_os = Q(vendas__ativo=True) & ~Q(vendas__ordem_servico='') & Q(vendas__ordem_servico__isnull=False)
                filtro_cc = _filtro_cc()
                filtro_inst = Q(vendas__status_esteira__nome__iexact='INSTALADA')
                tipo_rel = getattr(regra, 'tipo_relatorio', 'HOJE') or 'HOJE'

                lista_dados = []
                t_total = 0
                t_cc = 0
                titulo_extra = ""

                if tipo_rel == 'HOJE':
                    filtro = filtro_os & Q(vendas__data_abertura__date=hoje)
                    qs = users.annotate(
                        total=Count('vendas', filter=filtro),
                        cc=Count('vendas', filter=filtro & filtro_cc)
                    ).order_by('username')
                    if not qs.exists():
                        logger.info(f"Nenhum usuário ativo para regra {regra.nome} - pulando envio")
                        continue
                    titulo_extra = " Hoje"
                    for u in qs:
                        pct = int((u.cc / u.total * 100)) if u.total > 0 else 0
                        lista_dados.append({
                            'nome': u.username.upper(),
                            'cluster': getattr(u, 'cluster', None) or '-',
                            'canal': getattr(u, 'canal', None) or '-',
                            'total': u.total,
                            'cc': u.cc,
                            'pct': f"{pct}%"
                        })
                        t_total += u.total
                        t_cc += u.cc

                elif tipo_rel == 'SEMANAL':
                    qs_semana = users.annotate(
                        seg=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date=dias_semana[0])),
                        ter=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date=dias_semana[1])),
                        qua=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date=dias_semana[2])),
                        qui=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date=dias_semana[3])),
                        sex=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date=dias_semana[4])),
                        sab=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date=dias_semana[5])),
                        total_semana=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date__gte=inicio_semana)),
                        total_cc=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date__gte=inicio_semana) & filtro_cc)
                    ).order_by('username').values('username', 'cluster', 'canal', 'total_semana', 'total_cc')
                    if not qs_semana.exists():
                        logger.info(f"Nenhum usuário ativo para regra {regra.nome} - pulando envio")
                        continue
                    titulo_extra = " Semanal"
                    for u in qs_semana:
                        tot = u['total_semana']
                        cc = u['total_cc']
                        pct = int((cc / tot * 100)) if tot > 0 else 0
                        lista_dados.append({
                            'nome': u['username'].upper(),
                            'cluster': u.get('cluster') or '-',
                            'canal': u.get('canal') or '-',
                            'total': tot,
                            'cc': cc,
                            'pct': f"{pct}%"
                        })
                        t_total += tot
                        t_cc += cc

                else:  # MENSAL
                    qs_mes = users.annotate(
                        total_vendas=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date__gte=inicio_mes)),
                        total_cc=Count('vendas', filter=filtro_os & Q(vendas__data_abertura__date__gte=inicio_mes) & filtro_cc)
                    ).order_by('username').values('username', 'cluster', 'canal', 'total_vendas', 'total_cc')
                    if not qs_mes.exists():
                        logger.info(f"Nenhum usuário ativo para regra {regra.nome} - pulando envio")
                        continue
                    titulo_extra = " Mensal"
                    for u in qs_mes:
                        tot = u['total_vendas']
                        cc = u['total_cc']
                        pct = int((cc / tot * 100)) if tot > 0 else 0
                        lista_dados.append({
                            'nome': u['username'].upper(),
                            'cluster': u.get('cluster') or '-',
                            'canal': u.get('canal') or '-',
                            'total': tot,
                            'cc': cc,
                            'pct': f"{pct}%"
                        })
                        t_total += tot
                        t_cc += cc

                pct_geral = int((t_cc / t_total * 100)) if t_total > 0 else 0
                payload_imagem = {
                    'titulo': f"Performance -{titulo_extra.strip()}",
                    'data': hoje.strftime('%d/%m/%Y'),
                    'lista': lista_dados,
                    'totais': {'total': t_total, 'cc': t_cc, 'pct': f"{pct_geral}%"},
                    'tipo': tipo_rel,
                }

                # 3. Gerar Imagem no Backend (Pillow)
                img_b64 = svc.gerar_imagem_performance_b64(payload_imagem)

                # 4. Enviar (só registrar sucesso quando a Z-API confirmar com messageId/zaapId)
                if img_b64:
                    # Aceitar vírgula ou ponto-e-vírgula (ex: "id1,id2" ou "id1;id2")
                    raw = (regra.destinatarios or "").replace(";", ",")
                    destinos = [d.strip() for d in raw.split(",") if d.strip()]
                    if not destinos:
                        logger.warning(f"Regra '{regra.nome}': nenhum destinatário válido (destinatarios='{regra.destinatarios}')")
                        try:
                            LogEnvioPerformance.objects.create(
                                regra=regra, regra_nome=regra.nome, sucesso=False,
                                total_destinos=0, sucessos=0, falhas=0,
                                detalhe="Nenhum destinatário válido (use vírgula ou ; para separar)",
                            )
                        except Exception:
                            pass
                        continue
                    logger.info(f"Imagem gerada para regra '{regra.nome}', enviando para {len(destinos)} destino(s)")
                    # Legenda: "Atualização da Parcial de hoje" para HOJE, semanal/mensal para os outros
                    if tipo_rel == 'HOJE':
                        legenda = f"📊 *Atualização da Parcial de hoje* \n⏰ {agora.strftime('%H:%M')}"
                    elif tipo_rel == 'SEMANAL':
                        legenda = f"📊 *Atualização da Parcial semanal* \n⏰ {agora.strftime('%H:%M')}"
                    else:
                        legenda = f"📊 *Atualização da Parcial mensal* \n⏰ {agora.strftime('%H:%M')}"
                    sucessos = 0
                    falhas = 0
                    erros_desc = []

                    for dest in destinos:
                        try:
                            resultado = svc.enviar_imagem_b64(dest, img_b64, caption=legenda)
                            if resultado is not None:
                                sucessos += 1
                                logger.info(f"✅ Imagem enviada com sucesso para {dest}")
                            else:
                                falhas += 1
                                erros_desc.append(f"{dest}: Z-API não confirmou envio")
                                logger.error(f"❌ Falha ao enviar imagem para {dest}: Z-API não retornou messageId/zaapId")
                        except Exception as e:
                            falhas += 1
                            erros_desc.append(f"{dest}: {str(e)[:80]}")
                            logger.error(f"❌ Erro ao enviar imagem para {dest}: {e}")

                    if sucessos > 0:
                        logger.info(f"✅ Enviado regra '{regra.nome}' com imagem para {sucessos}/{len(destinos)} destinatário(s) (falhas: {falhas})")
                        regra.ultimo_disparo = agora
                        regra.save()
                        detalhe = f"{sucessos}/{len(destinos)} enviados"
                    else:
                        logger.error(f"❌ Nenhum envio bem-sucedido para regra '{regra.nome}' ({falhas} falha(s))")
                        detalhe = f"0/{len(destinos)} - " + ("; ".join(erros_desc[:3]) if erros_desc else "Z-API não confirmou envio")
                    try:
                        LogEnvioPerformance.objects.create(
                            regra=regra,
                            regra_nome=regra.nome,
                            sucesso=(sucessos > 0),
                            total_destinos=len(destinos),
                            sucessos=sucessos,
                            falhas=falhas,
                            detalhe=detalhe[:500],
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