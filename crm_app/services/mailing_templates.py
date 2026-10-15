"""Templates Meta (MARKETING) para mailings comprados — tom informativo, sem oferta."""
from __future__ import annotations

from typing import Any, Sequence, Tuple

from crm_app.models import MailingContato
from crm_app.services.mailing_import_service import primeiro_nome
from crm_app.services.whatsapp.nio_templates import enviar_template_cliente, tentar_enviar_ou_texto

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
        'categoria': 'MARKETING',
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
        'categoria': 'MARKETING',
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
        'categoria': 'MARKETING',
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
        'categoria': 'MARKETING',
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
        'categoria': 'MARKETING',
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
        'categoria': 'MARKETING',
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
        'categoria': 'MARKETING',
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
        'categoria': 'MARKETING',
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


def enviar_mailing_contato(contato: MailingContato) -> Tuple[bool, Any, str, str]:
    """Envia template (ou fallback texto). Retorna (ok, resp, canal, template_nome)."""
    template = template_para_situacao(contato.situacao)
    params = body_params_contato(contato)
    ok, resp, canal = tentar_enviar_ou_texto(
        contato.telefone_e164,
        template,
        params,
        fallback_texto(contato),
    )
    return ok, resp, canal, template
