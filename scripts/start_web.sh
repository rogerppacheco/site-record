#!/bin/sh
set -e

WORKERS="${GUNICORN_WORKERS:-2}"
THREADS="${GUNICORN_THREADS:-2}"

echo "[GUNICORN] workers=${WORKERS} threads=${THREADS} timeout=1200"

exec gunicorn gestao_equipes.wsgi \
  --timeout 1200 \
  --graceful-timeout 1200 \
  --keep-alive 5 \
  --workers "${WORKERS}" \
  --threads "${THREADS}"
