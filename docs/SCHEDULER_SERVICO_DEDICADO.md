# Scheduler em serviço dedicado

O APScheduler **não** roda mais dentro do Gunicorn. Tarefas automáticas ficam em um processo separado.

## Comandos

| Processo | Comando |
|----------|---------|
| Web (HTTP) | `gunicorn gestao_equipes.wsgi ...` |
| Scheduler | `python manage.py run_scheduler` |

## Railway (automático)

No PowerShell, na pasta do projeto:

```powershell
railway login
powershell -ExecutionPolicy Bypass -File scripts\railway_setup_scheduler.ps1
```

O script cria o serviço `site-record-scheduler`, copia as variáveis do web, faz deploy e usa `Dockerfile.scheduler` + `railway.scheduler.toml`.

Depois, no painel Railway (serviço scheduler): **Settings → Config-as-code** → `/railway.scheduler.toml` e **Replicas = 1**.

Serviço **web**: continua com `Dockerfile` (Gunicorn). **Não** roda mais o scheduler.

## Local

Terminal 1: `python manage.py runserver`  
Terminal 2: `python manage.py run_scheduler`

## Jobs (inalterados)

- Faturas Nio — diário 00:05
- Performance — verificação a cada 1 min
- Boas-vindas — fila a cada 5 min
- Sonax fallback — a cada 2 min
