from sqlalchemy.ext.declarative import declarative_base
from ..db import users as users_table, platforms as platforms_table, featured_deals as featured_deals_table, price_history as price_history_table, crawler_settings as crawler_settings_table

Base = declarative_base()


class User(Base):
    __table__ = users_table


class Platform(Base):
    __table__ = platforms_table


class FeaturedDeal(Base):
    __table__ = featured_deals_table


class PriceHistory(Base):
    __table__ = price_history_table


class CrawlerSetting(Base):
    __table__ = crawler_settings_table
