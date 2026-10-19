"""
Propensity scoring for a single customer (backs POST /api/predict/{id}).

The dashboard's bulk numbers come from the trained model's output that is
already stored in the database (propensity_score). This function returns
that stored score so the Customer Search page always agrees with the
dashboards. Only when a customer has no stored score does it fall back to
the transparent rule-based estimate below, and it says so in `source`.

All scores returned by the API are on a 0-100 scale.
"""


def _rule_based_score(customer: dict) -> float:
    score = 50.0

    credit_score = customer.get("credit_score") or 0
    if credit_score >= 750:
        score += 15
    elif credit_score >= 650:
        score += 5
    else:
        score -= 10

    score -= (customer.get("missed_emis_last_12m") or 0) * 5
    score += min(customer.get("mobile_app_logins_per_month") or 0, 20) * 0.5
    if customer.get("is_active_member"):
        score += 10

    return max(0.0, min(100.0, score))


def score_customer(customer: dict, scale: int = 100) -> dict:
    stored = customer.get("propensity_score")
    if stored is not None:
        pct = float(stored) * (100 if scale == 1 else 1)
        source = "model"
    else:
        pct = _rule_based_score(customer)
        source = "rule_based_fallback"

    product = customer.get("recommended_product")
    if not product:
        product = "Premium Credit Card" if pct >= 70 else "Personal Loan Top-up" if pct >= 45 else "Savings Plan"

    return {
        "customer_id": customer.get("customer_id"),
        "propensity_score": round(pct, 1),
        "recommended_product": product,
        "source": source,
    }
