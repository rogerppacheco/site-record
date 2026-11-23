#!/bin/sh
set -e

WORKERS="${GUNICORN_WORKERS:-2}"
THREADS="${GUNICORN_THREADS:-2}"

# Railway usa Dockerfile (não executa Procfile release) — migrações + cache.
if [ -f /app/scripts/migrate_unpooled.sh ]; then
  sh /app/scripts/migrate_unpooled.sh --noinput
else
  python manage.py migrate --noinput
fi
python manage.py createcachetable 2>/dev/null || true

# --clear: no Docker o COPY zera mtimes iguais e o collectstatic sem --clear
# marca tudo como "unmodified", mantendo staticfiles/ commitado (menu.js v5 etc.).
echo "[STATIC] collectstatic --clear (fonte: static/ → staticfiles/)..."
python manage.py collectstatic --noinput --clear --skip-checks
# Aceita qualquer patch 6.x (v6.0, v6.2, …) — o marcador muda com o cache-bust.
if ! grep -qE 'MENU\.JS v6\.' /app/staticfiles/js/menu.js 2>/dev/null \
   && ! grep -qE 'MENU\.JS v6\.' /app/staticfiles/js/menu.*.js 2>/dev/null; then
  echo "[STATIC] ERRO: menu.js v6.x nao apareceu em staticfiles apos collectstatic"
  ls -la /app/static/js/menu.js /app/staticfiles/js/menu* 2>&1 || true
  head -n 3 /app/staticfiles/js/menu.js 2>&1 || true
  exit 1
fi
echo "[STATIC] menu.js v6.x OK"

echo "[GUNICORN] workers=${WORKERS} threads=${THREADS} timeout=1200"

exec gunicorn gestao_equipes.wsgi \
  --timeout 1200 \
  --graceful-timeout 1200 \
  --keep-alive 5 \
  --preload \
  --workers "${WORKERS}" \
  --threads "${THREADS}"
