"""Fila de ofertas do Mercado Livre capturadas pela extensão (capture_queue -> listings).

Sem API autorizada de revalidação, a trava de preço do Mercado Livre é a idade da captura:
a oferta só é publicada até ML_MAX_AGE_HOURS depois do clique na extensão. Quando houver app
no DevCenter, `ml_offer` passa a consultar o preço atual pela API oficial.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from collect_shopee import normalized_title

PREFIX = "mercadolivre:"
BEAUTY_ROOT = "Beleza e Cuidado Pessoal"


def max_age() -> timedelta:
    return timedelta(hours=float(os.environ.get("ML_MAX_AGE_HOURS", "6")))


def ingest(db) -> tuple[int, int]:
    """Move capturas 'aguardando' para listings como candidatas. Devolve (importadas, retidas)."""
    rows = db.execute("SELECT * FROM capture_queue WHERE status='aguardando' ORDER BY captured_at").fetchall()
    imported = held = 0
    for row in rows:
        reason = None
        if not str(row["breadcrumb"] or "").startswith(BEAUTY_ROOT):
            reason = "fora da categoria Beleza e Cuidado Pessoal"
        elif row["available"] is False or row["available"] == 0:
            reason = "sem estoque na captura"
        elif not row["image_url"]:
            reason = "imagem ausente"
        elif datetime.fromisoformat(row["captured_at"]) < datetime.now(timezone.utc) - max_age():
            reason = "captura antiga demais para publicar"
        if reason:
            db.execute("UPDATE capture_queue SET status='retida',hold_reason=? WHERE id=?", (reason, row["id"]))
            held += 1
            continue
        key = PREFIX + row["external_id"]
        price = str(row["price"])
        db.execute("""INSERT INTO listings
          (listing_key,source,canonical_key,title,image_url,offer_link,product_link,price_min,price_max,
           rating,sales,first_seen,last_seen,lowest_seen,status,hold_reason)
          VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,?,?,?,'candidata',NULL)
          ON CONFLICT(listing_key) DO UPDATE SET title=excluded.title,image_url=excluded.image_url,
          offer_link=excluded.offer_link,product_link=excluded.product_link,price_min=excluded.price_min,
          price_max=excluded.price_max,last_seen=excluded.last_seen,status='candidata',hold_reason=NULL""",
          (key, "mercadolivre", normalized_title(row["title"]), row["title"], row["image_url"], row["affiliate_link"],
           row["page_url"], price, price, row["captured_at"], row["captured_at"], price))
        db.execute("INSERT INTO price_history(listing_key,observed_at,price_min,price_max) VALUES(?,?,?,?)",
                   (key, row["captured_at"], price, price))
        db.execute("UPDATE capture_queue SET status='importada' WHERE id=?", (row["id"],))
        imported += 1
    db.commit()
    return imported, held


def ml_offer(db, listing_key: str) -> dict:
    """Equivalente a revalidate_shopee.current_offer para o Mercado Livre (trava por idade da captura)."""
    row = db.execute("SELECT * FROM listings WHERE listing_key=?", (listing_key,)).fetchone()
    if not row:
        raise RuntimeError("Anúncio do Mercado Livre não encontrado")
    if datetime.fromisoformat(row["last_seen"]) < datetime.now(timezone.utc) - max_age():
        raise RuntimeError("Captura do Mercado Livre expirou; recapture para publicar")
    return {"priceMin": row["price_min"], "priceMax": row["price_max"], "offerLink": row["offer_link"],
            "imageUrl": row["image_url"]}
