"""
Utilitários para o fluxo de análise de crédito via WhatsApp.
Geração de celulares e emails aleatórios para preencher campos no PAP.
"""
import random
import string

# DDD fixo 31 (região de BH/Contagem)
DDD_CREDITO = "31"

# Domínios de email conhecidos para gerar endereços válidos
DOMINIOS_EMAIL = [
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com.br",
    "icloud.com",
]


def gerar_celular_random() -> str:
    """
    Gera um número de celular aleatório com DDD 31.
    Formato: 31 + 9 + 8 dígitos = 11 dígitos (ex: 31912345678)
    """
    # Celular brasileiro: 9XXXXXXXX (9 dígitos após DDD)
    sufixo = "".join(random.choices(string.digits, k=8))
    return f"{DDD_CREDITO}9{sufixo}"


def gerar_email_random() -> str:
    """
    Gera um email aleatório com domínio conhecido (gmail, hotmail, etc.).
    Formato: prefixo_único@dominio.com
    Evita colisões usando timestamp + random para o prefixo.
    """
    import time
    prefixo = f"credito{int(time.time() * 1000)}{random.randint(100, 999)}"
    dominio = random.choice(DOMINIOS_EMAIL)
    return f"{prefixo}@{dominio}"
