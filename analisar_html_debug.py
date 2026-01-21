#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para analisar o HTML de debug e encontrar seletores corretos
"""

import re
from html.parser import HTMLParser
from collections import defaultdict

class ElementFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.current_tag = None
        self.current_attrs = {}
        self.text_content = ""
        self.stack = []
    
    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        self.current_attrs = dict(attrs)
        self.stack.append((tag, dict(attrs), self.text_content))
    
    def handle_endtag(self, tag):
        if self.stack:
            tag_name, attrs, text = self.stack.pop()
            # Salvar elementos que podem ser botões ou links interessantes
            if tag_name in ['button', 'a', 'div', 'span', 'p']:
                text_clean = text.strip().lower()
                if any(keyword in text_clean for keyword in ['pagar', 'boleto', 'detalhes', 'gerar', 'consultar', 'download']):
                    self.elements.append({
                        'tag': tag_name,
                        'attrs': attrs,
                        'text': text.strip()[:100],
                        'classes': attrs.get('class', '').split() if 'class' in attrs else [],
                        'id': attrs.get('id', ''),
                        'href': attrs.get('href', ''),
                        'type': attrs.get('type', ''),
                    })
        self.text_content = ""
    
    def handle_data(self, data):
        self.text_content += data


def analisar_html(html_path):
    """Analisa o HTML e encontra elementos relevantes"""
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    print("="*80)
    print("ANÁLISE DO HTML DE DEBUG")
    print("="*80)
    
    # Encontrar elementos com texto relevante usando regex
    print("\n📋 ELEMENTOS ENCONTRADOS COM TEXTOS RELEVANTES:\n")
    
    # Procurar por padrões comuns
    patterns = [
        (r'<(button|a|div|span|p)[^>]*>([^<]*(?:pagar|Pagar|PAGAR)[^<]*)</(button|a|div|span|p)>', 'Pagar'),
        (r'<(button|a|div|span|p)[^>]*>([^<]*(?:boleto|Boleto|BOLETO)[^<]*)</(button|a|div|span|p)>', 'Boleto'),
        (r'<(button|a|div|span|p)[^>]*>([^<]*(?:detalhes|Detalhes|DETALHES)[^<]*)</(button|a|div|span|p)>', 'Detalhes'),
        (r'<(button|a|div|span|p)[^>]*>([^<]*(?:gerar|Gerar|GERAR)[^<]*)</(button|a|div|span|p)>', 'Gerar'),
        (r'<(button|a|div|span|p)[^>]*>([^<]*(?:download|Download|DOWNLOAD)[^<]*)</(button|a|div|span|p)>', 'Download'),
    ]
    
    elementos_encontrados = defaultdict(list)
    
    for pattern, categoria in patterns:
        matches = re.finditer(pattern, html, re.IGNORECASE)
        for match in matches:
            full_match = match.group(0)
            # Extrair atributos do elemento
            tag_match = re.search(r'<(\w+)', full_match)
            attrs_match = re.findall(r'(\w+)="([^"]*)"', full_match)
            text_match = re.search(r'>([^<]+)<', full_match)
            
            elementos_encontrados[categoria].append({
                'full_html': full_match[:300],
                'tag': tag_match.group(1) if tag_match else '?',
                'attrs': dict(attrs_match),
                'text': text_match.group(1).strip() if text_match else ''
            })
    
    # Mostrar resultados organizados
    for categoria, elementos in elementos_encontrados.items():
        print(f"\n{'='*80}")
        print(f"🔍 CATEGORIA: {categoria.upper()} ({len(elementos)} elementos encontrados)")
        print(f"{'='*80}")
        for i, elem in enumerate(elementos[:5], 1):  # Mostrar apenas os 5 primeiros
            print(f"\n{i}. Tag: <{elem['tag']}>")
            print(f"   Texto: {elem['text']}")
            if elem['attrs']:
                print(f"   Atributos:")
                for key, value in list(elem['attrs'].items())[:5]:  # Limitar atributos
                    print(f"     {key}: {value}")
            print(f"   HTML completo (primeiros 200 chars):")
            print(f"     {elem['full_html'][:200]}...")
    
    # Procurar por classes CSS comuns
    print("\n\n" + "="*80)
    print("📌 CLASSES CSS ENCONTRADAS:")
    print("="*80)
    classes_encontradas = re.findall(r'class="([^"]*)"', html)
    classes_relevantes = set()
    for class_str in classes_encontradas:
        for cls in class_str.split():
            if any(kw in cls.lower() for kw in ['button', 'btn', 'pagar', 'boleto', 'detail', 'action', 'link']):
                classes_relevantes.add(cls)
    
    print("\n".join(sorted(classes_relevantes)[:30]))
    
    # Procurar por IDs relevantes
    print("\n\n" + "="*80)
    print("🆔 IDs ENCONTRADOS:")
    print("="*80)
    ids_encontrados = re.findall(r'id="([^"]*)"', html)
    ids_relevantes = [id_val for id_val in ids_encontrados if any(kw in id_val.lower() for kw in ['button', 'btn', 'pagar', 'boleto', 'detail', 'action'])]
    print("\n".join(ids_relevantes[:30]))
    
    # Sugerir seletores
    print("\n\n" + "="*80)
    print("💡 SUGESTÕES DE SELETORES:")
    print("="*80)
    
    if elementos_encontrados.get('Pagar'):
        elem = elementos_encontrados['Pagar'][0]
        print("\nPara 'Pagar conta':")
        if elem['attrs'].get('class'):
            classes = elem['attrs']['class'].split()
            print(f"  - page.locator('.{classes[0]}')")
            print(f"  - page.locator('{elem['tag']}.{classes[0]}')")
        if elem['attrs'].get('id'):
            print(f"  - page.locator('#{elem['attrs']['id']}')")
        print(f"  - page.locator('{elem['tag']}:has-text(\"{elem['text'][:30]}\")')")
    
    if elementos_encontrados.get('Boleto'):
        elem = elementos_encontrados['Boleto'][0]
        print("\nPara 'Gerar boleto':")
        if elem['attrs'].get('class'):
            classes = elem['attrs']['class'].split()
            print(f"  - page.locator('.{classes[0]}')")
        if elem['attrs'].get('id'):
            print(f"  - page.locator('#{elem['attrs']['id']}')")
        print(f"  - page.locator('{elem['tag']}:has-text(\"{elem['text'][:30]}\")')")


if __name__ == '__main__':
    import sys
    html_path = 'downloads/debug_plano_a_no_pagar_81721021604.html'
    if len(sys.argv) > 1:
        html_path = sys.argv[1]
    
    try:
        analisar_html(html_path)
    except FileNotFoundError:
        print(f"❌ Arquivo não encontrado: {html_path}")
        print("Execute o teste primeiro para gerar o arquivo de debug.")
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()
