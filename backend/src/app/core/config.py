from pathlib import Path
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_DIR = BASE_DIR.parent

env_candidates = [PROJECT_DIR / ".env", BASE_DIR / ".env"]
for env_path in env_candidates:
    if env_path.exists():
        load_dotenv(env_path)
        break
else:
    load_dotenv()

CHEAPSHARK_BASE = os.getenv("CHEAPSHARK_BASE", "https://www.cheapshark.com/api/1.0")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "4000")
DB_NAME = os.getenv("DB_NAME")
DB_SSL = os.getenv("DB_SSL", "").lower() in ("1", "true", "yes")
DB_SSL_CA = os.getenv("DB_SSL_CA")

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URL_ASYNC")
DATABASE_URL_SYNC = os.getenv("DATABASE_URL_SYNC")

if not DATABASE_URL and DB_HOST and DB_USERNAME and DB_PASSWORD and DB_NAME:

    DATABASE_URL = f"mysql+aiomysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

if not DATABASE_URL_SYNC and DB_HOST and DB_USERNAME and DB_PASSWORD and DB_NAME:

    DATABASE_URL_SYNC = f"mysql+pymysql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

if DATABASE_URL and not DATABASE_URL_SYNC:
    DATABASE_URL_SYNC = (
        DATABASE_URL.replace("+aiomysql", "+pymysql")
        .replace("+asyncmy", "+pymysql")
    )

SECRET_KEY = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY", "change-me-in-prod")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET = os.getenv("R2_BUCKET")

SCRAPER_SECRET = os.getenv("SCRAPER_SECRET")

_default_cors = (
    "https://judgement-cut.vercel.app,"
    "http://localhost:5173,"
    "http://127.0.0.1:5173"
)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", _default_cors).split(",")
    if origin.strip()
]

IS_PRODUCTION = os.getenv("ENV", os.getenv("ENVIRONMENT", "development")).lower() in (
    "production",
    "prod",
)
