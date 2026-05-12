# crm_app/whatsapp_comissao_service.py
"""
Comandos de comissão pelo WhatsApp (espelho do que Diretoria/Admin faz no site).

- Bônus / desconto avulso → LancamentoFinanceiro (BONUS_PREMIACAO / DESCONTO).
- Adiant. comissão (instaladas) → mesma lógica do toggle na esteira.
- Adiant. sábado → _marcar_adiantamento_sabado_exec em views.
- Adiant. sábado em lote: *ADIANT_SABADO* (ou com data AAAA-MM-DD) lista por consultor;
  depois responda com *linha×quantidade* (ex.: 1x2 3x1). *CANCELAR* encerra.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, time as dt_time
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

ETAPA_ADIANT_SABADO_ESCOLHA = 'comissao_adiant_sabado_escolha'
CHAVE_DADOS_ADIANT_SABADO = 'comissao_adiant_sabado'
MAX_LINHAS_RESUMO_WPP = 28


def _is_diretoria_admin(user):
    from crm_app.utils import is_member

    if not user:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return is_member(user, ['Diretoria', 'Admin'])


def _pode_adiant_sabado(user):
    from crm_app.views import _pode_gerir_adiantamento_sabado

    return _pode_gerir_adiantamento_sabado(user)


def _ultimo_sabado(d=None):
    """Data (date) do sábado mais recente em relação a `d` (inclusive se `d` for sábado)."""
    d = d or timezone.localdate()
    days = (d.weekday() - 5) % 7
    return d - timedelta(days=days)


def _fmt_reais_br(val: Decimal) -> str:
    s = f'{Decimal(val):.2f}'
    inteiro, frac = s.split('.')
    inteiro = inteiro[::-1]
    grupos = [inteiro[i : i + 3] for i in range(0, len(inteiro), 3)]
    mil = '.'.join(g[::-1] for g in grupos)[::-1]
    return f'{mil},{frac}'


def _query_candidatas_adiantamento_sabado(ref_date):
    """
    Mesmo critério de `marcar_adiantamento_sabado_lote` (views):
    AGENDADO, abertura O.S. no sábado `ref_date`, não marcadas, vendedor recebe sábado.
    """
    from crm_app.models import Venda

    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(ref_date, dt_time.min), tz)
    end_dt = start_dt + timedelta(days=1)
    return (
        Venda.objects.filter(
            ativo=True,
            adiantamento_sabado_marcado=False,
            data_abertura__gte=start_dt,
            data_abertura__lt=end_dt,
            vendedor__recebe_adiantamento_sabado=True,
            status_esteira__nome__icontains='AGENDADO',
        )
        .select_related('vendedor', 'status_esteira', 'cliente', 'plano')
        .order_by('vendedor_id', 'id')
    )


def _montar_linhas_resumo_adiant_sabado(candidatas) -> list[dict[str, Any]]:
    from crm_app.views import _valor_adiantamento_base_comissao

    grupos: dict[int, dict[str, Any]] = {}
    for v in candidatas:
        uid = v.vendedor_id
        if uid not in grupos:
            u = v.vendedor
            nome = ''
            if u:
                nome = (u.get_full_name() or '').strip() or (u.username or '')
            grupos[uid] = {
                'vendedor_id': uid,
                'username': u.username if u else str(uid),
                'nome_exibicao': nome,
                'venda_ids': [],
                'valor_total': Decimal('0'),
            }
        vu = _valor_adiantamento_base_comissao(v)
        grupos[uid]['venda_ids'].append(v.id)
        grupos[uid]['valor_total'] += vu

    linhas = sorted(grupos.values(), key=lambda x: (x['nome_exibicao'] or x['username']).lower())
    out = []
    for i, g in enumerate(linhas, start=1):
        out.append(
            {
                'n': i,
                'vendedor_id': g['vendedor_id'],
                'username': g['username'],
                'nome_exibicao': g['nome_exibicao'],
                'qtd': len(g['venda_ids']),
                'valor_total': str(g['valor_total']),
                'venda_ids': g['venda_ids'],
            }
        )
    return out


def limpar_fluxo_adiant_sabado_sessao(sessao) -> None:
    d = dict(sessao.dados_temp or {})
    d.pop(CHAVE_DADOS_ADIANT_SABADO, None)
    sessao.dados_temp = d
    sessao.etapa = 'inicial'
    sessao.save()


def iniciar_resumo_adiant_sabado_whatsapp(sessao, actor, ref_date) -> str:
    """Monta lista por consultor, grava sessão e devolve texto para o WhatsApp."""
    if ref_date.weekday() != 5:
        return '❌ A data de referência deve ser um *sábado* (dia da abertura da O.S. no calendário).'

    candidatas = list(_query_candidatas_adiantamento_sabado(ref_date))
    linhas = _montar_linhas_resumo_adiant_sabado(candidatas)

    if not linhas:
        limpar_fluxo_adiant_sabado_sessao(sessao)
        return (
            f'📅 *Adiantamento sábado* — {ref_date.strftime("%d/%m/%Y")}\n\n'
            'Nenhuma venda *elegível* (AGENDADO, O.S. aberta nesse sábado, '
            'consultor com recebe adiant. sábado, ainda não marcada).'
        )

    d = dict(sessao.dados_temp or {})
    d[CHAVE_DADOS_ADIANT_SABADO] = {
        'ref_date': ref_date.isoformat(),
        'linhas': linhas,
    }
    sessao.dados_temp = d
    sessao.etapa = ETAPA_ADIANT_SABADO_ESCOLHA
    sessao.save()

    blocos = []
    total_cons = len(linhas)
    for chunk_start in range(0, total_cons, MAX_LINHAS_RESUMO_WPP):
        chunk = linhas[chunk_start : chunk_start + MAX_LINHAS_RESUMO_WPP]
        linhas_txt = []
        for L in chunk:
            nome = L['nome_exibicao'] or L['username']
            vt = Decimal(L['valor_total'])
            linhas_txt.append(
                f"{L['n']} — *{nome}* (@{L['username']}) — {L['qtd']} venda(s) — "
                f"R$ {_fmt_reais_br(vt)}"
            )
        parte = f'(parte {chunk_start // MAX_LINHAS_RESUMO_WPP + 1})\n' if total_cons > MAX_LINHAS_RESUMO_WPP else ''
        blocos.append(parte + '\n'.join(linhas_txt))

    instr = (
        '\n\n✏️ Responda com *linha×quantidade* para cada consultor que terá vendas antecipadas '
        '(só as primeiras N vendas da lista, na ordem).\n'
        'Ex.: `1x2 3x1` = linha 1 com 2 vendas, linha 3 com 1 venda.\n'
        '*CANCELAR* encerra sem marcar. *MENU* também cancela este passo.'
    )
    cab = (
        f'📅 *Adiantamento sábado* — sábado *{ref_date.strftime("%d/%m/%Y")}*\n'
        f'_Total: {total_cons} consultor(es) com vendas elegíveis._\n\n'
    )
    texto = cab + '\n\n'.join(blocos) + instr
    if len(texto) > 4000:
        texto = texto[:3950] + '\n\n_(mensagem truncada — reduza no site ou use data com menos vendas)._'
    return texto


def processar_escolha_adiant_sabado_sessao(sessao, actor, mensagem_texto: str, mensagem_limpa: str) -> Optional[str]:
    """Processa resposta no passo `comissao_adiant_sabado_escolha`. Retorna None para delegar a outros comandos."""
    if sessao.etapa != ETAPA_ADIANT_SABADO_ESCOLHA:
        return None
    if not _pode_adiant_sabado(actor):
        limpar_fluxo_adiant_sabado_sessao(sessao)
        return '❌ Sem permissão para concluir este passo.'

    raw = (mensagem_texto or '').strip()
    limpa = (mensagem_limpa or '').strip()
    tok0 = limpa.split()[0] if limpa else ''

    if tok0 in (
        'BONUS',
        'DESCONTO',
        'ADIANT_COMISSAO',
        'COMISSAO',
        'COMISSIONAMENTO',
        'COMISSÃO',
        'ADIANT_SABADO',
    ):
        limpar_fluxo_adiant_sabado_sessao(sessao)
        return None

    if limpa in ('CANCELAR', 'SAIR', 'ABORTAR'):
        limpar_fluxo_adiant_sabado_sessao(sessao)
        return '⏹ *Adiantamento sábado* cancelado. Nada foi marcado.'

    if not raw:
        return 'Informe as escolhas (ex.: *1x2 3x1*) ou *CANCELAR*.'

    bloco = (sessao.dados_temp or {}).get(CHAVE_DADOS_ADIANT_SABADO) or {}
    linhas = bloco.get('linhas') or []
    if not linhas:
        limpar_fluxo_adiant_sabado_sessao(sessao)
        return '❌ Sessão expirada ou lista vazia. Envie *ADIANT_SABADO* de novo.'

    pares = re.findall(r'(\d+)\s*[xX*]\s*(\d+)', raw)
    if not pares:
        return (
            '⏳ Ainda no passo *adiantamento sábado*.\n'
            'Responda com *linha×quantidade* (ex.: `1x2 3x1`) ou *CANCELAR*.'
        )

    mapa_n = {int(L['n']): L for L in linhas}
    from crm_app.models import Venda
    from crm_app.views import _marcar_adiantamento_sabado_exec

    ok_ids = []
    erros = []

    for a_str, q_str in pares:
        linha_n = int(a_str)
        qtd = int(q_str)
        L = mapa_n.get(linha_n)
        if not L:
            erros.append(f'Linha {linha_n} inválida.')
            continue
        ids_ord = [int(x) for x in L['venda_ids']]
        if qtd < 1:
            erros.append(f'Linha {linha_n}: quantidade deve ser ≥ 1.')
            continue
        if qtd > len(ids_ord):
            erros.append(
                f'Linha {linha_n}: pediu {qtd} venda(s), há só {len(ids_ord)} elegível(is).'
            )
            continue
        escolhidos = ids_ord[:qtd]
        for vid in escolhidos:
            v = Venda.objects.select_related('vendedor', 'status_esteira', 'cliente', 'plano').filter(
                id=vid, ativo=True
            ).first()
            if not v:
                erros.append(f'#{vid} não encontrada.')
                continue
            try:
                _marcar_adiantamento_sabado_exec(v, actor, manual=False, obs='')
                ok_ids.append(vid)
            except ValueError as e:
                erros.append(f'#{vid}: {e}')

    limpar_fluxo_adiant_sabado_sessao(sessao)

    partes = []
    if ok_ids:
        partes.append(f'✅ *Marcadas* {len(ok_ids)} venda(s): {", ".join(f"#{i}" for i in ok_ids)}.')
    if erros:
        partes.append('⚠️ *Atenção:*\n' + '\n'.join(f'• {e}' for e in erros[:15]))
        if len(erros) > 15:
            partes.append(f'_…e mais {len(erros) - 15} aviso(s)._')
    if not ok_ids and not erros:
        partes.append('Nenhuma marcação aplicada.')

    return '\n\n'.join(partes)


def texto_ajuda_comissao_whatsapp() -> str:
    return (
        "📊 *Comandos de comissão*\n"
        "_Bônus e adiant. comissão: Diretoria ou Admin. "
        "Adiant. sábado: também BackOffice._\n\n"
        "*BONUS* `login_ou_id` `valor` `AAAA-MM-DD` `descrição`\n"
        "Ex.: `BONUS jose.silva 250 2026-05-15 Premio regional`\n\n"
        "*DESCONTO* `login_ou_id` `valor` `AAAA-MM-DD` `descrição`\n\n"
        "*ADIANT_COMISSAO* `id_venda` `MARCAR` ou `DESMARCAR`\n"
        "_(venda instalada; mesmo critério da esteira)_\n\n"
        "*ADIANT_SABADO* — modo *lista* (recomendado):\n"
        "• Só a palavra *ADIANT_SABADO* → último sábado; mostra consultores e quantidades.\n"
        "• *ADIANT_SABADO* `AAAA-MM-DD` → sábado específico (mesmo critério da esteira).\n"
        "Depois responda *linha×quantidade* (ex.: `1x2 3x1`). *CANCELAR* encerra.\n\n"
        "*ADIANT_SABADO* — modo *uma venda*:\n"
        "`ADIANT_SABADO id_venda` ou `ADIANT_SABADO id MANUAL valor observação`\n\n"
        "Digite *COMISSAO* para repetir esta ajuda."
    )


def _strip_at(s: str) -> str:
    s = (s or '').strip()
    if s.startswith('@'):
        return s[1:]
    return s


def _parse_valor(text: str) -> Decimal:
    t = (text or '').strip().replace(' ', '')
    if ',' in t and '.' in t:
        t = t.replace('.', '').replace(',', '.')
    elif ',' in t:
        t = t.replace(',', '.')
    return Decimal(t)


def _parse_data(s: str):
    return datetime.strptime(s.strip(), '%Y-%m-%d').date()


def _buscar_usuario_alvo(token: str):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    t = _strip_at(token)
    if t.isdigit():
        return User.objects.filter(id=int(t), is_active=True).first()
    return User.objects.filter(username__iexact=t, is_active=True).first()


def _cmd_bonus_desconto(parts: list[str], cmd: str, actor) -> str:
    if len(parts) < 5:
        return (
            "❌ Uso: `BONUS login_ou_id valor AAAA-MM-DD descrição`\n"
            "(a descrição pode ter várias palavras)."
        )
    alvo_token = parts[1]
    valor_s = parts[2]
    data_s = parts[3]
    desc = ' '.join(parts[4:]).strip()
    if len(desc) < 2:
        return "❌ Informe uma descrição (texto após a data)."

    try:
        valor = _parse_valor(valor_s)
        if valor <= 0:
            return "❌ O valor deve ser maior que zero."
    except (InvalidOperation, ValueError):
        return "❌ Valor inválido. Use ex.: 150 ou 150,50"

    try:
        data = _parse_data(data_s)
    except ValueError:
        return "❌ Data inválida. Use o formato AAAA-MM-DD."

    alvo = _buscar_usuario_alvo(alvo_token)
    if not alvo:
        return f"❌ Colaborador não encontrado ou inativo: {alvo_token}"

    tipo = 'BONUS_PREMIACAO' if cmd == 'BONUS' else 'DESCONTO'
    from crm_app.models import LancamentoFinanceiro

    lanc = LancamentoFinanceiro.objects.create(
        usuario_id=alvo.id,
        tipo=tipo,
        data=data,
        valor=valor,
        quantidade_vendas=0,
        descricao=desc[:255],
        metadados={'origem': 'whatsapp', 'comando': cmd.lower()},
        criado_por=actor,
    )
    return (
        f"✅ Lançamento *#{lanc.id}* criado.\n"
        f"• Tipo: {lanc.get_tipo_display()}\n"
        f"• Consultor: {alvo.username}\n"
        f"• Valor: R$ {valor}\n"
        f"• Data: {data.isoformat()}\n"
        f"• Descrição: {desc[:200]}"
    )


def _toggle_adiantamento_comissao_instaladas(venda, marcar: bool, actor) -> tuple[bool, str]:
    """Mesma regra de `VendaViewSet.toggle_adiantamento_comissao` (retorno texto para WhatsApp)."""
    from django.db import transaction
    from django.utils import timezone

    from crm_app.models import LancamentoFinanceiro
    from crm_app.views import _valor_adiantamento_base_comissao

    if not venda.vendedor_id:
        return False, '❌ Venda sem vendedor.'
    if not venda.status_esteira or (venda.status_esteira.nome or '').strip().upper() != 'INSTALADA':
        return False, '❌ Só é permitido em vendas com status *INSTALADA*.'

    valor_unit = _valor_adiantamento_base_comissao(venda)
    if valor_unit <= 0:
        return False, '❌ Valor de adiantamento zero. Revise *Regras por faixa* (finalidade Comissão).'

    hoje = timezone.localdate()
    with transaction.atomic():
        if marcar:
            if getattr(venda, 'adiantamento_sabado_marcado', False):
                if venda.antecipacao_comissao:
                    return True, '✅ Já estava marcado (sem novo lançamento; vínculo sábado/instalada).'
                venda.antecipacao_comissao = True
                if not venda.adiantamento_sabado_quitado_em:
                    venda.adiantamento_sabado_quitado_em = timezone.now()
                venda.save(update_fields=['antecipacao_comissao', 'adiantamento_sabado_quitado_em'])
                return True, '✅ Adiantamento de comissão marcado (quitado na transição sábado → instalada).'
            if venda.antecipacao_comissao:
                return True, '✅ Adiantamento de comissão já estava ativo para esta venda.'
            venda.antecipacao_comissao = True
            venda.save(update_fields=['antecipacao_comissao'])
            lanc = LancamentoFinanceiro.objects.filter(
                usuario_id=venda.vendedor_id,
                tipo='ADIANTAMENTO_COMISSAO',
                data=hoje,
                descricao='Adiantamento comissão (Instaladas)',
            ).first()
            venda_ids = []
            if lanc and isinstance(lanc.metadados, dict):
                venda_ids = list(lanc.metadados.get('venda_ids') or [])
            if venda.id not in venda_ids:
                venda_ids.append(venda.id)
            if lanc:
                lanc.valor = Decimal(str(lanc.valor or 0)) + valor_unit
                lanc.quantidade_vendas = max(int(lanc.quantidade_vendas or 0), 0) + 1
                lanc.metadados = {'origem': 'instaladas_comissao', 'venda_ids': venda_ids}
                lanc.save(update_fields=['valor', 'quantidade_vendas', 'metadados'])
            else:
                LancamentoFinanceiro.objects.create(
                    usuario_id=venda.vendedor_id,
                    tipo='ADIANTAMENTO_COMISSAO',
                    data=hoje,
                    valor=valor_unit,
                    quantidade_vendas=1,
                    descricao='Adiantamento comissão (Instaladas)',
                    metadados={
                        'origem': 'instaladas_comissao',
                        'venda_ids': [venda.id],
                        'whatsapp_actor_id': actor.id,
                    },
                    criado_por=actor,
                )
            return True, (
                f"✅ Adiantamento de comissão *marcado* para a venda #{venda.id}.\n"
                f"Valor unitário na folha (hoje): R$ {valor_unit}"
            )
        if not venda.antecipacao_comissao:
            return True, '✅ Já estava desmarcado.'
        venda.antecipacao_comissao = False
        venda.save(update_fields=['antecipacao_comissao'])
        lancs = LancamentoFinanceiro.objects.filter(
            usuario_id=venda.vendedor_id,
            tipo='ADIANTAMENTO_COMISSAO',
            descricao='Adiantamento comissão (Instaladas)',
            data=hoje,
        )
        for lanc in lancs:
            meta = lanc.metadados if isinstance(lanc.metadados, dict) else {}
            venda_ids = list(meta.get('venda_ids') or [])
            if venda.id not in venda_ids:
                continue
            venda_ids = [vid for vid in venda_ids if int(vid) != int(venda.id)]
            novo_valor = Decimal(str(lanc.valor or 0)) - valor_unit
            nova_qtd = max(int(lanc.quantidade_vendas or 0) - 1, 0)
            if nova_qtd <= 0 or novo_valor <= 0:
                lanc.delete()
            else:
                lanc.valor = novo_valor
                lanc.quantidade_vendas = nova_qtd
                lanc.metadados = {'origem': 'instaladas_comissao', 'venda_ids': venda_ids}
                lanc.save(update_fields=['valor', 'quantidade_vendas', 'metadados'])
            break
        return True, f"✅ Adiantamento de comissão *desmarcado* para a venda #{venda.id}."


def _cmd_adiant_comissao(parts: list[str], actor) -> str:
    if len(parts) < 3:
        return "❌ Uso: `ADIANT_COMISSAO id_venda MARCAR` ou `DESMARCAR`"
    try:
        vid = int(parts[1])
    except ValueError:
        return "❌ O id da venda deve ser um número inteiro."
    acao = parts[2].upper()
    marcar = acao in ('MARCAR', 'SIM', 'ON', '1', 'TRUE')
    if not marcar and acao not in ('DESMARCAR', 'NAO', 'NÃO', 'OFF', '0', 'FALSE'):
        return "❌ Ação inválida. Use *MARCAR* ou *DESMARCAR*."

    from crm_app.models import Venda

    venda = Venda.objects.select_related('status_esteira', 'vendedor').filter(id=vid, ativo=True).first()
    if not venda:
        return f"❌ Venda #{vid} não encontrada ou inativa."

    _ok, msg = _toggle_adiantamento_comissao_instaladas(venda, marcar=marcar, actor=actor)
    return msg


def _marcar_um_adiant_sabado_por_id(parts: list[str], actor) -> str:
    """ADIANT_SABADO id [MANUAL valor obs...]"""
    if len(parts) < 2:
        return "❌ Uso: `ADIANT_SABADO id_venda` ou `ADIANT_SABADO id_venda MANUAL valor observação`"

    try:
        vid = int(parts[1])
    except ValueError:
        return "❌ O id da venda deve ser um número inteiro."

    manual = False
    valor_manual = None
    obs = ''
    if len(parts) >= 3 and parts[2].upper() == 'MANUAL':
        manual = True
        if len(parts) < 5:
            return "❌ Com MANUAL: `ADIANT_SABADO id MANUAL valor observação` (observação ≥ 3 caracteres)."
        valor_manual = parts[3]
        obs = ' '.join(parts[4:]).strip()
        if len(obs) < 3:
            return "❌ Informe observação com pelo menos 3 caracteres."

    from crm_app.models import Venda
    from crm_app.views import _marcar_adiantamento_sabado_exec

    venda = Venda.objects.filter(id=vid, ativo=True).first()
    if not venda:
        return f"❌ Venda #{vid} não encontrada ou inativa."

    try:
        out = _marcar_adiantamento_sabado_exec(
            venda,
            actor,
            manual=manual,
            obs=obs,
            valor_manual=valor_manual,
        )
    except ValueError as e:
        return f"❌ {e}"

    return (
        "✅ *Adiantamento sábado* registrado.\n"
        f"• Venda: #{vid}\n"
        f"• Valor: R$ {out['adiantamento_sabado_valor']}\n"
        f"• Data lançamento: {out['data_lancamento']}"
    )


def _dispatch_adiant_sabado(parts: list[str], actor, sessao) -> str:
    """
    ADIANT_SABADO → resumo por consultor (sessão).
    ADIANT_SABADO AAAA-MM-DD → idem com sábado informado.
    ADIANT_SABADO id … → uma venda (com ou sem MANUAL).
    """
    if sessao is None:
        return '❌ Erro interno: sessão WhatsApp ausente. Tente novamente.'

    if len(parts) == 1:
        return iniciar_resumo_adiant_sabado_whatsapp(sessao, actor, _ultimo_sabado())

    if len(parts) == 2:
        tok = parts[1].strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}$', tok):
            try:
                ref = _parse_data(tok)
            except ValueError:
                return '❌ Data inválida. Use *AAAA-MM-DD* (sábado).'
            return iniciar_resumo_adiant_sabado_whatsapp(sessao, actor, ref)
        if tok.isdigit():
            return _marcar_um_adiant_sabado_por_id(parts, actor)
        return '❌ Após *ADIANT_SABADO* use *AAAA-MM-DD* (sábado) ou o *id da venda*.'

    if len(parts) >= 3 and parts[1].isdigit() and parts[2].upper() == 'MANUAL':
        return _marcar_um_adiant_sabado_por_id(parts, actor)

    if len(parts) >= 2 and parts[1].isdigit():
        return _marcar_um_adiant_sabado_por_id(parts, actor)

    return '❌ Comando *ADIANT_SABADO* não reconhecido. Digite *COMISSAO* para ver a ajuda.'


def processar_whatsapp_comissao(
    usuario_actor,
    mensagem_texto: str,
    mensagem_limpa: str,
    sessao=None,
) -> Optional[str]:
    """
    Se for comando de comissão autorizado, retorna texto da resposta.
    Se não for deste módulo, retorna None para o webhook seguir o fluxo normal.
    """
    raw = (mensagem_texto or '').strip()
    if not raw:
        return None

    limpa_tokens = (mensagem_limpa or '').strip().split()
    palavra1_limpa = limpa_tokens[0] if limpa_tokens else ''

    first = raw.split(None, 1)[0]
    first_u = first.upper()

    if palavra1_limpa in ('COMISSAO', 'COMISSIONAMENTO', 'COMISSÃO') and len(limpa_tokens) == 1:
        if not (_is_diretoria_admin(usuario_actor) or _pode_adiant_sabado(usuario_actor)):
            return (
                "❌ Comandos de comissão pelo WhatsApp são restritos a "
                "*Diretoria*, *Admin* ou *BackOffice* (adiant. sábado)."
            )
        return texto_ajuda_comissao_whatsapp()

    if first_u not in ('BONUS', 'DESCONTO', 'ADIANT_COMISSAO', 'ADIANT_SABADO'):
        return None

    parts = raw.split()

    if first_u in ('BONUS', 'DESCONTO'):
        if not _is_diretoria_admin(usuario_actor):
            return "❌ Apenas *Diretoria* ou *Admin* podem registrar bônus ou desconto pelo WhatsApp."
        return _cmd_bonus_desconto(parts, parts[0].upper(), usuario_actor)

    if first_u == 'ADIANT_COMISSAO':
        if not _is_diretoria_admin(usuario_actor):
            return "❌ Apenas *Diretoria* ou *Admin* podem alterar adiantamento de comissão."
        return _cmd_adiant_comissao(parts, usuario_actor)

    if first_u == 'ADIANT_SABADO':
        if not _pode_adiant_sabado(usuario_actor):
            return "❌ Sem permissão para *adiantamento sábado*."
        return _dispatch_adiant_sabado(parts, usuario_actor, sessao)

    return None
