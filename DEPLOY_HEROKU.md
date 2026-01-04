# 🚀 Deploy de Otimizações no Heroku

## 📋 Comandos para Deploy em Produção (Heroku)

### Passo 1: Verificar Status do Git
```powershell
# Ver mudanças
git status

# Ver diferenças
git diff
```

### Passo 2: Adicionar e Commitar
```powershell
# Adicionar todos os arquivos modificados
git add crm_app/models.py
git add crm_app/views.py
git add crm_app/migrations/
git add docs/
git add scripts/
git add *.md

# OU adicionar tudo de uma vez
git add .

# Commit com mensagem descritiva
git commit -m "feat: Otimizações de performance PostgreSQL

- Adicionar índices db_index no modelo Venda
- Implementar bulk operations em ImportacaoChurn e CicloPagamento
- Criar índices compostos e parciais para PostgreSQL
- Otimizar queries com .defer()
- Adicionar documentação completa

Ganhos esperados:
- Queries de esteira/auditoria: 10-50x mais rápidas
- Importações: 50-100x mais rápidas"
```

### Passo 3: Push para GitHub/GitLab
```powershell
# Push para seu repositório
git push origin main
```

### Passo 4: Deploy no Heroku
```powershell
# Verificar apps Heroku disponíveis
heroku apps

# Deploy para produção (main)
git push heroku main

# OU se o remote for diferente
git push heroku-prod main
```

### Passo 5: Executar Migrations no Heroku
```powershell
# Aplicar migrations (ISSO VAI CRIAR OS ÍNDICES)
heroku run python manage.py migrate crm_app --app seu-app-name

# Aguardar 5-15 minutos para criação dos índices
# Você verá: "✓ Índices de performance PostgreSQL criados com sucesso!"
```

### Passo 6: Restart da Aplicação
```powershell
# Restart para garantir que mudanças foram aplicadas
heroku restart --app seu-app-name
```

### Passo 7: Validar Deploy
```powershell
# Ver logs em tempo real
heroku logs --tail --app seu-app-name

# Abrir aplicação no browser
heroku open --app seu-app-name
```

---

## 🔍 Comandos de Verificação

### Verificar se Índices foram Criados
```powershell
# Conectar ao PostgreSQL do Heroku
heroku pg:psql --app seu-app-name

# Dentro do psql, executar:
SELECT indexname FROM pg_indexes WHERE tablename = 'crm_venda' ORDER BY indexname;

# Ver tamanho dos índices
SELECT 
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as size
FROM pg_stat_user_indexes
WHERE tablename = 'crm_venda'
ORDER BY pg_relation_size(indexrelid) DESC;

# Sair
\q
```

### Verificar Migrations Aplicadas
```powershell
heroku run python manage.py showmigrations crm_app --app seu-app-name
```

### Executar Script de Validação
```powershell
heroku run python scripts/validar_performance.py --app seu-app-name
```

---

## ⚡ COMANDOS COMPLETOS EM SEQUÊNCIA

```powershell
# 1. Commitar mudanças
git add .
git commit -m "feat: Otimizações de performance PostgreSQL"

# 2. Push para repositório
git push origin main

# 3. Deploy no Heroku
git push heroku main

# 4. Aplicar migrations (criar índices)
heroku run python manage.py migrate crm_app --app seu-app-name

# 5. Restart
heroku restart --app seu-app-name

# 6. Monitorar logs
heroku logs --tail --app seu-app-name
```

---

## 📊 Testar Performance Pós-Deploy

### Teste 1: Acessar Esteira
1. Abrir: `https://seu-app.herokuapp.com/esteira`
2. Verificar tempo de carregamento (esperado: < 500ms)

### Teste 2: Acessar Auditoria
1. Abrir: `https://seu-app.herokuapp.com/auditoria`
2. Verificar tempo de carregamento (esperado: < 500ms)

### Teste 3: Importação
1. Fazer importação OSAB ou Churn pequena
2. Verificar tempo de processamento (deve ser muito mais rápido)

---

## 🆘 Troubleshooting

### Erro ao fazer git push heroku
```powershell
# Se o remote 'heroku' não existir
heroku git:remote -a seu-app-name

# Tentar novamente
git push heroku main
```

### Erro "No module named..."
```powershell
# Atualizar dependências
heroku run pip install -r requirements.txt --app seu-app-name
```

### Ver erros detalhados
```powershell
# Logs das últimas 200 linhas
heroku logs -n 200 --app seu-app-name

# Logs de erro apenas
heroku logs --tail --app seu-app-name | grep ERROR
```

### Migration travou
```powershell
# Cancelar e tentar novamente
heroku ps:restart --app seu-app-name
heroku run python manage.py migrate crm_app --app seu-app-name
```

---

## 🔄 Rollback (se necessário)

### Opção 1: Reverter no Git
```powershell
# Reverter commit
git revert HEAD

# Push
git push origin main
git push heroku main

# Restart
heroku restart --app seu-app-name
```

### Opção 2: Rollback do Heroku
```powershell
# Ver releases
heroku releases --app seu-app-name

# Rollback para release anterior
heroku rollback v123 --app seu-app-name
```

### Opção 3: Reverter Migration
```powershell
# Reverter para migration anterior aos índices
heroku run python manage.py migrate crm_app 0064 --app seu-app-name
```

---

## 📈 Monitoramento Pós-Deploy

### Métricas do Heroku
```powershell
# Ver uso de recursos
heroku ps --app seu-app-name

# Ver status do banco
heroku pg:info --app seu-app-name

# Ver conexões ativas
heroku pg:ps --app seu-app-name
```

### Logs de Performance
```powershell
# Filtrar por tempo de resposta
heroku logs --tail --app seu-app-name | grep "GET /api/vendas"
```

---

## ✅ Checklist de Deploy Heroku

- [ ] Código commitado localmente
- [ ] Push para repositório remoto (GitHub/GitLab)
- [ ] Deploy no Heroku (`git push heroku main`)
- [ ] Migrations aplicadas (`heroku run python manage.py migrate`)
- [ ] Aplicação reiniciada (`heroku restart`)
- [ ] Logs verificados (sem erros críticos)
- [ ] Testes de fumaça realizados (esteira, auditoria)
- [ ] Performance validada (< 500ms)
- [ ] Equipe avisada sobre deploy

---

## 🎯 Comando Único (Copiar e Colar)

```powershell
# Deploy completo em produção
git add . && git commit -m "feat: Otimizações de performance PostgreSQL" && git push origin main && git push heroku main && heroku run python manage.py migrate crm_app && heroku restart && heroku logs --tail
```

**Nota**: Substitua `seu-app-name` pelo nome real do seu app no Heroku onde necessário.

---

## 📞 Suporte Heroku

Em caso de problemas:
```powershell
# Abrir ticket de suporte
heroku help

# Documentação
heroku addons:docs heroku-postgresql
```

---

**Data**: 03/01/2026  
**Status**: ✅ PRONTO PARA DEPLOY NO HEROKU
