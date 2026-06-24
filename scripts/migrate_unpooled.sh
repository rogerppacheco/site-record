#!/bin/sh
# Migrations exigem sessão dedicada — não usar PgBouncer (modo transaction).
set -e

if [ -n "${DATABASE_UNPOOLED_URL:-}" ]; then
  echo "[MIGRATE] Usando DATABASE_UNPOOLED_URL (Postgres direto)"
  DATABASE_URL="$DATABASE_UNPOOLED_URL" python manage.py migrate "$@"
else
  echo "[MIGRATE] DATABASE_UNPOOLED_URL ausente — usando DATABASE_URL"
  python manage.py migrate "$@"
fi
