# Como ver a automação PAP no navegador

Você pode acompanhar cada etapa da automação (login, CEP, viabilidade, CPF, etc.) de duas formas.

---

## 1. Pelo terminal (recomendado para debug)

O comando **testar_pap_terminal** abre o navegador na sua tela e você digita no terminal como se fosse o WhatsApp. O fluxo é o mesmo da produção.

```bash
python manage.py testar_pap_terminal
```

- O Chromium abre em **modo visível** (não headless).
- Você digita: **VENDER** → **SIM** → **CEP** → **Número** → **Referência** → **CPF** → etc.
- Cada mensagem que você “envia” no terminal é processada e você vê o site PAP respondendo no navegador.

**Opções:**

```bash
# Usar credenciais específicas (senão usa um BO e vendedor do banco)
python manage.py testar_pap_terminal --matricula-bo=SUA_MAT --senha-bo=SUA_SENHA --matricula-vendedor=MAT_VENDEDOR
```

Para **sair**: digite **CANCELAR** ou **/sair**.

---

## 2. Fluxo real do WhatsApp com navegador visível (teste local)

Quando você sobe o servidor **localmente** e dispara o fluxo pelo WhatsApp de verdade, a automação pode abrir o navegador na sua máquina para você ver cada etapa.

### Passos

1. **Defina a variável de ambiente** para o navegador não ficar em segundo plano:

   **Windows (PowerShell):**
   ```powershell
   $env:PAP_HEADLESS="false"
   python manage.py runserver
   ```

   **Windows (CMD):**
   ```cmd
   set PAP_HEADLESS=false
   python manage.py runserver
   ```

   **Linux/macOS:**
   ```bash
   export PAP_HEADLESS=false
   python manage.py runserver
   ```

2. **Exponha o servidor local** (para o WhatsApp conseguir chamar seu app), por exemplo com [ngrok](https://ngrok.com/):
   ```bash
   ngrok http 8000
   ```
   Configure a URL do webhook do WhatsApp para apontar para o URL do ngrok.

3. **No WhatsApp**, envie **VENDER** e siga o fluxo (SIM, CEP, número, referência, CPF, etc.).

4. Na sua máquina o **navegador abrirá** e você verá o PAP sendo preenchido em tempo real.

### Importante

- Use **PAP_HEADLESS=false** só em **ambiente de teste local** (sua máquina com monitor).
- Em **produção** (Railway, Heroku, etc.) **não** defina `PAP_HEADLESS=false`: lá não há tela e o padrão é navegador em segundo plano (`PAP_HEADLESS=true`).

---

## 3. Ver o que aconteceu em produção (screenshots + trace)

Em produção não há tela, então não dá para "abrir o navegador" no servidor. A alternativa é **salvar screenshots** em cada etapa e, quando ativado, um **trace** do Playwright para inspecionar cada clique.

### Ativar em produção

1. **Variável de ambiente** no Railway/Heroku: `PAP_CAPTURE_SCREENSHOTS=true`
2. A automação salva:
   - **Screenshots** em `downloads/` como `pap_venda_{sessao_id}_{etapa}_{timestamp}.png`
   - **Trace** (quando screenshots estão ativos) como `pap_trace_{sessao_id}_{timestamp}.zip`
3. **Ver os screenshots:** em produção acesse `GET /api/crm/debug/screenshots/` para listar e `GET /api/crm/debug/screenshots/{nome_arquivo}/` para baixar.

### Etapas registradas em screenshot (Etapa 1 – Novo Pedido)

| Arquivo (exemplo) | Momento |
|------------------|--------|
| `01_login_ok` | Após login no PAP |
| `01a_antes_novo_pedido` | Tela atual antes de ir para Novo Pedido (ex.: auditoria) |
| `01b_apos_goto_novo_pedido` | Após navegar pela URL para novo pedido |
| `01c_apos_clique_menu_novo_pedido` | Só se foi usado fallback (clique no menu "Novo Pedido") |
| `01d_etapa1_concluida` | Formulário de novo pedido preenchido, antes da etapa CEP |
| `02_viabilidade_disponivel`, `03_cpf_cliente_ok`, etc. | Demais etapas da venda |

### Ver onde os cliques estão sendo feitos (Trace Playwright)

Quando `PAP_CAPTURE_SCREENSHOTS=true`, a automação também **grava um trace** (todas as ações: cliques, navegação, etc.). Assim você vê exatamente onde cada clique foi dado.

1. Após uma venda (ou erro), acesse `GET /api/crm/debug/screenshots/` e baixe o arquivo `pap_trace_*.zip` mais recente.
2. Abra [https://trace.playwright.dev](https://trace.playwright.dev) no navegador.
3. Arraste o arquivo `.zip` para a página (ou use "Load trace").
4. Use a timeline para ver cada ação; em cada frame dá para ver o snapshot da página e o elemento clicado.

Não é necessário nenhuma tecnologia extra no servidor: o Playwright grava o trace e o Trace Viewer é uma página web que abre o arquivo local.

### Salvar no OneDrive (junto com as outras ferramentas)

Se você já usa OneDrive no projeto (MS_CLIENT_ID, MS_REFRESH_TOKEN, etc.), pode enviar os screenshots para a mesma conta:

1. **Variáveis de ambiente:** `PAP_CAPTURE_SCREENSHOTS=true` e `PAP_SCREENSHOTS_ONEDRIVE=true`
2. Opcional: `PAP_ONEDRIVE_FOLDER=NomeDaPasta` (padrão: `PAP_Screenshots`). Os arquivos ficam em `{MS_DRIVE_FOLDER_ROOT}/{PAP_ONEDRIVE_FOLDER}/`, por exemplo `CDOI_Record_Vertical/PAP_Screenshots/`.
3. Cada screenshot continua sendo salvo em `downloads/` e também é enviado ao OneDrive; assim você vê tudo no mesmo lugar das outras ferramentas e não perde os arquivos se o servidor reiniciar.

**Nota:** Em plataformas como Railway a pasta `downloads/` pode ser efêmera; com OneDrive ativo os screenshots ficam guardados no drive.

---

## Resumo

| Objetivo | Como fazer |
|----------|------------|
| Ver cada etapa sem usar WhatsApp | `python manage.py testar_pap_terminal` |
| Ver cada etapa com fluxo real pelo WhatsApp | Rodar o servidor local com `PAP_HEADLESS=false` e disparar pelo WhatsApp (ex.: com ngrok) |
| Ver como estava a tela em produção | Ativar `PAP_CAPTURE_SCREENSHOTS=true` e acessar `/api/crm/debug/screenshots/` |
| Ver onde cada clique foi dado (trace) | Com screenshots ativos, baixar `pap_trace_*.zip` e abrir em https://trace.playwright.dev |

A lógica da automação é a mesma em ambos os casos; só muda quem “envia” as mensagens (terminal ou WhatsApp).

---

## 4. Correção: "Novo Pedido" (quando a tela não mudava)

Se o sistema ficava em **Auditoria de pedidos** (ou outra tela) e não abria o formulário de **Novo Pedido** só com a URL, a automação agora faz **fallback**: depois de tentar ir para a URL do novo pedido, se o campo "matrícula do vendedor" não aparecer em alguns segundos, ela **clica no item do menu lateral "Novo Pedido"**. Assim a troca de tela passa a funcionar mesmo quando a SPA não responde só ao `goto`.

Para acompanhar isso em produção, ative `PAP_CAPTURE_SCREENSHOTS=true` e confira os screenshots `01a_antes_novo_pedido`, `01b_apos_goto_novo_pedido` e, se houve fallback, `01c_apos_clique_menu_novo_pedido`.
