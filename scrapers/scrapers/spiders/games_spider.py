import scrapy
from datetime import datetime
from ..items import DealItem


class GamesSpider(scrapy.Spider):
    name = 'games'
    # Platforms mapped to example seed URLs. Replace with real listing/search URLs per platform.
    PLATFORM_SEEDS = {
        'steam': 'https://store.steampowered.com/search/?specials=1',
        'epic': 'https://www.epicgames.com/store/en-US/browse?sortBy=releaseDate&sortDir=DESC',
        'gog': 'https://www.gog.com/games?prices=discounted',
    }

    def start_requests(self):
        # Iterate platforms sequentially; Scrapy will process requests in order with CONCURRENT_REQUESTS=1
        for platform, url in self.PLATFORM_SEEDS.items():
            yield scrapy.Request(url, callback=self.parse_platform, cb_kwargs={'platform': platform})

    def parse_platform(self, response, platform):
        # Example parsing: this is a placeholder. Implement selectors per platform.
        # Here we yield a single item showing the page title as a smoke-test.
        title = response.xpath('//title/text()').get() or ''
        item = DealItem()
        item['deal_id'] = f"{platform}-{int(datetime.utcnow().timestamp())}"
        item['title'] = title.strip()
        item['store'] = platform
        item['price'] = None
        item['normal_price'] = None
        item['deal_rating'] = None
        item['url'] = response.url
        item['scraped_at'] = datetime.utcnow().isoformat()
        yield item
