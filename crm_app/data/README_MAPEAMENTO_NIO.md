# Mapeamento do fluxo 2ª Via Nio

## Objetivo

Mapear o fluxo de **2ª via de conta** no site
https://www.niointernet.com.br/ajuda/servicos/segunda-via/ para automação do
comando **Conta** no WhatsApp, evitando o reCAPTCHA do site negociacao.niointernet.com.br.

## Como usar

```bash
python manage.py mapear_segunda_via_nio
```

1. O navegador abre na página da segunda via
2. **Cada mudança de URL** é registrada automaticamente
3. **Pressione Enter** no terminal para capturar o estado atual (útil em SPAs onde a URL não muda)
4. **Ctrl+C** para salvar o mapa e sair

### Opções

- `--capture-once`: Captura uma vez e sai (testar se a página carrega)
- `--headless`: Roda sem janela visível (não recomendado para mapeamento)

## Resultado

O mapa é salvo em `crm_app/data/nio_segunda_via_map.json` com:

- `url`: URL atual
- `inputs`: Campos (id, name, placeholder, selectors)
- `buttons`: Botões e elementos clicáveis
- `links`: Links relevantes
- `iframes`: Se houver iframes no formulário

## Primeira captura (página inicial)

A captura inicial encontrou:

- **Input CPF/CNPJ**: `#cpf-cnpj` (ou `[name="cpf-cnpj"]`)
- **Links** para negociacao.niointernet.com.br ("2ª via de conta", "Segunda via de conta")

> ⚠️ Se o formulário redirecionar para negociacao.niointernet.com.br ao
> consultar, o fluxo passará pelo reCAPTCHA. Rode o mapeamento completo para
> descobrir se há alternativa sem captcha.

## Automação implementada

A função `buscar_fatura_segunda_via_site(cpf)` em `services_nio.py` automatiza:

1. Preencher CPF em `#cpf-cnpj`
2. Clicar seta para consultar (`img.segunda-via__icon-button`)
3. Extrair referência do mês (`div.resultados-entry__cell.title`)
4. Extrair valor (`div.resultados-entry__cell.amount`)
5. Extrair vencimento (`div.resultados-entry__cell.due-date`)
6. Extrair status (`span.resultados-status-chip`)
7. Clicar seta para expandir (`svg.resultados-entry__icon`)
8. Clicar "Gerar Pix" (`#desktop-generate-pix`)
9. Clicar "Copiar Código" (`#pixCopyButton`) e ler clipboard
10. Clicar Download (`#downloadInvoice`)
11. PDF salvo como `{cpf}_{ddmmaaaa}.pdf` (page.pdf() se modal Windows abrir)

## Comandos no WhatsApp

- **Fatura** – Mantém o fluxo atual (Nio Negociar / API).
- **Conta** – Usa o site 2ª via (www.niointernet.com.br/ajuda/servicos/segunda-via/), sem reCAPTCHA. O usuário envia *Conta*, informa o CPF e recebe os dados da conta + PDF quando disponível.
