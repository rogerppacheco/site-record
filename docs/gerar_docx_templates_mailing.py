"""Gera o Word dos templates MARKETING de mailing (sem oferta).

Uso (na raiz site-record, com venv):
  python docs/gerar_docx_templates_mailing.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

DOCS = Path(__file__).resolve().parent

# Specs espelhadas de crm_app.services.mailing_templates (sem Django)
TEMPLATE_SPECS = [
    {
        "nome": "mailing_reparo_v1",
        "titulo": "Reparo / problema de internet",
        "categoria": "MARKETING",
        "corpo": "Olá, {{1}}.\n\nSua internet está com algum problema?\n\nFale conosco — podemos te ajudar.",
        "variaveis": [["{{1}}", "Primeiro nome", "Maria"]],
        "botoes": ["Falar conosco", "Agora não"],
    },
    {
        "nome": "mailing_instalacao_v1",
        "titulo": "Instalação recente",
        "categoria": "MARKETING",
        "corpo": "Olá, {{1}}.\n\nTudo certo com a internet no seu endereço?\n\nSe precisar de suporte, fale conosco.",
        "variaveis": [["{{1}}", "Primeiro nome", "João"]],
        "botoes": ["Falar conosco", "Agora não"],
    },
    {
        "nome": "mailing_mudanca_v1",
        "titulo": "Mudança de endereço",
        "categoria": "MARKETING",
        "corpo": "Olá, {{1}}.\n\nHouve mudança de endereço ou instalação?\n\nPodemos esclarecer suas dúvidas por aqui.",
        "variaveis": [["{{1}}", "Primeiro nome", "Ana"]],
        "botoes": ["Falar conosco", "Agora não"],
    },
    {
        "nome": "mailing_servico_v1",
        "titulo": "Serviço / retirada",
        "categoria": "MARKETING",
        "corpo": "Olá, {{1}}.\n\nSobre o serviço de internet no seu endereço: podemos te orientar.\n\nFale conosco.",
        "variaveis": [["{{1}}", "Primeiro nome", "Carlos"]],
        "botoes": ["Falar conosco", "Agora não"],
    },
    {
        "nome": "mailing_cancelamento_v1",
        "titulo": "Cancelamento",
        "categoria": "MARKETING",
        "corpo": "Olá, {{1}}.\n\nVimos que o serviço em {{2}} foi cancelado.\n\nSe quiser informações, fale conosco.",
        "variaveis": [["{{1}}", "Primeiro nome", "Lucia"], ["{{2}}", "Cidade ou bairro", "Uberlândia"]],
        "botoes": ["Falar conosco", "Agora não"],
    },
    {
        "nome": "mailing_fechado_v1",
        "titulo": "Contrato fechado",
        "categoria": "MARKETING",
        "corpo": "Olá, {{1}}.\n\nO contrato em {{2}} aparece fechado.\n\nSe tiver dúvidas, podemos te ajudar.",
        "variaveis": [["{{1}}", "Primeiro nome", "Pedro"], ["{{2}}", "Cidade ou bairro", "Franca"]],
        "botoes": ["Falar conosco", "Agora não"],
    },
    {
        "nome": "mailing_aberto_v1",
        "titulo": "Chamado aberto / técnico",
        "categoria": "MARKETING",
        "corpo": "Olá, {{1}}.\n\nHá um chamado em andamento em {{2}}.\n\nPrecisa de orientação? Fale conosco.",
        "variaveis": [["{{1}}", "Primeiro nome", "Fernanda"], ["{{2}}", "Cidade ou bairro", "Uberaba"]],
        "botoes": ["Falar conosco", "Agora não"],
    },
    {
        "nome": "mailing_generico_v1",
        "titulo": "Genérico",
        "categoria": "MARKETING",
        "corpo": "Olá, {{1}}.\n\nPodemos te ajudar com informações sobre internet no seu endereço.\n\nFale conosco.",
        "variaveis": [["{{1}}", "Primeiro nome", "Rafael"]],
        "botoes": ["Falar conosco", "Agora não"],
    },
]

_spec = importlib.util.spec_from_file_location(
    "gerar_funil_util", DOCS / "gerar_docx_templates_funil_utilitarios.py"
)
_funil = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_funil)

OUT = DOCS / "WhatsApp_Templates_Mailing_Mercado.docx"
PREVIEWS_MAILING = DOCS / "previews_templates_mailing"


def main() -> None:
    PREVIEWS_MAILING.mkdir(parents=True, exist_ok=True)
    specs = []
    for i, raw in enumerate(TEMPLATE_SPECS, start=1):
        exemplo = raw["corpo"]
        for idx, (_var, _sig, ex) in enumerate(raw["variaveis"], start=1):
            exemplo = exemplo.replace("{{%d}}" % idx, ex)
        arquivo = f"{i:02d}_{raw['nome']}.png"
        img = PREVIEWS_MAILING / arquivo
        _funil.render_phone(img, exemplo, raw["botoes"])
        specs.append({
            "titulo": f"{i}. {raw['titulo']}",
            "nome": raw["nome"],
            "categoria": raw.get("categoria", "MARKETING"),
            "uso": "Mailing comprado no mercado. Tom informativo, sem oferta. Induz contato.",
            "corpo": raw["corpo"],
            "variaveis": raw["variaveis"],
            "botoes": raw["botoes"],
            "exemplo": exemplo,
            "imagem": img,
            "sessao": "Após o botão Falar conosco, atenda a dúvida do cliente sem pitch agressivo.",
        })

    doc = _funil.Document()
    section = doc.sections[0]
    section.top_margin = _funil.Cm(1.6)
    section.bottom_margin = _funil.Cm(1.6)
    section.left_margin = _funil.Cm(1.8)
    section.right_margin = _funil.Cm(1.8)

    _funil.add_heading_styled(doc, "Templates mailing de mercado — Meta WhatsApp", 1)
    _funil.add_p(
        doc,
        "Categoria MARKETING (listas frias)  ·  idioma pt_BR",
        size=12,
        color=_funil.RGBColor(80, 86, 92),
        after=8,
    )
    _funil.add_p(
        doc,
        "Mensagens curtas para induzir o cliente a pedir informação. Sem preço, promoção ou pitch. "
        "Botões: Falar conosco | Agora não.",
        after=12,
    )
    for spec in specs:
        _funil.add_template(doc, spec)
    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
