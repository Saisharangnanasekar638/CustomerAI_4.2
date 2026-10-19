"""
Check that the database in .env is reachable and holds usable data.

    python scripts/check_connection.py

Prints exactly what the API will see and explains the most common
Supabase connection failures.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from backend import database  # noqa: E402

HINTS = [
    ("password authentication failed", "Wrong database password. Supabase: Project Settings > Database > Reset database password."),
    ("tenant or user not found", "With the Supabase pooler the user must be postgres.YOUR_PROJECT_REF (not just postgres), "
                                  "and the host must be the one shown for your project's region."),
    ("network is unreachable", "Your network cannot reach the direct database host (it is IPv6 only on the free plan). "
                                "Use the Session pooler connection string instead."),
    ("could not translate host name", "The host name is wrong or has a typo. Copy it again from the Supabase dashboard."),
    ("name or service not known", "The host name is wrong or has a typo. Copy it again from the Supabase dashboard."),
    ("timeout", "The database did not answer in time. Check the host/port and that your network allows outbound 5432/6543."),
    ("ssl", "SSL problem. Add ?sslmode=require to DATABASE_URL."),
    ("does not exist", "The database or table name is wrong. For Supabase the database name is 'postgres'."),
]


def explain(exc: Exception) -> None:
    message = str(getattr(exc, "orig", exc))
    print("\nFAILED:", message.strip().splitlines()[0][:300])
    lowered = message.lower()
    for needle, hint in HINTS:
        if needle in lowered:
            print("Hint:", hint)
            break
    else:
        print("Hint: if your password contains @ # / : ? or %, URL-encode it in DATABASE_URL, or use the "
              "DB_DRIVER / DB_HOST / DB_USER / DB_PASSWORD form in .env, which needs no encoding.")


def main() -> int:
    info = database.connection_info()
    print(f"Target: {info['dialect']} | host {info['host'] or '(local file)'} | port {info['port']} | "
          f"database {info['database']} | table {info['table']}")

    try:
        with database.get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Connection: OK")
    except Exception as exc:
        explain(exc)
        return 1

    engine = database.get_engine()
    if not inspect(engine).has_table(info["table"]):
        print(f"\nThe connection works, but table '{info['table']}' does not exist yet.")
        print("Load your data: python scripts/load_data.py --csv path/to/your.csv   (or --from-source)")
        return 2

    try:
        table = database.customers_table()
        with engine.connect() as conn:
            rows = conn.execute(text(f"SELECT COUNT(*) FROM {engine.dialect.identifier_preparer.quote(info['table'])}")).scalar()
        columns = [c.name for c in table.columns]
        print(f"Table: {rows:,} rows, {len(columns)} columns")
        print("Columns:", ", ".join(columns))
        if "propensity_score" in columns:
            scale = database.score_scale()
            print(f"propensity_score scale: {'0-1 probability' if scale == 1 else '0-100 percentage'} (handled automatically)")
        else:
            print("WARNING: no propensity_score column; the dashboards cannot run without it.")
        sample = database.fetch_all_customers(limit=1)
        print("Sample row fetch through the API layer: OK" if sample else "WARNING: the table is empty.")
    except Exception as exc:
        explain(exc)
        return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
