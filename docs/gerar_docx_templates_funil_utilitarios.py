"""Gera o Word dos templates utilitários do funil, com prévia simulada."""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

DOCS = Path(__file__).resolve().parent
PREVIEWS = DOCS / "previews_templates_funil"
OUT = DOCS / "WhatsApp_Templates_Funil_Utilitarios.docx"

GREEN = (32, 168, 92)
GREEN_DARK = (18, 110, 62)
INK = (32, 36, 40)
MUTED = (110, 116, 122)
CARD = (255, 255, 255)
SCREEN = (247, 248, 249)
BEZEL = (28, 32, 36)
LINE = (226, 230, 233)

FONT_REG = Path(r"C:\Windows\Fonts\segoeui.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\segoeuib.ttf")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REG
    return ImageFont.truetype(str(path), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        current = ""
        for word in para.split(" "):
            trial = word if not current else f"{current} {word}"
            if draw.textlength(trial, font=fnt) <= max_w:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=1) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def render_phone(path: Path, body: str, buttons: list[str]) -> None:
    scale = 2
    width = 390 * scale
    pad = 18 * scale
    header_h = 58 * scale
    text_w = width - pad * 2 - 36 * scale
    f_body = font(15 * scale)
    f_time = font(11 * scale)
    f_btn = font(14 * scale, bold=True)
    f_header = font(15 * scale, bold=True)

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    body_lines = wrap(probe, body, f_body, text_w)
    line_h = int(21 * scale)
    body_h = max(line_h, len(body_lines) * line_h)
    card_h = 18 * scale + body_h + 28 * scale
    btn_h = 40 * scale
    btn_gap = 8 * scale
    buttons_h = len(buttons) * btn_h + (len(buttons) - 1) * btn_gap
    screen_h = header_h + 16 * scale + card_h + 14 * scale + buttons_h + 18 * scale
    bezel = 12 * scale
    img_w = width + bezel * 2
    img_h = screen_h + bezel * 2 + 8 * scale

    img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    rounded(draw, (0, 0, img_w - 1, img_h - 1), 28 * scale, BEZEL)
    sx, sy = bezel, bezel
    rounded(draw, (sx, sy, sx + width, sy + screen_h), 18 * scale, SCREEN)
    draw.rectangle((sx, sy + header_h - 8, sx + width, sy + header_h), fill=GREEN)
    rounded(draw, (sx, sy, sx + width, sy + header_h), 18 * scale, GREEN)
    draw.rectangle((sx, sy + header_h - 20, sx + width, sy + header_h), fill=GREEN)

    icon_cx = sx + 28 * scale
    icon_cy = sy + header_h // 2
    draw.ellipse(
        (icon_cx - 11 * scale, icon_cy - 11 * scale, icon_cx + 11 * scale, icon_cy + 11 * scale),
        outline=(255, 255, 255),
        width=2 * scale,
    )
    draw.rounded_rectangle(
        (icon_cx - 4 * scale, icon_cy - 6 * scale, icon_cx + 4 * scale, icon_cy + 5 * scale),
        radius=2 * scale,
        fill=(255, 255, 255),
    )
    draw.text((sx + 48 * scale, sy + 18 * scale), "WhatsApp Business", font=f_header, fill=(255, 255, 255))

    card_x = sx + 16 * scale
    card_y = sy + header_h + 16 * scale
    card_r = sx + width - 16 * scale
    card_b = card_y + card_h
    rounded(draw, (card_x + 3, card_y + 4, card_r + 3, card_b + 4), 14 * scale, (230, 232, 234))
    rounded(draw, (card_x, card_y, card_r, card_b), 14 * scale, CARD, LINE, 2)

    tx = card_x + 16 * scale
    ty = card_y + 16 * scale
    for line in body_lines:
        if line:
            draw.text((tx, ty), line, font=f_body, fill=INK)
        ty += line_h
    draw.text((card_r - 52 * scale, card_b - 20 * scale), "12:00", font=f_time, fill=MUTED)

    by = card_b + 14 * scale
    for label in buttons:
        rounded(
            draw,
            (card_x, by, card_r, by + btn_h),
            10 * scale,
            CARD,
            GREEN,
            2 * scale,
        )
        tw = draw.textlength(label, font=f_btn)
        draw.text(
            (card_x + (card_r - card_x - tw) / 2, by + 10 * scale),
            label,
            font=f_btn,
            fill=GREEN_DARK,
        )
        by += btn_h + btn_gap

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def _set_run_font(run, name: str, size: int, bold: bool = False, color: RGBColor | None = None) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def _shade(cell, hex_color: str) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    tc_pr.append(shd)


def add_p(doc: Document, text: str = "", *, bold: bool = False, size: int = 11, after: int = 6, color: RGBColor | None = None, center: bool = False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(0)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    _set_run_font(run, "Calibri", size, bold, color)
    return p


def add_heading_styled(doc: Document, text: str, level: int) -> None:
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        _set_run_font(run, "Calibri", 18 if level == 1 else 14, True, RGBColor(18, 110, 62))


def add_code(doc: Document, text: str) -> None:
    for line in text.split("\n"):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = p.add_run(line if line else " ")
        _set_run_font(run, "Consolas", 10, color=RGBColor(32, 36, 40))


def add_kv(doc: Document, label: str, value: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    r1 = p.add_run(f"{label}: ")
    _set_run_font(r1, "Calibri", 11, True)
    r2 = p.add_run(value)
    _set_run_font(r2, "Calibri", 11)


def add_table(doc: Document, headers: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(header)
        _set_run_font(run, "Calibri", 10, True, RGBColor(255, 255, 255))
        _shade(cell, "12703E")
    for r_i, row in enumerate(rows):
        for c_i, value in enumerate(row):
            cell = table.rows[r_i + 1].cells[c_i]
            cell.text = ""
            p = cell.paragraphs[0]
            run = p.add_run(value)
            _set_run_font(run, "Calibri", 10)
            if r_i % 2 == 1:
                _shade(cell, "F4F7F5")
    doc.add_paragraph()


def add_template(doc: Document, spec: dict) -> None:
    add_heading_styled(doc, spec["titulo"], 2)
    add_kv(doc, "Nome", spec["nome"])
    add_kv(doc, "Categoria", spec.get("categoria", "UTILITY"))
    add_kv(doc, "Idioma", "pt_BR")
    add_kv(doc, "Uso no funil", spec["uso"])
    add_p(doc, "Corpo para colar no gerenciador", bold=True, after=4)
    add_code(doc, spec["corpo"])
    add_p(doc, "")
    add_p(doc, "Variáveis e exemplo", bold=True, after=4)
    add_table(doc, ["Variável", "Significado", "Exemplo"], spec["variaveis"])
    add_p(doc, "Botões Quick Reply", bold=True, after=2)
    for i, botao in enumerate(spec["botoes"], start=1):
        add_p(doc, f"{i}. {botao}", after=1)
    add_p(doc, "")
    add_p(doc, "Exemplo preenchido", bold=True, after=4)
    add_code(doc, spec["exemplo"])
    add_p(doc, "")
    add_p(doc, "Prévia simulada", bold=True, after=2, center=True)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    p.add_run().add_picture(str(spec["imagem"]), width=Cm(8.2))
    add_p(doc, "Depois do botão, em mensagem de sessão", bold=True, after=2)
    add_p(doc, spec["sessao"], after=10)


TEMPLATES = [
    {
        "titulo": "1. Contrato cancelado e adimplente",
        "nome": "nio_reativacao_contrato_v1",
        "uso": "Funil VENDAS, cruzado com churn e adimplência. A mensagem informa o cancelamento e a reativação, sem citar débito.",
        "arquivo": "01_reativacao_contrato.png",
        "corpo": (
            "Olá, {{1}}.\n"
            "\n"
            "O contrato Nio Fibra {{2}}, no endereço {{3}}, está cancelado.\n"
            "\n"
            "A reativação da fibra neste endereço pode ser solicitada por este WhatsApp."
        ),
        "variaveis": [
            ["{{1}}", "Primeiro nome", "Lucas"],
            ["{{2}}", "Número do contrato", "1045821"],
            ["{{3}}", "Endereço resumido", "Rua das Flores, 120"],
        ],
        "botoes": ["Quero reativar", "Falar com atendente", "Estou com dúvida"],
        "exemplo": (
            "Olá, Lucas.\n"
            "\n"
            "O contrato Nio Fibra 1045821, no endereço Rua das Flores, 120, está cancelado.\n"
            "\n"
            "A reativação da fibra neste endereço pode ser solicitada por este WhatsApp."
        ),
        "sessao": (
            "Lucas, a reativação do contrato 1045821 inclui a liberação dos canais fechados de IPTV "
            "da oferta de fibra cadastrada. Posso registrar a confirmação?"
        ),
    },
    {
        "titulo": "2. Crédito e viabilidade aprovados",
        "nome": "nio_consulta_viabilidade_v1",
        "uso": "Funil INTERESSE. Crédito e viabilidade já aprovados. O pedido está pronto para continuar.",
        "arquivo": "02_consulta_viabilidade.png",
        "corpo": (
            "Olá, {{1}}.\n"
            "\n"
            "Informação sobre o seu pedido de internet.\n"
            "\n"
            "Crédito e viabilidade aprovados para o endereço {{2}}.\n"
            "\n"
            "O pedido Nio Fibra {{3}} está pronto para continuar.\n"
            "\n"
            "Clique em uma das opções abaixo:"
        ),
        "variaveis": [
            ["{{1}}", "Primeiro nome", "Mariana"],
            ["{{2}}", "Endereço resumido", "Av. Brasil, 450"],
            ["{{3}}", "Número do pedido", "882341"],
        ],
        "botoes": ["Continuar pedido", "Falar com atendente", "Estou com dúvida"],
        "exemplo": (
            "Olá, Mariana.\n"
            "\n"
            "Informação sobre o seu pedido de internet.\n"
            "\n"
            "Crédito e viabilidade aprovados para o endereço Av. Brasil, 450.\n"
            "\n"
            "O pedido Nio Fibra 882341 está pronto para continuar.\n"
            "\n"
            "Clique em uma das opções abaixo:"
        ),
        "sessao": (
            "Mariana, a conclusão do pedido 882341 inclui a liberação dos canais fechados de IPTV "
            "da oferta de fibra cadastrada. Posso registrar a confirmação?"
        ),
    },
    {
        "titulo": "3. Falta somente a selfie (v1 — nome + Prot.)",
        "nome": "nio_selfie_pendente_v1",
        "uso": "Repescagem Bio (repescável=SIM). Editar/reaprovar na WABA #247: {{1}}=primeiro nome, {{2}}=Prot. {protocolo}. Botões: Falar com atendente | Estou com dúvida.",
        "arquivo": "03_validacao_pedido.png",
        "corpo": (
            "Olá, {{1}}.\n"
            "\n"
            "Informação sobre a instalação da sua internet.\n"
            "\n"
            "Seu pedido {{2}} não foi concluído. Está faltando a selfie.\n"
            "\n"
            "Para concluí-lo, favor fazer a selfie.\n"
            "\n"
            "Clique nas opções abaixo:"
        ),
        "variaveis": [
            ["{{1}}", "Primeiro nome", "Camila"],
            ["{{2}}", "Protocolo GED (Prot. N)", "Prot. 1453635"],
        ],
        "botoes": ["Falar com atendente", "Estou com dúvida"],
        "exemplo": (
            "Olá, Camila.\n"
            "\n"
            "Informação sobre a instalação da sua internet.\n"
            "\n"
            "Seu pedido Prot. 1453635 não foi concluído. Está faltando a selfie.\n"
            "\n"
            "Para concluí-lo, favor fazer a selfie.\n"
            "\n"
            "Clique nas opções abaixo:"
        ),
        "sessao": (
            "Camila, segue o link para a selfie do protocolo 1453635. "
            "Concluída a foto, a instalação da fibra segue com a liberação dos canais fechados de IPTV "
            "da oferta cadastrada."
        ),
    },
    {
        "titulo": "4. Boas-vindas com indicação",
        "nome": "nio_boas_vindas_indicacao_v1",
        "categoria": "MARKETING",
        "uso": "Depois da instalação concluída. A indicação entra no final, antes do agradecimento.",
        "arquivo": "04_boas_vindas_indicacao.png",
        "corpo": (
            "Olá, {{1}}.\n"
            "\n"
            "Sua instalação Nio Fibra foi concluída. Seja bem-vindo(a).\n"
            "\n"
            "Guarde este WhatsApp para suporte e dúvidas sobre a sua conexão.\n"
            "\n"
            "A cada indicação com instalação concluída, pagamos R$ 50,00.\n"
            "\n"
            "Clique em uma das opções abaixo.\n"
            "\n"
            "Obrigado por escolher a Nio Fibra."
        ),
        "variaveis": [
            ["{{1}}", "Primeiro nome", "Lucas"],
        ],
        "botoes": ["Quero indicar", "Falar com atendente", "Estou com dúvida"],
        "exemplo": (
            "Olá, Lucas.\n"
            "\n"
            "Sua instalação Nio Fibra foi concluída. Seja bem-vindo(a).\n"
            "\n"
            "Guarde este WhatsApp para suporte e dúvidas sobre a sua conexão.\n"
            "\n"
            "A cada indicação com instalação concluída, pagamos R$ 50,00.\n"
            "\n"
            "Clique em uma das opções abaixo.\n"
            "\n"
            "Obrigado por escolher a Nio Fibra."
        ),
        "sessao": (
            "Lucas, me passe o nome e o WhatsApp de quem você quer indicar. "
            "Com a instalação concluída, os R$ 50,00 são pagos a você."
        ),
    },
]


def main() -> None:
    for spec in TEMPLATES:
        img = PREVIEWS / spec["arquivo"]
        render_phone(img, spec["exemplo"], spec["botoes"])
        spec["imagem"] = img

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.6)
    section.bottom_margin = Cm(1.6)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)

    add_heading_styled(doc, "Templates utilitários — funil de vendas", 1)
    add_p(doc, "Nio Fibra  ·  WhatsAtende / WABA", size=12, color=RGBColor(80, 86, 92), after=8)
    add_p(
        doc,
        "Templates para submissão, idioma pt_BR. "
        "Os três primeiros são UTILITY. O de boas-vindas com indicação é MARKETING, por causa do pagamento de R$ 50,00. "
        "Cada um traz o texto para colar, as variáveis com exemplo, os botões e a prévia da mensagem já preenchida.",
    )
    add_p(
        doc,
        "A oferta de fibra e os canais fechados de IPTV ficam fora do template. "
        "Eles entram na mensagem de sessão, depois que a pessoa toca no botão.",
        after=12,
    )

    for spec in TEMPLATES:
        add_template(doc, spec)

    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
