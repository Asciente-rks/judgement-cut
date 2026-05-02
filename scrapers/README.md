Scrapers (Scrapy)

This folder contains a minimal Scrapy project scaffold and an example spider that visits gaming platforms sequentially.

Deployment to Zyte Scrapy Cloud

- Ensure you have a Zyte account and the `shub` CLI installed.
- Log in with `shub login` and follow Zyte instructions.
- Deploy from the `scrapers/` project root, not from `scrapers/scrapers/`. Zyte will run your spiders on Scrapy Cloud.

Important: You have 1 Free Forever Scrapy Cloud Unit — spiders should be written to run sequentially (this scaffold sets `CONCURRENT_REQUESTS=1`). The example spider iterates platforms one-by-one.

Ingestion pipeline

- This project includes `scrapers/scrapers/pipelines.py` which will POST each scraped item to your backend ingestion endpoint at `BACKEND_INGEST_URL` (default `http://localhost:8000/internal/ingest`).
- Configure these environment variables in Zyte (or locally) before running the spider:
  - `BACKEND_INGEST_URL` — e.g. `https://your-backend.example.com/internal/ingest`
  - `SCRAPER_SECRET` — shared secret matching the backend `SCRAPER_SECRET` value

Zyte deployment notes (single unit)

- Because you have a single free Scrapy Cloud unit, write spiders to run sequentially (this scaffold sets `CONCURRENT_REQUESTS=1`).
- To deploy with `shub`:
  - Run this from `c:\Users\kirit\judgement-cut\scrapers`:

```bash
python -m pip install shub
shub login
shub deploy
```

Or on Windows, double-click or run `deploy.bat` from the `scrapers/` root. It forces the working directory to the correct project root before calling `shub`.

If `py -m pip install shub` fails with `No module named pip`, repair Python first:

```bash
py -m ensurepip --upgrade
py -m pip install --upgrade pip
py -m pip install shub
```

If `ensurepip` is unavailable, install a Python build that includes `pip` from python.org and make sure it is added to PATH.

If `shub` installs but `shub` is not recognized in the current terminal, either reopen the terminal after install or run it from the full path shown by pip, for example:

```bat
C:\Users\kirit\AppData\Local\Programs\Python\Python314\Scripts\shub.exe login
C:\Users\kirit\AppData\Local\Programs\Python\Python314\Scripts\shub.exe deploy
```

To make it permanent, add this folder to PATH:

```bat
C:\Users\kirit\AppData\Local\Programs\Python\Python314\Scripts
```

After deploy, configure the project settings on Zyte to set the environment variables `BACKEND_INGEST_URL` and `SCRAPER_SECRET` so the pipeline can authenticate when posting data to your backend.

Files:

- `scrapers/` — Scrapy project
  - `spiders/games_spider.py` — example spider that cycles platforms sequentially
  - `settings.py` — config (concurrency set to 1, polite delays)
