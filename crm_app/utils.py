from PIL import Image, ImageDraw, ImageFont
import io

def gerar_imagem_resumo(dados_comissao):
    """
    Gera uma imagem (buffer) com o resumo das comissões.
    dados_comissao: dict ex: {'vendedor': 'João', 'vendas': 15, 'total': 'R$ 5.000,00'}
    """
    # 1. Configurações da Imagem
    width, height = 600, 400
    background_color = (240, 240, 240) # Cinza claro
    card_color = (255, 255, 255)       # Branco
    primary_color = (0, 123, 255)      # Azul (exemplo de cor da marca)
    text_color = (50, 50, 50)          # Cinza escuro

    # Cria a "tela" vazia
    imagem = Image.new('RGB', (width, height), color=background_color)
    draw = ImageDraw.Draw(imagem)

    # 2. Desenhar o "Card" (Retângulo branco centralizado)
    margin = 40
    draw.rectangle(
        [(margin, margin), (width - margin, height - margin)], 
        fill=card_color, 
        outline=(200, 200, 200), 
        width=2
    )

    # 3. Carregar Fonte (Usa padrão se não tiver específica)
    try:
        # Tenta usar Arial ou similar se estiver no OS
        font_header = ImageFont.truetype("arial.ttf", 36)
        font_text = ImageFont.truetype("arial.ttf", 24)
        font_bold = ImageFont.truetype("arialbd.ttf", 28)
    except IOError:
        # Fallback para fonte padrão do Linux/Server
        font_header = ImageFont.load_default()
        font_text = ImageFont.load_default()
        font_bold = ImageFont.load_default()

    # 4. Escrever os Textos
    # Cabeçalho (Faixa azul ou apenas texto)
    draw.text((60, 60), "Resumo de Comissões", font=font_header, fill=primary_color)
    
    # Linha divisória
    draw.line([(60, 110), (540, 110)], fill=(230,230,230), width=2)

    # Dados do Vendedor
    y_start = 140
    line_height = 50
    
    draw.text((60, y_start), f"Vendedor:", font=font_text, fill=(150,150,150))
    draw.text((200, y_start), dados_comissao['vendedor'], font=font_bold, fill=text_color)
    
    draw.text((60, y_start + line_height), f"Qtd. Vendas:", font=font_text, fill=(150,150,150))
    draw.text((200, y_start + line_height), str(dados_comissao['vendas']), font=font_bold, fill=text_color)

    # Destaque do Valor
    draw.rectangle([(60, 260), (540, 340)], fill=(235, 245, 255)) # Fundo azul bem claro
    draw.text((80, 285), "Total a Receber:", font=font_text, fill=primary_color)
    draw.text((300, 280), dados_comissao['total'], font=font_header, fill=(0, 150, 0)) # Verde

    # 5. Salvar em Memória (não salva arquivo no disco)
    buffer = io.BytesIO()
    imagem.save(buffer, format='PNG')
    buffer.seek(0) # Volta o ponteiro para o início do arquivo na memória
    
    return buffer