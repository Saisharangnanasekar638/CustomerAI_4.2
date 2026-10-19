"""
Load customer data into the online database that the API reads from
(Supabase / PostgreSQL, or any database set in .env).

Run from the project root, with .env filled in:

  1. From your CSV
       python scripts/load_data.py --csv path/to/Indian_Banking_CRM_Complete.csv

  2. From your existing local MySQL table (keeps the model outputs your
     training script already wrote, e.g. propensity_score, recommended_product)
       python scripts/load_data.py --from-source
     The source is SOURCE_DATABASE_URL, or the old DB_HOST/DB_USER/... values.

Column names are normalized to snake_case (CreditScore -> credit_score).
The target table is replaced, inside a single transaction where the
database supports it, so a failed load leaves the previous table intact.
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from backend import database, ingest  # noqa: E402
from backend.ingest import RECOMMENDED, normalize_columns  # noqa: E402


def source_url() -> URL:
    raw = os.getenv("SOURCE_DATABASE_URL", "").strip()
    if raw:
        return make_url(database._normalize_url(raw))
    return URL.create(
        "mysql+mysqlconnector",
        username=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 3306)),
        database=os.getenv("DB_NAME", "customerai"),
    )


def describe(df: pd.DataFrame) -> bool:
    ok = True
    print(f"\nRows: {len(df):,}   Columns: {len(df.columns)}")
    if "customer_id" not in df.columns:
        print("ERROR: no customer_id column found after normalizing headers.")
        print("       Columns seen:", ", ".join(df.columns[:25]))
        ok = False
    elif df["customer_id"].duplicated().any():
        print(f"WARNING: {int(df['customer_id'].duplicated().sum()):,} duplicate customer_id values.")
    if "propensity_score" not in df.columns:
        print("ERROR: no propensity_score column. The dashboards need the model's purchase probability.")
        ok = False
    else:
        p = pd.to_numeric(df["propensity_score"], errors="coerce")
        scale = "0-1 probability" if p.max() <= 1 else "0-100 percentage"
        print(f"propensity_score: min {p.min():.4g}, mean {p.mean():.4g}, max {p.max():.4g}  ({scale}; "
              f"{int(p.isna().sum()):,} missing)")
    missing = [c for c in RECOMMENDED if c not in df.columns]
    if not any(c in df.columns for c in ("estimated_clv", "customer_lifetime_value", "expected_revenue")):
        missing.append("estimated_clv / customer_lifetime_value / expected_revenue")
    if missing:
        print("Not in the data (the dashboard will show defaults and say so):", ", ".join(missing))
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path, help="CSV file to load")
    source.add_argument("--from-source", action="store_true", help="copy the table from your old/local database")
    parser.add_argument("--table", default=database.TABLE_NAME, help="target table name (default: customers)")
    parser.add_argument("--source-table", default="customers", help="table to read with --from-source")
    args = parser.parse_args()

    target_engine = database.get_engine()
    target = database.database_url()

    if args.csv:
        if not args.csv.exists():
            raise SystemExit(f"File not found: {args.csv}")
        print(f"Reading {args.csv} ...")
        df = ingest.read_table(args.csv.read_bytes(), args.csv.name)
    else:
        src = source_url()
        if src.render_as_string(hide_password=True) == target.render_as_string(hide_password=True):
            raise SystemExit("The source and the target are the same database. Set DATABASE_URL in .env to your "
                             "Supabase connection string first (and SOURCE_DATABASE_URL to your local MySQL).")
        print(f"Reading table '{args.source_table}' from {src.render_as_string(hide_password=True)} ...")
        df = pd.read_sql_table(args.source_table, database.build_engine(src))

    df, info = ingest.clean_types(normalize_columns(df))
    if info["numbers"]:
        print("Converted text columns to numbers:", ", ".join(info["numbers"]))
    if info["flags"]:
        print("Converted Yes/No columns to 1/0:", ", ".join(info["flags"]))
    if not describe(df):
        raise SystemExit("\nNothing was written. Fix the issues above and run again.")

    print(f"\nWriting to {target.get_backend_name()} at {target.host or 'local file'} / "
          f"{target.database}, table '{args.table}' ...")
    ingest.replace_table(df, target_engine, args.table)
    ingest.post_load(target_engine, args.table, "customer_id" in df.columns)

    database.reset_cache()
    with target_engine.connect() as conn:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {ingest._quote(target_engine, args.table)}")).scalar()
    cols = [c["name"] for c in inspect(target_engine).get_columns(args.table)]
    print(f"\nDone. {count:,} rows and {len(cols)} columns are now in '{args.table}'.")
    print("Next: python scripts/check_connection.py, then start the API.")


if __name__ == "__main__":
    main()
