from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from vast_inferencer.config import get_settings

_LIBPQ_ONLY_PARAMS = {"sslmode", "channel_binding"}


def normalize_database_url(url: str) -> tuple[str, dict[str, Any]]:
    cleaned = url.strip()
    if cleaned.startswith("postgres://"):
        cleaned = "postgresql://" + cleaned[len("postgres://") :]
    if cleaned.startswith("postgresql+asyncpg://"):
        scheme = "postgresql+asyncpg"
        rest = cleaned.split("://", 1)[1]
    elif cleaned.startswith("postgresql://"):
        scheme = "postgresql+asyncpg"
        rest = cleaned[len("postgresql://") :]
    else:
        raise ValueError("DATABASE_URL must be a postgresql URL")

    parts = urlsplit(f"{scheme}://{rest}")
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    connect_args: dict[str, Any] = {"statement_cache_size": 0}
    sslmode = query.pop("sslmode", None)
    ssl_value = query.pop("ssl", None)
    for name in _LIBPQ_ONLY_PARAMS:
        query.pop(name, None)
    if ssl_value is not None:
        connect_args["ssl"] = ssl_value not in {"0", "false", "disable"}
    elif sslmode == "disable":
        connect_args["ssl"] = False
    else:
        connect_args["ssl"] = True
    normalized = urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), ""))
    return normalized, connect_args


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    url, connect_args = normalize_database_url(get_settings().database_url.get_secret_value())
    engine = create_async_engine(url, poolclass=NullPool, connect_args=connect_args)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
