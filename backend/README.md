Game Deals Backend (FastAPI)

Quick start (local):

1. Create a virtualenv and install deps

```bash
python -m venv .venv
source .venv/bin/activate    # or .venv\Scripts\activate on Windows
python -m pip install -r backend/requirements.txt
```

2. Run locally with uvicorn

```bash
uvicorn backend.src.main:app --reload --port 8000
```

Endpoints:

- `GET /deals` — proxy to CheapShark `deals` endpoint. Query params accepted: `storeID`, `title`, `pageSize`.

Deploy (CI/CD):

- The repository includes `.github/workflows/deploy-lambda.yml` which packages dependencies and source, then updates an AWS Lambda function using `aws lambda update-function-code`.
- Set the following GitHub secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `LAMBDA_FUNCTION_NAME`.

Notes:

- This initial scaffold proxies CheapShark; later we will integrate Zyte scraper results and TiDB storage.
- You mentioned aiming for zero cost: Zyte's free Scrapy Cloud unit will handle scraping. AWS Lambda and other services may incur costs — consider using free tiers or low-cost serverless providers to stay within zero cost.

Internal endpoints (for scrapers)

- `POST /internal/ingest` — protected ingestion endpoint for spiders. Set the header `X-Scraper-Secret` to the value of `SCRAPER_SECRET` in your backend `.env` and POST a JSON item or list of items matching the fields used by the spider (e.g. `deal_id`, `title`, `store`, `price`, `normal_price`, `deal_rating`).

Lambda handler notes:

- The Lambda function should use Python 3.11 runtime and have the handler set to `backend.src.handler.handler`.

Secrets and env vars (required/optional):

- `DATABASE_URL` or `DB_USERNAME`, `DB_PASSWORD`, `DB_HOST`, `DB_NAME` — TiDB connection
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` — Cloudflare R2
- `JWT_SECRET` — JWT signing secret. Use your own long random value.
- `SCRAPER_SECRET` — shared secret between scraper and backend for ingestion

Testing locally:

1. Create a `.env` in `backend/` with required vars (see `.env.example` or copy values).
2. Install deps and run:

```bash
python -m venv .venv
. .venv/bin/activate      # or .venv\Scripts\activate on Windows
python -m pip install -r backend/requirements.txt
uvicorn backend.src.main:app --reload --port 8000
```

If `python -m pip` reports `No module named pip`, repair Python first:

```bash
py -m ensurepip --upgrade
py -m pip install --upgrade pip
```

3. Login and use endpoints:

```bash
# login to get token
curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"adminpass"}'

# call featured deals (with token)
curl http://localhost:8000/v1/deals/featured -H "Authorization: Bearer <token>"
```
