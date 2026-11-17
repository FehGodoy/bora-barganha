"""Coleta ofertas da Shopee, persiste histórico e separa candidatas; não publica."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from db import connect
from shopee_probe import load_local_env, signed_request

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "offers.sqlite3"
WAIT_SECONDS = 31
QUERY = """query {
  productOfferV2(keyword: %s, sortType: 2, limit: 30, page: 1) {
    nodes {
      itemId shopId productName productCatIds imageUrl priceMin priceMax ratingStar sales
      priceDiscountRate commissionRate productLink offerLink periodEndTime
    }
    pageInfo { page limit hasNextPage }
  }
}"""


def normalized_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    words = re.findall(r"[a-z0-9]+", text)
    ignored = {"promo", "promocao", "oferta", "frete", "gratis", "original"}
    return " ".join(word for word in words if word not in ignored)


def amount(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number > 0 else None
    except (InvalidOperation, TypeError):
        return None


def open_db(path: Path) -> sqlite3.Connection:
    db = connect(path)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS listings (
      listing_key TEXT PRIMARY KEY,
      canonical_key TEXT NOT NULL,
      title TEXT NOT NULL,
      image_url TEXT,
      offer_link TEXT,
      product_link TEXT,
      price_min TEXT,
      price_max TEXT,
      rating TEXT,
      sales INTEGER,
      commission_rate TEXT,
      first_seen TEXT NOT NULL,
      last_seen TEXT NOT NULL,
      lowest_seen TEXT,
      original_price TEXT,
      status TEXT NOT NULL,
      hold_reason TEXT
    );
    CREATE INDEX IF NOT EXISTS listings_canonical_idx ON listings(canonical_key);
    CREATE TABLE IF NOT EXISTS price_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      listing_key TEXT NOT NULL,
      observed_at TEXT NOT NULL,
      price_min TEXT NOT NULL,
      price_max TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS publications (
      canonical_key TEXT NOT NULL,
      channel TEXT NOT NULL,
      published_at TEXT NOT NULL,
      price TEXT NOT NULL,
      external_id TEXT NOT NULL,
      UNIQUE(channel, external_id)
    );
    CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    if isinstance(db, sqlite3.Connection):
        columns = {row[1] for row in db.execute("PRAGMA table_info(listings)")}
        if "original_price" not in columns:
            db.execute("ALTER TABLE listings ADD COLUMN original_price TEXT")
    return db


def original_price(price: Decimal | None, discount_rate: object) -> Decimal | None:
    """Preço "de" informado pela Shopee: preço atual dividido por (1 - desconto)."""
    try:
        rate = Decimal(str(discount_rate))
    except (InvalidOperation, TypeError):
        return None
    if not price or not rate.is_finite() or rate < 5 or rate > 90:
        return None
    return (price / (1 - rate / 100)).quantize(Decimal("0.01"))


def throttle(db: sqlite3.Connection) -> None:
    row = db.execute("SELECT value FROM state WHERE key='last_unscrolled_request'").fetchone()
    if row:
        remaining = WAIT_SECONDS - (time.time() - float(row["value"]))
        if remaining > 0:
            print(f"Aguardando {remaining:.0f}s pelo intervalo exigido pela Shopee...", flush=True)
            time.sleep(remaining)
    db.execute("INSERT INTO state(key,value) VALUES('last_unscrolled_request',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(time.time()),))
    db.commit()


def fetch_offers(db: sqlite3.Connection, app_id: str, secret: str, keyword: str) -> list[dict]:
    throttle(db)
    query = QUERY % json.dumps(keyword, ensure_ascii=True)
    request = signed_request(app_id, secret, query)
    try:
        with urlopen(request, timeout=30) as response:
            body = json.load(response)
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {raw[:300].replace(app_id, '[oculto]').replace(secret, '[oculto]')}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError("Falha de rede ao consultar a Shopee") from error
    if body.get("errors"):
        codes = [str(e.get("extensions", {}).get("code", "?")) for e in body["errors"]]
        raise RuntimeError("GraphQL retornou erro(s): " + ", ".join(codes))
    return (body.get("data", {}).get("productOfferV2") or {}).get("nodes") or []


def fetch_offer_ids(db: sqlite3.Connection, app_id: str, secret: str, keyword: str) -> list[dict]:
    """Busca apenas identificadores; detalhes são consultados por itemId depois."""
    throttle(db)
    query = ("query { productOfferV2(keyword: " + json.dumps(keyword, ensure_ascii=True) +
             ", limit: 10, page: 1) { nodes { itemId shopId productName } } }")
    try:
        with urlopen(signed_request(app_id, secret, query), timeout=30) as response:
            body = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Busca básica Shopee respondeu HTTP {error.code}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Falha de rede na busca básica Shopee") from None
    if body.get("errors"):
        codes = [str(error.get("extensions", {}).get("code", "?")) for error in body["errors"]]
        raise RuntimeError("Busca básica Shopee falhou: " + ", ".join(codes))
    return (body.get("data", {}).get("productOfferV2") or {}).get("nodes") or []


def evaluate(item: dict, now: int) -> tuple[str, str | None]:
    title = str(item.get("productName") or "").lower()
    if any(word in title for word in ("chaveiro", "berloque")):
        return "retida", "acessório fora do nicho"
    low, high = amount(item.get("priceMin")), amount(item.get("priceMax"))
    if not low or not high:
        return "retida", "preço ausente"
    price_range = low != high
    if price_range and high / low > Decimal("1.4"):
        return "retida", "variantes com preços muito diferentes"
    if not item.get("imageUrl"):
        return "retida", "imagem ausente"
    if not item.get("offerLink"):
        return "retida", "link de afiliado ausente"
    end = item.get("periodEndTime")
    if end and int(end) < now:
        return "retida", "oferta encerrada"
    rating = amount(item.get("ratingStar"))
    if rating is None or rating < Decimal("4.5"):
        return "retida", "avaliação abaixo de 4,5 ou ausente"
    if int(item.get("sales") or 0) < 20:
        return "retida", "menos de 20 vendas"
    return ("candidata_a_partir" if price_range else "candidata"), None


def store_offers(db: sqlite3.Connection, offers: list[dict]) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    now_unix = int(time.time())
    candidates = 0
    held = 0
    seen_canonical: set[str] = set()
    for item in offers:
        item_id, shop_id = item.get("itemId"), item.get("shopId")
        title = str(item.get("productName") or "").strip()
        if not item_id or not shop_id or not title:
            held += 1
            continue
        listing_key = f"shopee:{shop_id}:{item_id}"
        canonical = normalized_title(title)
        status, reason = evaluate(item, now_unix)
        if canonical in seen_canonical and status.startswith("candidata"):
            status, reason = "retida", "produto repetido na mesma rodada"
        seen_canonical.add(canonical)
        low, high = amount(item.get("priceMin")), amount(item.get("priceMax"))
        old = db.execute("SELECT lowest_seen,image_url,hold_reason FROM listings WHERE listing_key=?", (listing_key,)).fetchone()
        if (old and old["image_url"] == item.get("imageUrl") and
                str(old["hold_reason"] or "").startswith(("imagem reprovada:", "imagem promocional"))):
            status, reason = "retida", old["hold_reason"]
        before = original_price(low, item.get("priceDiscountRate"))
        lowest = min(low, Decimal(old["lowest_seen"])) if low and old and old["lowest_seen"] else low
        db.execute("""INSERT INTO listings
          (listing_key,canonical_key,title,image_url,offer_link,product_link,price_min,price_max,rating,sales,commission_rate,first_seen,last_seen,lowest_seen,original_price,status,hold_reason)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(listing_key) DO UPDATE SET
          canonical_key=excluded.canonical_key,title=excluded.title,image_url=excluded.image_url,
          offer_link=excluded.offer_link,product_link=excluded.product_link,
          price_min=excluded.price_min,price_max=excluded.price_max,rating=excluded.rating,
          sales=excluded.sales,commission_rate=excluded.commission_rate,
          last_seen=excluded.last_seen,lowest_seen=excluded.lowest_seen,original_price=excluded.original_price,
          status=excluded.status,hold_reason=excluded.hold_reason""",
          (listing_key, canonical, title, item.get("imageUrl"), item.get("offerLink"), item.get("productLink"),
           str(low) if low else None, str(high) if high else None, item.get("ratingStar"), int(item.get("sales") or 0),
           item.get("commissionRate"), now, now, str(lowest) if lowest else None,
           str(before) if before else None, status, reason))
        if low and high:
            db.execute("INSERT INTO price_history(listing_key,observed_at,price_min,price_max) VALUES(?,?,?,?)", (listing_key, now, str(low), str(high)))
        if status.startswith("candidata"):
            candidates += 1
        else:
            held += 1
    db.commit()
    return candidates, held


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta e registra ofertas da Shopee sem publicar")
    parser.add_argument("--keyword", default="maquiagem")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    load_local_env(ROOT / ".env.local")
    import os
    app_id = os.environ.get("SHOPEE_APP_ID", "").strip()
    secret = os.environ.get("SHOPEE_APP_SECRET", "").strip()
    if not app_id or not secret:
        print("Credenciais ausentes no .env.local", file=sys.stderr)
        return 2
    with open_db(args.db) as db:
        for attempt in range(2):
            try:
                offers = fetch_offers(db, app_id, secret, args.keyword)
                break
            except RuntimeError as error:
                if attempt == 0 and "10000" in str(error):
                    print("Erro interno temporário da Shopee; tentando novamente após o intervalo mínimo...", flush=True)
                    continue
                print(f"Coleta falhou: {error}", file=sys.stderr)
                return 1
        candidates, held = store_offers(db, offers)
        print(f"Coleta: {len(offers)} anúncios; {candidates} candidatos; {held} retidos.")
        for row in db.execute("SELECT title,price_min,hold_reason,status FROM listings WHERE last_seen=(SELECT MAX(last_seen) FROM listings) LIMIT 5"):
            print(f"- {row['title'][:70]} | R$ {row['price_min'] or '?'} | {row['hold_reason'] or row['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




