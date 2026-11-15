"""Conexão de banco: Postgres do Supabase quando SUPABASE_DB_URL existe; senão, SQLite local.

O adaptador Postgres imita o que o código usa do sqlite3: placeholders `?`, linhas acessíveis
por nome e por índice, valores de data/número devolvidos como texto, `BEGIN IMMEDIATE`
(vira trava exclusiva em publication_jobs) e `executescript` (ignorado: o schema vem de
supabase/schema.sql).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent


def _load_env() -> None:
    path = ROOT / ".env.local"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("SUPABASE_DB_URL="):
            os.environ.setdefault("SUPABASE_DB_URL", line.split("=", 1)[1].strip().strip('"').strip("'"))


class Row(dict):
    def __init__(self, names: list[str], values: tuple):
        super().__init__(zip(names, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def keys(self):  # mesmo comportamento de sqlite3.Row
        return list(super().keys())


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _row_factory(cursor):
    names = [c.name for c in (cursor.description or [])]
    return lambda values: Row(names, tuple(_plain(v) for v in values))


class PgConnection:
    is_pg = True

    def __init__(self, url: str):
        import psycopg
        self.error = psycopg.Error
        self.conn = psycopg.connect(url, row_factory=_row_factory, prepare_threshold=None)
        self.row_factory = None  # atribuições de sqlite3.Row são ignoradas

    def execute(self, sql: str, params: tuple | list = ()):
        text = sql.strip()
        if text.upper() == "BEGIN IMMEDIATE":
            self.conn.commit()
            return self.conn.execute("LOCK TABLE publication_jobs IN EXCLUSIVE MODE")
        if text.upper().startswith("PRAGMA"):
            return self.conn.execute("SELECT 1 WHERE false")
        return self.conn.execute(sql.replace("%", "%%").replace("?", "%s"), tuple(params))

    def executescript(self, _script: str) -> None:
        return None

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        return False


def using_postgres() -> bool:
    _load_env()
    return bool(os.environ.get("SUPABASE_DB_URL", "").strip())


def connect(sqlite_path: Path):
    if using_postgres():
        return PgConnection(os.environ["SUPABASE_DB_URL"].strip())
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(sqlite_path)
    db.row_factory = sqlite3.Row
    return db
