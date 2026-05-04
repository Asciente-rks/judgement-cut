import json
from datetime import datetime

import scrapy

from ..items import DealItem


class GamesSpider(scrapy.Spider):
    name = "games"

    CHEAPSHARK_DEALS = "https://www.cheapshark.com/api/1.0/deals"
    EPIC_FREE = (
        "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
        "?locale=en-US&country=US&allowCountries=US"
    )

    CHEAPSHARK_STORES = {
        "steam": "1",
        "gog": "7",
        "humble": "11",
    }

    def start_requests(self):
        # CheapShark sales per platform
        for store_name, store_id in self.CHEAPSHARK_STORES.items():
            params = {
                "storeID": store_id,
                "pageSize": 60,
                "onSale": 1,
            }
            url = f"{self.CHEAPSHARK_DEALS}?" + "&".join(f"{k}={v}" for k, v in params.items())
            yield scrapy.Request(
                url,
                callback=self.parse_cheapshark,
                cb_kwargs={"store_name": store_name, "store_id": store_id},
                headers={"Accept": "application/json"},
            )

        # Epic free games (official store feed)
        yield scrapy.Request(
            self.EPIC_FREE,
            callback=self.parse_epic_free,
            headers={"Accept": "application/json"},
        )

    def parse_cheapshark(self, response, store_name, store_id):
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning("CheapShark response was not valid JSON")
            return

        if not isinstance(data, list):
            return

        for deal in data:
            item = DealItem()
            deal_id = deal.get("dealID")
            item["deal_id"] = deal_id or f"{store_name}-{int(datetime.utcnow().timestamp())}"
            item["title"] = deal.get("title") or ""
            item["store"] = store_id
            item["price"] = self._to_float(deal.get("salePrice"))
            item["normal_price"] = self._to_float(deal.get("normalPrice"))
            item["deal_rating"] = self._to_float(deal.get("dealRating"))
            if deal_id:
                item["url"] = f"https://www.cheapshark.com/redirect?dealID={deal_id}"
            else:
                item["url"] = deal.get("dealID") or ""
            item["scraped_at"] = datetime.utcnow().isoformat()
            yield item

    def parse_epic_free(self, response):
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            self.logger.warning("Epic free games response was not valid JSON")
            return

        elements = (
            data.get("data", {})
            .get("Catalog", {})
            .get("searchStore", {})
            .get("elements", [])
        )

        for game in elements:
            promotions = game.get("promotions") or {}
            current = promotions.get("promotionalOffers") or []
            offers = current[0].get("promotionalOffers", []) if current else []
            if not offers:
                continue

            price = self._extract_epic_price(game)
            if price is None:
                continue

            normal_price, discount_price = price
            if discount_price != 0:
                continue

            slug = game.get("productSlug") or game.get("urlSlug") or ""
            url = f"https://store.epicgames.com/en-US/p/{slug}" if slug else ""

            item = DealItem()
            item["deal_id"] = f"epic-{game.get('id')}" if game.get("id") else f"epic-{slug}"
            item["title"] = game.get("title") or ""
            item["store"] = "25"
            item["price"] = 0.0
            item["normal_price"] = normal_price
            item["deal_rating"] = None
            item["url"] = url
            item["scraped_at"] = datetime.utcnow().isoformat()
            yield item

    @staticmethod
    def _to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_epic_price(game):
        total = (game.get("price") or {}).get("totalPrice") or {}
        original = total.get("originalPrice")
        discount = total.get("discountPrice")
        if original is None or discount is None:
            return None
        try:
            return (float(original) / 100.0, float(discount) / 100.0)
        except (TypeError, ValueError):
            return None
