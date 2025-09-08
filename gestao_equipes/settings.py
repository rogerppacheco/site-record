from pathlib import Path
import os
from dotenv import load_dotenv
import dj_database_url
from datetime import timedelta  # Importe o timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key-for-development')

DEBUG = os.getenv('DEBUG', '0') == '1'

ALLOWED_HOSTS = [
    'controle-presenca-448646307036.herokuapp.com',
    'recordpap.com.br',
    'www.recordpap.com.br',
    '127.0.0.1',
    'record-pap-app-80fd14bb6cb5.herokuapp.com',
    '.herokuapp.com'
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'whitenoise.runserver_nostatic',
    'usuarios',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
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

# --- CORREÇÃO APLICADA AQUI ---
# Define a URL para acessar os arquivos estáticos no navegador.
STATIC_URL = '/static/'

# Informa ao Django para procurar arquivos estáticos em ambas as pastas.
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
    os.path.join(BASE_DIR, 'frontend', 'public'),
]

# Define onde o comando `collectstatic` irá copiar todos os arquivos para produção.
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Otimiza a entrega de arquivos estáticos em produção com o WhiteNoise.
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

# =======================================================================
# INÍCIO DA CONFIGURAÇÃO DE SESSÃO E TOKENS
# =======================================================================

SIMPLE_JWT = {
    # Define a vida útil do token. A sessão expirará após 5 minutos de INATIVIDADE.
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=5),

    # Define o tempo máximo que um token pode ser atualizado. Após 1 dia, o usuário
    # precisará fazer login novamente com usuário e senha.
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),

    # Configurações para o token deslizante
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),

    # Demais configurações (mantidas do original se houver)
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'TOKEN_TYPE_CLAIM': 'token_type',
    'JTI_CLAIM': 'jti',
}

CORS_ALLOWED_ORIGINS = [
    "https://record-pap-app-80fd14bb6cb5.herokuapp.com",
    "https://recordpap.com.br",
    "https://www.recordpap.com.br",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = [
    'https://record-pap-app-80fd14bb6cb5.herokuapp.com',
    "https://recordpap.com.br",
    "https://www.recordpap.com.br",
    'http://127.0.0.1:8000',
    'http://localhost:8000',
]

# Configurações de Cookie para produção (HTTPS)
# Em desenvolvimento, você pode precisar comentar estas linhas se não usar HTTPS
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax' # 'None' requer Secure=True
CSRF_COOKIE_SAMESITE = 'Lax'    # 'None' requer Secure=True

# =======================================================================
# FIM DA CONFIGURAÇÃO
# =======================================================================

AUTH_USER_MODEL = 'usuarios.Usuario'
LOGIN_URL = '/'