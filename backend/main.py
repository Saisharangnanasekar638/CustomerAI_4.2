"""
FastAPI backend for the CustomerAI Platform.

Run from the project root (the folder that contains backend/):
    uvicorn backend.main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
Health check:     http://localhost:8000/api/health
"""

import hmac
import os

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect
from sqlalchemy.exc import NoSuchTableError, SQLAlchemyError

from backend import database, ingest
from backend.model_utils import score_customer

app = FastAPI(title="CustomerAI Platform API")

# Set CORS_ORIGINS to a comma-separated list (e.g. your hosted Streamlit URL)
# when you deploy; "*" is fine for local development.
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(NoSuchTableError)
def _missing_table(_, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": f"Table '{database.TABLE_NAME}' was not found. Load your data first: "
                           f"python scripts/load_data.py --csv <your csv>"},
    )


@app.exception_handler(SQLAlchemyError)
def _db_error(_, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": f"Database error: {str(getattr(exc, 'orig', exc))[:300]}"},
    )


@app.get("/")
def root():
    return {"status": "ok", "message": "CustomerAI API is running"}


@app.get("/api/health")
def health():
    return database.ping()


@app.get("/api/customers")
def get_customers(limit: int = 100, offset: int = 0):
    return database.fetch_all_customers(limit=limit, offset=offset)


@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: str):
    customer = database.fetch_customer_by_id(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@app.get("/api/search")
def search(q: str):
    return database.search_customers(q)


@app.get("/api/stats")
def get_stats():
    return database.fetch_stats()


@app.get("/api/segments")
def get_segments():
    return database.fetch_segment_breakdown()


@app.post("/api/predict/{customer_id}")
def predict(customer_id: str):
    customer = database.fetch_customer_by_id(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return score_customer(customer, scale=database.score_scale())


# ----------------------------------------------------------------------------
# Upload: lets the Upload & Analyze page save a new file to the database.
# Replacing data is destructive, so it needs ADMIN_KEY (set it in the API's
# environment). With no ADMIN_KEY set, saving is switched off.
# ----------------------------------------------------------------------------
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))


def _require_admin(key):
    expected = os.getenv("ADMIN_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Saving data is switched off. Set ADMIN_KEY in the API's environment variables to enable it.",
        )
    if not key or not hmac.compare_digest(key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Wrong admin key.")


@app.get("/api/upload/status")
def upload_status():
    return {"enabled": bool(os.getenv("ADMIN_KEY")), "max_mb": MAX_UPLOAD_MB, "table": database.TABLE_NAME}


@app.post("/api/upload")
def upload(
    file: UploadFile = File(...),
    mode: str = Form("replace"),
    x_admin_key: str = Header(default=None),
):
    _require_admin(x_admin_key)
    if mode not in ("replace", "append"):
        raise HTTPException(status_code=400, detail="mode must be 'replace' or 'append'.")

    limit = MAX_UPLOAD_MB * 1024 * 1024
    raw = file.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_MB} MB.")

    try:
        df, report = ingest.prepare(raw, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if report["errors"]:
        raise HTTPException(status_code=422, detail=" ".join(report["errors"]))

    engine = database.get_engine()
    table = database.TABLE_NAME
    result = {"mode": mode, "rows": report["rows"], "columns": report["columns"], "warnings": report["warnings"]}

    if mode == "append":
        if table not in inspect(engine).get_table_names():
            raise HTTPException(status_code=400, detail="There is no saved data to add to yet. Use 'Replace all data'.")
        if database.score_scale() != report["scale"]:
            old = "0-1" if database.score_scale() == 1 else "0-100"
            new = "0-1" if report["scale"] == 1 else "0-100"
            raise HTTPException(
                status_code=422,
                detail=f"propensity_score scale differs: saved data is {old}, this file is {new}. "
                       "Convert the file to match, or use 'Replace all data'.",
            )
        try:
            result.update(ingest.append_rows(df, engine, table))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        ingest.replace_table(df, engine, table)

    ingest.post_load(engine, table, "customer_id" in df.columns, say=lambda _: None)
    database.reset_cache()
    result["total_customers"] = database.ping()["customers"]
    return result
