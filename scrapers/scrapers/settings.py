BOT_NAME = 'scrapers'

SPIDER_MODULES = ['scrapers.spiders']
NEWSPIDER_MODULE = 'scrapers.spiders'

# Run sequentially: single concurrent request and gentle delay
CONCURRENT_REQUESTS = 1
DOWNLOAD_DELAY = 2
CONCURRENT_REQUESTS_PER_DOMAIN = 1

ROBOTSTXT_OBEY = True

USER_AGENT = 'judgement-cut-bot/1.0 (+https://example.com)'

# Encoding for feed exports
FEED_EXPORT_ENCODING = 'utf-8'

# Enable ingestion pipeline to post items to backend
ITEM_PIPELINES = {
	'scrapers.pipelines.ScraperIngestPipeline': 300,
}
