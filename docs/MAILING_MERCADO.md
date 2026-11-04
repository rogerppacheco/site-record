# Mailings de mercado

Importa listas compradas (XLS), dispara templates Meta (tom informativo, **sem oferta**) e coloca as respostas na aba **MAILING** do Funil de Tratamento.

## Layouts aceitos

| Layout | Colunas mínimas | Situações |
|--------|-----------------|-----------|
| **OPTIC** | NOME, CPF, TELEFONE_COMPLETO, Macro Atividade | REP→reparo, INST→instalação, MUD→mudança, SRV/RET→serviço |
| **ATV ALG / mercado** | Nome (ou Cliente) + Telefone | Status opcional. Também aceita CPF/CNPJ, DOCUMENTO, CONTRATO_STATUS, Telefone1/Telefne2, Cidade, UF, Endereço, Plano |

### Situações (coluna Status / CONTRATO_STATUS / nome do arquivo)

| Origem | Situação no funil | Template |
|--------|-------------------|----------|
| Aberto, Técnico, EM APROVISIONAMENTO, PENDÊNCIA* | ABERTO | `mailing_aberto_v1` |
| Cancelamento, CANCELADO, DESISTÊNCIA* | CANCELAMENTO | `mailing_cancelamento_v1` |
| CONCLUÍDO | INSTALACAO | `mailing_instalacao_v1` |
| FECHADO | FECHADO | `mailing_fechado_v1` |
| Suspensão (ou arquivo SUSPENSÃO*) | GENERICO | `mailing_generico_v1` |
| Sem status (ex.: MASTER TIM) | GENERICO | `mailing_generico_v1` |

Planilhas de 03/11/2026 em `docs/mailings/` (Algar, TIM, Nio, Vero) sobem pela aba **MAILING** após este mapeamento. CPF `Null` é ignorado; o telefone é obrigatório.

## Fluxo

1. Funil → aba **MAILING** → **Importar XLS**
2. Revisar contagens por situação no alerta do lote
3. **Disparar lote** (primeiro ciclo imediato; scheduler continua a cada 2 min)
4. Respostas (texto ou botão *Falar conosco*) → status `RESPONDEU` na mesma aba
5. *Falar conosco* ou *Estou com dúvida* → resposta no Funil (`RESPONDEU`)

## Templates Meta (MARKETING / pt_BR)

Arquivo para colar no gerenciador: `docs/WhatsApp_Templates_Mailing_Mercado.docx`  
Gerar: `python docs/gerar_docx_templates_mailing.py`  
Pedido de aprovação (funil + mailing): `docs/SOLICITACAO_APROVACAO_TEMPLATES_FUNIL.md`

| Nome | Uso |
|------|-----|
| `mailing_reparo_v1` | OPTIC reparo |
| `mailing_instalacao_v1` | OPTIC instalação |
| `mailing_mudanca_v1` | OPTIC mudança |
| `mailing_servico_v1` | OPTIC serviço |
| `mailing_cancelamento_v1` | ATV cancelamento |
| `mailing_fechado_v1` | ATV fechado |
| `mailing_aberto_v1` | ATV aberto/técnico |
| `mailing_generico_v1` | fallback |

Botões: **Falar conosco** | **Estou com dúvida**

## API

- `GET/POST /api/crm/mailings/` — lista / upload
- `POST /api/crm/mailings/<id>/disparo/` — inicia disparo
- `DELETE /api/crm/mailings/<id>/disparo/` — pausa
- `GET /api/crm/mailings/funil/` — lista para o Funil
- `POST /api/crm/mailings/contatos/<id>/tratar/`

## Comando

```bash
python manage.py disparar_mailing --lote 1 --tudo
python manage.py disparar_mailing --ciclos
```

## Migração

```bash
python manage.py migrate crm_app 0221
```
