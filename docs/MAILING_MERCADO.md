# Mailings de mercado

Importa listas compradas (XLS), dispara templates Meta (tom informativo, **sem oferta**) e coloca as respostas na aba **MAILING** do Funil de Tratamento.

## Layouts aceitos

| Layout | Colunas mínimas | Situações |
|--------|-----------------|-----------|
| **OPTIC** | NOME, CPF, TELEFONE_COMPLETO, Macro Atividade | REP→reparo, INST→instalação, MUD→mudança, SRV/RET→serviço |
| **ATV ALG** | Cliente, Documento, Telefone, Status | CANCEL*→cancelamento, FECHADO, ABERTO/TECNICO |

## Fluxo

1. Funil → aba **MAILING** → **Importar XLS**
2. Revisar contagens por situação no alerta do lote
3. **Disparar lote** (primeiro ciclo imediato; scheduler continua a cada 2 min)
4. Respostas (texto ou botão *Falar conosco*) → status `RESPONDEU` na mesma aba
5. *Agora não* → opt-out (`IGNORADO`)

## Templates Meta (MARKETING / pt_BR)

Arquivo para colar no gerenciador: `docs/WhatsApp_Templates_Mailing_Mercado.docx`  
Gerar: `python docs/gerar_docx_templates_mailing.py`

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

Botões: **Falar conosco** | **Agora não**

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
