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

## 3. Ver o que aconteceu em produção (screenshots)

Em produção não há tela, então não dá para "abrir o navegador" no servidor. A alternativa é **salvar screenshots** em cada etapa e consultá-los pela API.

### Ativar em produção

1. **Variável de ambiente** no Railway/Heroku: `PAP_CAPTURE_SCREENSHOTS=true`
2. A automação salva imagens em `downloads/` como `pap_venda_{sessao_id}_{etapa}_{timestamp}.png` (etapas: `01_login_ok`, `02_viabilidade_disponivel`, `03_cpf_cliente_ok`, etc.).
3. **Ver os screenshots:** em produção acesse `GET /api/crm/debug/screenshots/` para listar e `GET /api/crm/debug/screenshots/{nome_arquivo}/` para baixar.

**Nota:** Em plataformas como Railway a pasta `downloads/` pode ser efêmera; para guardar por mais tempo, considere storage externo (S3, etc.).

---

## Resumo

| Objetivo | Como fazer |
|----------|------------|
| Ver cada etapa sem usar WhatsApp | `python manage.py testar_pap_terminal` |
| Ver cada etapa com fluxo real pelo WhatsApp | Rodar o servidor local com `PAP_HEADLESS=false` e disparar pelo WhatsApp (ex.: com ngrok) |
| Ver como estava a tela em produção | Ativar `PAP_CAPTURE_SCREENSHOTS=true` e acessar `/api/crm/debug/screenshots/` |

A lógica da automação é a mesma em ambos os casos; só muda quem “envia” as mensagens (terminal ou WhatsApp).
