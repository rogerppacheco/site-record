#!/bin/sh
set -e

WORKERS="${GUNICORN_WORKERS:-2}"
THREADS="${GUNICORN_THREADS:-2}"

# Railway usa Dockerfile (não executa Procfile release) — garante tabela de cache.
python manage.py createcachetable 2>/dev/null || true

# Fallback se imagem antiga não tiver staticfiles (deploy de emergência)
if [ ! -d staticfiles ] || [ -z "$(ls -A staticfiles 2>/dev/null)" ]; then
  echo "[STATIC] staticfiles ausente — executando collectstatic..."
  python manage.py collectstatic --noinput --skip-checks 2>/dev/null || true
fi

echo "[GUNICORN] workers=${WORKERS} threads=${THREADS} timeout=1200"

exec gunicorn gestao_equipes.wsgi \
  --timeout 1200 \
  --graceful-timeout 1200 \
  --keep-alive 5 \
  --workers "${WORKERS}" \
  --threads "${THREADS}"
