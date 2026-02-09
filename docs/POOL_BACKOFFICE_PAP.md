# Pool de Logins BackOffice para Automação PAP

## Contexto

Vendedores (perfil Vendedor) não conseguem realizar vendas pelo site [pap.niointernet.com.br](https://pap.niointernet.com.br/) diretamente. Usuários com **"Autorizar venda sem auditoria"** passam a usar credenciais de perfil **BackOffice** via pool, com seleção randômica e controle de uso.

## Fluxo

1. **Vendedor** digita VENDER no WhatsApp
2. Sistema verifica: `autorizar_venda_sem_auditoria` + `matricula_pap` (vendedor só precisa da matrícula)
3. Ao confirmar (SIM), o sistema obtém um login BackOffice disponível do pool
4. Login no PAP é feito com **credenciais do BO** (matrícula + senha)
5. No formulário de novo pedido, o **vendedor** é selecionado pela **matrícula do vendedor** (para atribuição da venda)
6. Ao finalizar (sucesso, erro ou cancelamento), o BO é liberado para o pool

## Segurança e Distribuição

- **Seleção randômica:** entre os BOs disponíveis
- **Exclusão de conflitos:** um BO em uso não é oferecido a outro vendedor
- **Timeout:** locks com mais de 30 minutos são liberados automaticamente (sessões travadas)
- **Mensagem quando todos ocupados:** "TODOS OS ACESSOS BACKOFFICE ESTÃO EM USO - Aguarde alguns minutos"

## Requisitos

### Vendedor (com autorizar_venda_sem_auditoria)
- `matricula_pap` preenchida (para ser selecionado como vendedor no pedido)
- `tel_whatsapp` para identificação

### BackOffice (para o pool)
- Perfil com `cod_perfil = 'backoffice'`
- `matricula_pap` e `senha_pap` preenchidos
- `is_active = True`

## Modelo e Serviço

- **Modelo:** `PapBoEmUso` – controla qual BO está em uso por qual vendedor
- **Serviço:** `crm_app.pool_bo_pap`
  - `obter_login_bo(telefone, sessao_id)` – obtém BO livre, retorna `(Usuario, None)` ou `(None, mensagem_erro)`
  - `liberar_bo(bo_usuario_id, telefone)` – libera o BO ao finalizar

## Migração

```bash
python manage.py migrate crm_app
```
