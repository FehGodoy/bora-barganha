"""Exporta uma vitrine pública e sem credenciais a partir das ofertas recentes."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
SITE = ROOT / "site"
DIST = SITE / "dist"
DATABASE = ROOT / "data" / "offers.sqlite3"


def _timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _allowed_link(value: object, source: str) -> str | None:
    if not value:
        return None
    url = str(value).strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    if source == "mercadolivre":
        allowed = host == "meli.la"
    else:
        allowed = host in {"shope.ee", "s.shopee.com.br"} or host == "shopee.com.br" or host.endswith(".shopee.com.br")
    return url if allowed else None


def _image_url(value: object) -> str | None:
    if not value:
        return None
    parsed = urlparse(str(value))
    return str(value) if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else None


def _price(value: object) -> str | None:
    try:
        price = Decimal(str(value))
        return f"{price:.2f}" if price.is_finite() and price > 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def select_offers(rows: list[dict], now: datetime) -> list[dict]:
    offers = []
    seen = set()
    for row in rows:
        source = str(row["source"])
        if source not in {"shopee", "mercadolivre"} or not str(row["status"]).startswith("candidata"):
            continue
        if source == "shopee" and any(word in str(row["title"]).lower() for word in ("chaveiro", "berloque")):
            continue
        observed = _timestamp(row["last_seen"])
        max_age = timedelta(hours=6 if source == "mercadolivre" else 2)
        if not observed or observed > now + timedelta(minutes=5) or now - observed > max_age:
            continue
        link = _allowed_link(row["offer_link"], source)
        image = _image_url(row["image_url"])
        price = _price(row["price_min"])
        canonical = str(row["canonical_key"])
        if not link or not image or not price or not canonical or canonical in seen:
            continue
        seen.add(canonical)
        offers.append({
            "id": str(row["listing_key"]),
            "title": str(row["title"]).strip()[:180],
            "source": source,
            "price": price,
            "image": image,
            "url": link,
            "observed_at": observed.isoformat(),
            "sales": max(0, int(row["sales"] or 0)),
        })
    offers.sort(key=lambda offer: (offer["sales"], offer["observed_at"]), reverse=True)
    return [{k: v for k, v in offer.items() if k != "sales"} for offer in offers[:60]]


def select_campaigns(stored: dict, now: datetime) -> list[dict]:
    updated = _timestamp(stored.get("updated_at"))
    if not updated or updated > now + timedelta(minutes=5) or now - updated > timedelta(hours=24):
        return []
    selected = []
    seen = set()
    for row in stored.get("campaigns", []):
        link = _allowed_link(row.get("offerLink"), "shopee")
        image = _image_url(row.get("imageUrl"))
        name = str(row.get("offerName") or "").strip()
        try:
            end = int(row.get("periodEndTime") or 0)
        except (ValueError, TypeError):
            continue
        if not name or not link or not image or link in seen or (end and end < now.timestamp()):
            continue
        seen.add(link)
        category = row.get("categoryId") == 100630 and str(row.get("offerType")) == "2"
        selected.append({"title": "Beleza na Shopee" if category else name,
                         "kind": "Seleção de beleza" if category else "Campanha",
                         "image": image, "url": link, "observed_at": updated.isoformat()})
    return selected[:8]


def read_campaigns() -> dict:
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if db_url:
        import psycopg

        with psycopg.connect(db_url) as conn:
            row = conn.execute("SELECT value FROM state WHERE key='shopee_beauty_campaigns'").fetchone()
    elif DATABASE.exists():
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute("SELECT value FROM state WHERE key='shopee_beauty_campaigns'").fetchone()
    else:
        row = None
    if not row:
        return {}
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return {}


def read_rows() -> list[dict]:
    db_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if db_url:
        import psycopg

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""SELECT listing_key, source, canonical_key, title, image_url,
                               offer_link, price_min, sales, last_seen, status FROM listings
                               WHERE status LIKE 'candidata%' AND last_seen >= now() - interval '6 hours'
                               ORDER BY last_seen DESC LIMIT 500""")
                names = [column.name for column in cursor.description]
                return [dict(zip(names, row)) for row in cursor.fetchall()]
    if not DATABASE.exists():
        return []
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("""SELECT listing_key, source, canonical_key,
            title, image_url, offer_link, price_min, sales, last_seen, status FROM listings
            WHERE status LIKE 'candidata%' ORDER BY last_seen DESC LIMIT 500""")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--empty", action="store_true", help="Gera página local sem ler o banco")
    args = parser.parse_args()
    DIST.mkdir(parents=True, exist_ok=True)
    for filename in ("index.html", "styles.css", "app.js", "favicon.svg"):
        shutil.copyfile(SITE / filename, DIST / filename)
    now = datetime.now(timezone.utc)
    offers = select_offers([] if args.empty else read_rows(), now)
    payload = {"updated_at": now.isoformat(), "offers": offers,
               "campaigns": [] if args.empty else select_campaigns(read_campaigns(), now)}
    temporary = DIST / "offers.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(DIST / "offers.json")
    print(f"Vitrine gerada: {len(offers)} ofertas recentes.")


if __name__ == "__main__":
    main()
