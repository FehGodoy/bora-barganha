"""Ciclo contínuo Shopee -> WhatsApp: coleta, seleção, análise de imagem, arte, revalidação e envio.

Cada execução é uma rodada curta (adequada a agendador/cron). Todas as etapas ficam
registradas em `worker_runs` e `worker_steps`. Travas preservadas:
- envio real só com `--send` E `BORA_OFFER_SEND_ENABLED=true` (verificado em publish_whatsapp);
- limite diário, intervalo de 3h e repetição de 7 dias (reserve() de publish_whatsapp);
- qualquer job `reserved` (envio incerto) pausa o worker até reconciliação manual;
- pausa de emergência: arquivo `PAUSE` na raiz ou `BORA_WORKER_PAUSED=true`.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collect_shopee import DB_PATH, fetch_offers, open_db, store_offers
from mercadolivre_queue import ingest as ingest_ml
from prepare_offer import load_openai_env, prepare, select_candidate
from publish_whatsapp import MAX_PER_DAY, MIN_GAP, ensure_tables, publish
from shopee_probe import load_local_env

ROOT = Path(__file__).parent
PAUSE_FILE = ROOT / "PAUSE"
LOCK_FILE = ROOT / "data" / "worker.lock"
LOCK_STALE = timedelta(minutes=30)
KEYWORDS = [
    "maquiagem", "skincare", "protetor solar", "serum facial", "hidratante facial",
    "base liquida", "corretivo", "mascara de cilios", "batom", "shampoo",
    "condicionador", "mascara capilar", "perfume feminino", "body splash", "esmalte",
    "gloss labial", "delineador", "paleta de sombras", "po compacto", "blush",
    "agua micelar", "sabonete facial", "vitamina c facial", "acido hialuronico", "creme para olhos",
    "oleo capilar", "leave in", "creme de pentear", "hidratante corporal", "desodorante",
    "perfume masculino", "esponja de maquiagem", "pinceis de maquiagem", "secador de cabelo", "prancha de cabelo",
]
COLLECT_EVERY = timedelta(minutes=50)
MAX_PREPARE_ATTEMPTS = 3


def now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_worker_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS worker_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
      mode TEXT NOT NULL, outcome TEXT, detail TEXT);
    CREATE TABLE IF NOT EXISTS worker_steps (
      id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, at TEXT NOT NULL,
      step TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT);
    """)
    ensure_tables(db)
    db.commit()


class Run:
    def __init__(self, db: sqlite3.Connection, mode: str):
        self.db = db
        self.id = db.execute("INSERT INTO worker_runs(started_at,mode) VALUES(?,?) RETURNING id", (now().isoformat(), mode)).fetchone()[0]
        db.commit()

    def step(self, name: str, ok: bool, detail: str = "") -> None:
        self.db.execute("INSERT INTO worker_steps(run_id,at,step,ok,detail) VALUES(?,?,?,?,?)",
                        (self.id, now().isoformat(), name, bool(ok), detail[:1000]))
        self.db.commit()
        print(f"[{'ok' if ok else 'xx'}] {name}: {detail}", flush=True)

    def finish(self, outcome: str, detail: str = "") -> None:
        self.db.execute("UPDATE worker_runs SET finished_at=?,outcome=?,detail=? WHERE id=?",
                        (now().isoformat(), outcome, detail[:1000], self.id))
        self.db.commit()
        print(f"Rodada {self.id}: {outcome} {detail}", flush=True)


def acquire_lock() -> bool:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        age = now() - datetime.fromtimestamp(LOCK_FILE.stat().st_mtime, timezone.utc)
        if age < LOCK_STALE:
            return False
        LOCK_FILE.unlink()
    try:
        with open(LOCK_FILE, "x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False


def paused() -> str | None:
    if PAUSE_FILE.exists():
        return "arquivo PAUSE presente"
    if os.environ.get("BORA_WORKER_PAUSED", "").strip().lower() == "true":
        return "BORA_WORKER_PAUSED=true"
    return None


def send_capacity(db: sqlite3.Connection) -> str | None:
    """Pré-checagem somente leitura; reserve() continua sendo a trava definitiva."""
    uncertain = db.execute("SELECT COUNT(*) FROM publication_jobs WHERE status='reserved'").fetchone()[0]
    if uncertain:
        return f"{uncertain} envio(s) incerto(s) aguardando reconciliação manual"
    current = now()
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    sent_today = db.execute("SELECT COUNT(*) FROM publications WHERE channel='whatsapp' AND published_at>=?",
                            (day_start,)).fetchone()[0]
    if sent_today >= MAX_PER_DAY:
        return "limite diário atingido"
    latest = db.execute("SELECT MAX(published_at) FROM publications WHERE channel='whatsapp'").fetchone()[0]
    if latest and datetime.fromisoformat(latest) > current - MIN_GAP:
        return f"intervalo mínimo de {int(MIN_GAP.total_seconds() // 60)} min ainda não cumprido"
    return None


def next_keyword(db: sqlite3.Connection) -> str:
    row = db.execute("SELECT value FROM state WHERE key='worker_keyword_index'").fetchone()
    index = (int(row[0]) + 1) % len(KEYWORDS) if row else 0
    db.execute("INSERT INTO state(key,value) VALUES('worker_keyword_index',?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(index),))
    db.commit()
    return KEYWORDS[index]


def collect(db: sqlite3.Connection, run: Run, keyword: str) -> None:
    load_local_env(ROOT / ".env.local")
    app_id = os.environ.get("SHOPEE_APP_ID", "").strip()
    secret = os.environ.get("SHOPEE_APP_SECRET", "").strip()
    if not app_id or not secret:
        raise RuntimeError("Credenciais Shopee ausentes")
    # A Shopee devolve "10000 System Error" de forma intermitente (recusa instantânea do lado deles,
    # sem relação com campos ou palavra-chave). Tenta até 4 vezes, trocando o termo, com o intervalo de 31 s.
    attempts = 4
    for attempt in range(attempts):
        try:
            offers = fetch_offers(db, app_id, secret, keyword)
            break
        except RuntimeError as error:
            if attempt < attempts - 1 and "10000" in str(error):
                run.step("coleta", False, f"erro 10000 em '{keyword}', tentando outro termo")
                keyword = next_keyword(db)
                continue
            raise
    candidates, held = store_offers(db, offers)
    run.step("coleta", True, f"'{keyword}': {len(offers)} anúncios, {candidates} candidatos, {held} retidos")


def run_cycle(send: bool, skip_collect: bool) -> int:
    with open_db(DB_PATH) as db:
        ensure_worker_tables(db)
        run = Run(db, "send" if send else "dry-run")
        try:
            reason = paused()
            if reason:
                run.finish("paused", reason)
                return 0
            blocked = send_capacity(db)
            if blocked and "incerto" in blocked:
                run.finish("blocked", blocked)
                return 3

            last = db.execute("SELECT value FROM state WHERE key='worker_last_collect'").fetchone()
            if last and now() - datetime.fromisoformat(last[0]) < COLLECT_EVERY:
                skip_collect = True
            if not skip_collect:
                keyword = next_keyword(db)
                try:
                    collect(db, run, keyword)
                    db.execute("INSERT INTO state(key,value) VALUES('worker_last_collect',?) "
                               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now().isoformat(),))
                    db.commit()
                except RuntimeError as error:
                    run.step("coleta", False, str(error))  # segue com candidatas já coletadas (<2h)

            try:
                imported, held = ingest_ml(db)
                if imported or held:
                    run.step("fila_mercadolivre", True, f"{imported} importadas, {held} retidas")
            except Exception as error:  # noqa: BLE001
                run.step("fila_mercadolivre", False, str(error))

            if blocked and send:
                run.finish("collected_only", blocked)
                return 0

            load_openai_env()
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY ausente")

            for attempt in range(1, MAX_PREPARE_ATTEMPTS + 1):
                try:
                    row = select_candidate(db, None)
                except RuntimeError as error:
                    run.finish("no_candidate", str(error))
                    return 0
                run.step("selecao", True, f"{row['listing_key']} | {row['title'][:60]} | R$ {row['price_min']}")
                draft_path = prepare(db, row, api_key, model)
                if not draft_path:
                    run.step("imagem", False, f"{row['listing_key']} retida pela análise de imagem")
                    continue
                run.step("rascunho", True, draft_path.name)
                try:
                    publish(draft_path, send)
                except (RuntimeError, ValueError, KeyError, OSError) as error:
                    message = str(error)
                    run.step("publicacao", False, message)
                    if any(k in message for k in ("mudou", "encerrada", "não encontrado")):
                        db.execute("UPDATE listings SET status='retida',hold_reason=? WHERE listing_key=?",
                                   ("revalidação: " + message[:200], row["listing_key"]))
                        db.commit()
                        continue
                    run.finish("publish_blocked", message)
                    return 1
                run.step("publicacao", True, "enviado" if send else "prévia confirmada, nada enviado")
                run.finish("sent" if send else "dry_run_ok", row["listing_key"])
                return 0
            run.finish("no_valid_offer", f"{MAX_PREPARE_ATTEMPTS} candidatas reprovadas")
            return 0
        except Exception as error:  # noqa: BLE001 - registrar e sair sem repetir
            run.step("erro", False, f"{type(error).__name__}: {error}")
            traceback.print_exc()
            run.finish("error", str(error))
            return 1


def status() -> int:
    with open_db(DB_PATH) as db:
        ensure_worker_tables(db)
        print("Bloqueio de envio:", send_capacity(db) or "nenhum")
        print("Pausa:", paused() or "não")
        for r in db.execute("SELECT id,started_at,mode,outcome,detail FROM worker_runs ORDER BY id DESC LIMIT 10"):
            print(f"#{r[0]} {r[1][:19]} {r[2]} {r[3]} {r[4] or ''}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Uma rodada do ciclo Shopee -> WhatsApp")
    parser.add_argument("--send", action="store_true", help="Envia de verdade (exige BORA_OFFER_SEND_ENABLED=true)")
    parser.add_argument("--skip-collect", action="store_true", help="Usa candidatas já coletadas")
    parser.add_argument("--status", action="store_true", help="Mostra últimas rodadas e bloqueios")
    args = parser.parse_args()
    if args.status:
        return status()
    if not acquire_lock():
        print("Outra rodada está em execução; saindo.", file=sys.stderr)
        return 4
    try:
        return run_cycle(args.send, args.skip_collect)
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
