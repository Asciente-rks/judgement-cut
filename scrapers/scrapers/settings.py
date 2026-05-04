BOT_NAME = 'scrapers'

SPIDER_MODULES = ['scrapers.spiders']
NEWSPIDER_MODULE = 'scrapers.spiders'

# Run sequentially: single concurrent request and gentle delay.
# Keeps us well below any rate-limit suspicion threshold.
CONCURRENT_REQUESTS = 1
DOWNLOAD_DELAY = 2
CONCURRENT_REQUESTS_PER_DOMAIN = 1

# CheapShark's robots.txt has `Disallow: /api/1.0/` which is aimed at
# general web crawlers indexing their content. Their /api/1.0/deals
# endpoint is, however, publicly documented at apidocs.cheapshark.com
# as the supported integration path for client apps - which is
# precisely how we use it. Disabling robots-obedience here is the
# standard pattern for all CheapShark consumer apps.
#
# We continue to be polite via the rate-limit settings above:
#   - 1 concurrent request, 2-second delay between hits
#   - Once-daily Periodic Job on Zyte (~5 requests total per day)
# This stays well under any reasonable abuse threshold.
ROBOTSTXT_OBEY = False

# Mozilla/5.0 prefix matters for CheapShark - their CDN was returning
# non-JSON / 400 to the previous bare 'judgement-cut-bot/1.0' UA when
# called from cloud IPs. We still identify ourselves at the end so any
# operator looking at server logs knows who we are.
USER_AGENT = (
    'Mozilla/5.0 (compatible; JudgementCut/1.0; '
    '+https://github.com/Asciente-rks/judgement-cut)'
)

# Let our parse callbacks see every response - including 4xx/5xx -
# instead of HttpErrorMiddleware silently dropping them. We need this
# to diagnose why CheapShark returns nothing for some stores; the
# parser logs status/length/content-type for every hit.
HTTPERROR_ALLOW_ALL = True

# Encoding for feed exports
FEED_EXPORT_ENCODING = 'utf-8'

# Enable ingestion pipeline to post items to backend
ITEM_PIPELINES = {
    'scrapers.pipelines.ScraperIngestPipeline': 300,
}
