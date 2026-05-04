from databases import Database
from sqlalchemy import MetaData, Table, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy import create_engine
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
    Column("deal_id", String(100), nullable=False),
    Column("title", String(300)),
    Column("store_id", String(50)),
    Column("price", Float),
    Column("normal_price", Float),
    Column("deal_rating", Float, default=0.0),
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


def create_tables_sync():
    if not DATABASE_URL and not DATABASE_URL_SYNC:
        raise RuntimeError("DATABASE_URL not configured")
    # Use synchronous engine to create tables
    connect_args = {"ssl": _ssl_context} if _ssl_context else {}
    engine = create_engine(DATABASE_URL_SYNC or DATABASE_URL, connect_args=connect_args)
    metadata.create_all(engine)


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
