# Relatório de Análise de Churn — Rede 1068561

**Período:** Out/2025 a Fev/2026  
**Base:** Planilha 1068561 (002).xlsx — abas BASE_CLICK e CHURN X GROSS

---

## 1. Glossário

| Sigla | Significado |
|-------|-------------|
| **EMP MEI** | Micro Empresário Individual |
| **EMP NMEI** | Empresa Não MEI (maior porte) |
| **Churn** | Rotatividade — clientes que deixaram o serviço |

---

## 2. Resumo executivo — Maiores problemas

Os **três maiores problemas** de churn identificados são:

1. **Segmento EMP MEI (Micro Empresário Individual)** — **maior risco**: taxas de churn muito altas (até **20,83%** em out/25), indicando insatisfação ou vulnerabilidade desse público.
2. **Plano 500MB — maior volume absoluto**: concentra a maior quantidade de cancelamentos (35 em out/25; 25 em nov/25; 21 em dez/25), impactando diretamente a base total.
3. **Plano 1GB**: taxas percentuais elevadas (7,27% e 7,55% em out/25 e nov/25), com base menor mas risco proporcional alto.

A tendência é de **queda forte do churn** de jan/26 em diante (inclusive 0% em fev/26), o que merece validação (dados fechados, efeito de ações de retenção ou mudança de critério).

---

## 3. Análise por segmento

### 3.1 EMP MEI (Micro Empresário Individual) — **prioridade máxima**

| Mês    | Churn (qtd) | Taxa  | Observação        |
|--------|-------------|--------|-------------------|
| Out/25 | 5           | **20,83%** | Pico — maior taxa da base |
| Nov/25 | 3           | **10,34%** | Ainda alta         |
| Dez/25 | 3           | **14,29%** | Alta               |
| Jan/26 | 0           | 0,00%  | Queda total        |
| Fev/26 | 0           | 0,00%  | Mantido            |

**Conclusão:** EMP MEI é o segmento com **maior taxa de churn** no período. Um em cada cinco clientes MEI de out/25 deu churn. Recomenda-se aprofundar motivos (preço, suporte, produto, concorrência) e desenho de ações específicas para MEI.

---

### 3.2 EMP NMEI (Empresa maior porte)

| Mês    | Churn (qtd) | Taxa   | Observação     |
|--------|-------------|--------|----------------|
| Out/25 | 1           | 2,44%  | Baixa          |
| Nov/25 | 2           | **9,52%** | Pico atípico   |
| Dez/25 | 0           | 0,00%  | Normalização   |
| Jan/26 | 0           | 0,00%  | —              |
| Fev/26 | 0           | 0,00%  | —              |

**Conclusão:** Nov/25 chama atenção (9,52%). Vale checar se houve evento pontual (mudança de oferta, fatura, cobrança) que tenha afetado empresas de maior porte naquele mês.

---

### 3.3 Varejo e total

- **Varejo** acompanha o **total**: taxas entre ~4,4% e 5,1% de out a dez/25, caindo para 0,89% em jan/26 e 0% em fev/26.
- O **volume absoluto** de churn vem principalmente do varejo (ex.: 38 de 44 no total em out/25), por ser a maior fatia da base.

---

## 4. Análise por plano (velocidade)

### 4.1 500MB — **maior impacto em volume**

| Mês    | Churn (qtd) | Taxa  |
|--------|-------------|--------|
| Out/25 | **35**      | 5,66% |
| Nov/25 | **25**      | 4,47% |
| Dez/25 | **21**      | 5,30% |
| Jan/26 | 3           | 0,64% |
| Fev/26 | 0           | 0,00% |

Cerca de **80% do churn total** nos primeiros meses está no plano 500MB. Mesmo com taxa percentual moderada, o **volume** é o principal motor da perda de base. Indica foco em retenção e valor percebido desse plano.

### 4.2 1GB — **maior taxa percentual entre planos**

Taxas de **7,27%** (out/25) e **7,55%** (nov/25). Base menor, mas risco relativo alto. Sugere revisão de oferta, preço ou expectativa desse segmento.

### 4.3 700MB

Comportamento intermediário (até 5% em nov/25), sem picos extremos como 1GB ou volume como 500MB.

---

## 5. Tendência temporal

- **Out a Dez/25:** churn relevante em todas as categorias; EMP MEI e 500MB se destacam.
- **Jan/26:** queda forte (total 5 → 0,82%); EMP MEI e vários cortes já em 0%.
- **Fev/26:** **0% de churn em todos os cortes** (quantidade e taxa).

É importante validar se:
- os dados de jan/fev/26 estão fechados e comparáveis;
- houve mudança de critério ou de processo de registro;
- ações de retenção ou mudança comercial explicam a queda.

---

## 6. Cruzamento com motivos (Planilha2)

Na base de retiradas, os **motivos mais citados** (aba Planilha2) são:

- **Problema de venda** (ex.: 50% em dez/25)
- **Problemas técnicos**
- **Mudança de endereço**
- **Contenção de despesas**
- **Problemas com a fatura**

Recomenda-se cruzar esses motivos com **EMP MEI** e **500MB** na BASE_CLICK para priorizar ações (venda, técnico, fatura, preço).

---

## 7. Conclusões e recomendações

| Prioridade | Problema                    | Ação sugerida |
|------------|-----------------------------|----------------|
| **1**      | Alto churn EMP MEI (até 20,83%) | Pesquisa de saída e plano de retenção específico para MEI (oferta, suporte, comunicação). |
| **2**      | Grande volume de churn no 500MB | Campanhas de retenção e revisão de valor (preço x benefício) do plano 500MB. |
| **3**      | Taxas altas no plano 1GB    | Análise de perfil e expectativa; ajuste de oferta ou suporte. |
| **4**      | Pico EMP NMEI em nov/25     | Investigar fatos de nov/25 (cobrança, oferta, mudança de processo). |
| **5**      | Churn zero em fev/26        | Confirmar se dados estão fechados e se a queda é sustentável. |

---

*Relatório gerado com base na planilha 1068561 (002).xlsx — Rede 1068561 (RECORD).*
