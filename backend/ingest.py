"""
Reading, cleaning, validating and saving an uploaded customer file.

Used by three places so they always behave the same:
  * scripts/load_data.py      (command-line loader)
  * POST /api/upload          (saves an uploaded file to the database)
  * the Upload & Analyze page (checks a file in the browser before saving)

Pure pandas except for the two write functions at the bottom, which import
SQLAlchemy only when called.
"""

import io
import re

import pandas as pd

ALIASES = {"customerid": "customer_id", "custid": "customer_id"}

RECOMMENDED = [
    "surname", "state", "age", "customer_segment", "recommended_product", "credit_score", "balance",
    "mobile_app_logins_per_month", "missed_emis_last_12m", "is_active_member",
    "preferred_communication_channel", "campaign_response",
]

YES_NO = {"yes": 1, "no": 0, "y": 1, "n": 0, "true": 1, "false": 0}


# ----------------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------------
def read_table(raw: bytes, filename: str) -> pd.DataFrame:
    """Read a CSV or Excel file from bytes. Raises ValueError with a plain message."""
    name = (filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            return pd.read_excel(io.BytesIO(raw))
        for encoding in ("utf-8-sig", "latin-1"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=encoding, low_memory=False)
            except UnicodeDecodeError:
                continue
    except Exception as exc:  # malformed file
        raise ValueError(f"Could not read '{filename}': {str(exc)[:160]}")
    raise ValueError(f"Could not decode '{filename}'. Save it as a UTF-8 CSV and try again.")


# ----------------------------------------------------------------------------
# Cleaning
# ----------------------------------------------------------------------------
def snake(name) -> str:
    s = re.sub(r"[%()]", "", str(name).strip())
    s = re.sub(r"[^0-9A-Za-z]+", "_", s)
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", s)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    return ALIASES.get(s, s or "column")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    seen, names = {}, []
    for col in df.columns:
        base = snake(col)
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    out = df.copy()
    out.columns = names
    return out


def _text_to_number(series: pd.Series) -> pd.Series:
    text_values = series.astype("string").str.strip()
    text_values = text_values.str.replace(r"(?i)[,₹$%]|\brs\.?|\binr\b", "", regex=True).str.strip()
    return pd.to_numeric(text_values, errors="coerce")


def clean_types(df: pd.DataFrame):
    """Store numbers as numbers. Returns (dataframe, info).

    Columns that arrive as text because of thousands separators or currency
    symbols ("1,23,456.50", "Rs. 5,000", "12.5%") become real numbers, and
    Yes/No columns become 1/0. customer_id is never touched.
    info = {"numbers": [...], "flags": [...]} lists what was converted.
    """
    out = df.copy()
    numbers, flags = [], []
    for col in out.columns:
        if col == "customer_id" or pd.api.types.is_numeric_dtype(out[col]) or pd.api.types.is_bool_dtype(out[col]):
            continue
        present = out[col].dropna().astype("string").str.strip()
        present = present[present != ""]
        if present.empty:
            continue
        lowered = present.str.lower()
        if lowered.nunique() <= 2 and lowered.isin(list(YES_NO)).all():
            out[col] = out[col].astype("string").str.strip().str.lower().map(YES_NO).astype("float").astype("Int64")
            flags.append(col)
            continue
        converted = _text_to_number(out[col])
        if converted.loc[present.index].notna().mean() >= 0.98:
            out[col] = converted.astype(float)
            numbers.append(col)
    return out, {"numbers": numbers, "flags": flags}


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------
def propensity_scale(df: pd.DataFrame):
    """1 if propensity_score looks like a 0-1 probability, 100 if 0-100, None if absent/empty."""
    if "propensity_score" not in df.columns:
        return None
    p = pd.to_numeric(df["propensity_score"], errors="coerce")
    if p.notna().sum() == 0:
        return None
    return 1 if p.max() <= 1 else 100


def prepare(raw: bytes, filename: str):
    """Read, normalize and clean a file. Returns (dataframe, report).

    report["errors"]   problems that block saving to the dashboards
    report["warnings"] things worth knowing, nothing blocked
    """
    df = read_table(raw, filename)
    df = df.dropna(how="all")
    if df.empty:
        raise ValueError("The file has no rows.")
    df, info = clean_types(normalize_columns(df))

    errors, warnings = [], []
    if "customer_id" not in df.columns:
        errors.append("No customer_id column was found. Rename your ID column to customer_id (or CustomerID).")
    else:
        dupes = int(df["customer_id"].duplicated().sum())
        if dupes:
            warnings.append(f"{dupes:,} duplicate customer_id values.")
        blanks = int(df["customer_id"].isna().sum())
        if blanks:
            errors.append(f"{blanks:,} rows have an empty customer_id.")

    scale = propensity_scale(df)
    if "propensity_score" not in df.columns:
        errors.append("No propensity_score column. The dashboards need the model's purchase probability "
                      "(0-1 or 0-100). You can still analyze this file on the Upload page without saving it.")
    elif scale is None:
        errors.append("propensity_score has no numeric values.")
    else:
        p = pd.to_numeric(df["propensity_score"], errors="coerce")
        missing = int(p.isna().sum())
        if missing:
            warnings.append(f"{missing:,} rows have a missing or non-numeric propensity_score.")
        if p.min() < 0 or p.max() > 100:
            errors.append(f"propensity_score must be between 0 and 100 (found {p.min():.4g} to {p.max():.4g}).")

    missing_cols = [c for c in RECOMMENDED if c not in df.columns]
    if not any(c in df.columns for c in ("estimated_clv", "customer_lifetime_value", "expected_revenue")):
        missing_cols.append("estimated_clv / customer_lifetime_value / expected_revenue")

    report = {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "scale": scale,
        "converted_numbers": info["numbers"],
        "converted_flags": info["flags"],
        "missing_recommended": missing_cols,
        "errors": errors,
        "warnings": warnings,
    }
    return df, report


# ----------------------------------------------------------------------------
# Writing (database)
# ----------------------------------------------------------------------------
def _quote(engine, name: str) -> str:
    return engine.dialect.identifier_preparer.quote(name)


def _chunk_size(df: pd.DataFrame) -> int:
    return max(1, min(1000, 60000 // max(1, len(df.columns))))  # stay under the 65,535 bind-parameter limit


def replace_table(df: pd.DataFrame, engine, table: str) -> None:
    """Replace the table in one transaction: a failed load leaves the old table intact."""
    with engine.begin() as conn:
        df.to_sql(table, conn, if_exists="replace", index=False, chunksize=_chunk_size(df), method="multi")


def append_rows(df: pd.DataFrame, engine, table: str) -> dict:
    """Add rows to an existing table. Customers whose customer_id is already in the
    table are replaced by the new row. Columns must already exist in the table."""
    from sqlalchemy import String, cast, delete, inspect, MetaData, Table

    existing = [c["name"] for c in inspect(engine).get_columns(table)]
    unknown = [c for c in df.columns if c not in existing]
    if unknown:
        raise ValueError("These columns are not in the saved table: " + ", ".join(unknown[:10]) +
                         ". Use 'Replace all data', or remove them from the file.")
    t = Table(table, MetaData(), autoload_with=engine)
    ids = [str(v) for v in df["customer_id"].dropna().unique().tolist()]
    replaced = 0
    with engine.begin() as conn:
        for i in range(0, len(ids), 5000):
            result = conn.execute(delete(t).where(cast(t.c.customer_id, String).in_(ids[i:i + 5000])))
            replaced += result.rowcount or 0
        df.to_sql(table, conn, if_exists="append", index=False, chunksize=_chunk_size(df), method="multi")
    return {"replaced_existing": int(replaced)}


def post_load(engine, table: str, has_customer_id: bool, say=print) -> None:
    """Index on customer_id, and (Postgres) row level security so Supabase's public
    REST route cannot read the table. The API connects as the owner, which bypasses RLS."""
    from sqlalchemy import text

    backend = engine.dialect.name
    if has_customer_id:
        stmt = f"CREATE INDEX idx_{table}_customer_id ON {_quote(engine, table)} (customer_id)"
        if backend in ("postgresql", "sqlite"):
            stmt = stmt.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1)
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception as exc:  # index is an optimization only
            say(f"  note: could not create customer_id index ({str(exc).splitlines()[0][:120]})")
    if backend == "postgresql":
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {_quote(engine, table)} ENABLE ROW LEVEL SECURITY"))
            say("  row level security enabled (blocks Supabase's public REST access to this table)")
        except Exception as exc:
            say(f"  note: could not enable row level security ({str(exc).splitlines()[0][:120]})")
