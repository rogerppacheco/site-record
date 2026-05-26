REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
from pathlib import Path
import os
from decouple import config
import dj_database_url
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    'testserver',
    'record-pap-app-80fd14bb6cb5.herokuapp.com',
    'www.recordpap.com.br',
    'recordpap.com.br',
    '.herokuapp.com',
    'site-record-production.up.railway.app',
    'site-record.up.railway.app',
    'pleasing-recreation.up.railway.app',
    # Permite qualquer subdomínio do Railway ou Heroku
    '.up.railway.app',
    '.herokuapp.com',
    # Teste local: ngrok (ex.: d021-177-137-82-21.ngrok-free.app)
    '.ngrok-free.app',
    '.ngrok.io',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'usuarios',
    'core',
    'presenca',
    'relatorios',
    'osab',
    'crm_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'gestao_equipes.middleware.DisableCsrfForJWT',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gestao_equipes.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            # Pasta frontend raiz
            os.path.join(BASE_DIR, 'frontend'),
            
            # ADICIONE ESTA LINHA ABAIXO:
            os.path.join(BASE_DIR, 'frontend', 'public'),
            
            os.path.join(BASE_DIR, 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'gestao_equipes.wsgi.application'

# ==============================================================================
# CONFIGURAÇÃO DE BANCO DE DADOS (JawsDB MySQL vs SQLite)
# ==============================================================================

# 1. Padrão: SQLite (Para uso local no seu computador)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 2. Produção: PostgreSQL (Railway) ou MySQL (JawsDB - Heroku)
# Suporta DATABASE_URL (PostgreSQL no Railway) ou JAWSDB_URL (MySQL no Heroku)
database_url = config('DATABASE_URL', default=None)  # Railway PostgreSQL
jawsdb_url = config('JAWSDB_URL', default=None)      # Heroku MySQL

if database_url:
    # Usar PostgreSQL (Railway)
    DATABASES['default'] = dj_database_url.parse(
        database_url,
        conn_max_age=600,
        ssl_require=False
    )
    # PostgreSQL settings
    DATABASES['default']['ENGINE'] = 'django.db.backends.postgresql'
    DATABASES['default']['OPTIONS'] = {
        'connect_timeout': 10,
    }
    _h = DATABASES['default'].get('HOST') or 'localhost'
    _n = DATABASES['default'].get('NAME')
    print(f"OK - PostgreSQL: host={_h!r} db={_n!r}")

elif jawsdb_url:
    # Usar MySQL (JawsDB - Heroku)
    DATABASES['default'] = dj_database_url.parse(
        jawsdb_url,
        conn_max_age=600,
        ssl_require=False
    )
    # MySQL settings
    DATABASES['default']['ENGINE'] = 'django.db.backends.mysql'
    DATABASES['default']['OPTIONS'] = {
        'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        'charset': 'utf8mb4',
    }
    print("[OK] Usando MySQL (JawsDB)")
else:
    print("[WARNING] Nenhuma variável de ambiente de banco encontrada. Usando SQLite.")

# ==============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
    os.path.join(BASE_DIR, 'frontend', 'public'),
]
# Garante que o Whitenoise sirva arquivos estáticos corretamente em produção

# Serve arquivos estáticos corretamente em todos ambientes
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
else:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# Instrução: Após cada deploy, execute no Railway:
# python manage.py collectstatic --noinput

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',
    ),
    # ✅ PAGINAÇÃO PARA PERFORMANCE
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,  # 20 registros por página
    'MAX_PAGE_SIZE': 1000,  # Permite até 1000 registros por página na API
    # ✅ FILTRAGEM
    'DEFAULT_FILTER_BACKENDS': [
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

AUTH_USER_MODEL = 'usuarios.Usuario'
LOGIN_URL = '/'

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://record-pap-app-80fd14bb6cb5.herokuapp.com',
    'https://www.recordpap.com.br',
    'https://recordpap.com.br',
]

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://record-pap-app-80fd14bb6cb5.herokuapp.com',
    'https://www.recordpap.com.br',
    'https://recordpap.com.br',
]

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'SAMEORIGIN'

# --- CONFIGURAÇÕES DE E-MAIL ---
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

# --- CONFIGURAÇÕES MICROSOFT GRAPH (ONEDRIVE) ---
MS_CLIENT_ID = config('MS_CLIENT_ID')
MS_CLIENT_SECRET = config('MS_CLIENT_SECRET')
MS_REFRESH_TOKEN = config('MS_REFRESH_TOKEN')
MS_DRIVE_FOLDER_ROOT = "CDOI_Record_Vertical"

# --- CONFIGURAÇÕES Z-API ---
ZAPI_INSTANCE_ID = config('ZAPI_INSTANCE_ID', default='')
ZAPI_TOKEN = config('ZAPI_TOKEN', default='')
ZAPI_CLIENT_TOKEN = config('ZAPI_CLIENT_TOKEN', default='')
# Descarta webhooks Z-API irrelevantes (grupo, fromMe, etc.) antes do handler pesado
WHATSAPP_WEBHOOK_FASTPATH = config('WHATSAPP_WEBHOOK_FASTPATH', default=True, cast=bool)
# --- CONFIGURAÇÕES ZENVIA VOICE (AUDITORIA DE LIGAÇÕES) ---
ZENVIA_VOICE_API_URL = config('ZENVIA_VOICE_API_URL', default='https://voice-api.zenvia.com')
ZENVIA_VOICE_ACCESS_TOKEN = config('ZENVIA_VOICE_ACCESS_TOKEN', default='')
ZENVIA_VOICE_CALLS_ENDPOINT = config('ZENVIA_VOICE_CALLS_ENDPOINT', default='/chamada')
ZENVIA_VOICE_RECORDING_ENDPOINT_TEMPLATE = config(
    'ZENVIA_VOICE_RECORDING_ENDPOINT_TEMPLATE',
    default='/chamada/{call_id}/gravacao'
)
ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER = config('ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER', default='')
ZENVIA_VOICE_TIMEOUT_SECONDS = config('ZENVIA_VOICE_TIMEOUT_SECONDS', default=20, cast=int)
ZENVIA_VOICE_WEBHOOK_SECRET = config('ZENVIA_VOICE_WEBHOOK_SECRET', default='')
AUDITORIA_ONEDRIVE_FOLDER = config('AUDITORIA_ONEDRIVE_FOLDER', default='Auditoria_Ligacoes')

# --- Sonax (auditoria: click2call + gravação pega_gravacao / webhook) ---
# Provedor SIP da auditoria. Padrão: sonax. Use AUDITORIA_VOICE_PROVIDER=zenvia só se for fallback explícito.
AUDITORIA_VOICE_PROVIDER = config('AUDITORIA_VOICE_PROVIDER', default='sonax').strip().lower()
SONAX_CLICK2CALL_URL = config(
    'SONAX_CLICK2CALL_URL',
    default='https://click2call.sonax.net.br/sonax-click2call.php',
)
SONAX_CLICK2CALL_TOKEN = config('SONAX_CLICK2CALL_TOKEN', default='')
SONAX_ID_CLIENTE = config('SONAX_ID_CLIENTE', default='')
# Token usado em dbdial_webapi.php (pega_gravacao, etc.); se vazio, usa SONAX_CLICK2CALL_TOKEN.
SONAX_INTEGRATION_TOKEN = config('SONAX_INTEGRATION_TOKEN', default='')
SONAX_DBDIAL_BASE_URL = config(
    'SONAX_DBDIAL_BASE_URL',
    default='https://api.sonax.net.br/a2billing_v2/admin/Public/dbdial_webapi.php',
)
SONAX_RAMAIS = config('SONAX_RAMAIS', default='101,102,103')
SONAX_TIMEOUT_SECONDS = config('SONAX_TIMEOUT_SECONDS', default=30, cast=int)
SONAX_WEBHOOK_SECRET = config('SONAX_WEBHOOK_SECRET', default='')

# --- Fallback Sonax (quando webhook de desligamento não chegar) ---
# Intervalo (minutos) para varrer chamadas pendentes e consultar status/baixar gravação.
SONAX_AUDITORIA_FALLBACK_INTERVAL_MINUTES = config('SONAX_AUDITORIA_FALLBACK_INTERVAL_MINUTES', default=2, cast=int)
# Quantidade máxima de ligações por execução (ordem antiga → nova).
SONAX_AUDITORIA_FALLBACK_LIMIT = config('SONAX_AUDITORIA_FALLBACK_LIMIT', default=15, cast=int)
# "Janela de graça" após iniciar a chamada antes de começar o polling (segundos).
SONAX_AUDITORIA_FALLBACK_GRACE_SECONDS = config('SONAX_AUDITORIA_FALLBACK_GRACE_SECONDS', default=90, cast=int)

# --- CONFIGURAÇÕES DE CAPTCHA (reCAPTCHA SOLVER) ---
# Use CapSolver, 2Captcha ou API customizada para resolver reCAPTCHA v2 na página Nio (PDF fatura)
CAPTCHA_API_KEY = config('CAPTCHA_API_KEY', default='CAP-4A266E1BA9DC47B87D28FBDE12A129014DB5B7EABC69D961115B3E184D497F85')
CAPTCHA_PROVIDER = config('CAPTCHA_PROVIDER', default='capsolver')  # Opções: 'capsolver', '2captcha' ou 'custom'
# Para provedor 'custom': URL da sua API que recebe POST JSON { siteKey, pageUrl } e retorna { token } ou { gRecaptchaResponse }
RECAPTCHA_SOLVER_API_URL = config('RECAPTCHA_SOLVER_API_URL', default='')

# Caminho para armazenar/reusar cookies da Nio (storage state do Playwright)
NIO_STORAGE_STATE = os.path.join(BASE_DIR, '.playwright_state.json')

# --- CONFIGURAÇÕES DE ARQUIVOS ESTÁTICOS E MÍDIA ---
# Para upload de PDFs das faturas M-10
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# --- LIMITES DE UPLOAD ---
# Ajuste para permitir arquivos grandes (ex: 200MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024  # 200MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024  # 200MB

# --- LOGGING PARA DEBUG NO HEROKU ---
# ==============================================================================
# AUTOMAÇÃO PAP (VENDER NO WHATSAPP)
# ==============================================================================
# PAP_HEADLESS: Se True (padrão), o navegador roda em segundo plano (produção).
# Se False, o navegador abre na tela para você ver cada etapa (só use em teste local).
# Variável de ambiente: PAP_HEADLESS=false para ver o navegador.
PAP_HEADLESS = config('PAP_HEADLESS', default=True, cast=lambda v: str(v).lower() not in ('false', '0', 'no'))

# FORCE_FATURA_PDF_PLAYWRIGHT: Se True, o PDF da fatura é SEMPRE buscado abrindo o navegador (Playwright),
# em vez de tentar primeiro a API. Use só para debug: ver os cliques (Consultar → Pagar conta → Gerar boleto → Baixar PDF).
# Variável de ambiente: FORCE_FATURA_PDF_PLAYWRIGHT=true
FORCE_FATURA_PDF_PLAYWRIGHT = config('FORCE_FATURA_PDF_PLAYWRIGHT', default=False, cast=lambda v: str(v).lower() in ('true', '1', 'yes'))

# PAP_CAPTURE_SCREENSHOTS: Se True, salva screenshot em cada etapa da venda PAP (em produção).
# Os arquivos ficam em downloads/pap_venda_*.png e podem ser vistos em /api/crm/debug/screenshots/
# Variável de ambiente: PAP_CAPTURE_SCREENSHOTS=true
PAP_CAPTURE_SCREENSHOTS = config('PAP_CAPTURE_SCREENSHOTS', default=False, cast=lambda v: str(v).lower() in ('true', '1', 'yes'))

# PAP_SCREENSHOTS_ONEDRIVE: Se True, além de salvar em downloads/, envia cada screenshot para o OneDrive
# (mesma conta configurada em MS_CLIENT_ID / MS_REFRESH_TOKEN, pasta em MS_DRIVE_FOLDER_ROOT).
# Também habilita captura em FALHAS da Etapa 1 (novo pedido / vendedor) mesmo com PAP_CAPTURE_SCREENSHOTS=false,
# para ver no OneDrive a tela no momento do erro (prefixo pap_venda_*_01_err_* / 01_excecao_*).
# Variável de ambiente: PAP_SCREENSHOTS_ONEDRIVE=true
PAP_SCREENSHOTS_ONEDRIVE = config('PAP_SCREENSHOTS_ONEDRIVE', default=False, cast=lambda v: str(v).lower() in ('true', '1', 'yes'))
# Pasta no OneDrive (dentro de MS_DRIVE_FOLDER_ROOT). Ex: PAP_Screenshots → CDOI_Record_Vertical/PAP_Screenshots/
PAP_ONEDRIVE_FOLDER = config('PAP_ONEDRIVE_FOLDER', default='PAP_Screenshots')

# Homologação: vendedor pode digitar FORCAR_SIM na etapa de aguardar SIM do cliente (sem resposta real do cliente).
# Variável: PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE=true (não use em produção com clientes reais).
PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE = config(
    'PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)

# Desenvolvimento local: com DEBUG=True, após enviar o resumo ao cliente marca o SIM automaticamente
# (não precisa do webhook nem de FORCAR_SIM). Nunca use em produção (DEBUG=False ignora mesmo com true).
PAP_WHATSAPP_AUTO_SIM_CLIENTE_LOCAL = config(
    'PAP_WHATSAPP_AUTO_SIM_CLIENTE_LOCAL',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)

# Após "Abrir OS", tempo máximo (ms) aguardando a UI de agendamento (portal pode demorar nas validações).
PAP_ETAPA7_AGENDAMENTO_TIMEOUT_MS = config('PAP_ETAPA7_AGENDAMENTO_TIMEOUT_MS', default=120000, cast=int)

# Pasta no OneDrive para selfies de confirmação de presença (por data: Presenca_Selfies/YYYY-MM-DD/)
PRESENCA_ONEDRIVE_FOLDER = config('PRESENCA_ONEDRIVE_FOLDER', default='Presenca_Selfies')
# Pasta no OneDrive para solicitações de inclusão/viabilidade (subpasta por solicitação)
INCLUSAO_ONEDRIVE_FOLDER = config('INCLUSAO_ONEDRIVE_FOLDER', default='Inclusao_Viabilidade')

# --- Análise de crédito via WhatsApp: e-mails para o PAP/Nio ---
# O Nio valida o e-mail (envia teste). Use um dos dois:
# CREDITO_EMAILS: lista de e-mails reais separados por vírgula; o sistema escolhe um aleatório a cada análise.
#   Ex: comunicacao@recordpap.com.br,suporte@recordpap.com.br,vendas@recordpap.com.br
# CREDITO_EMAIL_MAILINATOR: se true, gera endereços @mailinator.com (aceitam envio; Nio pode bloquear o domínio).
CREDITO_EMAILS = config('CREDITO_EMAILS', default='')
CREDITO_EMAIL_MAILINATOR = config('CREDITO_EMAIL_MAILINATOR', default=True, cast=lambda v: str(v).lower() in ('true', '1', 'yes'))

# Google Street View Static API - foto automática na automação Inclusão/Viabilidade
GOOGLE_STREETVIEW_API_KEY = config('GOOGLE_STREETVIEW_API_KEY', default='')

# Funil de vendas (WhatsApp VENDER): grava tentativas e eventos no banco. Produção: FUNIL_VENDAS_REGISTRAR=true
FUNIL_VENDAS_REGISTRAR = config(
    'FUNIL_VENDAS_REGISTRAR',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
