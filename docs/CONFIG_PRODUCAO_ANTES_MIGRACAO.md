# CONFIGURAÇÕES DE PRODUÇÃO - ANTES DA MIGRAÇÃO
# Data: 02/01/2026
# Backup para rollback rápido se necessário

## DATABASE (JawsDB MySQL)
JAWSDB_URL=mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45

## CUSTOS MENSAIS
- Web Dyno (Basic): $7.00/mês
- JawsDB (Blacktip Shared): $24.00/mês
- **TOTAL: $31.00/mês**

## ESTATÍSTICAS DO BANCO
- Total de registros: 28.752
- Tamanho dos dados: ~30 MB
- Tabelas: 33
- Banco: MySQL 5.7

## BACKUP COMPLETO
- Arquivo: backup_mysql_producao_20260102_221849.json
- Tamanho: 30.18 MB
- Local: C:\site-record\
- Data: 02/01/2026 22:18:49

## VERSÕES
- Python: 3.13
- Django: 5.2.1
- MySQL Client: mysqlclient 2.2.7

## INSTRUÇÕES DE ROLLBACK DE EMERGÊNCIA

Se algo der errado após a migração:

1. Voltar DATABASE_URL no Heroku:
   ```
   heroku config:set JAWSDB_URL=mysql://uioi72s40x893ncn:a1y7asmfuv5k7fd4@ryvdxs57afyjk41z.cbetxkdyhwsb.us-east-1.rds.amazonaws.com:3306/pbxh93dye9h7ua45 --app record-pap-app
   ```

2. Reiniciar dynos:
   ```
   heroku restart --app record-pap-app
   ```

3. Verificar logs:
   ```
   heroku logs --tail --app record-pap-app
   ```

Site volta ao normal em < 30 segundos!
