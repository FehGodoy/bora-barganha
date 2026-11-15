"""Prepara arte e textos de uma oferta validada, sem publicar em nenhum canal."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from collect_shopee import DB_PATH
from render_offer import OUT_DIR, download_image, render

ROOT = Path(__file__).parent
OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"


def load_openai_env() -> None:
    path = ROOT / ".env.local"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {"OPENAI_API_KEY", "OPENAI_MODEL"}:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def structured_response(api_key: str, model: str, prompt: str, schema_name: str, properties: dict, image_data: str | None = None) -> dict:
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    if image_data:
        content.append({"type": "input_image", "image_url": image_data, "detail": "high"})
    payload = {
        "model": model,
        "input": [{"role": "user", "content": content}],
        "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": {
            "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False,
        }}},
        "max_output_tokens": 500,
    }
    request = Request(OPENAI_ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"OpenAI respondeu HTTP {exc.code}; detalhes omitidos para proteger a chave") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Falha de rede ao consultar a OpenAI") from None
    if result.get("status") != "completed":
        raise RuntimeError("Resposta incompleta da OpenAI")
    for item in result.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "refusal":
                    raise RuntimeError("A OpenAI recusou a análise")
                if part.get("type") == "output_text":
                    parsed = json.loads(part["text"])
                    if isinstance(parsed, dict):
                        return parsed
    raise RuntimeError("A OpenAI não devolveu o JSON esperado")


def select_candidate(db: sqlite3.Connection, listing_key: str | None) -> sqlite3.Row:
    db.row_factory = sqlite3.Row
    if listing_key:
        rows = db.execute("SELECT * FROM listings WHERE listing_key=?", (listing_key,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM listings WHERE status LIKE 'candidata%' ORDER BY sales DESC LIMIT 50").fetchall()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    for row in rows:
        if not str(row["status"]).startswith("candidata") or not row["image_url"] or not row["offer_link"]:
            continue
        if datetime.fromisoformat(row["last_seen"]) < cutoff:
            continue
        previous = db.execute("SELECT 1 FROM publications WHERE canonical_key=? AND channel='whatsapp' AND published_at>? LIMIT 1",
                              (row["canonical_key"], (datetime.now(timezone.utc) - timedelta(days=7)).isoformat())).fetchone()
        if not previous:
            return row
    raise RuntimeError("Nenhuma candidata recente e inédita disponível; rode uma nova coleta")


def inspect_image(api_key: str, model: str, image, title: str) -> dict:
    preview = image.copy()
    preview.thumbnail((1000, 1000))
    preview = preview.convert("RGB")
    buffer = io.BytesIO()
    preview.save(buffer, format="JPEG", quality=86)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    prompt = ("Analise a imagem original de um anúncio de beleza. Produto anunciado: " + title +
              ". Responda com precisão: matches_product=true somente se a imagem mostra o produto anunciado; "
              "has_offer_text=true se há preço, percentual de desconto, cupom, data de campanha ou banner de promoção "
              "sobreposto na foto (texto normal da embalagem, como marca e FPS, não conta); "
              "legible=true se o produto é identificável e a foto tem qualidade suficiente para uma arte. "
              "Se houver dúvida, marque de modo conservador e explique brevemente em português.")
    return structured_response(api_key, model, prompt, "image_review", {
        "matches_product": {"type": "boolean"},
        "has_offer_text": {"type": "boolean"},
        "legible": {"type": "boolean"},
        "reason": {"type": "string"},
    }, "data:image/jpeg;base64," + encoded)


def create_copy(api_key: str, model: str, title: str) -> dict:
    prompt = ("Escreva para Bora Barganha, perfil divertido de achados de beleza. Produto: " + title +
              ". Gere somente: headline curta e simpática (até 70 caracteres), CTA curta para conferir o link "
              "(até 60 caracteres) e short_title para a arte (até 44 caracteres, somente palavras e números "
              "presentes no nome do produto, preservando marca e tipo). Não inclua preço, desconto, porcentagem, frete, prazo, estoque, eficácia, "
              "benefício, comparação, urgência, URL nem informação que não esteja no nome do produto. "
              "Não use hashtags. Português do Brasil.")
    data = structured_response(api_key, model, prompt, "offer_copy", {
        "headline": {"type": "string"}, "cta": {"type": "string"}, "short_title": {"type": "string"},
    })
    title_numbers = set(re.findall(r"\d+(?:[,.]\d+)?", title))
    fallback = False
    for key, limit in (("headline", 70), ("cta", 60)):
        value = str(data[key]).strip()
        numbers = set(re.findall(r"\d+(?:[,.]\d+)?", value))
        invalid_numbers = bool(numbers - title_numbers) if key == "headline" else bool(numbers)
        if (not value or len(value) > limit or invalid_numbers or
                re.search(r"%|R\$|https?://|www\.|\b(off|desconto|frete|cupom)\b", value, re.I)):
            value = "Olha esse achado de beleza!" if key == "headline" else "Confira os detalhes no link"
            fallback = True
        data[key] = value
    short_title = str(data["short_title"]).strip()
    title_words = set(re.findall(r"[a-z0-9]+", title.casefold()))
    short_words = set(re.findall(r"[a-z0-9]+", short_title.casefold()))
    if (not short_title or len(short_title) > 44 or not short_words.issubset(title_words)):
        short_title = short_title_fallback(title)
        fallback = True
    data["short_title"] = short_title
    data["fallback"] = fallback
    return data


def short_title_fallback(title: str) -> str:
    words = title.split()
    candidate = " ".join(words[:2] + words[-3:]) if len(words) >= 6 else title
    if len(candidate) <= 44:
        return candidate
    return title[:44].rsplit(" ", 1)[0]


def money(value: str) -> str:
    return f"R$ {Decimal(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def prepare(db: sqlite3.Connection, row: sqlite3.Row, api_key: str, model: str) -> Path | None:
    image = download_image(row["image_url"])
    verdict = inspect_image(api_key, model, image, row["title"])
    if not verdict["matches_product"] or verdict["has_offer_text"] or not verdict["legible"]:
        reason = str(verdict.get("reason") or "imagem inadequada")[:250]
        db.execute("UPDATE listings SET status='retida',hold_reason=? WHERE listing_key=?", ("imagem reprovada: " + reason, row["listing_key"]))
        db.commit()
        print(f"Imagem reprovada; oferta retida: {reason}")
        return None
    copy = create_copy(api_key, model, row["title"])
    price = money(row["price_min"])
    prefix = "A partir de " if Decimal(row["price_min"]) != Decimal(row["price_max"]) else ""
    disclosure = "Publicidade • Link de afiliado; podemos receber comissão. Preço sujeito a alteração."
    whatsapp = f"✨ {copy['headline']}\n\n{row['title']}\n💸 {prefix}{price}\n\n{copy['cta']} 👇\n{row['offer_link']}\n\n{disclosure}"
    instagram = f"✨ {copy['headline']}\n\n{row['title']}\n💸 {prefix}{price}\n\nOfertas e link no grupo da bio.\n\n{disclosure}"
    art = render(row, image, copy["short_title"])
    draft = {
        "listing_key": row["listing_key"], "canonical_key": row["canonical_key"],
        "observed_at": row["last_seen"], "prepared_at": datetime.now(timezone.utc).isoformat(),
        "price_min": row["price_min"], "price_max": row["price_max"],
        "offer_link": row["offer_link"], "image_review": verdict, "copy_fallback": copy["fallback"],
        "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "art_title": copy["short_title"],
        "art_path": str(art), "whatsapp_text": whatsapp, "instagram_caption": instagram,
        "status": "draft_only",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    destination = OUT_DIR / (row["listing_key"].replace(":", "-") + ".json")
    destination.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Cria rascunho de oferta, sem publicar")
    parser.add_argument("--listing-key", help="Anúncio específico; padrão: melhor candidata recente")
    args = parser.parse_args()
    load_openai_env()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    if not api_key:
        print("OPENAI_API_KEY ausente no .env.local; nenhuma chamada à IA foi feita", file=sys.stderr)
        return 2
    try:
        with sqlite3.connect(DB_PATH) as db:
            row = select_candidate(db, args.listing_key)
            result = prepare(db, row, api_key, model)
        if result:
            print(f"Rascunho pronto: {result}")
            print("Nenhuma publicação foi feita.")
        return 0
    except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
        print(f"Preparo interrompido: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
