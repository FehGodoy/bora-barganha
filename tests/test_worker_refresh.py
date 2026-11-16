import sqlite3
import unittest
from unittest.mock import Mock, patch

import worker


class RefreshExistingTests(unittest.TestCase):
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
