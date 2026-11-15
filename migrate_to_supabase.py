"""Copia o histórico do SQLite local (data/offers.sqlite3) para o Postgres do Supabase.

Idempotente: linhas já existentes são ignoradas. Requer SUPABASE_DB_URL no .env.local.
"""

from __future__ import annotations

import sqlite3
import sys

from collect_shopee import DB_PATH
from db import PgConnection, using_postgres
import os

TABLES = {
    "listings": ("listing_key", None),
    "publications": ("channel, external_id", None),
    "publication_jobs": ("draft_id", None),
    "state": ("key", None),
}


def main() -> int:
    if not using_postgres():
        print("SUPABASE_DB_URL ausente no .env.local", file=sys.stderr)
        return 2
    src = sqlite3.connect(DB_PATH)
    src.row_factory = sqlite3.Row
    dst = PgConnection(os.environ["SUPABASE_DB_URL"].strip())
    with dst:
        for table, (conflict, _) in TABLES.items():
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"{table}: 0")
                continue
            cols = [c for c in rows[0].keys() if not (table == "publications" and c == "id")]
            sql = (f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))}) "
                   f"ON CONFLICT ({conflict}) DO NOTHING")
            for row in rows:
                dst.execute(sql, [row[c] for c in cols])
            print(f"{table}: {len(rows)}")
        rows = src.execute("SELECT listing_key,observed_at,price_min,price_max FROM price_history").fetchall()
        known = {r[0] for r in dst.execute("SELECT listing_key FROM listings").fetchall()}
        count = dst.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        if int(count) == 0:
            for row in rows:
                if row[0] in known:
                    dst.execute("INSERT INTO price_history(listing_key,observed_at,price_min,price_max) VALUES(?,?,?,?)", tuple(row))
        print(f"price_history: {len(rows) if int(count) == 0 else 'já migrado'}")
    print("Migração concluída.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
