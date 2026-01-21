#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para descobrir os seletores corretos da página após consulta
"""

import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from playwright.sync_api import sync_playwright
import re

def descobrir_seletores(cpf):
    """Descobre seletores da página após consulta"""
    print("="*80)
    print(f"DESCOBRINDO SELETORES PARA CPF: {cpf}")
    print("="*80)
    
    NIO_BASE_URL = "https://www.niointernet.com.br/ajuda/servicos/segunda-via/"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless=False para ver o navegador
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        
        print("\n1. Navegando para a página...")
        page.goto(NIO_BASE_URL, wait_until="networkidle")
        page.wait_for_timeout(2000)
        
        print("2. Preenchendo CPF...")
        input_cpf = page.locator('#cpf-cnpj').first
        input_cpf.fill(cpf)
        page.wait_for_timeout(500)
        
        print("3. Clicando em Consultar...")
        btn_consultar = page.locator('button[type="submit"]').first
        btn_consultar.click()
        
        print("4. Aguardando carregamento da página de resultado...")
        page.wait_for_url('**/resultado/**', timeout=15000)
        page.wait_for_timeout(3000)  # Aguardar mais tempo para garantir carregamento
        
        print("\n" + "="*80)
        print("ANALISANDO ELEMENTOS DA PÁGINA")
        print("="*80)
        
        # Pegar HTML completo
        html = page.content()
        
        # Listar todos os botões
        print("\n📌 TODOS OS BOTÕES ENCONTRADOS:")
        print("-"*80)
        buttons = page.locator('button').all()
        for i, btn in enumerate(buttons[:20], 1):  # Limitar a 20
            try:
                text = btn.inner_text(timeout=1000)
                is_visible = btn.is_visible()
                classes = btn.get_attribute('class') or ''
                btn_id = btn.get_attribute('id') or ''
                btn_type = btn.get_attribute('type') or ''
                
                if is_visible and text.strip():
                    print(f"\n{i}. Texto: '{text.strip()}'")
                    print(f"   Visível: {is_visible}")
                    if btn_id:
                        print(f"   ID: #{btn_id}")
                    if classes:
                        print(f"   Classes: .{classes.split()[0] if classes.split() else ''}")
                    if btn_type:
                        print(f"   Type: {btn_type}")
                    
                    # Sugerir seletor
                    if btn_id:
                        print(f"   Seletor sugerido: button#{btn_id}")
                    elif classes:
                        primeira_classe = classes.split()[0]
                        print(f"   Seletor sugerido: button.{primeira_classe}")
                    else:
                        print(f"   Seletor sugerido: button:has-text('{text.strip()[:30]}')")
            except Exception as e:
                pass
        
        # Listar todos os links (a)
        print("\n\n🔗 TODOS OS LINKS ENCONTRADOS:")
        print("-"*80)
        links = page.locator('a').all()
        for i, link in enumerate(links[:20], 1):  # Limitar a 20
            try:
                text = link.inner_text(timeout=1000)
                is_visible = link.is_visible()
                href = link.get_attribute('href') or ''
                classes = link.get_attribute('class') or ''
                link_id = link.get_attribute('id') or ''
                
                if is_visible and text.strip():
                    texto_limpo = text.strip()
                    if any(kw in texto_limpo.lower() for kw in ['pagar', 'boleto', 'detalhes', 'gerar', 'download', 'baixar']):
                        print(f"\n{i}. Texto: '{texto_limpo}'")
                        print(f"   Visível: {is_visible}")
                        if link_id:
                            print(f"   ID: #{link_id}")
                        if classes:
                            print(f"   Classes: .{classes.split()[0] if classes.split() else ''}")
                        if href:
                            print(f"   Href: {href[:100]}")
                        
                        # Sugerir seletor
                        if link_id:
                            print(f"   Seletor sugerido: a#{link_id}")
                        elif classes:
                            primeira_classe = classes.split()[0]
                            print(f"   Seletor sugerido: a.{primeira_classe}")
                        else:
                            print(f"   Seletor sugerido: a:has-text('{texto_limpo[:30]}')")
            except Exception as e:
                pass
        
        # Procurar por elementos com texto específico usando JavaScript
        print("\n\n🔍 ELEMENTOS COM TEXTOS RELEVANTES (via JavaScript):")
        print("-"*80)
        
        # Executar JavaScript para encontrar elementos
        elementos_js = page.evaluate("""
            () => {
                const keywords = ['pagar', 'boleto', 'detalhes', 'gerar', 'download', 'baixar', 'conta'];
                const resultados = [];
                
                // Função para verificar se elemento está visível
                function isVisible(el) {
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
                }
                
                // Procurar em todos os elementos
                const allElements = document.querySelectorAll('*');
                allElements.forEach(el => {
                    const text = el.innerText || el.textContent || '';
                    if (text.trim() && isVisible(el)) {
                        const textoLower = text.trim().toLowerCase();
                        if (keywords.some(kw => textoLower.includes(kw))) {
                            const tagName = el.tagName.toLowerCase();
                            const id = el.id ? '#' + el.id : '';
                            const classes = el.className ? '.' + el.className.split(' ').join('.') : '';
                            const selector = tagName + id + classes;
                            
                            resultados.push({
                                tag: tagName,
                                text: text.trim().substring(0, 100),
                                selector: selector,
                                id: el.id || '',
                                classes: el.className || '',
                                visible: isVisible(el)
                            });
                        }
                    }
                });
                
                return resultados.slice(0, 30); // Limitar a 30
            }
        """)
        
        for i, elem in enumerate(elementos_js, 1):
            print(f"\n{i}. Tag: <{elem['tag']}>")
            print(f"   Texto: '{elem['text'][:80]}'")
            print(f"   Seletor CSS: {elem['selector'][:100]}")
            if elem['id']:
                print(f"   ID: #{elem['id']}")
            if elem['classes']:
                classes_list = elem['classes'].split()[:3]
                print(f"   Classes (primeiras): .{' .'.join(classes_list)}")
        
        # Salvar HTML para análise manual
        downloads_dir = os.path.join(os.path.dirname(__file__), 'downloads')
        os.makedirs(downloads_dir, exist_ok=True)
        html_path = os.path.join(downloads_dir, f'debug_seletores_{cpf}.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"\n\n💾 HTML salvo em: {html_path}")
        print("   Você pode abrir este arquivo no navegador para inspecionar manualmente")
        
        # Pausar para inspeção manual (opcional)
        print("\n" + "="*80)
        print("⏸️  Navegador aberto. Pressione Enter para fechar...")
        print("   Você pode inspecionar a página manualmente usando F12 (DevTools)")
        print("="*80)
        input()
        
        browser.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Uso: python descobrir_seletores.py <CPF>")
        print("Exemplo: python descobrir_seletores.py 81721021604")
        sys.exit(1)
    
    cpf = sys.argv[1]
    # Limpar CPF
    import re
    cpf_limpo = re.sub(r'\D', '', cpf)
    
    if len(cpf_limpo) != 11:
        print(f"❌ CPF inválido. Deve ter 11 dígitos. Recebido: {len(cpf_limpo)} dígitos")
        sys.exit(1)
    
    descobrir_seletores(cpf_limpo)
