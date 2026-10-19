"""
Database access for the CustomerAI Platform.

Works with Supabase / any PostgreSQL, MySQL, or SQLite. The connection is
configured only through environment variables (see .env.example):

  1. DATABASE_URL                       full URL, e.g. your Supabase connection string
  2. DB_DRIVER=postgresql + DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME
     (same pieces as the old local-MySQL setup; use this if your password
     contains special characters and you do not want to URL-encode it)
  3. DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME with no DB_DRIVER
     keeps working exactly as before against local MySQL.

No other file should talk to the database directly -- everything goes
through here. The `customers` table is reflected at runtime, so whatever
columns your dataset has are served as-is.
"""

import math
import os
from decimal import Decimal
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import Integer, MetaData, String, Table, cast, create_engine, func, or_, select, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.pool import StaticPool

load_dotenv()

TABLE_NAME = os.getenv("CUSTOMERS_TABLE", "customers")
MAX_ROWS = 50000

_DRIVERS = {"postgresql": "postgresql+psycopg", "postgres": "postgresql+psycopg", "mysql": "mysql+mysqlconnector"}


def _normalize_url(raw: str) -> str:
    """Accept the URL styles people actually copy from dashboards."""
    raw = raw.strip().strip('"').strip("'")
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    if raw.startswith("mysql://"):
        return "mysql+mysqlconnector://" + raw[len("mysql://"):]
    return raw


def database_url() -> URL:
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw:
        return make_url(_normalize_url(raw))

    driver = os.getenv("DB_DRIVER", "mysql").strip().lower()
    default_port = 5432 if driver.startswith("postgres") else 3306
    return URL.create(
        drivername=_DRIVERS.get(driver, driver),
        username=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", default_port)),
        database=os.getenv("DB_NAME", "customerai"),
    )


def build_engine(url: Optional[URL] = None) -> Engine:
    url = url or database_url()
    backend = url.get_backend_name()
    kwargs = {"pool_pre_ping": True, "pool_recycle": 300}
    connect_args = {}

    if backend == "sqlite":
        connect_args["check_same_thread"] = False
        if url.database in (None, "", ":memory:"):
            kwargs["poolclass"] = StaticPool
    elif backend == "postgresql":
        # Supabase's pooler runs pgbouncer in transaction mode, which does not
        # support server-side prepared statements.
        connect_args["prepare_threshold"] = None
        if "sslmode" not in (url.query or {}) and url.host not in (None, "localhost", "127.0.0.1"):
            connect_args["sslmode"] = "require"
        kwargs.update(pool_size=5, max_overflow=5)
    elif backend == "mysql":
        kwargs.update(pool_size=5, max_overflow=5)

    return create_engine(url, connect_args=connect_args, **kwargs)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return build_engine()


_cache: dict = {}


def reset_cache() -> None:
    _cache.clear()


def customers_table() -> Table:
    table = _cache.get("table")
    if table is None:
        table = Table(TABLE_NAME, MetaData(), autoload_with=get_engine())
        _cache["table"] = table
    return table


def _clean(value):
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _row(row) -> dict:
    return {k: _clean(v) for k, v in row._mapping.items()}


def connection_info() -> dict:
    url = database_url()
    return {
        "dialect": url.get_backend_name(),
        "host": url.host,
        "port": url.port,
        "database": url.database,
        "table": TABLE_NAME,
    }


def ping() -> dict:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
        count = conn.execute(select(func.count()).select_from(customers_table())).scalar()
    return {"status": "ok", "customers": int(count or 0), **connection_info()}


def fetch_all_customers(limit: int = 100, offset: int = 0):
    t = customers_table()
    limit = max(1, min(int(limit), MAX_ROWS))
    stmt = select(t)
    if "customer_id" in t.c:
        stmt = stmt.order_by(t.c.customer_id)
    with get_engine().connect() as conn:
        return [_row(r) for r in conn.execute(stmt.limit(limit).offset(max(0, int(offset))))]


def fetch_customer_by_id(customer_id: str):
    t = customers_table()
    stmt = select(t).where(cast(t.c.customer_id, String) == str(customer_id)).limit(1)
    with get_engine().connect() as conn:
        row = conn.execute(stmt).first()
    return _row(row) if row is not None else None


def fetch_stats():
    t = customers_table()
    cols = [func.count().label("total_customers")]
    if "propensity_score" in t.c:
        cols.append(func.avg(t.c.propensity_score).label("avg_propensity"))
    if "purchased_new_product" in t.c:
        cols.append(
            (func.sum(cast(t.c.purchased_new_product, Integer)) * 100.0 / func.count()).label("purchase_rate_pct")
        )
    with get_engine().connect() as conn:
        return _row(conn.execute(select(*cols)).first())


def fetch_segment_breakdown():
    t = customers_table()
    if "customer_segment" not in t.c:
        return []
    cols = [t.c.customer_segment, func.count().label("customer_count")]
    if "propensity_score" in t.c:
        cols.append(func.avg(t.c.propensity_score).label("avg_propensity"))
    if "purchased_new_product" in t.c:
        cols.append(
            (func.sum(cast(t.c.purchased_new_product, Integer)) * 100.0 / func.count()).label("purchase_rate_pct")
        )
    stmt = select(*cols).group_by(t.c.customer_segment)
    stmt = stmt.order_by((func.avg(t.c.propensity_score) if "propensity_score" in t.c else func.count()).desc())
    with get_engine().connect() as conn:
        return [_row(r) for r in conn.execute(stmt)]


def search_customers(query: str, limit: int = 50):
    t = customers_table()
    searchable = [c for c in ("customer_id", "surname", "customer_segment") if c in t.c]
    if not searchable or not query.strip():
        return []
    escaped = query.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    stmt = (
        select(t)
        .where(or_(*[func.lower(cast(t.c[c], String)).like(pattern, escape="\\") for c in searchable]))
        .limit(max(1, min(int(limit), 500)))
    )
    with get_engine().connect() as conn:
        return [_row(r) for r in conn.execute(stmt)]


def score_scale() -> int:
    """1 if propensity_score is stored as a 0-1 probability, 100 if 0-100."""
    if "scale" not in _cache:
        t = customers_table()
        if "propensity_score" not in t.c:
            _cache["scale"] = 100
        else:
            with get_engine().connect() as conn:
                top = conn.execute(select(func.max(t.c.propensity_score))).scalar()
            _cache["scale"] = 1 if (top is not None and float(top) <= 1.0) else 100
    return _cache["scale"]
