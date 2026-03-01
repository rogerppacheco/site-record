# Base de conhecimento da IA do bot WhatsApp

O conteúdo desta pasta é carregado e enviado à IA (Groq/Gemini) para que o bot responda com base em **telecom**, **Nio** e **dados da sua empresa**.

## Arquivos

- **conhecimento.md** – Edite este arquivo com:
  - Informações sobre a empresa e a Nio
  - Resumo dos planos (nome, velocidade, valor, benefícios) – pode colar texto extraído dos PDFs
  - Regras de negócio, prazos, processos
  - Qualquer texto que ajude a IA a responder dúvidas dos vendedores

- **schema_tabelas.md** – (opcional) Descrição das tabelas do banco. Pode ser gerado automaticamente pelo projeto; você pode completar com explicações.

## Como usar

1. Edite **conhecimento.md** em qualquer editor de texto.
2. Use as seções sugeridas (Empresa/Nio, Planos, Processos) ou crie as suas.
3. Para conteúdo de PDF: copie e cole o texto dos planos/tabelas para dentro do `conhecimento.md`. Se o PDF for só imagem, use um conversor PDF → texto antes.
4. Salve o arquivo. Na próxima mensagem no WhatsApp que for respondida pela IA, o novo conteúdo já será considerado (não precisa reiniciar o servidor se o arquivo for lido a cada requisição).

## Dicas

- Seja objetivo: listas e tópicos curtos funcionam melhor do que parágrafos longos.
- Inclua nomes exatos de planos, valores e prazos que a IA deve citar.
- Não coloque dados sensíveis (senhas, chaves) aqui; o arquivo pode ir para o repositório.
