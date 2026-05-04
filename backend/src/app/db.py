from databases import Database
from sqlalchemy import MetaData, Table, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy import create_engine, text
from .core.config import DATABASE_URL, DATABASE_URL_SYNC, DB_HOST, DB_SSL, DB_SSL_CA
import sqlalchemy
import asyncio
import ssl
from passlib.context import CryptContext
from datetime import datetime

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(150), unique=True, nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("is_admin", Boolean, default=False),
)

platforms = Table(
    "platforms",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(100), unique=True, nullable=False),
    Column("is_enabled", Boolean, default=True),
)

featured_deals = Table(
    "featured_deals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # deal_id is unique - the spider re-ingests the same deals daily, and
    # we want UPSERT semantics so the table doesn't grow unbounded.
    Column("deal_id", String(100), nullable=False, unique=True),
    Column("title", String(300)),
    Column("store_id", String(50)),
    # USD prices straight from CheapShark.
    Column("price", Float),
    Column("normal_price", Float),
    Column("deal_rating", Float, default=0.0),
    # CheapShark CDN URL for the cover art. Mirrored to R2 lazily on
    # /v1/deals/{id}/thumbnail.
    Column("thumbnail_url", String(500), nullable=True),
    # For Steam deals, the underlying Steam app ID. Lets us call
    # store.steampowered.com/api/appdetails?cc=PH for native PHP pricing
    # rather than naive USD->PHP currency conversion.
    Column("steam_app_id", String(50), nullable=True),
    # Native regional pricing populated from Steam's API. NULL means the
    # client should fall back to USD * fx_rate.
    Column("price_php", Float, nullable=True),
    Column("normal_price_php", Float, nullable=True),
    Column("regional_price_at", DateTime, nullable=True),
    Column("synced_at", DateTime, default=datetime.utcnow),
)

price_history = Table(
    "price_history",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("deal_id", String(100)),
    Column("price", Float),
    Column("recorded_at", DateTime, default=datetime.utcnow),
)

crawler_settings = Table(
    "crawler_settings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(100), unique=True, nullable=False),
    Column("value", Text, nullable=True),
)


def _build_ssl_context() -> ssl.SSLContext | None:
    use_ssl = DB_SSL or bool(DB_SSL_CA) or (DB_HOST and DB_HOST.endswith("tidbcloud.com"))
    if not use_ssl:
        return None
    if DB_SSL_CA:
        return ssl.create_default_context(cafile=DB_SSL_CA)
    return ssl.create_default_context()


_ssl_context = _build_ssl_context()
_db_kwargs = {"ssl": _ssl_context} if _ssl_context else {}

# Database object for async operations
database = Database(DATABASE_URL, **_db_kwargs)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Module-level flag: schema setup runs once per Lambda container.
# Cold starts re-run it; warm invocations skip the round trip to TiDB.
_SCHEMA_BOOTSTRAPPED = False

# One-shot ALTER statements that metadata.create_all() can't add to
# existing tables. Each is idempotent: a duplicate-column / duplicate-
# index error from MySQL means the migration already ran on this DB.
_MIGRATIONS = [
    # Original thumbnail mirror column.
    "ALTER TABLE featured_deals ADD COLUMN thumbnail_url VARCHAR(500) NULL",
    # Steam app ID + native regional pricing.
    "ALTER TABLE featured_deals ADD COLUMN steam_app_id VARCHAR(50) NULL",
    "ALTER TABLE featured_deals ADD COLUMN price_php DOUBLE NULL",
    "ALTER TABLE featured_deals ADD COLUMN normal_price_php DOUBLE NULL",
    "ALTER TABLE featured_deals ADD COLUMN regional_price_at DATETIME NULL",
    # Dedup the table: if the spider posts the same deal_id twice, we
    # want UPSERT semantics, not a duplicate row. The repository layer
    # uses INSERT ... ON DUPLICATE KEY UPDATE which requires this index.
    # On TiDB / MySQL, adding a UNIQUE constraint will fail if the
    # existing data has duplicates; we de-dupe first.
    (
        "DELETE FROM featured_deals WHERE id NOT IN ("
        "  SELECT id FROM ("
        "    SELECT MIN(id) AS id FROM featured_deals GROUP BY deal_id"
        "  ) t"
        ")"
    ),
    "CREATE UNIQUE INDEX idx_featured_deals_deal_id ON featured_deals (deal_id)",
]


def _apply_migrations(engine):
    with engine.connect() as conn:
        for sql in _MIGRATIONS:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                # Already applied (duplicate column, index, etc.) - safe to skip.
                pass


def create_tables_sync():
    """Create tables and apply schema migrations.

    Skipped on subsequent calls within the same Lambda container so warm
    invocations don't pay for extra TiDB round trips.
    """
    global _SCHEMA_BOOTSTRAPPED
    if _SCHEMA_BOOTSTRAPPED:
        return

    if not DATABASE_URL and not DATABASE_URL_SYNC:
        raise RuntimeError("DATABASE_URL not configured")
    connect_args = {"ssl": _ssl_context} if _ssl_context else {}
    engine = create_engine(DATABASE_URL_SYNC or DATABASE_URL, connect_args=connect_args)
    metadata.create_all(engine)
    _apply_migrations(engine)
    _SCHEMA_BOOTSTRAPPED = True


async def connect_db():
    await database.connect()


async def disconnect_db():
    await database.disconnect()


async def seed_initial_data():
    # create default users (admin and user) if they don't exist
    query = users.select().where(users.c.username == "admin")
    admin = await database.fetch_one(query)
    if not admin:
        await database.execute(
            users.insert().values(
                username="admin",
                password_hash=pwd_context.hash("adminpass"),
                is_admin=True,
            )
        )

    query = users.select().where(users.c.username == "user")
    user = await database.fetch_one(query)
    if not user:
        await database.execute(
            users.insert().values(
                username="user",
                password_hash=pwd_context.hash("userpass"),
                is_admin=False,
            )
        )

    # seed some platforms if missing
    for pname in ["Steam", "Epic", "GOG", "Humble"]:
        q = platforms.select().where(platforms.c.name == pname)
        p = await database.fetch_one(q)
        if not p:
            await database.execute(platforms.insert().values(name=pname, is_enabled=True))
