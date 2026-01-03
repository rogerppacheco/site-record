# 🤖 Automação de Busca de Faturas - Nio Internet

Sistema de automação para buscar e preencher automaticamente os dados das faturas do Bônus M-10 diretamente do site da Nio Internet.

---

## 📋 **Funcionalidades**

✅ Busca automática de faturas no site da Nio  
✅ Extração de: Valor, Data de Vencimento, Código PIX, Código de Barras  
✅ Download automático do PDF da fatura  
✅ Preenchimento automático dos campos no sistema  
✅ Processamento em lote via comando Django  
✅ Interface com botão "Buscar Automaticamente" no frontend  

---

## 🚀 **Como Usar**

### **1. Via Interface (Botão no Modal)**

1. Acesse a página **Bônus M-10**
2. Clique em **"Editar Faturas"** de um contrato
3. Em qualquer aba de fatura, clique em **"Buscar Automaticamente (Nio)"**
4. O sistema buscará e preencherá os dados automaticamente

**Requisito:** O contrato precisa ter o **CPF do cliente** cadastrado.

---

### **2. Via Comando Django (Processamento em Lote)**

#### **Processar todos os contratos (limite 10):**
```bash
python manage.py buscar_faturas_nio
```

#### **Processar uma safra específica:**
```bash
python manage.py buscar_faturas_nio --safra-id 5
```

#### **Processar um contrato específico:**
```bash
python manage.py buscar_faturas_nio --contrato-id 123
```

#### **Processar 50 contratos:**
```bash
python manage.py buscar_faturas_nio --limite 50
```

---

## 📦 **Requisitos Técnicos**

### **Pacotes Python:**
- `selenium==4.27.1` - Automação web
- `webdriver-manager==4.0.2` - Gerenciamento automático do ChromeDriver

### **Navegador:**
- Google Chrome instalado no sistema
- ChromeDriver (instalado automaticamente pelo webdriver-manager)

### **Instalação:**
```bash
pip install selenium webdriver-manager
```

Ou via requirements.txt:
```bash
pip install -r requirements.txt
```

---

## 🛠️ **Configuração**

### **1. Verificar CPF dos Clientes**

O sistema precisa do CPF cadastrado no contrato. Verifique com:

```python
from crm_app.models import ContratoM10

# Contratos SEM CPF
sem_cpf = ContratoM10.objects.filter(cpf_cliente__isnull=True)
print(f"Contratos sem CPF: {sem_cpf.count()}")

# Adicionar CPF manualmente
contrato = ContratoM10.objects.get(id=1)
contrato.cpf_cliente = "12345678900"
contrato.save()
```

### **2. Modo Headless**

Por padrão, o navegador roda em background (headless=True). Para debug visual:

```python
from crm_app.services_nio import NioFaturaService

# Com interface visual
service = NioFaturaService(headless=False)
dados = service.buscar_fatura("12345678900")
```

---

## 🔍 **Como Funciona**

### **Fluxo de Execução:**

1. **Recebe CPF** do cliente
2. **Abre navegador** (Chrome em background)
3. **Acessa** https://servicos.niointernet.com.br/ajuda/servicos/segunda-via
4. **Preenche formulário** com CPF
5. **Extrai dados** da página (valor, vencimento, PIX, código de barras)
6. **Baixa PDF** se disponível
7. **Salva no banco** de dados
8. **Fecha navegador**

### **Seletores CSS/XPath:**

Os seletores estão configurados para capturar elementos genéricos. Se o site mudar, ajuste em:

```python
# crm_app/services_nio.py
def _extrair_dados_pagina(self):
    # Ajuste os seletores aqui
    valor_element = self.driver.find_element(...)
```

---

## ⚠️ **Considerações Importantes**

### **1. Taxa Limite (Rate Limiting)**
- O script adiciona delays entre requisições
- Evite processar muitos contratos simultaneamente
- Recomendado: Máximo 50 contratos por execução

### **2. Captcha**
- Se o site implementar CAPTCHA, será necessário resolver manualmente
- Considere usar serviços de resolução de CAPTCHA (2Captcha, Anti-Captcha)

### **3. Mudanças no Site**
- Se a Nio alterar a estrutura do site, os seletores precisarão ser atualizados
- Monitore logs de erro para identificar falhas

### **4. Termos de Uso**
- Verifique os termos de uso do site da Nio
- Use com responsabilidade e moderação
- Não abuse da automação

### **5. Produção (Heroku)**
- No Heroku, precisa configurar buildpack do Chrome:
  ```bash
  heroku buildpacks:add heroku/google-chrome
  heroku buildpacks:add heroku/chromedriver
  ```

---

## 🐛 **Troubleshooting**

### **Erro: ChromeDriver not found**
```bash
pip install webdriver-manager
```

### **Erro: Elemento não encontrado**
- O site pode ter mudado a estrutura
- Verifique os seletores CSS/XPath em `services_nio.py`
- Execute com `headless=False` para debug visual

### **Erro: Timeout**
- Aumente o timeout em `buscar_fatura(cpf, timeout=60)`
- Verifique conexão com internet
- Site da Nio pode estar fora do ar

### **Erro: CPF não encontrado**
- Verifique se o CPF está correto no cadastro
- Confirme se existe fatura disponível no site da Nio
- Teste manualmente no site

---

## 📊 **Monitoramento**

### **Logs do Sistema:**

```python
# Ver contratos processados
from crm_app.models import FaturaM10

# Faturas com PIX preenchido
com_pix = FaturaM10.objects.exclude(codigo_pix__isnull=True).exclude(codigo_pix='')
print(f"Faturas com PIX: {com_pix.count()}")

# Faturas com PDF
com_pdf = FaturaM10.objects.exclude(arquivo_pdf='')
print(f"Faturas com PDF: {com_pdf.count()}")
```

---

## 🔐 **Segurança**

- ✅ Requer autenticação JWT
- ✅ Apenas usuários autorizados (Diretoria, BackOffice, Admin)
- ✅ Não expõe CPFs nos logs
- ✅ Dados criptografados em trânsito (HTTPS)

---

## 📞 **Suporte**

Em caso de problemas:
1. Verifique os logs do servidor
2. Execute comando com `--limite 1` para testar
3. Teste com `headless=False` para debug visual
4. Verifique se o Chrome está instalado

---

## 🎯 **Roadmap**

- [ ] Suporte para mais operadoras
- [ ] Resolução automática de CAPTCHA
- [ ] Agendamento automático (Celery)
- [ ] Dashboard de monitoramento
- [ ] Retry automático em caso de falha
- [ ] Notificações por email/WhatsApp

---

## ✅ **Exemplo de Uso Completo**

```python
# 1. Buscar fatura manualmente
from crm_app.services_nio import buscar_fatura_nio_por_cpf

dados = buscar_fatura_nio_por_cpf("12345678900")
print(dados)

# 2. Processar em lote via comando
python manage.py buscar_faturas_nio --safra-id 5 --limite 20

# 3. Via API (POST)
curl -X POST http://localhost:8000/api/bonus-m10/buscar-fatura-nio/ \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "cpf": "12345678900",
    "contrato_id": 123,
    "numero_fatura": 1,
    "salvar": true
  }'
```

---

**Desenvolvido para otimizar o processo de preenchimento de faturas no módulo Bônus M-10.**
