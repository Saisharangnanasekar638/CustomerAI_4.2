"""
CustomerAI Platform -- Streamlit frontend.

Run from the frontend/ folder:   streamlit run app.py
The API must be running first (see README.md). The API address comes from
API_BASE_URL in .env (default http://localhost:8000).
"""

import os
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lets the page reuse backend/ingest.py
try:
    from backend import ingest
except ImportError:  # frontend deployed without the backend folder
    ingest = None

from config.business_rules import (
    CUSTOMER_VALUE_WEIGHT,
    DIGITAL_ENGAGEMENT_WEIGHT,
    EXPECTED_REVENUE_SOURCE_COLUMNS,
    HIGH_PRIORITY_THRESHOLD,
    LIFETIME_VALUE_SOURCE_COLUMNS,
    MEDIUM_PRIORITY_THRESHOLD,
    PURCHASE_PROBABILITY_WEIGHT,
)
from src.priority_engine import apply_priority_engine, first_present
from styles import (
    get_css,
    hex_to_rgba,
    insight_html,
    kpi_strip,
    panel_header,
    plotly_layout,
    style_axes,
    tier_colors,
    tokens,
)

st.set_page_config(page_title="CustomerAI Platform", layout="wide", initial_sidebar_state="expanded")


def _secret(name):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


API_BASE = (os.getenv("API_BASE_URL") or _secret("API_BASE_URL") or "http://localhost:8000").rstrip("/")

st.session_state.setdefault("dark_mode", False)
st.session_state.setdefault("reset", 0)
DARK = bool(st.session_state["dark_mode"])
T = tokens(DARK)
TIER_COLORS = tier_colors(DARK)
TIER_ORDER = ["High", "Medium", "Low"]
PLOT_CONFIG = {"displayModeBar": False}

st.markdown(get_css(DARK), unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def num(value, default=0.0):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(v) else v


def inr_short(x) -> str:
    x = num(x)
    ax = abs(x)
    if ax >= 1e7:
        return f"₹{x / 1e7:,.2f} Cr"
    if ax >= 1e5:
        return f"₹{x / 1e5:,.1f} L"
    if ax >= 1e3:
        return f"₹{x / 1e3:,.1f} K"
    return f"₹{x:,.0f}"


def inr_axis(max_value: float, n: int = 5):
    vals = np.linspace(0, max(max_value, 1) * 1.12, n)
    return vals.tolist(), [inr_short(v) if v else "0" for v in vals]


def wrap(label, width: int = 22) -> str:
    """Break a long category name over several lines so it fits beside its bar."""
    text = str(label)
    return "<br>".join(textwrap.wrap(text, width=width, break_long_words=False)) or text


def tier_label(level: str) -> str:
    return f"{level} Priority"


@contextmanager
def panel(key: str, title: str, caption: str = None):
    with st.container(key=f"panel_{key}"):
        st.markdown(panel_header(title, caption), unsafe_allow_html=True)
        yield


def insight(text: str):
    st.markdown(insight_html(text), unsafe_allow_html=True)


def show(fig, key, height, select=False, extra_layout=None):
    fig.update_layout(**plotly_layout(DARK, height))
    if extra_layout:
        fig.update_layout(**extra_layout)
    kwargs = dict(key=key, theme=None, width="stretch", config=PLOT_CONFIG)
    if select:
        fig.update_layout(clickmode="event+select", dragmode=False)
        return st.plotly_chart(fig, on_select="rerun", selection_mode="points", **kwargs)
    return st.plotly_chart(fig, **kwargs)


def extract_click(event, field):
    if not event:
        return None
    selection = event.get("selection") if isinstance(event, dict) else getattr(event, "selection", None)
    points = (selection.get("points") if isinstance(selection, dict) else getattr(selection, "points", None)) if selection else None
    if not points:
        return None
    point = points[0]
    value = point.get(field) if isinstance(point, dict) else getattr(point, field, None)
    return value


def reset_clicks(*keys):
    for key in keys:
        st.session_state[key] = None
    st.session_state["reset"] += 1


def active_filter_bar(items: dict, clear_keys: tuple, button_key: str):
    active = {label: value for label, value in items.items() if value}
    if not active:
        return
    left, right = st.columns([6, 1])
    with left:
        st.caption("Filtered by chart click: " + ", ".join(f"{k} = {v}" for k, v in active.items()))
    with right:
        if st.button("Clear", key=button_key):
            reset_clicks(*clear_keys)
            st.rerun()


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def _detail(response) -> str:
    try:
        return response.json().get("detail") or response.text[:300]
    except Exception:
        return response.text[:300]


@st.cache_data(ttl=300, show_spinner="Loading customer data...")
def load_prepared(base_url: str, refresh: int):
    """Fetch every customer, derive the business fields, return (dataframe, notes, meta).
    Exceptions are raised (not cached) so a temporary outage is retried on the next run."""
    try:
        response = requests.get(f"{base_url}/api/customers", params={"limit": 50000}, timeout=90)
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach the API at {base_url}. Is it running? ({exc.__class__.__name__})")
    if not response.ok:
        raise RuntimeError(f"The API answered with an error ({response.status_code}): {_detail(response)}")

    return prepare_frame(pd.DataFrame(response.json()))


def prepare_frame(df: pd.DataFrame):
    """Derive the business fields from a raw customer table. Used for the saved
    data (load_prepared) and for a file checked on the Upload & Analyze page.
    Returns (dataframe, notes, meta); raises RuntimeError when the table cannot be used."""
    df = df.copy()
    if df.empty:
        raise RuntimeError("The customers table is empty. Load your data with scripts/load_data.py.")
    if "propensity_score" not in df.columns:
        raise RuntimeError("The customers table has no propensity_score column, which the dashboards need.")

    notes = []

    if "customer_id" not in df.columns:
        df["customer_id"] = df.index.astype(str)
        notes.append("customer_id (generated from the row number)")

    for column, default in [
        ("customer_segment", "Unsegmented"),
        ("state", "Unknown"),
        ("recommended_product", "Unassigned"),
        ("preferred_communication_channel", "Not specified"),
        ("campaign_response", "Not specified"),
        ("surname", ""),
    ]:
        if column not in df.columns:
            df[column] = default
            if column != "surname":
                notes.append(f"{column} (set to '{default}')")
        else:
            df[column] = df[column].fillna(default).astype(str)

    for column in ("credit_score", "missed_emis_last_12m", "mobile_app_logins_per_month", "balance"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    # Purchase probability: stored either as 0-1 or 0-100; everything downstream is 0-100.
    p = pd.to_numeric(df["propensity_score"], errors="coerce").fillna(0)
    scale_note = "0-1 probability, shown as a percentage" if p.max() <= 1.0 else "0-100 percentage"
    df["propensity_score"] = (p * 100 if p.max() <= 1.0 else p).clip(0, 100)

    if "age" in df.columns:
        age = pd.to_numeric(df["age"], errors="coerce")
        labels = ["18-25", "26-35", "36-45", "46-55", "56+"]
        df["age_band"] = pd.cut(age, bins=[0, 25, 35, 45, 55, 200], labels=labels).astype(str)
        df["age_band"] = df["age_band"].replace("nan", "Unknown")
    else:
        df["age_band"] = "All ages"
        notes.append("age (age-band charts show a single group)")

    revenue_col = first_present(df, EXPECTED_REVENUE_SOURCE_COLUMNS)
    df["expected_revenue"] = pd.to_numeric(df[revenue_col], errors="coerce").fillna(0) if revenue_col else 0.0
    if revenue_col is None:
        notes.append("expected revenue (no revenue or lifetime value column found; shown as 0)")
    ltv_col = first_present(df, LIFETIME_VALUE_SOURCE_COLUMNS)
    df["clv"] = pd.to_numeric(df[ltv_col], errors="coerce").fillna(0) if ltv_col else df["expected_revenue"]

    cluster_col = first_present(df, ["cluster_name", "cluster", "cluster_id"])
    if cluster_col:
        df["cluster_label"] = df[cluster_col].astype(str)
        cluster_title = "Customer Cluster"
    else:
        ranks = df["propensity_score"].rank(method="first")
        df["cluster_label"] = pd.qcut(ranks, 5, labels=["Quintile 1 (lowest)", "Quintile 2", "Quintile 3", "Quintile 4", "Quintile 5 (highest)"]).astype(str)
        cluster_title = "Propensity Quintile"
        notes.append("cluster (no cluster column found; customers are grouped into propensity quintiles instead)")

    df = apply_priority_engine(df, purchase_probability_col="propensity_score")
    meta = {
        "normalization": df.attrs.get("normalization"),
        "value_source": df.attrs.get("value_source"),
        "engagement_source": df.attrs.get("engagement_source"),
        "revenue_source": revenue_col,
        "ltv_source": ltv_col,
        "scale_note": scale_note,
        "cluster_title": cluster_title,
    }
    if meta["value_source"] is None:
        notes.append("customer value (no value column found; neutral 50 used in the priority score)")
    if meta["engagement_source"] is None:
        notes.append("digital engagement (no engagement column found; neutral 50 used in the priority score)")
    df["priority"] = df["priority_level"]
    return df, notes, meta


@st.cache_data(ttl=20, show_spinner=False)
def api_health(base_url: str):
    try:
        response = requests.get(f"{base_url}/api/health", timeout=8)
        if response.ok:
            return response.json()
        return {"error": _detail(response)}
    except requests.RequestException as exc:
        return {"error": f"unreachable ({exc.__class__.__name__})"}


def api_get(path, params=None):
    try:
        response = requests.get(f"{API_BASE}{path}", params=params, timeout=30)
        if not response.ok:
            st.error(_detail(response))
            return None
        return response.json()
    except requests.RequestException as exc:
        st.error(f"Could not reach the API at {API_BASE}. Is it running? ({exc.__class__.__name__})")
        return None


def api_post(path):
    try:
        response = requests.post(f"{API_BASE}{path}", timeout=30)
        if not response.ok:
            st.error(_detail(response))
            return None
        return response.json()
    except requests.RequestException as exc:
        st.error(f"Could not reach the API at {API_BASE}. Is it running? ({exc.__class__.__name__})")
        return None


BINARY_COLUMNS = {
    "has_cr_card": "Has Credit Card",
    "is_active_member": "Active Member",
    "purchased_new_product": "Purchased New Product",
    "exited": "Exited",
}


def humanize_binary_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for column, label in BINARY_COLUMNS.items():
        if column in out.columns:
            out[column] = out[column].map({1: "Yes", 0: "No", True: "Yes", False: "No"}).fillna(out[column])
            out = out.rename(columns={column: label})
    return out


def generate_reason(row: dict) -> str:
    factors = []
    credit = num(row.get("credit_score"))
    if credit >= 750:
        factors.append(("an excellent credit score", 3))
    elif credit >= 650:
        factors.append(("a good credit score", 1))
    elif credit > 0:
        factors.append(("a below-average credit score", -2))

    missed = num(row.get("missed_emis_last_12m"))
    if "missed_emis_last_12m" in row:
        if missed == 0:
            factors.append(("a clean repayment history", 3))
        elif missed <= 1:
            factors.append(("mostly on-time repayments", 1))
        else:
            factors.append((f"{int(missed)} missed EMIs in the past year", -3))

    logins = num(row.get("mobile_app_logins_per_month"))
    if "mobile_app_logins_per_month" in row:
        if logins >= 15:
            factors.append(("high digital engagement", 2))
        elif logins >= 5:
            factors.append(("moderate digital engagement", 1))
        else:
            factors.append(("low digital engagement", -1))

    if row.get("is_active_member") in (1, True):
        factors.append(("active membership status", 1))

    positives = sorted([f for f in factors if f[1] > 0], key=lambda x: -x[1])
    negatives = sorted([f for f in factors if f[1] < 0], key=lambda x: x[1])
    if positives:
        reason = "Flagged due to " + " and ".join(label for label, _ in positives[:2]) + "."
        if negatives and negatives[0][1] <= -3:
            reason += f" Caution: {negatives[0][0]}."
        return reason
    if negatives:
        return f"Limited positive signals; primary concern is {negatives[0][0]}."
    return "No strong signals either way; standard-priority contact."


def build_pitch_profile(customer: dict) -> dict:
    capable, incapable, products = [], [], []
    credit = num(customer.get("credit_score"))
    if credit >= 750:
        capable.append("Premium credit products (excellent credit score)")
        products.append("Premium Credit Card")
    elif 0 < credit < 650:
        incapable.append("High-limit credit products (below-average credit score)")

    missed = num(customer.get("missed_emis_last_12m"))
    if missed == 0:
        capable.append("Loan top-ups (clean repayment history)")
        products.append("Personal Loan Top-up")
    elif missed >= 2:
        incapable.append("New loan offers (recent missed EMIs; repayment risk)")

    logins = num(customer.get("mobile_app_logins_per_month"))
    if logins >= 15:
        capable.append("Digital-first and app-exclusive offers (high app engagement)")
    else:
        incapable.append("App-only campaigns (low digital engagement; use call or branch instead)")

    if customer.get("is_active_member") in (1, True):
        capable.append("Loyalty and relationship-based upsell (active member)")

    if num(customer.get("balance")) > 500000:
        capable.append("Wealth management and investment products (high account balance)")
        products.append("Investment / Mutual Fund Plan")

    if not products:
        products.append(customer.get("recommended_product") or "Savings Plan")

    channel = customer.get("preferred_communication_channel") or "Phone Call"
    snippet = "their clean repayment history" if missed == 0 else "their existing account relationship"
    return {
        "capable": capable or ["No standout strengths identified; treat as a standard profile"],
        "incapable": incapable or ["No major red flags identified"],
        "pitch_products": list(dict.fromkeys(products)),
        "talking_point": f"Reach out via {channel}. Lead with {products[0]}, referencing {snippet}.",
    }


# ----------------------------------------------------------------------------
# Load data (stop with a clear message if the API or database is not ready)
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Upload & Analyze page
# ----------------------------------------------------------------------------
TEMPLATE_COLUMNS = [
    "customer_id", "surname", "state", "age", "customer_segment", "recommended_product", "credit_score",
    "balance", "estimated_clv", "mobile_app_logins_per_month", "missed_emis_last_12m", "is_active_member",
    "preferred_communication_channel", "campaign_response", "propensity_score",
]


@st.cache_data(show_spinner="Checking the file...")
def check_upload(raw: bytes, filename: str):
    """Returns (dataframe, report) or raises ValueError with a plain message."""
    return ingest.prepare(raw, filename)


@st.cache_data(show_spinner=False)
def upload_status(base_url: str, refresh: int):
    try:
        response = requests.get(f"{base_url}/api/upload/status", timeout=8)
        return response.json() if response.ok else {"error": _detail(response)}
    except requests.RequestException as exc:
        return {"error": f"The API is unreachable ({exc.__class__.__name__})."}


def profile_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in df.columns:
        s = df[col]
        numeric = pd.api.types.is_numeric_dtype(s)
        rows.append({
            "Column": col,
            "Type": "number" if numeric else "text",
            "Missing %": round(float(s.isna().mean() * 100), 1),
            "Distinct values": int(s.nunique(dropna=True)),
            "Min": float(s.min()) if numeric and s.notna().any() else None,
            "Average": round(float(s.mean()), 2) if numeric and s.notna().any() else None,
            "Max": float(s.max()) if numeric and s.notna().any() else None,
        })
    return pd.DataFrame(rows)


def explore_tab(df: pd.DataFrame):
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c != "customer_id"]
    cat_cols = [c for c in df.columns if c not in numeric_cols and c != "customer_id" and 1 < df[c].nunique() <= 60]
    kinds = []
    if numeric_cols:
        kinds.append("Distribution of a number")
    if cat_cols:
        kinds.append("Customers per category")
    if cat_cols and numeric_cols:
        kinds.append("Compare categories on a number")
    if len(numeric_cols) >= 2:
        kinds.append("Relationship between two numbers")
    if not kinds:
        st.info("This file has no columns that can be charted. Check the Data profile tab.")
        return
    kind = st.selectbox("What do you want to see?", kinds, key="up_kind")
    nice = lambda c: c.replace("_", " ").title()

    if kind == "Distribution of a number":
        col = st.selectbox("Column", numeric_cols, key="up_dist_col", format_func=nice)
        values = df[col].dropna()
        fig = go.Figure(go.Histogram(
            x=values, nbinsx=30, marker=dict(color=T["accent"], line=dict(color=T["solid"], width=1)),
            hovertemplate=f"<b>{nice(col)}</b><br>Range: %{{x}}<br>Customers: %{{y:,}}<extra></extra>"))
        style_axes(fig, DARK, nice(col), "Customers", grid_x=False)
        show(fig, "up_hist", 430)
        insight(f"Median {values.median():,.2f}, average {values.mean():,.2f}, from {values.min():,.2f} to {values.max():,.2f} "
                f"across {len(values):,} customers with a value.")
    elif kind == "Customers per category":
        col = st.selectbox("Column", cat_cols, key="up_cat_col", format_func=nice)
        counts = df[col].astype(str).value_counts().head(15).sort_values()
        fig = go.Figure(go.Bar(
            x=counts.values, y=[wrap(i, 24) for i in counts.index], orientation="h", marker=dict(color=T["accent"]),
            customdata=(counts / counts.sum() * 100).round(1),
            hovertemplate=f"<b>%{{y}}</b><br>Customers: %{{x:,}}<br>Share: %{{customdata}}%<extra></extra>"))
        style_axes(fig, DARK, "Customers", None, grid_y=False)
        show(fig, "up_cat", max(380, 34 * len(counts) + 120))
        top = counts.index[-1]
        insight(f"'{top}' is the largest group with {counts.iloc[-1]:,} customers ({counts.iloc[-1] / counts.sum() * 100:.0f}% of those shown).")
    elif kind == "Compare categories on a number":
        c1, c2, c3 = st.columns(3)
        cat = c1.selectbox("Group by", cat_cols, key="up_cmp_cat", format_func=nice)
        val = c2.selectbox("Number", numeric_cols, key="up_cmp_val", format_func=nice)
        how = c3.selectbox("Measure", ["Average", "Total", "Median"], key="up_cmp_how")
        agg = {"Average": "mean", "Total": "sum", "Median": "median"}[how]
        grouped = df.groupby(df[cat].astype(str))[val].agg(agg).sort_values().tail(15)
        sizes = df[cat].astype(str).value_counts()
        fig = go.Figure(go.Bar(
            x=grouped.values, y=[wrap(i, 24) for i in grouped.index], orientation="h", marker=dict(color=T["accent"]),
            customdata=[int(sizes.get(i, 0)) for i in grouped.index],
            hovertemplate=f"<b>%{{y}}</b><br>{how} {nice(val)}: %{{x:,.2f}}<br>Customers in group: %{{customdata:,}}<extra></extra>"))
        style_axes(fig, DARK, f"{how} {nice(val)}", None, grid_y=False)
        show(fig, "up_cmp", max(380, 34 * len(grouped) + 120))
        insight(f"'{grouped.index[-1]}' has the highest {how.lower()} {nice(val).lower()} ({grouped.iloc[-1]:,.2f}); "
                f"'{grouped.index[0]}' has the lowest ({grouped.iloc[0]:,.2f}).")
    else:
        c1, c2 = st.columns(2)
        x = c1.selectbox("Horizontal axis", numeric_cols, key="up_sc_x", format_func=nice)
        y = c2.selectbox("Vertical axis", numeric_cols, index=min(1, len(numeric_cols) - 1), key="up_sc_y", format_func=nice)
        pair = df[[x, y]].dropna()
        sample = pair.sample(min(len(pair), 3000), random_state=1)
        fig = go.Figure(go.Scattergl(
            x=sample[x], y=sample[y], mode="markers", marker=dict(color=T["accent"], size=6, opacity=0.5),
            hovertemplate=f"{nice(x)}: %{{x:,.2f}}<br>{nice(y)}: %{{y:,.2f}}<extra></extra>"))
        style_axes(fig, DARK, nice(x), nice(y))
        show(fig, "up_sc", 450)
        corr = pair[x].corr(pair[y]) if len(pair) > 2 else float("nan")
        strength = "strong" if abs(corr) >= 0.6 else "moderate" if abs(corr) >= 0.3 else "weak"
        insight(f"Correlation {corr:+.2f}: a {strength} {'positive' if corr > 0 else 'negative'} relationship. "
                f"Correlation shows that two columns move together, not that one causes the other."
                + (f" Showing a random {len(sample):,} of {len(pair):,} customers." if len(pair) > len(sample) else ""))


def priority_tab(df: pd.DataFrame):
    try:
        scored, notes, pmeta = prepare_frame(df)
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    counts = scored["priority_level"].value_counts().reindex(TIER_ORDER).fillna(0).astype(int)
    st.markdown(kpi_strip([
        {"title": "Customers", "value": f"{len(scored):,}"},
        {"title": "High priority", "value": f"{counts['High']:,}", "sub": f"{counts['High'] / len(scored):.0%} of file",
         "accent": TIER_COLORS["High"], "tip_title": "High priority",
         "tip": f"Priority score of {HIGH_PRIORITY_THRESHOLD} or more."},
        {"title": "Medium priority", "value": f"{counts['Medium']:,}", "sub": f"{counts['Medium'] / len(scored):.0%} of file",
         "accent": TIER_COLORS["Medium"], "tip_title": "Medium priority",
         "tip": f"Priority score from {MEDIUM_PRIORITY_THRESHOLD} to just under {HIGH_PRIORITY_THRESHOLD}."},
        {"title": "Low priority", "value": f"{counts['Low']:,}", "sub": f"{counts['Low'] / len(scored):.0%} of file",
         "accent": TIER_COLORS["Low"], "tip_title": "Low priority", "tip": f"Priority score below {MEDIUM_PRIORITY_THRESHOLD}."},
    ]), unsafe_allow_html=True)
    fig = go.Figure(go.Bar(
        x=[tier_label(t) for t in TIER_ORDER], y=counts.values, marker=dict(color=[TIER_COLORS[t] for t in TIER_ORDER]),
        text=[f"{v:,}" for v in counts.values], textposition="outside", cliponaxis=False,
        customdata=[f"{v / len(scored):.1%}" for v in counts.values],
        hovertemplate="<b>%{x}</b><br>Customers: %{y:,}<br>Share of file: %{customdata}<extra></extra>"))
    style_axes(fig, DARK, None, "Customers", grid_x=False)
    show(fig, "up_tiers", 380, extra_layout=dict(bargap=0.45))
    insight(f"Priority score = {PURCHASE_PROBABILITY_WEIGHT:.0%} purchase probability + {CUSTOMER_VALUE_WEIGHT:.0%} customer value "
            f"+ {DIGITAL_ENGAGEMENT_WEIGHT:.0%} digital engagement. Value came from "
            f"{pmeta['value_source'] or 'no column (neutral 50)'}, engagement from {pmeta['engagement_source'] or 'no column (neutral 50)'}.")
    if notes:
        st.caption("Defaults used because the file lacks: " + "; ".join(notes))
    top_n = st.slider("How many top customers to list", 10, 200, 25, step=5, key="up_topn")
    cols = [c for c in ["customer_id", "surname", "customer_segment", "recommended_product", "propensity_score",
                        "customer_value_score", "digital_engagement_score", "priority_score", "priority_level",
                        "recommended_action"] if c in scored.columns]
    top = scored.sort_values("priority_score", ascending=False).head(top_n)[cols].round(1)
    st.dataframe(top, width="stretch", hide_index=True)
    st.download_button("Download the full scored file as CSV", scored[cols].round(2).to_csv(index=False).encode("utf-8"),
                       file_name="scored_customers.csv", mime="text/csv", key="up_scored_dl")


def save_panel(file, report):
    status = upload_status(API_BASE, st.session_state["reset"])
    if "error" in status:
        st.warning("Saving is not available right now. " + status["error"])
        return
    if not status.get("enabled"):
        st.info("Saving to the shared database is switched off on this API. Set an ADMIN_KEY environment variable "
                "on the API server (see SETUP.md) to turn it on. You can still analyze files above without saving.")
        return
    if report["errors"]:
        st.error("This file cannot be saved until the problems listed in the file check are fixed.")
        return
    st.markdown("Saved data feeds every other page. The file is checked again on the server before anything is written.")
    mode_label = st.radio("What should happen to the data already saved?",
                          ["Replace all saved data with this file", "Add these customers to the saved data"],
                          key="up_mode")
    mode = "replace" if mode_label.startswith("Replace") else "append"
    if mode == "append":
        st.caption("A customer whose customer_id is already saved is updated with the new row. The file's columns "
                   "must already exist in the saved table, and propensity_score must use the same scale.")
    key = st.text_input("Admin key", type="password", key="up_admin_key",
                        help="The ADMIN_KEY set on the API server. It stops strangers from changing your data.")
    confirm = st.checkbox("I understand this changes the data that every dashboard shows.", key="up_confirm")
    if st.button("Save to database", type="primary", disabled=not (key and confirm), key="up_save"):
        try:
            with st.spinner("Saving..."):
                response = requests.post(
                    f"{API_BASE}/api/upload", headers={"X-Admin-Key": key}, data={"mode": mode},
                    files={"file": (file.name, file.getvalue())}, timeout=300)
        except requests.RequestException as exc:
            st.error(f"Could not reach the API ({exc.__class__.__name__}).")
            return
        if not response.ok:
            st.error(_detail(response))
            return
        result = response.json()
        load_prepared.clear()
        api_health.clear()
        st.session_state["reset"] += 1
        extra = f" {result['replaced_existing']:,} existing customers were updated." if result.get("replaced_existing") else ""
        st.success(f"Saved {result['rows']:,} customers. The database now holds {result['total_customers']:,}.{extra} "
                   "Open any other page to see them.")
        for w in result.get("warnings", []):
            st.caption(w)


def upload_page():
    st.markdown('<div class="eyebrow">CustomerAI Platform</div>', unsafe_allow_html=True)
    st.title("Upload and Analyze")
    st.markdown('<div class="subtitle">Bring your own customer file. Check it, analyze it right here, and save it '
                'to the database so every other page shows it.</div>', unsafe_allow_html=True)
    if ingest is None:
        st.error("The upload tools (backend/ingest.py) were not found next to the frontend. Deploy the whole "
                 "project folder, not only frontend/.")
        return

    with panel("up_file", "1. Choose a file", "CSV or Excel. One row per customer. Headers like CustomerID or Credit Score are fine; "
                                               "they are converted automatically."):
        file = st.file_uploader("Customer file", type=["csv", "xlsx", "xls"], key="up_file", label_visibility="collapsed")
        template = pd.DataFrame(columns=TEMPLATE_COLUMNS).to_csv(index=False).encode("utf-8")
        st.download_button("Download an empty template (CSV)", template, file_name="customer_template.csv",
                           mime="text/csv", key="up_template",
                           help="Required: customer_id and propensity_score (0-1 or 0-100). The rest improves the analysis.")
    if file is None:
        st.caption("Nothing is saved until you press Save in step 4. Analysis in step 3 runs on your file only.")
        return

    try:
        df, report = check_upload(file.getvalue(), file.name)
    except ValueError as exc:
        st.error(str(exc))
        return

    with panel("up_check", "2. File check"):
        scale = {1: "0 to 1", 100: "0 to 100", None: "not found"}[report["scale"]]
        st.markdown(kpi_strip([
            {"title": "Rows", "value": f"{report['rows']:,}"},
            {"title": "Columns", "value": f"{report['columns']:,}"},
            {"title": "Propensity scale", "value": scale},
            {"title": "Blocking problems", "value": str(len(report["errors"])),
             "accent": TIER_COLORS["High"] if report["errors"] else None},
        ]), unsafe_allow_html=True)
        for message in report["errors"]:
            st.error(message)
        for message in report["warnings"]:
            st.warning(message)
        if report["converted_numbers"]:
            st.caption("Text converted to numbers: " + ", ".join(report["converted_numbers"]))
        if report["converted_flags"]:
            st.caption("Yes/No converted to 1/0: " + ", ".join(report["converted_flags"]))
        if report["missing_recommended"]:
            st.caption("Not in the file (the dashboards use defaults): " + ", ".join(report["missing_recommended"]))
        if not report["errors"] and not report["warnings"]:
            st.success("The file is ready to analyze and save.")

    with panel("up_analysis", "3. Analyze", "Runs on your uploaded file only. Nothing here changes the saved data."):
        has_priority = "propensity_score" in df.columns and report["scale"] is not None
        tabs = st.tabs((["Priority customers"] if has_priority else []) + ["Explore any column", "Data profile"])
        i = 0
        if has_priority:
            with tabs[0]:
                priority_tab(df)
            i = 1
        with tabs[i]:
            explore_tab(df)
        with tabs[i + 1]:
            st.dataframe(profile_table(df), width="stretch", hide_index=True)
            st.markdown("**First rows**")
            st.dataframe(df.head(50), width="stretch", hide_index=True)

    with panel("up_save", "4. Save to the database", "Optional. Saving makes the file the data behind every dashboard."):
        save_panel(file, report)


NAV_OPTIONS = {
    "Business Overview": "overview",
    "Sales Action Center": "actions",
    "Customer Search": "search",
    "Data Explorer": "explorer",
    "Upload and Analyze": "upload",
}

with st.sidebar:
    st.markdown(
        '<div class="brand-name">CustomerAI</div><div class="brand-tag">Customer Intelligence Platform</div>',
        unsafe_allow_html=True,
    )
    nav_label = st.radio("Navigation", list(NAV_OPTIONS.keys()), label_visibility="collapsed")
    st.divider()
    st.toggle("Dark theme", key="dark_mode")
    if st.button("Refresh data", width="stretch"):
        load_prepared.clear()
        api_health.clear()
        st.session_state["reset"] += 1
        st.rerun()
    health = api_health(API_BASE)
    if "error" in health:
        st.markdown(f'<span class="status-pill status-bad">Database offline</span>', unsafe_allow_html=True)
        st.caption(str(health["error"])[:160])
    else:
        st.markdown(
            f'<span class="status-pill">Connected to <b>{health.get("dialect", "database")}</b> '
            f'| {health.get("customers", 0):,} customers</span>',
            unsafe_allow_html=True,
        )

view = NAV_OPTIONS[nav_label]

if view == "upload":  # works even before any data is saved, so a first upload is possible
    try:
        upload_page()
    except Exception as exc:
        st.error("Something broke while rendering this page. Full error below:")
        st.exception(exc)
    st.stop()

try:
    df_all, data_notes, meta = load_prepared(API_BASE, st.session_state["reset"])
except RuntimeError as exc:
    st.markdown('<div class="eyebrow">CustomerAI Platform</div>', unsafe_allow_html=True)
    st.title("Data not available")
    st.error(str(exc))
    st.markdown(
        "If this is a brand new database, open **Upload and Analyze** in the sidebar and save your first file there. "
        "Otherwise check that the API is running (`uvicorn backend.main:app --port 8000` from the project folder), "
        "that `.env` points to your database, and that `python scripts/check_connection.py` passes."
    )
    st.stop()

if view in ("overview", "actions"):
    st.markdown('<div class="eyebrow">CustomerAI Platform</div>', unsafe_allow_html=True)

try:
    # ==================================================================
    # PAGE 1: Business Performance Overview
    # ==================================================================
    if view == "overview":
        st.title("Customer Propensity and Revenue Opportunity")
        st.markdown('<div class="subtitle">Where is the biggest business opportunity? Customer analytics and AI-driven sales intelligence.</div>', unsafe_allow_html=True)

        f1, f2, f3 = st.columns(3)
        with f1:
            f_priority = st.multiselect("Priority", TIER_ORDER, help="Show only customers at these business priority levels.")
        with f2:
            f_state = st.multiselect("State", sorted(df_all["state"].unique().tolist()), help="Show only customers located in these states.")
        with f3:
            f_persona = st.multiselect("Persona", sorted(df_all["customer_segment"].unique().tolist()), help="Show only customers in these segments.")

        df = df_all
        if f_priority:
            df = df[df["priority_level"].isin(f_priority)]
        if f_state:
            df = df[df["state"].isin(f_state)]
        if f_persona:
            df = df[df["customer_segment"].isin(f_persona)]

        click_product = st.session_state.get("click_product")
        click_persona = st.session_state.get("click_persona")
        if click_product:
            df = df[df["recommended_product"] == click_product]
        if click_persona:
            df = df[df["customer_segment"] == click_persona]
        active_filter_bar(
            {"Product": click_product, "Persona": click_persona},
            ("click_product", "click_persona"),
            "clear_overview_clicks",
        )

        if df.empty:
            st.info("No customers match the current filters. Clear a filter to continue.")
            st.stop()

        total = len(df)
        high_n = int((df["priority_level"] == "High").sum())
        revenue_total = float(df["expected_revenue"].sum())

        st.markdown(
            kpi_strip(
                [
                    {
                        "title": "Total Customers", "value": f"{total:,}", "accent": T["accent"],
                        "sub": "of {:,} in database".format(len(df_all)) if total != len(df_all) else "in database",
                        "tip": "Shows the total number of unique customers currently included in the analysis after applying all dashboard filters.",
                    },
                    {
                        "title": "High Priority Customers", "value": f"{high_n:,}", "accent": T["gold"],
                        "sub": f"{high_n / total:.1%} of selection",
                        "tip": "Shows customers with a high predicted probability of purchasing an additional product. These customers should receive priority attention from sales and marketing teams.",
                    },
                    {
                        "title": "Avg. Purchase Probability", "value": f"{df['propensity_score'].mean():.1f}%", "accent": T["accent2"],
                        "sub": "selection average",
                        "tip": "Shows the average predicted likelihood of customers purchasing an additional product within the currently selected customer population.",
                    },
                    {
                        "title": "Avg. Priority Score", "value": f"{df['priority_score'].mean():.1f}", "accent": T["slate"],
                        "sub": "out of 100",
                        "tip": (f"Average business priority score: {PURCHASE_PROBABILITY_WEIGHT:.0%} purchase probability, "
                                f"{CUSTOMER_VALUE_WEIGHT:.0%} customer value and {DIGITAL_ENGAGEMENT_WEIGHT:.0%} digital engagement. "
                                f"High is {HIGH_PRIORITY_THRESHOLD} or above, Medium is {MEDIUM_PRIORITY_THRESHOLD} or above."),
                    },
                    {
                        "title": "Expected Revenue", "value": inr_short(revenue_total), "accent": T["green"],
                        "sub": f"{inr_short(revenue_total / total)} per customer",
                        "tip": "Estimated business opportunity calculated using customer purchase probability and illustrative product-level revenue assumptions.",
                    },
                ]
            ),
            unsafe_allow_html=True,
        )

        # ---- Compact snapshot row (small charts) ----
        age_order = [a for a in ["18-25", "26-35", "36-45", "46-55", "56+", "Unknown", "All ages"] if a in df["age_band"].unique()]
        by_age = (
            df.groupby("age_band")
            .agg(customers=("customer_id", "count"), revenue=("expected_revenue", "sum"), prob=("propensity_score", "mean"))
            .reindex(age_order)
            .fillna(0)
            .reset_index()
        )
        by_age["share"] = by_age["customers"] / total * 100
        by_age["rev_share"] = by_age["revenue"] / max(revenue_total, 1) * 100
        by_age["rev_txt"] = by_age["revenue"].map(inr_short)

        def mini(title, x, y, hover, custom, key):
            st.markdown(f'<div class="mini-label">{title}</div>', unsafe_allow_html=True)
            fig = go.Figure(go.Bar(x=x, y=y, marker=dict(color=hex_to_rgba(T["accent"], 0.85), line=dict(width=0)), customdata=custom, hovertemplate=hover))
            style_axes(fig, DARK, grid_x=False, grid_y=False)
            fig.update_yaxes(visible=False)
            fig.update_xaxes(tickfont=dict(size=10, color=T["muted"]))
            show(fig, key, 100, extra_layout=dict(margin=dict(l=2, r=2, t=4, b=2), bargap=0.28))

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            mini("Customers by age", by_age["age_band"], by_age["customers"],
                 "<b>Age %{x}</b><br>Customers: %{y:,}<br>Share of selection: %{customdata[0]:.1f}%<extra></extra>",
                 by_age[["share"]].values.tolist(), "mini_age_customers")
        with m2:
            mini("Revenue by age", by_age["age_band"], by_age["revenue"],
                 "<b>Age %{x}</b><br>Expected revenue: %{customdata[0]}<br>Share of revenue: %{customdata[1]:.1f}%<extra></extra>",
                 by_age[["rev_txt", "rev_share"]].values.tolist(), "mini_age_revenue")
        with m3:
            lvl = df["priority_level"].value_counts().reindex(TIER_ORDER).fillna(0)
            mini("Priority split", [tier_label(i) for i in TIER_ORDER], lvl.values,
                 "<b>%{x}</b><br>Customers: %{y:,}<br>Share of selection: %{customdata[0]:.1f}%<extra></extra>",
                 [[v / total * 100] for v in lvl.values], "mini_priority")
        with m4:
            mini("Avg. probability by age", by_age["age_band"], by_age["prob"],
                 "<b>Age %{x}</b><br>Avg. purchase probability: %{y:.1f}%<br>Customers: %{customdata[0]:,}<extra></extra>",
                 by_age[["customers"]].values.tolist(), "mini_age_prob")

        # ---- Row A: revenue by product + priority donut ----
        col_a, col_b = st.columns([3, 2])
        with col_a:
            with panel("rev_product", "Revenue Opportunity by Recommended Product",
                       "Total expected revenue per recommended product. Click a bar to filter the whole page to that product."):
                g = (df.groupby("recommended_product")
                       .agg(revenue=("expected_revenue", "sum"), customers=("customer_id", "count"), prob=("propensity_score", "mean"))
                       .reset_index().sort_values("revenue"))
                g["share"] = g["revenue"] / max(g["revenue"].sum(), 1) * 100
                g["rev_txt"] = g["revenue"].map(inr_short)
                colors = [T["accent"] if i == len(g) - 1 else hex_to_rgba(T["accent"], 0.55) for i in range(len(g))]
                fig = go.Figure(go.Bar(
                    x=g["revenue"], y=g["recommended_product"], orientation="h",
                    marker=dict(color=colors, line=dict(width=0)),
                    text=g["rev_txt"], textposition="outside", cliponaxis=False, textfont=dict(size=12, color=T["text"]),
                    customdata=g[["rev_txt", "customers", "prob", "share"]].values.tolist(),
                    hovertemplate=("<b>%{y}</b><br>Total Expected Revenue: %{customdata[0]}<br>"
                                   "Customers Recommended This Product: %{customdata[1]:,}<br>"
                                   "Average Purchase Probability: %{customdata[2]:.1f}%<br>"
                                   "Share of Expected Revenue: %{customdata[3]:.1f}%<extra></extra>"),
                ))
                tickvals, ticktext = inr_axis(g["revenue"].max())
                style_axes(fig, DARK, x_title="Total Expected Revenue", grid_y=False)
                fig.update_xaxes(tickvals=tickvals, ticktext=ticktext, range=[0, g["revenue"].max() * 1.25])
                fig.update_yaxes(tickmode="array", tickvals=g["recommended_product"].tolist(), ticktext=[wrap(x) for x in g["recommended_product"]])
                fig.add_vline(x=g["revenue"].mean(), line_dash="dot", line_color=T["muted"], line_width=1.2)
                fig.add_annotation(x=g["revenue"].mean(), y=1, xref="x", yref="paper", yanchor="bottom", xanchor="center", showarrow=False,
                                   text=f"Average per product: {inr_short(g['revenue'].mean())}", font=dict(size=11, color=T["muted"]))
                event = show(fig, f"rev_product_{st.session_state['reset']}", max(400, 62 * len(g) + 110), select=True,
                             extra_layout=dict(margin=dict(l=150, r=22, t=40, b=6)))
                clicked = extract_click(event, "y")
                if clicked and clicked != click_product:
                    st.session_state["click_product"] = clicked
                    st.rerun()
                top = g.iloc[-1]
                low = g.iloc[0]
                insight(f"<b>{top['recommended_product']}</b> is the largest opportunity at {top['rev_txt']} "
                        f"({top['share']:.0f}% of expected revenue across {int(top['customers']):,} customers). "
                        f"The smallest is {low['recommended_product']} at {low['rev_txt']}.")
        with col_b:
            with panel("priority_donut", "Customer Priority Distribution",
                       "How many customers require immediate attention, by business priority level."):
                dg = (df.groupby("priority_level")
                        .agg(customers=("customer_id", "count"), prob=("propensity_score", "mean"), pscore=("priority_score", "mean"),
                             value=("customer_value_score", "mean"), revenue=("expected_revenue", "sum"))
                        .reindex(TIER_ORDER).fillna(0).reset_index())
                dg["rev_txt"] = dg["revenue"].map(inr_short)
                fig = go.Figure(go.Pie(
                    labels=[tier_label(i) for i in dg["priority_level"]], values=dg["customers"], hole=0.64, sort=False,
                    marker=dict(colors=[TIER_COLORS[i] for i in dg["priority_level"]], line=dict(color=T["solid"], width=2)),
                    text=[f"{v / total:.1%}" if v else "" for v in dg["customers"]],  # no "0%" label on an empty tier
                    textinfo="text", textfont=dict(size=13, color="#FFFFFF"), direction="clockwise",
                    customdata=dg[["prob", "pscore", "value", "rev_txt"]].values.tolist(),
                    hovertemplate=("<b>%{label}</b><br>Number of Customers: %{value:,}<br>"
                                   "Percentage of Customers: %{percent:.1%}<br>"
                                   "Average Purchase Probability: %{customdata[0]:.1f}%<br>"
                                   "Average Priority Score: %{customdata[1]:.1f}<br>"
                                   "Average Customer Value: %{customdata[2]:.1f}<br>"
                                   "Expected Revenue: %{customdata[3]}<extra></extra>"),
                ))
                fig.add_annotation(text=f"<b>{total:,}</b><br><span style='font-size:12px'>customers</span>", showarrow=False,
                                   font=dict(size=26, color=T["text"]))
                show(fig, "donut_priority", max(400, 62 * df["recommended_product"].nunique() + 110),
                     extra_layout=dict(showlegend=True, legend=dict(orientation="h", y=-0.04, x=0.5, xanchor="center", font=dict(size=12)),
                                       margin=dict(l=6, r=6, t=10, b=34)))
                hi_rev = float(dg.loc[dg["priority_level"] == "High", "revenue"].iloc[0])
                if high_n:
                    insight(f"<b>{high_n:,} customers ({high_n / total:.1%})</b> are High priority and carry "
                            f"{inr_short(hi_rev)} of expected revenue ({hi_rev / max(revenue_total, 1):.0%} of the total).")
                else:
                    insight(f"No customer reaches High priority at the current threshold of {HIGH_PRIORITY_THRESHOLD}; the highest "
                            f"priority score in this selection is <b>{df['priority_score'].max():.1f}</b>. Weights and thresholds can be "
                            f"changed in config/business_rules.py.")

        # ---- Row B: probability histogram + persona ----
        col_c, col_d = st.columns(2)
        with col_c:
            with panel("prob_hist", "Purchase Probability Distribution",
                       "Are most customers low, medium or high potential? Customers per 10-point probability band."):
                edges = np.arange(0, 101, 10)
                counts, _ = np.histogram(df["propensity_score"].clip(0, 100), bins=edges)
                share = counts / total * 100
                labels = [f"{a}-{b}%" for a, b in zip(edges[:-1], edges[1:])]
                centers = (edges[:-1] + edges[1:]) / 2
                fig = go.Figure(go.Bar(
                    x=centers, y=counts, width=9, marker=dict(color=hex_to_rgba(T["accent"], 0.85), line=dict(width=0)),
                    text=[f"{c:,}" if c else "" for c in counts], textposition="outside", cliponaxis=False,
                    textfont=dict(size=11, color=T["text"]),
                    customdata=[[lab, s] for lab, s in zip(labels, share)],
                    hovertemplate=("<b>Purchase Probability Range: %{customdata[0]}</b><br>Number of Customers: %{y:,}<br>"
                                   "Percentage of Customers: %{customdata[1]:.1f}%<extra></extra>"),
                ))
                style_axes(fig, DARK, x_title="Purchase Probability", y_title="Number of Customers", grid_x=False)
                fig.update_xaxes(tickvals=edges.tolist(), ticktext=[f"{e}%" for e in edges], range=[0, 100])
                fig.update_yaxes(range=[0, max(counts.max(), 1) * 1.18])
                median = float(df["propensity_score"].median())
                fig.add_vline(x=median, line_dash="dot", line_color=T["gold"], line_width=1.6,
                              annotation_text=f"Median {median:.0f}%", annotation_position="top right",
                              annotation_font=dict(size=11, color=T["gold"]))
                show(fig, "prob_hist", 400)
                high_share = float((df["propensity_score"] >= 60).mean() * 100)
                insight(f"The median customer has a <b>{median:.0f}%</b> purchase probability, and "
                        f"<b>{high_share:.1f}%</b> of customers score 60% or higher.")
        with col_d:
            with panel("persona", "Customer Persona",
                       "Customers per persona. Click a bar to filter the page to that persona."):
                pg = (df.groupby("customer_segment")
                        .agg(customers=("customer_id", "count"), prob=("propensity_score", "mean"), revenue=("expected_revenue", "sum"))
                        .reset_index().sort_values("customers"))
                pg["share"] = pg["customers"] / total * 100
                pg["rev_txt"] = pg["revenue"].map(inr_short)
                colors = [T["accent"] if i == len(pg) - 1 else hex_to_rgba(T["accent"], 0.55) for i in range(len(pg))]
                fig = go.Figure(go.Bar(
                    x=pg["customers"], y=pg["customer_segment"], orientation="h", marker=dict(color=colors, line=dict(width=0)),
                    text=[f"{c:,} ({s:.0f}%)" for c, s in zip(pg["customers"], pg["share"])], textposition="outside",
                    cliponaxis=False, textfont=dict(size=12, color=T["text"]),
                    customdata=pg[["share", "prob", "rev_txt"]].values.tolist(),
                    hovertemplate=("<b>%{y}</b><br>Customers: %{x:,}<br>Percentage of Total Customers: %{customdata[0]:.1f}%<br>"
                                   "Average Purchase Probability: %{customdata[1]:.1f}%<br>Expected Revenue: %{customdata[2]}<extra></extra>"),
                ))
                style_axes(fig, DARK, x_title="Number of Customers", grid_y=False)
                fig.update_xaxes(range=[0, pg["customers"].max() * 1.28])
                fig.update_yaxes(tickmode="array", tickvals=pg["customer_segment"].tolist(), ticktext=[wrap(x) for x in pg["customer_segment"]])
                fig.add_vline(x=pg["customers"].mean(), line_dash="dot", line_color=T["muted"], line_width=1.2)
                fig.add_annotation(x=pg["customers"].mean(), y=1, xref="x", yref="paper", yanchor="bottom", xanchor="center", showarrow=False,
                                   text=f"Average per persona: {pg['customers'].mean():,.0f}", font=dict(size=11, color=T["muted"]))
                event = show(fig, f"persona_{st.session_state['reset']}", 400, select=True,
                             extra_layout=dict(margin=dict(l=150, r=22, t=40, b=6)))
                clicked = extract_click(event, "y")
                if clicked and clicked != click_persona:
                    st.session_state["click_persona"] = clicked
                    st.rerun()
                best = pg.sort_values("prob").iloc[-1]
                insight(f"<b>{pg.iloc[-1]['customer_segment']}</b> is the largest persona ({pg.iloc[-1]['share']:.0f}% of customers). "
                        f"<b>{best['customer_segment']}</b> has the highest average purchase probability ({best['prob']:.1f}%).")

        # ---- Opportunity chart ----
        with panel("opportunity", "Customer Opportunity Chart",
                   "Purchase probability against business priority. Bubble size is customer lifetime value and colour is priority level. "
                   "The shaded zone marks customers with both strong likelihood and strong value."):
            PER_TIER = 1000  # fixed seed: the same customers are drawn on every rerun
            shown = pd.concat([sub.sample(min(len(sub), PER_TIER), random_state=7) for _, sub in df.groupby("priority_level")])
            cap = float(shown["clv"].quantile(0.99)) if len(shown) else 1.0
            sizes = shown["clv"].clip(lower=0, upper=max(cap, 1))
            sizeref = 2.0 * max(sizes.max(), 1) / (26.0 ** 2)
            y_lo = max(0.0, float(shown["priority_score"].min()) - 5)
            y_hi = min(102.0, max(float(shown["priority_score"].max()) + 6, MEDIUM_PRIORITY_THRESHOLD + 8))
            fig = go.Figure()
            fig.add_shape(type="rect", x0=60, x1=100, y0=MEDIUM_PRIORITY_THRESHOLD, y1=y_hi, layer="below", line=dict(width=0),
                          fillcolor=hex_to_rgba(T["accent"], 0.07))
            fig.add_annotation(x=61, y=y_hi - 0.5, text="Strongest opportunities", showarrow=False, xanchor="left", yanchor="top",
                               font=dict(size=11.5, color=T["accent"]))
            for threshold, label in ((HIGH_PRIORITY_THRESHOLD, "High priority from"), (MEDIUM_PRIORITY_THRESHOLD, "Medium priority from")):
                if y_lo < threshold < y_hi:
                    fig.add_hline(y=threshold, line_dash="dot", line_color=T["muted"], line_width=1.1,
                                  annotation_text=f"{label} {threshold}", annotation_position="bottom left",
                                  annotation_font=dict(size=10.5, color=T["muted"]))
            for level in TIER_ORDER:
                mask = shown["priority_level"] == level
                sub = shown[mask]
                if sub.empty:
                    continue
                fig.add_trace(go.Scatter(
                    x=sub["propensity_score"], y=sub["priority_score"], mode="markers", name=tier_label(level),
                    marker=dict(size=sizes[mask], sizemode="area", sizeref=sizeref, sizemin=4, color=TIER_COLORS[level],
                                opacity=0.72, line=dict(width=0.6, color=T["solid"])),
                    customdata=np.column_stack([
                        sub["customer_id"].astype(str), sub["clv"].map(inr_short), sub["digital_engagement_score"].round(0),
                        sub["recommended_product"], sub["expected_revenue"].map(inr_short),
                    ]).tolist(),
                    hovertemplate=("<b>Customer %{customdata[0]}</b><br>Purchase Probability: %{x:.1f}%<br>Priority Score: %{y:.1f}<br>"
                                   "Priority Level: " + level + "<br>Customer Lifetime Value: %{customdata[1]}<br>"
                                   "Digital Engagement: %{customdata[2]}<br>Recommended Product: %{customdata[3]}<br>"
                                   "Expected Revenue: %{customdata[4]}<extra></extra>"),
                ))
            style_axes(fig, DARK, x_title="Purchase Probability (%)", y_title="Priority Score")
            fig.update_xaxes(range=[0, 102])
            fig.update_yaxes(range=[y_lo, y_hi])
            show(fig, "opportunity", 500, extra_layout=dict(
                showlegend=True, legend=dict(orientation="h", y=1.07, x=0, font=dict(size=12)), margin=dict(l=6, r=22, t=34, b=6)))
            zone = int(((df["propensity_score"] >= 60) & (df["priority_score"] >= MEDIUM_PRIORITY_THRESHOLD)).sum())
            note = (f" Showing {len(shown):,} of {total:,} customers: a random sample of up to {PER_TIER:,} per priority level, "
                    f"so every level is visible." if total > len(shown) else "")
            insight(f"<b>{zone:,} customers</b> sit in the strongest-opportunity zone (purchase probability of 60% or more and a "
                    f"priority score of {MEDIUM_PRIORITY_THRESHOLD} or more).{note}")

        # ---- Opportunity matrix table ----
        with panel("matrix", "Customer Opportunity Matrix",
                   "Top 200 customers ranked by priority score, then purchase probability. Purchase probability is the model output; "
                   "priority score is the business decision built on it."):
            cols = ["customer_id", "surname", "priority_level", "propensity_score", "priority_score", "customer_value_score",
                    "digital_engagement_score", "expected_revenue", "recommended_product", "recommended_action"]
            matrix = df.sort_values(["priority_score", "propensity_score"], ascending=False)[[c for c in cols if c in df.columns]].head(200)
            st.dataframe(
                matrix, width="stretch", hide_index=True,
                column_config={
                    "customer_id": "Customer ID", "surname": "Surname", "priority_level": "Priority",
                    "propensity_score": st.column_config.ProgressColumn("Purchase Probability", min_value=0, max_value=100, format="%.0f%%"),
                    "priority_score": st.column_config.ProgressColumn("Priority Score", min_value=0, max_value=100, format="%.0f"),
                    "customer_value_score": st.column_config.ProgressColumn("Customer Value", min_value=0, max_value=100, format="%.0f"),
                    "digital_engagement_score": st.column_config.ProgressColumn("Digital Engagement", min_value=0, max_value=100, format="%.0f"),
                    "expected_revenue": st.column_config.NumberColumn("Expected Revenue", format="₹%.0f"),
                    "recommended_product": st.column_config.TextColumn("Recommended Product", width=200),
                    "recommended_action": st.column_config.TextColumn("Recommended Action", width="large"),
                },
            )
            st.caption(f"Showing the top {len(matrix):,} of {total:,} customers in the current selection.")

        with st.expander("Data sources and notes"):
            st.markdown(
                f"- Purchase probability is stored as a {meta['scale_note']}.\n"
                f"- Customer value comes from `{meta['value_source'] or 'not available'}`, digital engagement from "
                f"`{meta['engagement_source'] or 'not available'}`, expected revenue from `{meta['revenue_source'] or 'not available'}`, "
                f"bubble size from `{meta['ltv_source'] or 'expected revenue'}`.\n"
                f"- Priority score = {PURCHASE_PROBABILITY_WEIGHT:.0%} purchase probability + {CUSTOMER_VALUE_WEIGHT:.0%} customer value + "
                f"{DIGITAL_ENGAGEMENT_WEIGHT:.0%} digital engagement (each on a 0-100 scale). High is {HIGH_PRIORITY_THRESHOLD}+, "
                f"Medium is {MEDIUM_PRIORITY_THRESHOLD}+, otherwise Low.\n"
                f"- Customer value and digital engagement are scaled with "
                f"{'percentile ranks (the median customer scores 50)' if meta['normalization'] == 'percentile' else 'min-max scaling'} "
                f"(`SCORE_NORMALIZATION` in config/business_rules.py)."
            )
            if data_notes:
                st.markdown("**Not found in the database (defaults used):**\n" + "\n".join(f"- {n}" for n in data_notes))

    # ==================================================================
    # PAGE 2: Sales Action Center
    # ==================================================================
    elif view == "actions":
        st.title("Sales Action Center")
        st.markdown('<div class="subtitle">AI-driven customer recommendations and sales prioritization.</div>', unsafe_allow_html=True)

        f1, f2, f3 = st.columns(3)
        with f1:
            f_product = st.multiselect("Recommended Product", sorted(df_all["recommended_product"].unique().tolist()))
        with f2:
            f_priority2 = st.multiselect("Priority", TIER_ORDER, key="priority_page2")
        with f3:
            f_cluster = st.multiselect(meta["cluster_title"], sorted(df_all["cluster_label"].unique().tolist()))

        df = df_all
        if f_product:
            df = df[df["recommended_product"].isin(f_product)]
        if f_priority2:
            df = df[df["priority_level"].isin(f_priority2)]
        if f_cluster:
            df = df[df["cluster_label"].isin(f_cluster)]

        click_priority = st.session_state.get("click_priority2")
        click_product2 = st.session_state.get("click_product2")
        if click_priority:
            df = df[df["priority_level"] == click_priority]
        if click_product2:
            df = df[df["recommended_product"] == click_product2]
        active_filter_bar(
            {"Priority": click_priority, "Product": click_product2},
            ("click_priority2", "click_product2"),
            "clear_actions_clicks",
        )

        if df.empty:
            st.info("No customers match the current filters. Clear a filter to continue.")
            st.stop()
        total = len(df)

        with panel("recommendations", "Customer Recommendation Table",
                   "Customers ranked by business priority score, with the recommended product, the reason the model flags them and the suggested action."):
            ranked = df.sort_values("priority_score", ascending=False).head(1000).copy()
            ranked["why"] = [generate_reason(r) for r in ranked.to_dict("records")]
            table_cols = ["customer_id", "surname", "state", "customer_segment", "priority_level", "priority_score", "propensity_score",
                          "recommended_product", "recommended_action", "why", "preferred_communication_channel", "campaign_response",
                          "expected_revenue"]
            st.dataframe(
                ranked[[c for c in table_cols if c in ranked.columns]], width="stretch", hide_index=True,
                column_config={
                    "customer_id": "Customer ID", "surname": "Surname", "state": "State", "customer_segment": "Persona",
                    "priority_level": "Priority",
                    "priority_score": st.column_config.ProgressColumn("Priority Score", min_value=0, max_value=100, format="%.0f"),
                    "propensity_score": st.column_config.ProgressColumn("Purchase Probability", min_value=0, max_value=100, format="%.0f%%"),
                    "recommended_product": "Recommended Product",
                    "recommended_action": st.column_config.TextColumn("Recommended Action", width="large"),
                    "why": st.column_config.TextColumn("Why", width="large"),
                    "preferred_communication_channel": "Preferred Channel", "campaign_response": "Campaign Response",
                    "expected_revenue": st.column_config.NumberColumn("Expected Revenue", format="₹%.0f"),
                },
            )
            st.caption(f"Showing the top {len(ranked):,} of {total:,} customers in the current selection, highest priority first.")

        row1a, row1b = st.columns(2)
        with row1a:
            with panel("p2_priority", "Customer Priority Distribution",
                       "Customers per priority level. Click a bar to filter the page to that level."):
                pg = (df.groupby("priority_level")
                        .agg(customers=("customer_id", "count"), prob=("propensity_score", "mean"), pscore=("priority_score", "mean"),
                             value=("customer_value_score", "mean"), revenue=("expected_revenue", "sum"))
                        .reindex(TIER_ORDER[::-1]).fillna(0).reset_index())
                pg["share"] = pg["customers"] / total * 100
                pg["rev_txt"] = pg["revenue"].map(inr_short)
                fig = go.Figure(go.Bar(
                    x=pg["customers"], y=pg["priority_level"], orientation="h",
                    marker=dict(color=[TIER_COLORS[i] for i in pg["priority_level"]], line=dict(width=0)),
                    text=[f"{c:,.0f} ({s:.0f}%)" for c, s in zip(pg["customers"], pg["share"])], textposition="outside",
                    cliponaxis=False, textfont=dict(size=12, color=T["text"]),
                    customdata=pg[["share", "prob", "pscore", "value", "rev_txt"]].values.tolist(),
                    hovertemplate=("<b>%{y} Priority</b><br>Customer Count: %{x:,}<br>Percentage of Customers: %{customdata[0]:.1f}%<br>"
                                   "Average Purchase Probability: %{customdata[1]:.1f}%<br>Average Priority Score: %{customdata[2]:.1f}<br>"
                                   "Average Customer Value: %{customdata[3]:.1f}<br>Expected Revenue: %{customdata[4]}<extra></extra>"),
                ))
                style_axes(fig, DARK, x_title="Number of Customers", grid_y=False)
                fig.update_xaxes(range=[0, max(pg["customers"].max(), 1) * 1.3])
                event = show(fig, f"p2_priority_{st.session_state['reset']}", 340, select=True)
                clicked = extract_click(event, "y")
                if clicked and clicked != click_priority:
                    st.session_state["click_priority2"] = clicked
                    st.rerun()
                top_level = pg.sort_values("customers").iloc[-1]
                insight(f"<b>{top_level['priority_level']}</b> priority is the largest group with {top_level['customers']:,.0f} customers "
                        f"({top_level['share']:.0f}%). Average priority score across the selection is <b>{df['priority_score'].mean():.1f}</b>.")
        with row1b:
            with panel("p2_channel", "Preferred Communication Channel",
                       "How customers in the current selection prefer to be contacted, with their average purchase probability."):
                cg = (df.groupby("preferred_communication_channel")
                        .agg(customers=("customer_id", "count"), prob=("propensity_score", "mean"), revenue=("expected_revenue", "sum"))
                        .reset_index().sort_values("customers", ascending=False))
                cg["share"] = cg["customers"] / total * 100
                cg["rev_txt"] = cg["revenue"].map(inr_short)
                colors = [T["accent"] if i == 0 else hex_to_rgba(T["accent"], 0.55) for i in range(len(cg))]
                fig = go.Figure(go.Bar(
                    x=cg["preferred_communication_channel"], y=cg["customers"], marker=dict(color=colors, line=dict(width=0)),
                    text=[f"{c:,}" for c in cg["customers"]], textposition="outside", cliponaxis=False, textfont=dict(size=12, color=T["text"]),
                    customdata=cg[["share", "prob", "rev_txt"]].values.tolist(),
                    hovertemplate=("<b>%{x}</b><br>Customers: %{y:,}<br>Percentage of Total Customers: %{customdata[0]:.1f}%<br>"
                                   "Average Purchase Probability: %{customdata[1]:.1f}%<br>Expected Revenue: %{customdata[2]}<extra></extra>"),
                ))
                style_axes(fig, DARK, y_title="Number of Customers", grid_x=False)
                fig.update_yaxes(range=[0, cg["customers"].max() * 1.18])
                fig.update_xaxes(tickmode="array", tickvals=cg["preferred_communication_channel"].tolist(), ticktext=[wrap(x, 14) for x in cg["preferred_communication_channel"]])
                show(fig, "p2_channel", 340)
                best = cg.sort_values("prob").iloc[-1]
                insight(f"<b>{cg.iloc[0]['preferred_communication_channel']}</b> is the most common channel ({cg.iloc[0]['share']:.0f}%). "
                        f"Customers who prefer <b>{best['preferred_communication_channel']}</b> have the highest average purchase probability ({best['prob']:.1f}%).")

        row2a, row2b = st.columns(2)
        with row2a:
            with panel("p2_product", "Recommended Product Distribution",
                       "How many customers map to each AI-recommended product. Click a bar to filter the page to that product."):
                prg = (df.groupby("recommended_product")
                         .agg(customers=("customer_id", "count"), prob=("propensity_score", "mean"), revenue=("expected_revenue", "sum"))
                         .reset_index().sort_values("customers", ascending=False))
                prg["share"] = prg["customers"] / total * 100
                prg["rev_txt"] = prg["revenue"].map(inr_short)
                colors = [T["accent"] if i == 0 else hex_to_rgba(T["accent"], 0.55) for i in range(len(prg))]
                fig = go.Figure(go.Bar(
                    x=prg["recommended_product"], y=prg["customers"], marker=dict(color=colors, line=dict(width=0)),
                    text=[f"{c:,}" for c in prg["customers"]], textposition="outside", cliponaxis=False, textfont=dict(size=12, color=T["text"]),
                    customdata=prg[["share", "prob", "rev_txt"]].values.tolist(),
                    hovertemplate=("<b>%{x}</b><br>Customers: %{y:,}<br>Percentage of Total Customers: %{customdata[0]:.1f}%<br>"
                                   "Average Purchase Probability: %{customdata[1]:.1f}%<br>Expected Revenue: %{customdata[2]}<extra></extra>"),
                ))
                style_axes(fig, DARK, y_title="Number of Customers", grid_x=False)
                fig.update_yaxes(range=[0, prg["customers"].max() * 1.18])
                fig.update_xaxes(tickmode="array", tickvals=prg["recommended_product"].tolist(), ticktext=[wrap(x, 14) for x in prg["recommended_product"]])
                event = show(fig, f"p2_product_{st.session_state['reset']}", 380, select=True)
                clicked = extract_click(event, "x")
                if clicked and clicked != click_product2:
                    st.session_state["click_product2"] = clicked
                    st.rerun()
                insight(f"<b>{prg.iloc[0]['recommended_product']}</b> is recommended most often ({prg.iloc[0]['share']:.0f}% of customers), "
                        f"worth {prg.iloc[0]['rev_txt']} in expected revenue.")
        with row2b:
            with panel("p2_cluster", f"{meta['cluster_title']} Distribution",
                       "Customers per group, with average purchase probability on hover."):
                kg = (df.groupby("cluster_label")
                        .agg(customers=("customer_id", "count"), prob=("propensity_score", "mean"), revenue=("expected_revenue", "sum"))
                        .reset_index().sort_values("cluster_label"))
                kg["share"] = kg["customers"] / total * 100
                kg["rev_txt"] = kg["revenue"].map(inr_short)
                fig = go.Figure(go.Bar(
                    x=kg["cluster_label"], y=kg["customers"], marker=dict(color=hex_to_rgba(T["accent"], 0.8), line=dict(width=0)),
                    text=[f"{c:,}" for c in kg["customers"]], textposition="outside", cliponaxis=False, textfont=dict(size=12, color=T["text"]),
                    customdata=kg[["share", "prob", "rev_txt"]].values.tolist(),
                    hovertemplate=("<b>%{x}</b><br>Customers: %{y:,}<br>Percentage of Total Customers: %{customdata[0]:.1f}%<br>"
                                   "Average Purchase Probability: %{customdata[1]:.1f}%<br>Expected Revenue: %{customdata[2]}<extra></extra>"),
                ))
                style_axes(fig, DARK, y_title="Number of Customers", grid_x=False)
                fig.update_yaxes(range=[0, kg["customers"].max() * 1.18])
                fig.update_xaxes(tickmode="array", tickvals=kg["cluster_label"].tolist(), ticktext=[wrap(x, 14) for x in kg["cluster_label"]])
                show(fig, "p2_cluster", 380)
                best = kg.sort_values("prob").iloc[-1]
                insight(f"<b>{best['cluster_label']}</b> has the highest average purchase probability ({best['prob']:.1f}%) "
                        f"across {best['customers']:,} customers.")

    # ==================================================================
    # PAGE 3: Customer Search
    # ==================================================================
    elif view == "search":
        st.markdown('<div class="eyebrow">CustomerAI Platform</div>', unsafe_allow_html=True)
        st.title("Customer Search")
        st.markdown('<div class="subtitle">Look up a customer and get a tailored pitch.</div>', unsafe_allow_html=True)

        with panel("search_box", "Search customers", "Search by customer ID, surname or persona."):
            query = st.text_input("Search", label_visibility="collapsed", placeholder="Search by ID, surname, or segment...")
            results = pd.DataFrame()
            if query:
                found = api_get("/api/search", params={"q": query})
                if found:
                    results = pd.DataFrame(found)
                    st.dataframe(humanize_binary_columns(results), width="stretch", hide_index=True)
                elif found is not None:
                    st.info("No matches found.")

        if not results.empty:
            selected = st.selectbox("View full profile and pitch guidance for:", results["customer_id"].tolist())
            if selected:
                customer = results[results["customer_id"] == selected].iloc[0].to_dict()
                prediction = api_post(f"/api/predict/{selected}") or {}
                row = df_all[df_all["customer_id"].astype(str) == str(selected)]
                engine = row.iloc[0].to_dict() if not row.empty else {}

                with panel("profile", f"Profile: {customer.get('surname') or selected} ({selected})"):
                    st.markdown(
                        kpi_strip([
                            {"title": "Purchase Probability", "value": f"{num(prediction.get('propensity_score'), float('nan')):.1f}%" if prediction else "n/a",
                             "accent": T["accent"], "tip": "Predicted likelihood that this customer purchases an additional product."},
                            {"title": "Customer Value", "value": f"{engine.get('customer_value_score', float('nan')):.0f} / 100" if engine else "n/a",
                             "accent": T["green"], "tip": "Relative business value of this customer on a 0-100 scale, taken from the customer value data."},
                            {"title": "Digital Engagement", "value": f"{engine.get('digital_engagement_score', float('nan')):.0f} / 100" if engine else "n/a",
                             "accent": T["accent2"], "tip": "How actively the customer engages with digital channels, on a 0-100 scale."},
                            {"title": "Priority Score", "value": f"{engine.get('priority_score', float('nan')):.0f} / 100" if engine else "n/a",
                             "accent": T["gold"], "tip": "Business priority: a weighted blend of purchase probability, customer value and digital engagement."},
                            {"title": "Priority Level", "value": f"{engine.get('priority_level', 'n/a')}", "accent": T["slate"],
                             "tip": f"High is {HIGH_PRIORITY_THRESHOLD}+, Medium is {MEDIUM_PRIORITY_THRESHOLD}+, otherwise Low (priority score)."},
                        ]),
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"**Why (purchase likelihood):** {generate_reason(customer)}")
                    if engine:
                        st.markdown(f"**Recommended action (business priority):** {engine.get('recommended_action', 'n/a')}")
                    if prediction.get("source") == "rule_based_fallback":
                        st.caption("This customer has no stored model score, so the probability above is a rule-based estimate.")

                pitch = build_pitch_profile(customer)
                c1, c2 = st.columns(2)
                with c1:
                    with panel("good_fit", "Good fit for"):
                        for item in pitch["capable"]:
                            st.markdown(f"- {item}")
                with c2:
                    with panel("avoid", "Avoid pitching"):
                        for item in pitch["incapable"]:
                            st.markdown(f"- {item}")
                with panel("pitch", "Suggested pitch"):
                    st.markdown(f"**Lead with:** {', '.join(pitch['pitch_products'])}")
                    st.markdown(f"**Opening line:** {pitch['talking_point']}")

    # ==================================================================
    # PAGE 4: Data Explorer
    # ==================================================================
    elif view == "explorer":
        st.markdown('<div class="eyebrow">CustomerAI Platform</div>', unsafe_allow_html=True)
        st.title("Data Explorer")
        st.markdown('<div class="subtitle">Filter the full customer dataset and download exactly what you see.</div>', unsafe_allow_html=True)

        with panel("explorer_filters", "Filter rows"):
            d1, d2, d3, d4 = st.columns(4)
            with d1:
                d_priority = st.multiselect("Priority", TIER_ORDER, key="explorer_priority")
            with d2:
                d_state = st.multiselect("State", sorted(df_all["state"].unique().tolist()), key="explorer_state")
            with d3:
                d_persona = st.multiselect("Persona", sorted(df_all["customer_segment"].unique().tolist()), key="explorer_persona")
            with d4:
                d_product = st.multiselect("Recommended Product", sorted(df_all["recommended_product"].unique().tolist()), key="explorer_product")

        explorer = df_all
        if d_priority:
            explorer = explorer[explorer["priority_level"].isin(d_priority)]
        if d_state:
            explorer = explorer[explorer["state"].isin(d_state)]
        if d_persona:
            explorer = explorer[explorer["customer_segment"].isin(d_persona)]
        if d_product:
            explorer = explorer[explorer["recommended_product"].isin(d_product)]

        with panel("explorer_table", f"Dataset ({len(explorer):,} of {len(df_all):,} rows)"):
            internal = ["priority", "cluster_label", "age_band", "clv"]
            visible = explorer.drop(columns=[c for c in internal if c in explorer.columns])
            st.dataframe(humanize_binary_columns(visible), width="stretch", hide_index=True)
            st.download_button(
                f"Download filtered rows as CSV ({len(explorer):,} rows)",
                data=visible.to_csv(index=False).encode("utf-8"),
                file_name="customers_export.csv", mime="text/csv", key="download_customers_csv",
                help="Downloads only the rows matching the filters above. Clear all filters to download everything.",
            )

except Exception as exc:  # last-resort guard so a chart bug never blanks the whole app
    st.error("Something broke while rendering this page. Full error below:")
    st.exception(exc)
