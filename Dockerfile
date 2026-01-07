# Dockerfile para Django + Playwright + Railway
FROM python:3.11-buster

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    libnss3 libatk-bridge2.0-0 libgtk-3-0 libxss1 libasound2 libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libpangocairo-1.0-0 libatspi2.0-0 libdrm2 libxext6 libxfixes3 libxi6 libxtst6 libwayland-client0 libwayland-cursor0 libwayland-egl1 libxinerama1 libxkbcommon0 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Cria diretório de trabalho
WORKDIR /app

# Copia arquivos do projeto
COPY . /app/

# Instala dependências Python
RUN pip install --upgrade pip && pip install -r requirements.txt

# Instala Playwright e browsers
RUN pip install playwright && playwright install

# Comando de inicialização
CMD ["gunicorn", "gestao_equipes.wsgi", "--timeout", "120", "--max-requests", "50", "--max-requests-jitter", "10"]
