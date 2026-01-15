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
    print("OK - Usando PostgreSQL (Railway)")

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

# --- CONFIGURAÇÕES DE CAPTCHA (reCAPTCHA SOLVER) ---
# Use CapSolver ou 2Captcha para resolver automaticamente reCAPTCHA v2
CAPTCHA_API_KEY = config('CAPTCHA_API_KEY', default='CAP-4A266E1BA9DC47B87D28FBDE12A129014DB5B7EABC69D961115B3E184D497F85')
CAPTCHA_PROVIDER = config('CAPTCHA_PROVIDER', default='capsolver')  # Opções: 'capsolver' ou '2captcha'

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
