import sqlite3
import unittest
from unittest.mock import Mock, patch

import worker


class RefreshExistingTests(unittest.TestCase):
    def test_full_keyword_search_keeps_only_beauty_category(self):
        db = sqlite3.connect(":memory:")
        run = Mock()
        rows = [{"itemId": "1", "productCatIds": [100630]},
                {"itemId": "2", "productCatIds": [100123]}]
        with patch.object(worker, "load_local_env"), patch.dict(worker.os.environ, {"SHOPEE_APP_ID": "id", "SHOPEE_APP_SECRET": "secret"}), \
             patch.object(worker, "fetch_offers", return_value=rows), \
             patch.object(worker, "store_offers", return_value=(1, 0)) as store:
            count = worker.collect(db, run, "batom")
        self.assertEqual(count, 1)
        self.assertEqual([item["itemId"] for item in store.call_args.args[1]], ["1"])
        db.close()

    def test_keyword_fallback_only_stores_confirmed_beauty_products(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        run = Mock()
        ids = [
            {"itemId": "34", "shopId": "12", "productName": "Batom rosa"},
            {"itemId": "35", "shopId": "12", "productName": "Chaveiro de batom"},
            {"itemId": "36", "shopId": "12", "productName": "Batom cenográfico"},
        ]
        def detail(_db, key):
            return {"itemId": key.split(":")[-1], "shopId": "12", "productName": "Batom rosa",
                    "productCatIds": [100630] if key.endswith("34") else [100123]}
        with patch.object(worker, "load_local_env"), patch.dict(worker.os.environ, {"SHOPEE_APP_ID": "id", "SHOPEE_APP_SECRET": "secret"}), \
             patch.object(worker, "fetch_offers", side_effect=RuntimeError("10000")), \
             patch.object(worker, "fetch_offer_ids", return_value=ids), \
             patch.object(worker, "current_offer", side_effect=detail), \
             patch.object(worker, "store_offers", return_value=(1, 0)) as store:
            count = worker.collect(db, run, "batom")
        self.assertEqual(count, 1)
        self.assertEqual(len(store.call_args.args[1]), 1)
        self.assertEqual(store.call_args.args[1][0]["itemId"], "34")
        db.close()

    def test_refreshes_known_shopee_item_and_preserves_optional_fields(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE listings (
            listing_key TEXT, status TEXT, last_seen TEXT, sales INTEGER,
            product_link TEXT, commission_rate TEXT)""")
        db.execute("""INSERT INTO listings VALUES
            ('shopee:12:34','candidata','2026-11-15',25,'https://shopee.com.br/item','0.08'),
            ('mercadolivre:MLB1','candidata','2026-11-15',50,'https://mercadolivre.com.br/item',NULL)""")
        run = Mock()
        current = {"itemId": "34", "shopId": "12", "productName": "Creme"}
        with patch.object(worker, "current_offer", return_value=current), patch.object(worker, "store_offers", return_value=(1, 0)) as store:
            count = worker.refresh_existing(db, run)
        self.assertEqual(count, 1)
        stored = store.call_args.args[1][0]
        self.assertEqual(stored["productLink"], "https://shopee.com.br/item")
        self.assertEqual(stored["commissionRate"], "0.08")
        db.close()


if __name__ == "__main__":
    unittest.main()
