import http.client
import json
import os
import threading
import unittest
from datetime import datetime, timezone
from http.server import HTTPServer
from unittest.mock import patch

from api import offers as offers_api


class OffersApiTests(unittest.TestCase):
    def request(self):
        server = HTTPServer(("127.0.0.1", 0), offers_api.handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/offers")
            response = connection.getresponse()
            result = response.status, dict(response.getheaders()), json.loads(response.read())
            connection.close()
            return result
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_missing_database_setting_returns_generic_error(self):
        with patch.dict(os.environ, {"SUPABASE_DB_URL": ""}):
            status, headers, body = self.request()
        self.assertEqual(status, 503)
        self.assertEqual(body, {"error": "Ofertas indisponíveis"})
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_success_exposes_only_public_offer_fields(self):
        now = datetime.now(timezone.utc)
        row = {
            "listing_key": "shopee:1:2",
            "source": "shopee",
            "canonical_key": "produto-1",
            "title": "Creme facial",
            "image_url": "https://img.example.com/creme.jpg",
            "offer_link": "https://s.shopee.com.br/exemplo",
            "price_min": "29.90",
            "sales": 10,
            "last_seen": now.isoformat(),
            "status": "candidata",
        }
        with patch.dict(os.environ, {"SUPABASE_DB_URL": "placeholder"}), patch.object(offers_api, "read_rows", return_value=[row]), patch.object(offers_api, "read_campaigns", return_value={}):
            status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(len(body["offers"]), 1)
        self.assertEqual(set(body["offers"][0]), {"id", "title", "source", "price", "original_price", "image", "url", "observed_at"})
        self.assertIn("s-maxage=300", headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
