from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from app.config import get_settings


def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_demo_read_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.demo_read_database_url or settings.database_url, pool_pre_ping=True)


def get_connection() -> Iterator[Connection]:
    engine = get_engine()
    with engine.begin() as connection:
        yield connection
