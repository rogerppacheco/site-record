# Solicitação de aprovação — templates Meta do Funil

WABA / conexão WhatsAtende do Funil: **#247** (não misturar com Qualidade #194).  
Idioma de todos: **pt_BR**.

Colar o corpo exatamente como está abaixo (cada linha vazia = Enter).  
Textos e Word oficiais:

- Funil (UTILITY): `docs/templates_meta_funil_envio.txt` e `docs/WhatsApp_Templates_Funil_Utilitarios.docx`
- Mailing (UTILITY): `docs/templates_meta_mailing.txt` e `docs/WhatsApp_Templates_Mailing_Mercado.docx`

Gerar os Word:

```bash
python docs/gerar_docx_templates_funil_utilitarios.py
python docs/gerar_docx_templates_mailing.py
```

## O que já está aprovado (não reenviar, só conferir)

| Módulo | Nome | Categoria | Ação |
|--------|------|-----------|------|
| Interesse | `nio_consulta_viabilidade_v1` | UTILITY | Conferir se ainda está APPROVED |
| Repescar Churn | `nio_reativacao_contrato_v1` | UTILITY | Conferir se ainda está APPROVED |

## Reenviar / editar

| Módulo | Nome | Categoria | Ação |
|--------|------|-----------|------|
| Repescar Bio | `nio_selfie_pendente_v1` | UTILITY | Editar para 2 variáveis (nome + `Prot. {protocolo}`) e **reaprovar**. Botões: Falar com atendente \| Estou com dúvida |

## Submeter agora (novos)

### Mailings (aba MAILING) — UTILITY

Sem preço, promoção ou pitch. Botões em todos: **Falar conosco** | **Estou com dúvida**.

| Nome | Variáveis | Uso |
|------|-----------|-----|
| `mailing_reparo_v1` | {{1}} nome | OPTIC reparo |
| `mailing_instalacao_v1` | {{1}} nome | OPTIC instalação / Nio CONCLUÍDO |
| `mailing_mudanca_v1` | {{1}} nome | OPTIC mudança |
| `mailing_servico_v1` | {{1}} nome | OPTIC serviço |
| `mailing_cancelamento_v1` | {{1}} nome, {{2}} cidade | Cancelamento Algar / Nio CANCELADO |
| `mailing_fechado_v1` | {{1}} nome, {{2}} cidade | Contrato fechado |
| `mailing_aberto_v1` | {{1}} nome, {{2}} cidade | Aberto / Técnico / Aprovisionamento |
| `mailing_generico_v1` | {{1}} nome | TIM, Vero, Suspensão, fallback |

### Funil — extra (se ainda não existir na WABA #247)

| Módulo | Nome | Categoria | Observação |
|--------|------|-----------|------------|
| Pós-instalação / indicação | `nio_boas_vindas_indicacao_v1` | MARKETING | Está no Word do funil; não é disparo da aba Pré-venda/Venda |

Pré-venda e Venda do funil **não** têm template de disparo em massa neste pacote (o envio automático do funil cobre Interesse, Churn, Bio e Mailing).

## Checklist no WhatsAtende / Meta

1. Abrir a WABA da conexão **#247**
2. Conferir APPROVED: `nio_consulta_viabilidade_v1`, `nio_reativacao_contrato_v1`
3. Editar e reenviar `nio_selfie_pendente_v1`
4. Criar os 8 `mailing_*_v1` como UTILITY / pt_BR com os 2 botões
5. (Opcional) criar `nio_boas_vindas_indicacao_v1`
6. Só depois disparar lote na aba MAILING — template rejeitado cai em fallback de texto e pode quebrar política de lista fria
