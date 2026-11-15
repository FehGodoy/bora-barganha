"""Envia uma oferta ao único grupo permitido, com travas e histórico local.

Requer --send e BORA_OFFER_SEND_ENABLED=true. Um envio incerto não é repetido.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collect_shopee import DB_PATH, open_db
from evolution_publisher import GROUP_JID, list_groups, request_json, settings
from render_offer import OUT_DIR, download_image, render
from revalidate_shopee import current_offer, matches_draft

MAX_PER_DAY = 3
MIN_GAP = timedelta(hours=3)


def read_draft(path: Path) -> dict:
    resolved = path.resolve()
    if resolved.parent != OUT_DIR.resolve() or resolved.suffix != ".json":
        raise ValueError("O rascunho deve ser um JSON diretamente em drafts/")
    draft = json.loads(resolved.read_text(encoding="utf-8"))
    review = draft.get("image_review") or {}
    if (draft.get("status") != "draft_only" or not review.get("matches_product") or
            review.get("has_offer_text") or not review.get("legible") or not draft.get("image_sha256")):
        raise ValueError("Rascunho sem aprovação completa da imagem")
    if not draft.get("whatsapp_text") or draft.get("whatsapp_text", "").count(draft.get("offer_link", "")) != 1:
        raise ValueError("Mensagem ou link de afiliado inconsistentes")
    return draft


def validate_group(base: str, instance: str, api_key: str, jid: str) -> None:
    if not GROUP_JID.fullmatch(jid):
        raise ValueError("BORA_GROUP_JID ausente ou inválido")
    groups = [item for item in list_groups(base, instance, api_key) if item.get("id") == jid]
    if len(groups) != 1 or "bora barganha" not in str(groups[0].get("subject") or "").casefold():
        raise ValueError("O destino não foi confirmado como grupo Bora Barganha")


def ensure_tables(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS publication_jobs (
        draft_id TEXT PRIMARY KEY, listing_key TEXT NOT NULL, canonical_key TEXT NOT NULL, channel TEXT NOT NULL,
        status TEXT NOT NULL, reserved_at TEXT NOT NULL, external_id TEXT)""")
    columns = {row[1] for row in db.execute("PRAGMA table_info(publication_jobs)")}
    if "canonical_key" not in columns:
        db.execute("ALTER TABLE publication_jobs ADD COLUMN canonical_key TEXT")
        db.execute("""UPDATE publication_jobs SET canonical_key=(
            SELECT canonical_key FROM listings WHERE listings.listing_key=publication_jobs.listing_key
        ) WHERE canonical_key IS NULL""")
    db.commit()


def draft_id(draft: dict) -> str:
    identity = "|".join(str(draft[key]) for key in ("listing_key", "observed_at", "price_min", "offer_link"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def reserve(db: sqlite3.Connection, draft: dict) -> str:
    identity = draft_id(draft)
    now = datetime.now(timezone.utc)
    db.execute("BEGIN IMMEDIATE")
    try:
        prior_job = db.execute("SELECT status FROM publication_jobs WHERE draft_id=?", (identity,)).fetchone()
        if prior_job:
            raise RuntimeError(f"Rascunho já tentado ({prior_job[0]}); não repetir automaticamente")
        pending_product = db.execute("SELECT 1 FROM publication_jobs WHERE canonical_key=? AND channel='whatsapp' AND status='reserved' LIMIT 1",
                                     (draft["canonical_key"],)).fetchone()
        if pending_product:
            raise RuntimeError("Há uma tentativa pendente para este produto; verificar antes de repetir")
        cutoff = (now - timedelta(days=7)).isoformat()
        prior_product = db.execute("SELECT 1 FROM publications WHERE canonical_key=? AND channel='whatsapp' AND published_at>? LIMIT 1",
                                   (draft["canonical_key"], cutoff)).fetchone()
        if prior_product:
            raise RuntimeError("Produto publicado no WhatsApp nos últimos sete dias")
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        count = db.execute("SELECT COUNT(*) FROM publications WHERE channel='whatsapp' AND published_at>=?", (day_start,)).fetchone()[0]
        count += db.execute("SELECT COUNT(*) FROM publication_jobs WHERE channel='whatsapp' AND status='reserved' AND reserved_at>=?", (day_start,)).fetchone()[0]
        if count >= MAX_PER_DAY:
            raise RuntimeError("Limite diário de ofertas no WhatsApp atingido")
        latest = db.execute("""SELECT MAX(moment) FROM (
            SELECT published_at AS moment FROM publications WHERE channel='whatsapp'
            UNION ALL SELECT reserved_at AS moment FROM publication_jobs WHERE channel='whatsapp' AND status='reserved'
        )""").fetchone()[0]
        if latest and datetime.fromisoformat(latest) > now - MIN_GAP:
            raise RuntimeError("Intervalo mínimo de três horas entre ofertas não cumprido")
        db.execute("INSERT INTO publication_jobs(draft_id,listing_key,canonical_key,channel,status,reserved_at) VALUES(?,?,?,?,?,?)",
                   (identity, draft["listing_key"], draft["canonical_key"], "whatsapp", "reserved", now.isoformat()))
        db.commit()
        return identity
    except Exception:
        db.rollback()
        raise


def confirm(db: sqlite3.Connection, draft: dict, identity: str, external_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("INSERT INTO publications(canonical_key,channel,published_at,price,external_id) VALUES(?,?,?,?,?)",
                   (draft["canonical_key"], "whatsapp", now, str(draft["price_min"]), external_id))
        db.execute("UPDATE publication_jobs SET status='sent',external_id=? WHERE draft_id=? AND status='reserved'",
                   (external_id, identity))
        db.commit()
    except Exception:
        db.rollback()
        raise


def send_media(base: str, instance: str, api_key: str, jid: str, image_path: Path, caption: str) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    response = request_json(base, instance, api_key, "POST", "/message/sendMedia", {
        "number": jid, "mediatype": "image", "mimetype": "image/png", "fileName": image_path.name,
        "media": encoded, "caption": caption,
    })
    if not isinstance(response, dict) or not isinstance(response.get("key"), dict):
        raise RuntimeError("Evolution não confirmou o envio da mídia; verificar manualmente antes de qualquer nova tentativa")
    key = response["key"]
    if key.get("remoteJid") != jid or not key.get("id"):
        raise RuntimeError("Resposta da Evolution sem confirmação inequívoca do grupo")
    return str(key["id"])


def publish(path: Path, send: bool) -> None:
    draft = read_draft(path)
    base, instance, api_key, jid = settings()
    validate_group(base, instance, api_key, jid)
    with open_db(DB_PATH) as db:
        ensure_tables(db)
        item = current_offer(db, draft["listing_key"])
        matches_draft(draft, item)
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM listings WHERE listing_key=?", (draft["listing_key"],)).fetchone()
        if not row or not str(row["status"]).startswith("candidata") or row["image_url"] != item.get("imageUrl"):
            raise RuntimeError("Anúncio ou imagem mudou após o preparo")
        image = download_image(row["image_url"])
        if hashlib.sha256(image.tobytes()).hexdigest() != draft["image_sha256"]:
            raise RuntimeError("Conteúdo da imagem mudou após a análise")
        if not send:
            print("Prévia: grupo, preço, link e imagem confirmados. Nenhuma mensagem foi enviada.")
            return
        if os.environ.get("BORA_OFFER_SEND_ENABLED", "").strip().lower() != "true":
            raise RuntimeError("Ofertas desativadas: BORA_OFFER_SEND_ENABLED não é true")
        final_art = render(row, image, draft.get("art_title"), final=True)
        identity = reserve(db, draft)
        try:
            external_id = send_media(base, instance, api_key, jid, final_art, draft["whatsapp_text"])
        except Exception:
            # A resposta pode ter se perdido após o WhatsApp receber a mídia.
            # A reserva permanece e bloqueia novas tentativas automáticas.
            raise
        confirm(db, draft, identity, external_id)
        print(f"Oferta publicada no grupo Bora Barganha; ID: {external_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prévia ou envio controlado de oferta ao grupo Bora Barganha")
    parser.add_argument("draft", type=Path)
    parser.add_argument("--send", action="store_true", help="Exige também BORA_OFFER_SEND_ENABLED=true")
    args = parser.parse_args()
    try:
        publish(args.draft, args.send)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, sqlite3.Error) as exc:
        print(f"Publicação bloqueada: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
