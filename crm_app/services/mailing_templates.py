"""Templates Meta (UTILITY) para mailings — tom informativo, sem oferta."""
from __future__ import annotations

from typing import Any, Sequence, Tuple

from crm_app.models import MailingContato
from crm_app.services.mailing_import_service import primeiro_nome
from crm_app.services.whatsapp.nio_templates import (
    render_template_preview,
    tentar_enviar_ou_texto_funil,
)

TEMPLATE_REPARO = 'mailing_reparo_v1'
TEMPLATE_INSTALACAO = 'mailing_instalacao_v1'
TEMPLATE_MUDANCA = 'mailing_mudanca_v1'
TEMPLATE_SERVICO = 'mailing_servico_v1'
TEMPLATE_CANCELAMENTO = 'mailing_cancelamento_v1'
TEMPLATE_FECHADO = 'mailing_fechado_v1'
TEMPLATE_ABERTO = 'mailing_aberto_v1'
TEMPLATE_GENERICO = 'mailing_generico_v1'

SITUACAO_PARA_TEMPLATE = {
    MailingContato.SIT_REPARO: TEMPLATE_REPARO,
    MailingContato.SIT_INSTALACAO: TEMPLATE_INSTALACAO,
    MailingContato.SIT_MUDANCA: TEMPLATE_MUDANCA,
    MailingContato.SIT_SERVICO: TEMPLATE_SERVICO,
    MailingContato.SIT_CANCELAMENTO: TEMPLATE_CANCELAMENTO,
    MailingContato.SIT_FECHADO: TEMPLATE_FECHADO,
    MailingContato.SIT_ABERTO: TEMPLATE_ABERTO,
    MailingContato.SIT_GENERICO: TEMPLATE_GENERICO,
}

# Specs para aprovação Meta / docx
TEMPLATE_SPECS = [
    {
        'nome': TEMPLATE_REPARO,
        'titulo': 'Reparo / problema de internet',
        'categoria': 'UTILITY',
        'corpo': (
            'Olá, {{1}}.\n'
            '\n'
            'Sua internet está com algum problema?\n'
            '\n'
            'Fale conosco — podemos te ajudar.'
        ),
        'variaveis': [['{{1}}', 'Primeiro nome', 'Maria']],
        'botoes': ['Falar conosco', 'Estou com dúvida'],
        'params_count': 1,
    },
    {
        'nome': TEMPLATE_INSTALACAO,
        'titulo': 'Instalação recente',
        'categoria': 'UTILITY',
        'corpo': (
            'Olá, {{1}}.\n'
            '\n'
            'Tudo certo com a internet no seu endereço?\n'
            '\n'
            'Se precisar de suporte, fale conosco.'
        ),
        'variaveis': [['{{1}}', 'Primeiro nome', 'João']],
        'botoes': ['Falar conosco', 'Estou com dúvida'],
        'params_count': 1,
    },
    {
        'nome': TEMPLATE_MUDANCA,
        'titulo': 'Mudança de endereço',
        'categoria': 'UTILITY',
        'corpo': (
            'Olá, {{1}}.\n'
            '\n'
            'Houve mudança de endereço ou instalação?\n'
            '\n'
            'Podemos esclarecer suas dúvidas por aqui.'
        ),
        'variaveis': [['{{1}}', 'Primeiro nome', 'Ana']],
        'botoes': ['Falar conosco', 'Estou com dúvida'],
        'params_count': 1,
    },
    {
        'nome': TEMPLATE_SERVICO,
        'titulo': 'Serviço / retirada',
        'categoria': 'UTILITY',
        'corpo': (
            'Olá, {{1}}.\n'
            '\n'
            'Sobre o serviço de internet no seu endereço: podemos te orientar.\n'
            '\n'
            'Fale conosco.'
        ),
        'variaveis': [['{{1}}', 'Primeiro nome', 'Carlos']],
        'botoes': ['Falar conosco', 'Estou com dúvida'],
        'params_count': 1,
    },
    {
        'nome': TEMPLATE_CANCELAMENTO,
        'titulo': 'Cancelamento',
        'categoria': 'UTILITY',
        'corpo': (
            'Olá, {{1}}.\n'
            '\n'
            'Vimos que o serviço em {{2}} foi cancelado.\n'
            '\n'
            'Se quiser informações, fale conosco.'
        ),
        'variaveis': [
            ['{{1}}', 'Primeiro nome', 'Lucia'],
            ['{{2}}', 'Cidade ou bairro', 'Uberlândia'],
        ],
        'botoes': ['Falar conosco', 'Estou com dúvida'],
        'params_count': 2,
    },
    {
        'nome': TEMPLATE_FECHADO,
        'titulo': 'Contrato fechado',
        'categoria': 'UTILITY',
        'corpo': (
            'Olá, {{1}}.\n'
            '\n'
            'O contrato em {{2}} aparece fechado.\n'
            '\n'
            'Se tiver dúvidas, podemos te ajudar.'
        ),
        'variaveis': [
            ['{{1}}', 'Primeiro nome', 'Pedro'],
            ['{{2}}', 'Cidade ou bairro', 'Franca'],
        ],
        'botoes': ['Falar conosco', 'Estou com dúvida'],
        'params_count': 2,
    },
    {
        'nome': TEMPLATE_ABERTO,
        'titulo': 'Chamado aberto / técnico',
        'categoria': 'UTILITY',
        'corpo': (
            'Olá, {{1}}.\n'
            '\n'
            'Há um chamado em andamento em {{2}}.\n'
            '\n'
            'Precisa de orientação? Fale conosco.'
        ),
        'variaveis': [
            ['{{1}}', 'Primeiro nome', 'Fernanda'],
            ['{{2}}', 'Cidade ou bairro', 'Uberaba'],
        ],
        'botoes': ['Falar conosco', 'Estou com dúvida'],
        'params_count': 2,
    },
    {
        'nome': TEMPLATE_GENERICO,
        'titulo': 'Genérico',
        'categoria': 'UTILITY',
        'corpo': (
            'Olá, {{1}}.\n'
            '\n'
            'Podemos te ajudar com informações sobre internet no seu endereço.\n'
            '\n'
            'Fale conosco.'
        ),
        'variaveis': [['{{1}}', 'Primeiro nome', 'Rafael']],
        'botoes': ['Falar conosco', 'Estou com dúvida'],
        'params_count': 1,
    },
]


def template_para_situacao(situacao: str) -> str:
    return SITUACAO_PARA_TEMPLATE.get(situacao, TEMPLATE_GENERICO)


def local_curto(contato: MailingContato) -> str:
    for candid in (contato.cidade, contato.bairro, contato.uf):
        t = (candid or '').strip()
        if t:
            return t[:40]
    return 'seu município'


def body_params_contato(contato: MailingContato) -> list[str]:
    nome = primeiro_nome(contato.nome)
    template = template_para_situacao(contato.situacao)
    if template in (TEMPLATE_CANCELAMENTO, TEMPLATE_FECHADO, TEMPLATE_ABERTO):
        return [nome, local_curto(contato)]
    return [nome]


def fallback_texto(contato: MailingContato) -> str:
    nome = primeiro_nome(contato.nome)
    loc = local_curto(contato)
    mapa = {
        MailingContato.SIT_REPARO: f'{nome}, sua internet está com algum problema? Fale conosco — podemos te ajudar.',
        MailingContato.SIT_INSTALACAO: f'{nome}, tudo certo com a internet no seu endereço? Se precisar de suporte, fale conosco.',
        MailingContato.SIT_MUDANCA: f'{nome}, houve mudança de endereço ou instalação? Podemos esclarecer suas dúvidas por aqui.',
        MailingContato.SIT_SERVICO: f'{nome}, sobre o serviço de internet no seu endereço: podemos te orientar. Fale conosco.',
        MailingContato.SIT_CANCELAMENTO: f'{nome}, vimos que o serviço em {loc} foi cancelado. Se quiser informações, fale conosco.',
        MailingContato.SIT_FECHADO: f'{nome}, o contrato em {loc} aparece fechado. Se tiver dúvidas, podemos te ajudar.',
        MailingContato.SIT_ABERTO: f'{nome}, há um chamado em andamento em {loc}. Precisa de orientação? Fale conosco.',
    }
    return mapa.get(
        contato.situacao,
        f'{nome}, podemos te ajudar com informações sobre internet no seu endereço. Fale conosco.',
    )


def enviar_mailing_contato(
    contato: MailingContato,
    *,
    usuario=None,
) -> Tuple[bool, Any, str, str]:
    """Envia template (ou fallback texto). Retorna (ok, resp, canal, template_nome)."""
    from crm_app.models import FunilTemplateEnvio

    template = template_para_situacao(contato.situacao)
    params = body_params_contato(contato)
    preview = fallback_texto(contato) or render_template_preview(template, params)
    ok, resp, canal = tentar_enviar_ou_texto_funil(
        contato.telefone_e164,
        template,
        params,
        preview,
        usuario=usuario,
        aba=FunilTemplateEnvio.ABA_MAILING,
        ref_id=str(contato.pk),
        espelho_texto=f'[Template {template}] ' + ' · '.join(str(p) for p in params[:4]),
    )
    return ok, resp, canal, template


def corrigir_datas_mailing_no_inbox(*, limite: int = 2000) -> dict:
    """Alinha data_hora das msgs espelhadas com MailingEnvio.enviado_em."""
    from crm_app.models import MailingEnvio, MensagemWhatsAppAtendimento, WhatsAppConversation

    limite = max(1, min(int(limite or 2000), 5000))
    envios = list(
        MailingEnvio.objects.filter(sucesso=True)
        .exclude(message_id="")
        .exclude(enviado_em__isnull=True)
        .order_by("-enviado_em")[:limite]
    )
    by_mid = {
        (e.message_id or "")[:128]: e.enviado_em
        for e in envios
        if e.message_id and e.enviado_em
    }
    if not by_mid:
        return {"ok": True, "atualizados": 0, "conversas": 0}

    msgs = list(
        MensagemWhatsAppAtendimento.objects.filter(
            origem=MensagemWhatsAppAtendimento.ORIGEM_FUNIL,
            message_id__in=list(by_mid.keys()),
        ).only("id", "message_id", "data_hora", "conversa_id", "telefone", "texto", "direcao")
    )
    atualizados = 0
    conv_ids: set[int] = set()
    for msg in msgs:
        mid = (msg.message_id or "")[:128]
        dt = by_mid.get(mid)
        if not dt:
            continue
        if msg.data_hora and abs((msg.data_hora - dt).total_seconds()) < 2:
            continue
        MensagemWhatsAppAtendimento.objects.filter(pk=msg.pk).update(data_hora=dt)
        atualizados += 1
        if msg.conversa_id:
            conv_ids.add(msg.conversa_id)

    # Recalcula preview/data da conversa pela mensagem mais recente.
    conversas_ok = 0
    for cid in conv_ids:
        ultima = (
            MensagemWhatsAppAtendimento.objects.filter(conversa_id=cid)
            .order_by("-data_hora", "-id")
            .only("data_hora", "texto", "direcao")
            .first()
        )
        if ultima is None:
            continue
        preview = (ultima.texto or "").replace("\n", " ").strip()[:240]
        WhatsAppConversation.objects.filter(pk=cid).update(
            last_message_at=ultima.data_hora,
            last_message_preview=preview,
            last_direction=ultima.direcao or "",
        )
        conversas_ok += 1

    return {
        "ok": True,
        "atualizados": atualizados,
        "conversas": conversas_ok,
        "candidatos": len(msgs),
    }


def backfill_mailing_no_inbox(*, limite: int = 300, corrigir_datas: bool = True) -> dict:
    """Espelha envios de mailing já feitos (histórico) no inbox CRM.

    Só sucesso + message_id; não duplica se a mensagem já existir.
    Por padrão também corrige data_hora de espelhos já criados.
    """
    from crm_app.models import MailingEnvio, MensagemWhatsAppAtendimento
    from crm_app.services.whatsapp.atendimento_crm import espelhar_envio_funil_no_inbox
    from crm_app.services.whatsapp.nio_templates import render_template_preview

    limite = max(1, min(int(limite or 300), 1500))
    envios = list(
        MailingEnvio.objects.filter(sucesso=True)
        .exclude(message_id="")
        .select_related("contato")
        .order_by("-enviado_em")[:limite]
    )
    mids = [(env.message_id or "")[:128] for env in envios if env.message_id]
    ja = set(
        MensagemWhatsAppAtendimento.objects.filter(message_id__in=mids).values_list(
            "message_id", flat=True
        )
    )
    criados = 0
    pulados = 0
    for env in envios:
        mid = (env.message_id or "")[:128]
        if not mid or mid in ja:
            pulados += 1
            continue
        contato = env.contato
        tel = getattr(contato, "telefone_e164", "") or ""
        if len("".join(ch for ch in tel if ch.isdigit())) < 8:
            pulados += 1
            continue
        params = body_params_contato(contato) if contato else []
        preview = render_template_preview(env.template_nome or "", params)
        if not preview or preview.startswith("Template:"):
            preview = fallback_texto(contato) if contato else f"[Mailing] {env.template_nome}"
        try:
            # Sem vincular FunilTratamento (ref mailing) — só timeline + etapa.
            espelhar_envio_funil_no_inbox(
                telefone=tel,
                template_nome=env.template_nome or "",
                texto=preview[:500],
                message_id=mid,
                sucesso=True,
                aba="MAILING",
                ref_id="",
                data_hora=env.enviado_em,
            )
            ja.add(mid)
            criados += 1
        except Exception:
            pulados += 1
    out = {"ok": True, "criados": criados, "pulados": pulados, "limite": limite}
    if corrigir_datas:
        out["datas"] = corrigir_datas_mailing_no_inbox(limite=max(limite, 500))
    return out
