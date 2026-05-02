import scrapy


class DealItem(scrapy.Item):
    deal_id = scrapy.Field()
    title = scrapy.Field()
    store = scrapy.Field()
    price = scrapy.Field()
    normal_price = scrapy.Field()
    deal_rating = scrapy.Field()
    url = scrapy.Field()
    scraped_at = scrapy.Field()
