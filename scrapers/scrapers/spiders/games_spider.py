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

    # CheapShark caps pageSize at 60 per request. We paginate per-store
    # because the user shops mostly on Steam, so Steam gets a much
    # deeper crawl while GOG / Humble stay shallow. Total ~428 deals
    # per run × once-daily schedule = ~12.8k Lambda invocations/month,
    # comfortably under the free-tier 1M cap.
    CHEAPSHARK_STORES = {
        "steam": {"id": "1", "pages": 5},   # 300 deals/day, deep coverage
        "gog": {"id": "7", "pages": 1},     # 60 deals/day, top deals only
        "humble": {"id": "11", "pages": 1}, # 60 deals/day, top deals only
    }

    # Epic's API ships an array of typed images per game. We pick the
    # first one matching any of these (in order) for the thumbnail.
    _EPIC_IMAGE_PRIORITY = (
        "OfferImageWide",
        "DieselStoreFrontWide",
        "Thumbnail",
        "OfferImageTall",
    )

    def start_requests(self):
        # CheapShark sales per platform, paginated. CheapShark uses
        # 0-indexed pageNumber and a cap of 60 results per page.
        for store_name, cfg in self.CHEAPSHARK_STORES.items():
            store_id = cfg["id"]
            pages = cfg["pages"]
            for page_num in range(pages):
                params = {
                    "storeID": store_id,
                    "pageSize": 60,
                    "pageNumber": page_num,
                    "onSale": 1,
                }
                url = f"{self.CHEAPSHARK_DEALS}?" + "&".join(
                    f"{k}={v}" for k, v in params.items()
                )
                yield scrapy.Request(
                    url,
                    callback=self.parse_cheapshark,
                    errback=self.errback_cheapshark,
                    cb_kwargs={
                        "store_name": store_name,
                        "store_id": store_id,
                        "page_num": page_num,
                    },
                    headers={"Accept": "application/json"},
                    # Don't let middlewares filter this on duplicate URL or
                    # cache - we always want a live hit so the diagnostic
                    # logs reflect the current state.
                    dont_filter=True,
                )

        # Epic free games (official store feed)
        yield scrapy.Request(
            self.EPIC_FREE,
            callback=self.parse_epic_free,
            headers={"Accept": "application/json"},
        )

    def errback_cheapshark(self, failure):
        """Surface network-level failures (DNS, TCP, TLS) that wouldn't
        produce a Response object at all. Without this, the spider just
        finishes silently with no clue what happened."""
        request = failure.request
        store = request.cb_kwargs.get("store_name", "?")
        self.logger.error(
            "CheapShark request failed for store=%s url=%s reason=%s",
            store,
            request.url,
            repr(failure.value),
        )

    def parse_cheapshark(self, response, store_name, store_id, page_num=0):
        # Diagnostic: log status, length and content-type so we can tell
        # whether Zyte's IPs are hitting a 200-empty / 403 / HTML wall.
        self.logger.info(
            "CheapShark store=%s page=%d status=%s length=%d content-type=%s",
            store_name,
            page_num,
            response.status,
            len(response.text),
            response.headers.get(b"Content-Type", b"").decode("utf-8", "ignore"),
        )

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            # Show what we actually got so we can tell the difference
            # between a CAPTCHA HTML page, a plaintext 'Access Denied',
            # or a partial JSON.
            self.logger.warning(
                "CheapShark store=%s returned non-JSON. First 300 chars: %s",
                store_name,
                response.text[:300],
            )
            return

        if not isinstance(data, list):
            self.logger.warning(
                "CheapShark store=%s returned non-list payload: %r",
                store_name,
                data,
            )
            return

        if not data:
            self.logger.warning(
                "CheapShark store=%s returned an empty array. The IP may "
                "be rate-limited or the storeID may not be valid for this "
                "region.",
                store_name,
            )

        for deal in data:
            item = DealItem()
            deal_id = deal.get("dealID")
            item["deal_id"] = deal_id or f"{store_name}-{int(datetime.utcnow().timestamp())}"
            item["title"] = deal.get("title") or ""
            item["store"] = store_id
            item["price"] = self._to_float(deal.get("salePrice"))
            item["normal_price"] = self._to_float(deal.get("normalPrice"))
            item["deal_rating"] = self._to_float(deal.get("dealRating"))
            # CheapShark already returns the cover-art URL on /deals; we
            # just preserve it. No extra HTTP request needed.
            item["thumbnail_url"] = deal.get("thumb") or None
            # CheapShark also returns `steamAppID` for Steam deals -
            # the backend uses this to fetch native PHP pricing from
            # store.steampowered.com instead of guessing via USD->PHP FX.
            item["steam_app_id"] = deal.get("steamAppID") or None
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
            # Epic ships a typed image array; pick a wide cover if available.
            item["thumbnail_url"] = self._pick_epic_image(game.get("keyImages"))
            item["scraped_at"] = datetime.utcnow().isoformat()
            yield item

    @classmethod
    def _pick_epic_image(cls, key_images):
        if not isinstance(key_images, list):
            return None
        by_type = {}
        for img in key_images:
            if not isinstance(img, dict):
                continue
            t = img.get("type")
            url = img.get("url")
            if t and url:
                by_type[t] = url
        for preferred in cls._EPIC_IMAGE_PRIORITY:
            if preferred in by_type:
                return by_type[preferred]
        # No preferred type found - return whatever's there, if anything.
        return next(iter(by_type.values()), None)

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
