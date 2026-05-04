import scrapy


class DealItem(scrapy.Item):
    deal_id = scrapy.Field()
    title = scrapy.Field()
    store = scrapy.Field()
    price = scrapy.Field()
    normal_price = scrapy.Field()
    deal_rating = scrapy.Field()
    url = scrapy.Field()
    # CheapShark / Epic provide a thumbnail URL in their existing API
    # response. We just forward it - no extra scraping or HTML parsing.
    thumbnail_url = scrapy.Field()
    # Steam's app ID for Steam deals (CheapShark `steamAppID`). The
    # backend uses it to call store.steampowered.com for native regional
    # PHP pricing instead of naive USD->PHP conversion.
    steam_app_id = scrapy.Field()
    scraped_at = scrapy.Field()
