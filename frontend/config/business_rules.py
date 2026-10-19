"""
Centralized, configurable business rules for the CustomerAI priority engine.

Change weights, thresholds and source columns HERE ONLY. Nothing else in
the app hard-codes these numbers.
"""

# ---- Priority Score weights (must sum to 1.0) ----
PURCHASE_PROBABILITY_WEIGHT = 0.55   # was 0.60 — still the biggest factor
CUSTOMER_VALUE_WEIGHT       = 0.30   # was 0.25 — give revenue more weight
DIGITAL_ENGAGEMENT_WEIGHT   = 0.15   # unchanged

assert abs(
    PURCHASE_PROBABILITY_WEIGHT + CUSTOMER_VALUE_WEIGHT + DIGITAL_ENGAGEMENT_WEIGHT - 1.0
) < 1e-9, "Priority score weights must sum to 1.0"

# ---- Priority Level thresholds ----
HIGH_PRIORITY_THRESHOLD   = 78   # was 80 — slightly more High tier
MEDIUM_PRIORITY_THRESHOLD = 58   # was 60

# ---- How Customer Value and Digital Engagement are put on a 0-100 scale ----
# "percentile": each customer's score is their percentile rank among all customers
#               (the median customer scores 50). Robust to a few very large values,
#               so High / Medium / Low all stay populated.
# "minmax":     (value - smallest) / (largest - smallest) * 100. A single very large
#               lifetime value squeezes everyone else toward 0, which can leave the
#               High tier empty on skewed data.
SCORE_NORMALIZATION = "percentile"

# ---- Source columns ----
# Each list is tried in order and the first column found in the data is used.
# Columns whose name ends in "_score" and already sit inside 0-100 are used
# as-is; anything else is min-max normalized to 0-100 from the real data.
CUSTOMER_VALUE_SOURCE_COLUMNS    = ["customer_value_score", "estimated_clv", "customer_lifetime_value", "balance"]
DIGITAL_ENGAGEMENT_SOURCE_COLUMNS = ["digital_engagement_score", "mobile_app_logins_per_month", "app_logins_per_month"]
EXPECTED_REVENUE_SOURCE_COLUMNS   = ["expected_revenue", "estimated_clv", "customer_lifetime_value"]
LIFETIME_VALUE_SOURCE_COLUMNS     = ["customer_lifetime_value", "estimated_clv"]