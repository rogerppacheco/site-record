"""Settings para testes locais em SQLite (ignora DATABASE_URL do .env)."""

from gestao_equipes.settings import *  # noqa: F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'test_db.sqlite3',  # noqa: F405
    }
}
DATABASES.pop('unpooled', None)
