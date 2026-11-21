"""
Stage 2 — Scrape article text from URLs in data/raw_news.csv
Run modes:
  python3 02_scrape_text.py --test   # test on 10 URLs, print 3 samples, then stop
  python3 02_scrape_text.py          # scrape all 480 URLs, save data/news_with_text.csv
"""

import argparse
import os
import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import RAW_NEWS_CSV, NEWS_WITH_TEXT_CSV, SCRAPE_DELAY, MIN_TEXT_CHARS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Recurring boilerplate phrases to strip (case-insensitive)
BOILERPLATE = [
    r"subscribe\s+to\s+(our\s+)?newsletter",
    r"sign\s+up\s+for\s+(our\s+)?newsletter",
    r"cookies?\s+(help\s+us|policy|settings|preferences)",
    r"by\s+clicking\s+.{0,40}\s+you\s+agree",
    r"all\s+rights\s+reserved",
    r"©\s*\d{4}",
    r"related\s+articles?",
    r"read\s+more\s*:",
    r"advertisement",
    r"sponsored\s+content",
    r"this\s+article\s+originally\s+appeared",
]
BOILERPLATE_RE = re.compile("|".join(BOILERPLATE), re.IGNORECASE)


def fetch_article(url: str, timeout: int = 10) -> str | None:
    """
    Fetch a URL and return cleaned article body text, or None on failure.
    Removes script/style/nav/footer/header/aside, takes <p> text,
    collapses whitespace, strips boilerplate.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noisy tags
        for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                         "figure", "figcaption", "form", "noscript"]):
            tag.decompose()

        # Collect paragraph text
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(separator=" ", strip=True)
            if len(text) > 40:  # skip very short fragments
                paragraphs.append(text)

        if not paragraphs:
            # Fallback: grab all visible text from body
            body = soup.find("body")
            if body:
                paragraphs = [body.get_text(separator=" ", strip=True)]

        combined = " ".join(paragraphs)

        # Collapse whitespace
        combined = re.sub(r"\s+", " ", combined).strip()

        # Strip boilerplate sentences
        sentences = re.split(r"(?<=[.!?])\s+", combined)
        clean_sentences = [s for s in sentences if not BOILERPLATE_RE.search(s)]
        combined = " ".join(clean_sentences).strip()

        return combined if len(combined) >= MIN_TEXT_CHARS else None

    except Exception:
        return None


def run_test(df: pd.DataFrame):
    """Test on 10 URLs (2-3 per ticker), print 3 samples, report success rate."""
    # Pick ~2-3 per ticker for diversity
    sample_rows = (
        df.groupby("Stock_symbol", group_keys=False)
          .apply(lambda g: g.sample(min(3, len(g)), random_state=42))
          .head(10)
          .reset_index(drop=True)
    )

    print(f"Testing {len(sample_rows)} URLs …\n")
    results = []
    for i, row in sample_rows.iterrows():
        url = row.get("Url", row.get("url", ""))
        ticker = row.get("Stock_symbol", "")
        title_col = next((c for c in row.index if "title" in c.lower()), None)
        title = row[title_col] if title_col else url

        print(f"[{i+1}/{len(sample_rows)}] {ticker} — {str(title)[:80]}")
        text = fetch_article(url)
        status = "OK" if text else "FAIL"
        length = len(text) if text else 0
        print(f"  → {status}  ({length} chars)")
        results.append({"ticker": ticker, "url": url, "title": title,
                        "status": status, "length": length, "text": text})
        time.sleep(SCRAPE_DELAY)

    successes = sum(1 for r in results if r["status"] == "OK")
    print(f"\n── Test summary ──────────────────────────────")
    print(f"Success: {successes}/{len(results)}  ({successes/len(results)*100:.0f}%)")

    # Print 3 cleaned text samples
    ok_results = [r for r in results if r["text"]]
    print(f"\n── 3 sample texts ────────────────────────────")
    for r in ok_results[:3]:
        print(f"\nTicker: {r['ticker']}")
        print(f"URL:    {r['url']}")
        print(f"Text ({r['length']} chars):\n  {r['text'][:600]} …\n")

    fail_rate = (len(results) - successes) / len(results)
    if fail_rate > 0.5:
        print("⚠️  MORE THAN HALF FAILED — stopping as instructed.")
        print("Likely causes: paywall, JavaScript-rendered page, or bot blocking.")
        print("Suggested fallbacks:")
        print("  1. Use headline + Lsa_summary / Textrank_summary columns from the dataset")
        print("  2. Try Wayback Machine CDX API for archived copies")
        print("  3. Filter to publishers that succeed (e.g. benzinga.com)")
        return False

    print("\n✓ Test looks good — run without --test to scrape all 480 URLs.")
    return True


def run_full(df: pd.DataFrame):
    """Scrape all URLs, save progress every 25 rows, resume if interrupted."""
    title_col = next((c for c in df.columns if "title" in c.lower()), None)
    url_col = next((c for c in df.columns if c.lower() == "url"), "Url")

    # Resume support: load already-scraped URLs
    done_urls = set()
    if os.path.exists(NEWS_WITH_TEXT_CSV):
        existing = pd.read_csv(NEWS_WITH_TEXT_CSV)
        done_urls = set(existing[url_col].dropna())
        print(f"Resuming — {len(done_urls)} URLs already scraped.")
        rows_out = existing.to_dict("records")
    else:
        rows_out = []

    pending = df[~df[url_col].isin(done_urls)].reset_index(drop=True)
    print(f"URLs to scrape: {len(pending)}\n")

    for i, row in pending.iterrows():
        url = row.get(url_col, "")
        ticker = row.get("Stock_symbol", "")
        title = row[title_col] if title_col else url

        print(f"[{len(done_urls)+1}/{len(df)}] {ticker} — {str(title)[:70]}", end=" … ")

        text = fetch_article(url)
        if text is None:
            # One retry
            time.sleep(2)
            text = fetch_article(url)

        if text:
            row_dict = row.to_dict()
            row_dict["body_text"] = text
            rows_out.append(row_dict)
            done_urls.add(url)
            print(f"OK ({len(text)} chars)")
        else:
            done_urls.add(url)  # mark done so we don't retry on resume
            print("FAIL (skipped)")

        # Save progress every 25 rows
        if (i + 1) % 25 == 0:
            pd.DataFrame(rows_out).to_csv(NEWS_WITH_TEXT_CSV, index=False)
            print(f"  ── progress saved ({len(rows_out)} rows with text) ──")

        time.sleep(SCRAPE_DELAY)

    # Final save
    result_df = pd.DataFrame(rows_out)
    result_df.to_csv(NEWS_WITH_TEXT_CSV, index=False)

    print(f"\n── Final counts ──────────────────────────────")
    for t in result_df["Stock_symbol"].unique():
        n = (result_df["Stock_symbol"] == t).sum()
        print(f"  {t}: {n}")
    total = len(result_df)
    attempted = len(df)
    print(f"\nSaved {total}/{attempted} articles → {NEWS_WITH_TEXT_CSV}")
    if total < 100 * 4:
        print("⚠️  Some tickers may be below 100 — check counts above.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Test on 10 URLs only")
    args = parser.parse_args()

    df = pd.read_csv(RAW_NEWS_CSV)
    print(f"Loaded {len(df)} rows from {RAW_NEWS_CSV}\n")

    if args.test:
        run_test(df)
    else:
        if os.path.exists(NEWS_WITH_TEXT_CSV):
            existing = pd.read_csv(NEWS_WITH_TEXT_CSV)
            if len(existing) == len(df):
                print(f"{NEWS_WITH_TEXT_CSV} already complete ({len(existing)} rows) — nothing to do.")
                return
        run_full(df)


if __name__ == "__main__":
    main()
