"""Confere preço, identidade e link do anúncio na API Shopee antes de qualquer envio."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from collect_shopee import DB_PATH, open_db, throttle
from shopee_probe import load_local_env, signed_request
from pathlib import Path

ROOT = Path(__file__).parent


def current_offer(db: sqlite3.Connection, listing_key: str) -> dict:
    parts = listing_key.split(":")
    if len(parts) != 3 or parts[0] != "shopee" or not all(part.isdigit() for part in parts[1:]):
        raise ValueError("Identificador Shopee inválido")
    shop_id, item_id = parts[1], parts[2]
    load_local_env(ROOT / ".env.local")
    app_id, secret = os.environ.get("SHOPEE_APP_ID", ""), os.environ.get("SHOPEE_APP_SECRET", "")
    if not app_id or not secret:
        raise RuntimeError("Credenciais Shopee ausentes")
    query = ("query { productOfferV2(itemId: " + item_id + ", limit: 5, page: 1) { nodes { "
             "itemId shopId productName productCatIds imageUrl priceMin priceMax ratingStar sales offerLink periodEndTime "
             "} } }")
    throttle(db)
    try:
        with urlopen(signed_request(app_id, secret, query), timeout=30) as response:
            body = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Shopee respondeu HTTP {exc.code}") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Falha de rede na revalidação Shopee") from None
    if body.get("errors"):
        codes = [str(error.get("extensions", {}).get("code", "?")) for error in body["errors"]]
        raise RuntimeError("Consulta exata Shopee falhou: " + ", ".join(codes))
    nodes = (body.get("data", {}).get("productOfferV2") or {}).get("nodes") or []
    matches = [node for node in nodes if str(node.get("itemId")) == item_id and str(node.get("shopId")) == shop_id]
    if len(matches) != 1:
        raise RuntimeError("Anúncio exato não encontrado na API Shopee")
    item = matches[0]
    if not item.get("offerLink") or not item.get("priceMin") or not item.get("priceMax"):
        raise RuntimeError("Oferta atual sem preço ou link de afiliado")
    if item.get("periodEndTime") and int(item["periodEndTime"]) < time.time():
        raise RuntimeError("Oferta encerrada")
    return item


def matches_draft(draft: dict, item: dict) -> None:
    if Decimal(str(item["priceMin"])) != Decimal(str(draft["price_min"])):
        raise RuntimeError("Preço mínimo mudou; rascunho precisa ser refeito")
    if Decimal(str(item["priceMax"])) != Decimal(str(draft["price_max"])):
        raise RuntimeError("Preço máximo mudou; rascunho precisa ser refeito")
    if item["offerLink"] != draft["offer_link"]:
        raise RuntimeError("Link de afiliado mudou; rascunho precisa ser refeito")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Revalida um rascunho Shopee sem publicar")
    parser.add_argument("draft", type=Path)
    args = parser.parse_args()
    try:
        draft = json.loads(args.draft.read_text(encoding="utf-8"))
        with open_db(DB_PATH) as db:
            item = current_offer(db, draft["listing_key"])
        matches_draft(draft, item)
        print("Preço, link e anúncio confirmados na Shopee. Nenhuma publicação foi feita.")
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, Exception) as exc:
        print(f"Revalidação bloqueou o rascunho: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
