"""
Utilitários de conexão PostgreSQL com PgBouncer (modo transaction).

Railway nativo: DATABASE_URL → pooler; DATABASE_UNPOOLED_URL → Postgres direto.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def is_pgbouncer_enabled() -> bool:
    """Pooler ativo quando há URL unpooled separada ou flag explícita."""
    if os.environ.get("PGBOUNCER_ENABLED", "").lower() in ("1", "true", "yes"):
        return True
    return bool(os.environ.get("DATABASE_UNPOOLED_URL"))


def append_query_param(url: str, key: str, value: str) -> str:
    """Adiciona ou substitui um parâmetro de query na URL PostgreSQL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query[key] = [value]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def normalize_postgres_url(url: str) -> str:
    """Normaliza postgres:// para postgresql:// (Django/psycopg2)."""
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


def build_django_pooled_url(url: str) -> str:
    """URL pooled para Django — conecta direto ao PgBouncer, sem ?pgbouncer=true."""
    return normalize_postgres_url(url)


def build_prisma_pooled_url(url: str) -> str:
    """URL pooled para Prisma — exige ?pgbouncer=true no query string."""
    url = normalize_postgres_url(url)
    if "pgbouncer=true" not in url:
        url = append_query_param(url, "pgbouncer", "true")
    return url


def build_pooled_url(url: str) -> str:
    """Alias Prisma (retrocompat)."""
    return build_prisma_pooled_url(url)


def build_prisma_urls(pooled_base: str, unpooled_base: str, schema: str) -> dict[str, str]:
    """Monta DATABASE_URL + DIRECT_URL para Prisma com schema dedicado."""
    pooled = append_query_param(normalize_postgres_url(pooled_base), "schema", schema)
    pooled = build_prisma_pooled_url(pooled)
    direct = append_query_param(normalize_postgres_url(unpooled_base), "schema", schema)
    return {"DATABASE_URL": pooled, "DATABASE_DIRECT_URL": direct}


def django_database_options(*, pooled: bool) -> dict[str, Any]:
    """OPTIONS do Django para Postgres com ou sem PgBouncer."""
    _ = pooled
    return {"connect_timeout": 10}
