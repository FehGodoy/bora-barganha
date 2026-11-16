"""Endpoint público da vitrine; nunca devolve credenciais ou dados internos."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_site import read_rows, select_offers  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not os.environ.get("SUPABASE_DB_URL", "").strip():
            self._respond(503, {"error": "Ofertas indisponíveis"}, "no-store")
            return
        try:
            now = datetime.now(timezone.utc)
            payload = {"updated_at": now.isoformat(), "offers": select_offers(read_rows(), now)}
        except Exception:
            self._respond(503, {"error": "Ofertas indisponíveis"}, "no-store")
            return
        self._respond(200, payload, "public, s-maxage=300, stale-while-revalidate=300")

    def _respond(self, status: int, payload: dict, cache_control: str) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)
