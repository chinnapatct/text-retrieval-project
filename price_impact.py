"""
price_impact.py — Price impact star scorer for StockView
Rates each news article 1–5 stars for potential stock price impact
using signals already in Elasticsearch (no external API needed).
"""

# Words that signal a moderate price-moving event
MEDIUM_IMPACT_WORDS = [
    "downgrade", "upgrade", "miss", "beat", "cut", "layoff", "layoffs",
    "investigation", "lawsuit", "ban", "sanction", "recall", "hack",
    "breach", "crash", "surge", "plunge", "soar", "collapse",
    "guidance", "forecast", "outlook", "warning", "alert",
    "acquisition", "merger", "deal", "spinoff", "bankruptcy",
]

# Words that signal an extreme, company-shaking event — instant +2 stars
EXTREME_IMPACT_WORDS = [
    "resign", "resigned", "resignation", "fired", "ousted", "departed",
    "departure", "scandal", "fraud", "indicted", "arrested", "charged",
    "spy", "espionage", "toppled", "stepping down", "steps down",
    "ceo leaves", "coo leaves", "cfo leaves", "cto leaves",
    "delisted", "default", "chapter 11", "chapter 7",
    "catastrophic", "critical vulnerability", "data breach",
]


def score_article(result: dict) -> int:
    """
    Score a search result for potential stock price impact.
    Returns 1–5 stars based on sentiment, risk tags, earnings proximity,
    and headline keywords. Extreme events (CEO scandal, fraud, spy) jump to 4-5.
    """
    stars = 1

    sentiment = (result.get("finbert_sentiment") or "neutral").lower()
    fin_score = float(result.get("finbert_score") or 0.5)
    tags      = result.get("risk_theme_tags") or []
    days_to   = result.get("days_to_earnings")
    headline  = (result.get("headline") or "").lower()
    body      = (result.get("body_text") or "").lower()[:300]
    full_text = headline + " " + body

    # ── Extreme events: CEO departure, scandal, fraud → floor at 4 stars ───────
    extreme_hit = any(w in full_text for w in EXTREME_IMPACT_WORDS)
    if extreme_hit:
        stars = max(stars, 4)

    # ── Sentiment signal ───────────────────────────────────────────────────────
    if sentiment == "negative":
        stars += 1
        if fin_score >= 0.85:
            stars += 1
    elif sentiment == "positive" and fin_score >= 0.80:
        stars += 1

    # ── Risk theme tag ─────────────────────────────────────────────────────────
    if any(t for t in tags if t != "general_news"):
        stars += 1

    # ── Earnings proximity ─────────────────────────────────────────────────────
    if days_to is not None and days_to <= 7:
        stars += 1

    # ── Medium-impact headline keywords ───────────────────────────────────────
    if any(w in full_text for w in MEDIUM_IMPACT_WORDS):
        stars += 1

    return min(stars, 5)


def stars_html(stars: int) -> str:
    """Return colored star HTML for the given rating (1–5)."""
    color_map = {1: "#aaa", 2: "#aaa", 3: "#f39c12", 4: "#e67e22", 5: "#e74c3c"}
    color  = color_map.get(stars, "#aaa")
    filled = "★" * stars
    empty  = "☆" * (5 - stars)
    return (
        f"<span style='color:{color};font-size:15px;letter-spacing:1px;'>{filled}</span>"
        f"<span style='color:#ccc;font-size:15px;letter-spacing:1px;'>{empty}</span>"
        f"<span style='color:{color};font-size:12px;font-weight:700;margin-left:4px;'>"
        f"{stars}/5</span>"
    )
