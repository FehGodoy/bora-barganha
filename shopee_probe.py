"""Consulta de leitura à Shopee Affiliate Open API; não publica nem salva credenciais."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"


def load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"SHOPEE_APP_ID", "SHOPEE_APP_SECRET"}:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def build_query(keyword: str) -> str:
    quoted = json.dumps(keyword, ensure_ascii=False)
    return f"""query {{
  productOfferV2(keyword: {quoted}, sortType: 2, limit: 5, page: 1) {{
    nodes {{
      itemId shopId productName imageUrl priceMin priceMax
      ratingStar sales priceDiscountRate productLink offerLink periodEndTime
    }}
    pageInfo {{ page limit hasNextPage }}
  }}
}}"""


def signed_request(app_id: str, secret: str, query: str) -> Request:
    payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    factor = app_id + timestamp + payload + secret
    signature = hashlib.sha256(factor.encode("utf-8")).hexdigest()
    auth = f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"
    return Request(
        ENDPOINT,
        data=payload.encode("utf-8"),
        headers={"Authorization": auth, "Content-Type": "application/json"},
        method="POST",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica leitura de ofertas na API Shopee")
    parser.add_argument("--keyword", default="beleza", help="Busca inicial, padrão: beleza")
    parser.add_argument("--dry-run", action="store_true", help="Mostra consulta sem chamar a API")
    args = parser.parse_args()
    query = build_query(args.keyword)
    if args.dry_run:
        print(query)
        return 0

    load_local_env(Path(__file__).with_name(".env.local"))
    app_id = os.environ.get("SHOPEE_APP_ID", "").strip()
    secret = os.environ.get("SHOPEE_APP_SECRET", "").strip()
    if not app_id or not secret:
        print("Faltam SHOPEE_APP_ID e SHOPEE_APP_SECRET no .env.local ou ambiente.", file=sys.stderr)
        return 2

    request = signed_request(app_id, secret, query)
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        print(f"HTTP {error.code}: {body[:800].replace(app_id, '[oculto]').replace(secret, '[oculto]')}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError) as error:
        print(f"Falha de rede: {error.reason if isinstance(error, URLError) else error}", file=sys.stderr)
        return 1

    if data.get("errors"):
        safe = json.dumps(data["errors"], ensure_ascii=False).replace(app_id, "[oculto]").replace(secret, "[oculto]")
        print(f"GraphQL retornou erro: {safe[:800]}", file=sys.stderr)
        return 1

    offers = data.get("data", {}).get("productOfferV2") or {}
    nodes = offers.get("nodes") or []
    print(f"API respondeu com {len(nodes)} oferta(s) para '{args.keyword}'.")
    for offer in nodes:
        name = (offer.get("productName") or "Sem nome").replace("\n", " ")[:95]
        print(f"- {name} | R$ {offer.get('priceMin')}–{offer.get('priceMax')} | link: {'sim' if offer.get('offerLink') else 'não'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
