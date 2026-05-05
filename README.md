# Judgement Cut

> A daily-refreshing dashboard of game deals across **Steam**, **GOG**, **Humble**, and **Epic**, with **native Steam Philippine peso pricing** so the numbers match what you actually pay.

Originally built for personal use — designed to cost **$0/month forever** on free tiers across the entire stack.

---

## What it does

- **Crawls 4 storefronts daily** at 02:00 PHT — Steam (8 pages, ~480 deals filtered to `steamRating ≥ 70`), GOG (top 60), Humble (top 60), and Epic (free games only)
- **Native Steam PH pricing** — queries `store.steampowered.com/api/appdetails?cc=PH` directly so prices match Steam's storefront exactly, not a USD × FX approximation
- **Title-search fallback** — if CheapShark doesn't include `steamAppID` for a deal, we search Steam by title to recover it
- **Honest pricing badges** — green "Steam PH price" for accurate native PHP, amber "USD est." when we have to fall back to FX conversion
- **Price history** per deal with all-time-low tracker
- **Admin panel** with platform toggles, user management, and scraper monitor heartbeat
- **Lambda-frugal** — batched ingest cuts invocations to ~900/month, well under the 1M free tier

---

## Architecture

```
┌────────────────┐       ┌─────────────────┐
│ GitHub Actions │ cron  │ Zyte Scrapy     │  scrapes
│ run-spider     │──────►│ Cloud           │──────────┐
│ daily          │       │ (1 spider)      │          │
└────────────────┘       └─────────────────┘          ▼
                                              ┌──────────────┐
                                              │  CheapShark  │ Steam/GOG/Humble (USD)
                                              │  Epic Store  │ Free games feed
                                              └──────┬───────┘
                                                     │
                                              POST /internal/ingest
                                              (batched 25 items)
                                                     │
                                                     ▼
┌────────────────┐    ┌──────────────────────────────────────────┐
│ Cloudflare R2  │◄───│      AWS Lambda (FastAPI + Mangum)       │
│ thumbnail      │    │  ap-southeast-1, 256 MB, 30s, Function   │
│ mirror         │    │  URL (no API Gateway, no auth)            │
└────────────────┘    │                                          │
                      │  • parallel Steam regional API           │
                      │    enrichment (5-way semaphore)          │
                      │  • title-search fallback for missing     │
                      │    steamAppIDs                           │
                      │  • 3-phase finalize: re-enrich,          │
                      │    mark stale, delete inactive           │
                      └──────────┬───────────────────────────────┘
                                 │
                                 ▼
                      ┌───────────────────────┐
                      │  TiDB Cloud           │  ← MySQL-compatible serverless
                      │  (5GB free tier)      │     SSL-enforced from Lambda
                      └───────────────────────┘
                                 ▲
                                 │ JWT-protected reads
                      ┌──────────┴────────────┐
                      │  React + Vite + TW    │  ← SPA, single App.jsx
                      │  Frontend (static)    │     hosted separately
                      └───────────────────────┘
```

---

## Tech stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Spider** | Scrapy on Zyte Scrapy Cloud | Free tier, rotating IPs, 1 free spider unit |
| **Backend** | FastAPI + Mangum on AWS Lambda | Free tier 1M invocations/month, ap-southeast-1 region |
| **Database** | TiDB Cloud (Serverless) | 5GB free, MySQL-compatible, no cold start |
| **Object storage** | Cloudflare R2 | 10GB free, no egress fees |
| **Frontend** | React 18 + Vite 5 + Tailwind 3 | Single SPA, fast dev loop |
| **Scheduler** | GitHub Actions cron | Free for public repos, ~1 min/month usage |
| **Deal source** | CheapShark API (USD) | Free, no key required |
| **Native PHP** | Steam storefront API (`cc=PH`) | Free, no key required |
| **FX rates** | open.er-api.com (24h cached) | Free, no key required |

---

## Database schema

Five tables on TiDB. The interesting ones:

### `featured_deals`
Active deals shown on the dashboard. Wiped down to the latest crawl on every spider run via the finalize step.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT (PK) | autoincrement |
| `deal_id` | VARCHAR(100) UNIQUE | CheapShark dealID, primary lookup key |
| `title` | VARCHAR(300) | game name |
| `store_id` | VARCHAR(50) | "1"=Steam, "7"=GOG, "11"=Humble, "25"=Epic |
| `price` / `normal_price` | FLOAT | USD prices from CheapShark |
| `price_php` / `normal_price_php` | DOUBLE | **native** Steam PH prices (when available) |
| `regional_price_at` | DATETIME | when PHP pricing was last fetched |
| `steam_app_id` | VARCHAR(50) | Steam appID, recovered via title-search if CheapShark didn't provide |
| `thumbnail_url` | VARCHAR(500) | CheapShark cover-art URL (R2 mirror is lazy) |
| `deal_rating` | FLOAT | CheapShark's deal score, used for sorting |
| `last_seen_at` | DATETIME | NOW() on every ingest |
| `is_active` | TINYINT(1) | flipped to 0 by finalize for stale rows, then deleted |
| `synced_at` | DATETIME | last upsert time |

**Unique index on `deal_id`** is what makes `INSERT … ON DUPLICATE KEY UPDATE` work.

### `price_history`
Every observed price for every deal. Survives `featured_deals` deletions so historical lookups keep working.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT (PK) | autoincrement |
| `deal_id` | VARCHAR(100) | foreign reference (no FK constraint) |
| `price` | FLOAT | USD price at time of observation |
| `recorded_at` | DATETIME | observation time |

### `crawler_settings`
Key-value heartbeat keys read by the admin monitor:
- `_last_ingest_at` / `_last_ingest_count`
- `_last_finalize_at` / `_last_finalize_deactivated` / `_last_finalize_deleted`
- `_last_finalize_reenriched` (e.g. `"42/50"` = 42 successes out of 50 retry attempts)
- `_fx_rate_*` (cached USD→PHP, refreshed every 24h)

### `users`
Username + bcrypt hash. Two seeded accounts:
- `admin` / `adminpass` — full admin access
- `user` / `userpass` — read-only

### `platforms`
Toggle which CheapShark stores show up on the search page (`is_enabled`). Doesn't affect the daily crawl.

---

## How pricing accuracy works

For a typical Steam deal, the data flow is:

1. **CheapShark gives us USD price + `steamAppID`** during the crawl
2. **We call Steam's `appdetails?cc=PH`** in parallel (5-way semaphore) for the native PHP price
3. **If Steam returns valid PHP** → store as `price_php` / `normal_price_php`. Frontend shows it with green "Steam PH price" badge
4. **If Steam fails** (timeout, 5xx, success=false) → we retry up to 3 times with exponential backoff
5. **If still no PHP price** → leave `price_php = NULL`. Frontend falls back to USD × FX with amber **"USD est."** badge

For Steam deals **without `steamAppID`** (a few % of CheapShark's catalog):
1. Title-search Steam's `storesearch` API
2. If top result's name has substring relationship with our title, use its `appid`
3. Persist via `update_steam_app_id` so next run skips the search
4. Continue with the regional API path above

The end-of-crawl **finalize endpoint** does three things in order:

```
Phase 1 → Re-enrich up to 50 active deals still missing price_php
Phase 2 → Mark deals not seen this run as is_active = 0
Phase 3 → DELETE all is_active = 0 rows so the table = latest crawl
```

Phase 3 is what keeps TiDB row count = Zyte run total = dashboard "live deals" count.

---

## Repository structure

```
.
├── README.md                                    ← you are here
├── .github/workflows/
│   ├── deploy-lambda.yml                        ← auto-deploys backend on push
│   ├── deploy-spider.yml                        ← auto-deploys spider on scrapers/** push
│   └── run-spider-daily.yml                     ← daily 02:00 PHT cron
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   └── src/
│       ├── handler.py                           ← Mangum Lambda entrypoint
│       └── app/
│           ├── main.py                          ← FastAPI app + router includes
│           ├── db.py                            ← TiDB schema + idempotent migrations
│           ├── api/
│           │   ├── auth.py                      ← /auth/login (JWT)
│           │   ├── internal.py                  ← /ingest, /ingest/finalize (X-Scraper-Secret)
│           │   ├── deals.py                     ← legacy CheapShark proxy
│           │   └── v1/
│           │       ├── user_routes.py           ← /v1/me, /v1/deals/featured, /v1/deals/{id}/history
│           │       └── admin_routes.py          ← /v1/admin/platforms, users, monitor
│           ├── core/
│           │   ├── config.py                    ← env-var loading
│           │   └── services/
│           │       ├── steam_pricing.py         ← Steam appdetails + storesearch
│           │       ├── deals_service.py         ← featured deals + live search
│           │       └── cheapshark.py            ← live CheapShark proxy
│           └── data/
│               ├── repositories/
│               │   ├── deals_repo.py            ← upserts, finalize ops
│               │   ├── price_history_repo.py
│               │   ├── crawler_repo.py          ← heartbeat keys
│               │   └── platforms_repo.py
│               └── storage.py                   ← R2 client
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.jsx                              ← single-file React SPA
│       ├── lib/api.js                           ← fetch wrappers
│       └── assets/JudgementCut_Logo.png
└── scrapers/
    ├── scrapinghub.yml                          ← Zyte project ID (860207)
    ├── scrapy.cfg
    ├── requirements.txt
    └── scrapers/
        ├── settings.py
        ├── items.py                             ← DealItem schema
        ├── pipelines.py                         ← batched ingest + finalize POST
        └── spiders/
            └── games_spider.py                  ← the only spider
```

---

## Deployment

### Required GitHub repository secrets

| Secret | Used by | Where to get it |
|--------|---------|-----------------|
| `AWS_ACCESS_KEY_ID` | `deploy-lambda.yml` | AWS IAM user with Lambda update permissions |
| `AWS_SECRET_ACCESS_KEY` | `deploy-lambda.yml` | same |
| `AWS_LAMBDA_FUNCTION_NAME` | `deploy-lambda.yml` | the Lambda function name in ap-southeast-1 |
| `SHUB_API_KEY` | `deploy-spider.yml`, `run-spider-daily.yml` | https://app.zyte.com/o/.../account/apikey |

### Required Lambda environment variables

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | TiDB async connection string (`mysql+aiomysql://…`) |
| `DATABASE_URL_SYNC` | TiDB sync string (`mysql+pymysql://…`) for migration bootstrap |
| `JWT_SECRET` | random 32+ char string for signing access tokens |
| `SCRAPER_SECRET` | random 32+ char string, must match Zyte's spider setting |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY` / `R2_SECRET_KEY` / `R2_BUCKET` | Cloudflare R2 for thumbnail mirror |
| `CHEAPSHARK_BASE` | `https://www.cheapshark.com/api/1.0` (default) |

### Required Zyte Scrapy Cloud spider settings

(Set in the Zyte project dashboard → Spider Settings, NOT as env vars)

| Setting | Value |
|---------|-------|
| `BACKEND_INGEST_URL` | your Lambda Function URL + `/internal/ingest` |
| `SCRAPER_SECRET` | same value as the Lambda's `SCRAPER_SECRET` |

### Deploy flow

- **Backend** → push to `main` triggers `deploy-lambda.yml` (zips, strips, uploads via AWS CLI)
- **Spider** → push affecting `scrapers/**` triggers `deploy-spider.yml` (`shub deploy` to project 860207)
- **Frontend** → host wherever you like. Configure with `VITE_API_BASE_URL=https://<lambda-function-url>`

### Daily crawl

`run-spider-daily.yml` fires automatically at **18:00 UTC = 02:00 PHT** every day. It hits Zyte's `run.json` endpoint with the `SHUB_API_KEY` secret, queueing one spider job per day. Bypasses Scrapy Cloud's paid Periodic Jobs feature entirely.

You can also trigger it manually from the **Actions** tab → "Run Spider Daily" → **Run workflow**.

---

## API endpoints

All `/v1/*` routes require a JWT in `Authorization: Bearer <token>`. Internal routes are gated by the `X-Scraper-Secret` header.

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `POST /auth/login` | none | username/password → JWT |
| `GET  /v1/me` | JWT | current user info |
| `GET  /v1/deals/featured?limit=N` | JWT | top N active deals by deal_rating |
| `GET  /v1/deals/search?title=X` | JWT | live CheapShark proxy |
| `GET  /v1/deals/{id}/history` | JWT | price history for a deal |
| `GET  /v1/deals/{id}/thumbnail` | JWT | lazy R2-mirrored thumbnail URL |
| `GET  /v1/exchange-rate?base=USD&target=PHP` | JWT | cached FX rate |
| `GET  /v1/admin/platforms` | JWT + admin | enabled-platforms list |
| `POST /v1/admin/platforms/{name}/toggle?enabled=…` | JWT + admin | flip platform |
| `GET  /v1/admin/users` | JWT + admin | user list |
| `POST /v1/admin/users/{username}/admin?enabled=…` | JWT + admin | promote/demote |
| `GET  /v1/admin/monitor/scraper` | JWT + admin | heartbeat keys |
| `POST /internal/ingest` | shared secret | spider POSTs deal items (single or batched list) |
| `POST /internal/ingest/finalize` | shared secret | spider POSTs `{run_started_at}` at end of crawl |

---

## Cost breakdown — designed for $0/month forever

| Service | Free tier | We use | Headroom |
|---------|-----------|--------|----------|
| AWS Lambda | 1M invocations/mo | ~900 | 99.9% |
| AWS Lambda compute | 400K GB-s/mo | ~10K GB-s | 97.5% |
| TiDB Cloud Serverless | 5 GB storage | <100 MB | 98% |
| Cloudflare R2 | 10 GB / 10M ops/mo | <1 GB | 90%+ |
| GitHub Actions (cron) | 2000 min/mo | ~1 min | 99.9% |
| Zyte Scrapy Cloud | 1 free spider, daily run | 1 spider | within limits |
| CheapShark / Steam / Epic APIs | unlimited public | ~1500 calls/day | within limits |

**Total: $0/month**, with massive headroom on every line.

---

## Local development

```bash
# Backend (Python 3.11)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in DATABASE_URL etc
uvicorn src.app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
echo "VITE_API_BASE_URL=http://localhost:8000" > .env.local
npm run dev  # http://localhost:5173

# Spider (local crawl, posts to local backend)
cd scrapers
pip install scrapy requests
export BACKEND_INGEST_URL=http://localhost:8000/internal/ingest
export SCRAPER_SECRET=<your-secret>
scrapy crawl games
```

---

## License

Personal project. No license attached. If you want to fork it, go ahead — just understand it was tuned for one Filipino gamer's use case.
