# gestao_equipes/settings.py
from pathlib import Path
import os
from dotenv import load_dotenv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key-for-development')

# --- CORREÇÃO 1: DEBUG E ALLOWED_HOSTS PARA PRODUÇÃO ---
DEBUG = os.getenv('DEBUG', '0') == '1'

ALLOWED_HOSTS = [
    'controle-presenca-448646307036.herokuapp.com', # Nome completo do app Heroku
    'recordpap.com.br',
    'www.recordpap.com.br',
    '127.0.0.1',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles', # Deve vir antes do whitenoise
    'whitenoise.runserver_nostatic', # Adicionado para servir arquivos estáticos
    'django.contrib.staticfiles',
    'usuarios',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'core',
    'presenca',
    'relatorios',
    'crm_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # --- CORREÇÃO 2: MIDDLEWARE DO WHITENOISE PARA ARQUIVOS ESTÁTICOS ---
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gestao_equipes.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'frontend', 'public')],
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

# --- CORREÇÃO 3: CONFIGURAÇÃO DO BANCO DE DADOS PARA PRODUÇÃO ---
# Esta lógica usa a variável de ambiente JAWSDB_URL do Heroku.
# Se não a encontrar, ele volta a usar o seu banco de dados SQLite local.
if 'JAWSDB_URL' in os.environ:
    DATABASES = {
        'default': dj_database_url.config(env='JAWSDB_URL', conn_max_age=600)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


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

# --- CONFIGURAÇÃO DE ARQUIVOS ESTÁTICOS (Mantida e com adição) ---
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'frontend', 'public'),
]

# Onde o Heroku irá coletar todos os arquivos estáticos
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
# Otimização para servir arquivos estáticos de forma eficiente
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    )
}

# Atualize esta lista conforme necessário para seu frontend em produção
CORS_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://recordpap.com.br",
    "https://www.recordpap.com.br",
]

AUTH_USER_MODEL = 'usuarios.Usuario'
LOGIN_URL = '/'