"""
Business priority engine.

Purchase_Probability (the ML model's output) answers "how likely is this
customer to buy?". Priority_Score / Priority_Level answer "how much should
the business care?" by blending in customer value and digital engagement.
This module is the only place those signals are combined; the model's
probability itself is never modified.

All weights, thresholds and source columns live in config/business_rules.py.
"""

import pandas as pd

from config.business_rules import (
    CUSTOMER_VALUE_SOURCE_COLUMNS,
    CUSTOMER_VALUE_WEIGHT,
    DIGITAL_ENGAGEMENT_SOURCE_COLUMNS,
    DIGITAL_ENGAGEMENT_WEIGHT,
    HIGH_PRIORITY_THRESHOLD,
    MEDIUM_PRIORITY_THRESHOLD,
    PURCHASE_PROBABILITY_WEIGHT,
    SCORE_NORMALIZATION,
)


def first_present(df: pd.DataFrame, candidates):
    for name in candidates:
        if name in df.columns:
            return name
    return None


def normalize_0_100(series: pd.Series, method: str = None) -> pd.Series:
    """Put a numeric column on a 0-100 scale using only the real data.

    method "percentile": percentile rank (0 = lowest customer, 100 = highest).
    method "minmax":     linear between the observed minimum and maximum.
    Defaults to SCORE_NORMALIZATION in config/business_rules.py.
    """
    method = method or SCORE_NORMALIZATION
    s = pd.to_numeric(series, errors="coerce").fillna(0).astype(float)
    lo, hi = s.min(), s.max()
    if hi == lo or len(s) < 2:
        return pd.Series(50.0, index=s.index)  # flat input: neutral midpoint
    if method == "minmax":
        return (s - lo) / (hi - lo) * 100
    ranks = s.rank(method="average")  # ties share the average rank
    return (ranks - 1) / (len(s) - 1) * 100


def to_score(series: pd.Series, column_name: str) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(0).astype(float)
    if column_name.endswith("_score") and s.min() >= 0 and s.max() <= 100:
        return s
    return normalize_0_100(s)


def component_score(df: pd.DataFrame, candidates):
    """Returns (score_series, source_column_or_None)."""
    column = first_present(df, candidates)
    if column is None:
        return pd.Series(50.0, index=df.index), None
    return to_score(df[column], column), column


def compute_priority_score(purchase_probability, customer_value, digital_engagement) -> pd.Series:
    """All three inputs must already be on a 0-100 scale."""
    return (
        purchase_probability * PURCHASE_PROBABILITY_WEIGHT
        + customer_value * CUSTOMER_VALUE_WEIGHT
        + digital_engagement * DIGITAL_ENGAGEMENT_WEIGHT
    )


def assign_priority_level(priority_score: pd.Series) -> pd.Series:
    def level(score):
        if score >= HIGH_PRIORITY_THRESHOLD:
            return "High"
        if score >= MEDIUM_PRIORITY_THRESHOLD:
            return "Medium"
        return "Low"

    return priority_score.apply(level)


def recommend_action(level, customer_segment, recommended_product, purchase_probability, customer_value) -> str:
    segment = str(customer_segment or "").lower()
    product = recommended_product or "a relevant product"
    purchase_probability = purchase_probability or 0
    customer_value = customer_value or 0

    if level == "High":
        if customer_value >= 85 and purchase_probability >= 85:
            return (f"Immediate high-touch outreach (call or branch) leading with {product}; strong purchase "
                    f"likelihood combined with high business value.")
        return "Prioritize for targeted sales or marketing outreach."

    if level == "Medium":
        if "digital" in segment or customer_value < 50:
            return f"Include in targeted digital campaigns for {product}; monitor response before escalating."
        return "Include in targeted digital campaigns and monitor response."

    if purchase_probability >= 60:
        return (f"Purchase likelihood is decent but business value is low; use low-cost automated "
                f"campaigns for {product} rather than direct sales time.")
    return "Use low-cost automated engagement campaigns and monitor future behaviour."


def apply_priority_engine(df: pd.DataFrame, purchase_probability_col: str = "propensity_score") -> pd.DataFrame:
    """Adds customer_value_score, digital_engagement_score, priority_score,
    priority_level and recommended_action. The input must already carry the
    purchase probability on a 0-100 scale. Which source columns were used is
    recorded in out.attrs["value_source"] / out.attrs["engagement_source"]."""
    out = df.copy()
    out["customer_value_score"], value_source = component_score(out, CUSTOMER_VALUE_SOURCE_COLUMNS)
    out["digital_engagement_score"], engagement_source = component_score(out, DIGITAL_ENGAGEMENT_SOURCE_COLUMNS)
    out["priority_score"] = compute_priority_score(
        out[purchase_probability_col], out["customer_value_score"], out["digital_engagement_score"]
    )
    out["priority_level"] = assign_priority_level(out["priority_score"])
    out["recommended_action"] = [
        recommend_action(lvl, seg, prod, prob, val)
        for lvl, seg, prod, prob, val in zip(
            out["priority_level"],
            out["customer_segment"] if "customer_segment" in out else [None] * len(out),
            out["recommended_product"] if "recommended_product" in out else [None] * len(out),
            out[purchase_probability_col],
            out["customer_value_score"],
        )
    ]
    out.attrs["normalization"] = SCORE_NORMALIZATION
    out.attrs["value_source"] = value_source
    out.attrs["engagement_source"] = engagement_source
    return out
