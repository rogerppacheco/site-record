# Sessões PAP (storage state Playwright)

Este diretório guarda os arquivos `pap_session_<MATRICULA>.json` com cookies e tokens
de sessão do portal PAP Nio / V.tal.

## Segurança

- **Nunca** commite arquivos `*.json` desta pasta — eles contêm JWT e cookies ativos.
- O `.gitignore` bloqueia `pap_sessions/*.json`.
- Se um token já foi exposto no Git, invalide a sessão no PAP (novo login) ou remova o arquivo localmente.

## Desenvolvimento local

Por padrão as sessões ficam em `pap_sessions/` na raiz do projeto (`PAP_SESSIONS_DIR` não definido).

## Produção (Railway — serviço PAP)

O `railway.pap.toml` monta o volume `pap-sessions` em `/data/pap_sessions` e define:

```env
PAP_SESSIONS_DIR=/data/pap_sessions
```

**Configuração única no Railway:**

1. Abra o serviço **site-record-pap** (ou equivalente).
2. Em **Volumes**, crie um volume chamado `pap-sessions` (se ainda não existir).
3. Confirme que a variável `PAP_SESSIONS_DIR=/data/pap_sessions` está definida (o toml já injeta).
4. Redeploy do serviço PAP.

As sessões sobrevivem a redeploys sem precisar relogar a cada deploy.
