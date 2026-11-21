"""
risk_themes.py — keyword-based risk theme tagger
Provides tag_risks(text) -> list[str]
Returns a list of matched theme tags, or ["general_news"] if none match.
"""

import re

# ── Keyword lists per theme ───────────────────────────────────────────────────
THEMES = {
    "supply_chain": [
        "shortage", "supply chain", "chip shortage", "semiconductor shortage",
        "manufacturing disruption", "delayed shipment", "capacity constraints",
        "export controls", "supply crunch", "inventory shortage", "stockpile",
        "supply constraint", "production delay", "fab capacity",
    ],
    "regulatory_antitrust": [
        "lawsuit", "sued", "antitrust", "investigation", "probe", "fine",
        "settlement", "regulators", "DOJ", "FTC", "European Commission",
        "class action", "subpoena", "penalty", "violation", "compliance",
        "regulatory approval", "merger blocked", "competition authority",
    ],
    "cybersecurity": [
        "data breach", "hack", "cyberattack", "ransomware", "vulnerability",
        "security incident", "phishing", "malware", "zero-day", "exploit",
        "data leak", "intrusion", "security flaw", "cyber threat",
    ],
    "guidance_outlook": [
        "cuts guidance", "lowered forecast", "withdraws guidance",
        "misses estimates", "profit warning", "downgrade", "weak outlook",
        "lowers price target", "below expectations", "disappoints",
        "revenue miss", "earnings miss", "reduced outlook", "cautious outlook",
        "below consensus", "guidance cut", "forecast cut", "lower guidance",
        "warns of", "below estimate",
    ],
    "leadership": [
        "CEO resigns", "steps down", "names new CEO", "executive departure",
        "CFO", "management shakeup", "chief executive", "appoints",
        "president resigned", "board chair", "new chief", "leadership change",
        "succession", "interim CEO", "co-founder leaves",
    ],
}

# Pre-compile patterns: word-boundary aware, case-insensitive
_COMPILED = {
    theme: re.compile(
        "|".join(r"\b" + re.escape(kw) + r"\b" for kw in keywords),
        re.IGNORECASE,
    )
    for theme, keywords in THEMES.items()
}


def tag_risks(text: str) -> list[str]:
    """
    Match text against all theme keyword lists.
    Returns list of matched theme names, or ["general_news"] if none match.
    """
    if not text or not isinstance(text, str):
        return ["general_news"]
    matched = [theme for theme, pattern in _COMPILED.items() if pattern.search(text)]
    return matched if matched else ["general_news"]
