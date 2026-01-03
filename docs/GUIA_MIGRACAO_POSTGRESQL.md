# 🚀 GUIA COMPLETO: Migração MySQL → PostgreSQL (Railway)

## STATUS ATUAL:
✅ MySQL (JawsDB): 28.788 registros, 56 tabelas
✅ PostgreSQL (Railway): Criado e online
✅ Backup JSON: backup_mysql_producao_20260102_221849.json
✅ Conexões: Testadas e funcionando

---

## PASSO 1: CONFIGURAR SETTINGS PARA POSTGRESQL

Edite: `gestao_equipes/settings.py`

Encontre a seção DATABASES e altere para:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'railway',
        'USER': 'postgres',
        'PASSWORD': 'tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz',
        'HOST': 'maglev.proxy.rlwy.net',
        'PORT': '56422',
        'ATOMIC_REQUESTS': True,
        'CONN_MAX_AGE': 600,
    }
}
```

**IMPORTANTE**: Este é um passo LOCAL apenas. A produção continua em MySQL!

---

## PASSO 2: PREPARAR BANCO POSTGRESQL

```bash
# Instalar pacotes necessários
pip install psycopg2-binary

# Criar tabelas no PostgreSQL
python manage.py migrate --run-syncdb

# Carregar dados do backup
python manage.py loaddata backup_mysql_producao_20260102_221849.json
```

---

## PASSO 3: TESTAR LOCALMENTE

```bash
# Verificar dados importados
python manage.py dbshell

# Ou no Python:
python manage.py shell
>>> from crm_app.models import Cliente
>>> Cliente.objects.count()  # Deve retornar o mesmo que MySQL
```

---

## PASSO 4: CONFIGURAR NO HEROKU

```bash
# Adicionar variável de ambiente com PostgreSQL
heroku config:set DATABASE_URL='postgresql://postgres:tpOxGAuhWgQLedMRcYARBiPCkGMyZUkz@maglev.proxy.rlwy.net:56422/railway' --app record-pap-app

# Revert settings.py para MySQL (deixar como estava)
# (para não quebrar a build do Heroku)

# Deploy
git add .
git commit -m "PREP: Pronto para migrar para PostgreSQL"
git push heroku main:master

# Heroku vai detectar DATABASE_URL e usar PostgreSQL
```

---

## PASSO 5: MONITORAR

```bash
# Ver logs
heroku logs -n 100 --tail --app record-pap-app

# Verificar no banco PostgreSQL
```

---

## 🔄 ROLLBACK (Se der problema)

```bash
# Voltar para MySQL
heroku config:unset DATABASE_URL --app record-pap-app

# Ou usar o JAWSDB original
heroku config:set JAWSDB_URL='mysql://...' --app record-pap-app

# Reiniciar
heroku restart --app record-pap-app
```

---

## ⚠️ IMPORTANTE:

1. **LOCAL**: Use PostgreSQL para testar
2. **HEROKU**: Use variável de ambiente DATABASE_URL
3. **ROLLBACK**: JawsDB continua ativo por 7 dias (você paga, mas pode voltar rapidinho)

---

## PRÓXIMOS PASSOS:

1. ✋ Avise quando completar PASSO 1 (editar settings.py)
2. Vou ajudar com PASSO 2 se tiver erros
3. Depois testamos localmente
4. Só depois migra para produção

**Quer começar?**
