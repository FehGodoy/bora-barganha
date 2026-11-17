"""Consulta campanhas de beleza da Shopee e guarda uma seleção no estado do worker."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from collect_shopee import throttle
from shopee_probe import signed_request

STATE_KEY = "shopee_beauty_campaigns"
REFRESH_EVERY = timedelta(hours=3)
QUERY = """query { shopeeOfferV2(limit: 30, page: 1) {
  nodes { offerName offerType categoryId collectionId imageUrl offerLink periodEndTime }
} }"""
BEAUTY_WORDS = ("beauty", "beleza", "maquiagem", "skincare", "perfume", "cabelo")


def refresh_campaigns(db) -> int | None:
    previous = db.execute("SELECT value FROM state WHERE key=?", (STATE_KEY,)).fetchone()
    now = datetime.now(timezone.utc)
    if previous:
        try:
            stored = json.loads(previous["value"])
            updated = datetime.fromisoformat(stored["updated_at"])
            if now - updated < REFRESH_EVERY:
                return None
        except (ValueError, KeyError, TypeError):
            pass
    app_id = os.environ.get("SHOPEE_APP_ID", "").strip()
    secret = os.environ.get("SHOPEE_APP_SECRET", "").strip()
    if not app_id or not secret:
        raise RuntimeError("Credenciais Shopee ausentes para campanhas")
    throttle(db)
    try:
        with urlopen(signed_request(app_id, secret, QUERY), timeout=30) as response:
            body = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Campanhas Shopee responderam HTTP {error.code}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Falha de rede ao consultar campanhas Shopee") from None
    if body.get("errors"):
        codes = [str(error.get("extensions", {}).get("code", "?")) for error in body["errors"]]
        raise RuntimeError("Consulta de campanhas Shopee falhou: " + ", ".join(codes))
    nodes = (body.get("data", {}).get("shopeeOfferV2") or {}).get("nodes") or []
    selected = []
    for node in nodes:
        name = str(node.get("offerName") or "").strip()
        if node.get("categoryId") == 100630 or any(word in name.lower() for word in BEAUTY_WORDS):
            selected.append(node)
    payload = json.dumps({"updated_at": now.isoformat(), "campaigns": selected}, ensure_ascii=False)
    db.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (STATE_KEY, payload))
    db.commit()
    return len(selected)
