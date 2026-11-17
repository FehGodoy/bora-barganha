import unittest
from datetime import datetime, timedelta, timezone

from build_site import select_campaigns, select_offers


class SiteExportTests(unittest.TestCase):
    def test_campaigns_require_safe_link_image_and_valid_period(self):
        now = datetime(2026, 11, 16, 15, tzinfo=timezone.utc)
        base = {"offerName": "- - Beauty", "offerType": 2, "categoryId": 100630,
                "imageUrl": "https://cf.shopee.com.br/file/example",
                "offerLink": "https://s.shopee.com.br/example",
                "periodEndTime": int((now + timedelta(days=1)).timestamp())}
        stored = {"updated_at": now.isoformat(), "campaigns": [base,
                  {**base, "offerLink": "https://evil.example/campaign"},
                  {**base, "periodEndTime": 1}]}
        campaigns = select_campaigns(stored, now)
        self.assertEqual(len(campaigns), 1)
        self.assertEqual(campaigns[0]["title"], "Beleza na Shopee")
        self.assertEqual(select_campaigns(stored, now + timedelta(hours=25)), [])

    def test_only_recent_valid_unique_offers_are_public(self):
        now = datetime(2026, 11, 16, 15, tzinfo=timezone.utc)
        base = {
            "listing_key": "shopee:1:2",
            "source": "shopee",
            "canonical_key": "produto-1",
            "title": "Creme facial",
            "image_url": "https://img.example.com/creme.jpg",
            "offer_link": "https://s.shopee.com.br/exemplo",
            "price_min": "29.90",
            "sales": 10,
            "last_seen": (now - timedelta(minutes=20)).isoformat(),
            "status": "candidata",
        }
        rows = [
            base,
            {**base, "listing_key": "shopee:1:3"},
            {**base, "listing_key": "shopee:1:4", "canonical_key": "velho", "last_seen": (now - timedelta(hours=3)).isoformat()},
            {**base, "listing_key": "shopee:1:5", "canonical_key": "inseguro", "offer_link": "https://evil.example/"},
            {**base, "listing_key": "shopee:1:6", "canonical_key": "retido", "status": "retida"},
        ]
        offers = select_offers(rows, now)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["price"], "29.90")
        self.assertNotIn("sales", offers[0])

    def test_mercado_livre_uses_six_hour_window_and_meli_link(self):
        now = datetime(2026, 11, 16, 15, tzinfo=timezone.utc)
        row = {
            "listing_key": "mercadolivre:MLB1",
            "source": "mercadolivre",
            "canonical_key": "mlb1",
            "title": "Shampoo",
            "image_url": "https://http2.mlstatic.com/image.jpg",
            "offer_link": "https://meli.la/abc",
            "price_min": "45",
            "sales": 0,
            "last_seen": (now - timedelta(hours=5)).isoformat(),
            "status": "candidata",
        }
        self.assertEqual(len(select_offers([row], now)), 1)
        self.assertEqual(select_offers([{**row, "offer_link": "https://mercadolivre.com.br/item"}], now), [])


if __name__ == "__main__":
    unittest.main()
