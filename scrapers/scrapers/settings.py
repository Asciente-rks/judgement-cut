BOT_NAME = 'scrapers'

SPIDER_MODULES = ['scrapers.spiders']
NEWSPIDER_MODULE = 'scrapers.spiders'

CONCURRENT_REQUESTS = 1
DOWNLOAD_DELAY = 2
CONCURRENT_REQUESTS_PER_DOMAIN = 1

ROBOTSTXT_OBEY = False

USER_AGENT = (
    'Mozilla/5.0 (compatible; JudgementCut/1.0; '
    '+https://github.com/Asciente-rks/judgement-cut)'
)

HTTPERROR_ALLOW_ALL = True

FEED_EXPORT_ENCODING = 'utf-8'

ITEM_PIPELINES = {
    'scrapers.pipelines.ScraperIngestPipeline': 300,
}
