"""Camada de acesso ao Lakebase (Postgres).

Conexão por request (a app é uma ferramenta administrativa de baixo volume;
o token OAuth do Lakebase expira em ~1h, então pool de longa duração não
compensa a complexidade). Sempre com search_path no schema do Lakeguard.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras

from server.config import PG_SCHEMA, lakebase_params


@contextmanager
def connection() -> Iterator[psycopg2.extensions.connection]:
    """Abre uma conexão, fixa o search_path e garante commit/rollback/close."""
    params = lakebase_params()
    conn = psycopg2.connect(connect_timeout=10, **params)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {PG_SCHEMA}, public")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    """SELECT → lista de dicts."""
    with connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    with connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def execute(sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    """INSERT/UPDATE/DELETE. Retorna a primeira linha do RETURNING, se houver."""
    with connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            if cur.description is not None:
                row = cur.fetchone()
                return dict(row) if row else None
            return None


def healthcheck() -> bool:
    try:
        return query_one("SELECT 1 AS ok") == {"ok": 1}
    except Exception:
        return False
