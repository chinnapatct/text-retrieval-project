"""
Stage 2b — Wayback Machine test on 10 URLs
For each URL: asks the CDX API for the closest archived snapshot,
then fetches and cleans the text the same way as 02_scrape_text.py.
Prints success rate and 3 sample texts, then stops.
"""

import re
import time
import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import RAW_NEWS_CSV, SCRAPE_DELAY, MIN_TEXT_CHARS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

CDX_API = "http://web.archive.org/cdx/search/cdx"
WAYBACK  = "https://web.archive.org/web"

BOILERPLATE_RE = re.compile(
    r"subscribe\s+to\s+(our\s+)?newsletter"
    r"|sign\s+up\s+for\s+(our\s+)?newsletter"
    r"|cookies?\s+(help\s+us|policy|settings)"
    r"|by\s+clicking\s+.{0,40}\s+you\s+agree"
    r"|all\s+rights\s+reserved|©\s*\d{4}"
    r"|related\s+articles?|read\s+more\s*:"
    r"|advertisement|sponsored\s+content",
    re.IGNORECASE,
)


def get_wayback_url(original_url: str, timeout: int = 10) -> str | None:
    """Ask CDX API for the closest available snapshot URL."""
    try:
        params = {
            "url": original_url,
            "output": "json",
            "limit": 1,
            "fl": "timestamp,statuscode",
            "filter": "statuscode:200",   # only successful snapshots
            "collapse": "digest",
        }
        resp = requests.get(CDX_API, params=params, timeout=timeout, headers=HEADERS)
        data = resp.json()
        # data[0] is the header row ["timestamp","statuscode"], data[1] is first result
        if len(data) < 2:
            return None
        timestamp = data[1][0]
        return f"{WAYBACK}/{timestamp}/{original_url}"
    except Exception:
        return None


def fetch_and_clean(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL and return cleaned article body text."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove Wayback Machine toolbar (it injects its own nav bar)
        for tag in soup.find_all(id=re.compile(r"wm-ipp|wm-ipp-base|wm_tb")):
            tag.decompose()

        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "figure", "figcaption", "form", "noscript"]):
            tag.decompose()

        paragraphs = [
            p.get_text(separator=" ", strip=True)
            for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 40
        ]

        if not paragraphs:
            body = soup.find("body")
            paragraphs = [body.get_text(separator=" ", strip=True)] if body else []

        combined = re.sub(r"\s+", " ", " ".join(paragraphs)).strip()

        sentences = re.split(r"(?<=[.!?])\s+", combined)
        combined = " ".join(s for s in sentences if not BOILERPLATE_RE.search(s)).strip()

        return combined if len(combined) >= MIN_TEXT_CHARS else None

    except Exception:
        return None


def main():
    df = pd.read_csv(RAW_NEWS_CSV)
    print(f"Loaded {len(df)} rows from {RAW_NEWS_CSV}\n")

    # Sample 10 URLs: 2-3 per ticker
    sample = (
        df.groupby("Stock_symbol", group_keys=False)
          .apply(lambda g: g.sample(min(3, len(g)), random_state=99), include_groups=False)
          .head(10)
          .reset_index(drop=True)
    )
    # Re-attach Stock_symbol since include_groups=False drops it
    sample = df.loc[
        df.groupby("Stock_symbol", group_keys=False)
          .apply(lambda g: g.sample(min(3, len(g)), random_state=99), include_groups=False)
          .head(10)
          .index
    ].reset_index(drop=True)

    title_col = next((c for c in df.columns if "title" in c.lower()), "Url")
    results = []

    print(f"Testing {len(sample)} URLs via Wayback Machine …\n")
    for i, row in sample.iterrows():
        url = row["Url"]
        ticker = row["Stock_symbol"]
        title = str(row[title_col])[:70]

        print(f"[{i+1}/{len(sample)}] {ticker} — {title}")

        # Step 1: find snapshot
        wb_url = get_wayback_url(url)
        if wb_url is None:
            print(f"  → NO SNAPSHOT in Wayback Machine")
            results.append({"ticker": ticker, "url": url, "status": "no_snapshot", "text": None})
            time.sleep(1)
            continue

        print(f"  snapshot: {wb_url[:90]}")

        # Step 2: fetch and clean
        text = fetch_and_clean(wb_url)
        if text:
            print(f"  → OK  ({len(text)} chars)")
            results.append({"ticker": ticker, "url": url, "wb_url": wb_url,
                            "status": "ok", "text": text})
        else:
            print(f"  → FAIL  (fetched but text too short / empty)")
            results.append({"ticker": ticker, "url": url, "wb_url": wb_url,
                            "status": "fail", "text": None})

        time.sleep(SCRAPE_DELAY + 1)   # be polite to Wayback Machine

    # ── Summary ─────────────────────────────────────────────────────────────
    ok      = [r for r in results if r["status"] == "ok"]
    no_snap = [r for r in results if r["status"] == "no_snapshot"]
    fail    = [r for r in results if r["status"] == "fail"]

    print(f"\n── Test summary ──────────────────────────────")
    print(f"  OK (text extracted) : {len(ok)}/{len(results)}")
    print(f"  No snapshot found   : {len(no_snap)}/{len(results)}")
    print(f"  Snapshot but no text: {len(fail)}/{len(results)}")
    print(f"  Success rate        : {len(ok)/len(results)*100:.0f}%")

    # ── 3 sample texts ───────────────────────────────────────────────────────
    print(f"\n── Sample texts ──────────────────────────────")
    for r in ok[:3]:
        print(f"\nTicker: {r['ticker']}")
        print(f"URL:    {r['url']}")
        print(f"Text ({len(r['text'])} chars):\n  {r['text'][:500]} …\n")

    if len(ok) / len(results) >= 0.5:
        print("✓ Success rate ≥ 50% — Wayback Machine approach is viable.")
        print("  Next step: run 02_scrape_text.py (full scrape via Wayback) for all 480 URLs.")
    else:
        print("✗ Success rate < 50% — Wayback Machine won't give enough coverage.")
        print("  Fallback: headline-only search engine (Option C).")


if __name__ == "__main__":
    main()
