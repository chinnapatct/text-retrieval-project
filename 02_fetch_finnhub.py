"""
Stage 2 — Fetch news articles from Finnhub API
Queries company news by ticker over a wide date range,
saves headline + summary as body_text to data/news_with_text.csv.
Re-runnable: skips tickers already fully fetched.

Usage:
  python3 02_fetch_finnhub.py --test   # fetch 5 articles per ticker and print samples
  python3 02_fetch_finnhub.py          # fetch full dataset, save news_with_text.csv
"""

import argparse
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from config import TICKERS, NEWS_WITH_TEXT_CSV

FINNHUB_KEY = "dbjb6nhr01qkamq35mggdbjb6nhr01qkamq35mh0"
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"

# Fetch news from this many days back — Finnhub free tier covers ~1 year
DAYS_BACK = 365 * 3   # try 3 years; will get whatever is available
TARGET_PER_TICKER = 120
MIN_SUMMARY_CHARS = 100  # drop articles with very short summaries


def fetch_news(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """Fetch all company news for a ticker between from_date and to_date (YYYY-MM-DD)."""
    params = {
        "symbol": ticker,
        "from": from_date,
        "to": to_date,
        "token": FINNHUB_KEY,
    }
    resp = requests.get(FINNHUB_NEWS_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()  # list of article dicts


def articles_to_df(articles: list[dict], ticker: str) -> pd.DataFrame:
    """Convert Finnhub article list to a clean DataFrame."""
    rows = []
    for a in articles:
        summary = str(a.get("summary", "")).strip()
        headline = str(a.get("headline", "")).strip()
        if not headline:
            continue
        # body_text = headline + summary for richer text
        body_text = (headline + ". " + summary).strip() if summary else headline
        if len(body_text) < MIN_SUMMARY_CHARS:
            continue
        rows.append({
            "Stock_symbol": ticker,
            "Article_title": headline,
            "Date": datetime.fromtimestamp(a.get("datetime", 0)).strftime("%Y-%m-%d"),
            "Url": a.get("url", ""),
            "Publisher": a.get("source", ""),
            "body_text": body_text,
        })
    return pd.DataFrame(rows)


def fetch_ticker(ticker: str, target: int, test: bool = False) -> pd.DataFrame:
    """Fetch up to target articles for a ticker, splitting into 90-day windows."""
    today = datetime.today()
    all_dfs = []
    total = 0

    # Walk backwards in 90-day windows until we have enough or run out of history
    window_end = today
    max_windows = 12  # up to 3 years back

    for _ in range(max_windows):
        window_start = window_end - timedelta(days=90)
        from_str = window_start.strftime("%Y-%m-%d")
        to_str   = window_end.strftime("%Y-%m-%d")

        print(f"  {ticker}: fetching {from_str} → {to_str} …", end=" ")
        try:
            articles = fetch_news(ticker, from_str, to_str)
        except Exception as e:
            print(f"ERROR: {e}")
            break

        df = articles_to_df(articles, ticker)
        print(f"{len(df)} articles")

        if not df.empty:
            all_dfs.append(df)
            total += len(df)

        if test and total >= 5:
            break
        if not test and total >= target:
            break

        window_end = window_start
        time.sleep(0.5)  # stay within free tier rate limit (60 calls/min)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Url"]).drop_duplicates(subset=["Article_title"])
    combined = combined.sort_values("Date", ascending=False)

    if not test:
        # Even spread across time: sort ascending and sample evenly
        combined = combined.sort_values("Date", ascending=True)
        if len(combined) > target:
            indices = [round(i * (len(combined) - 1) / (target - 1)) for i in range(target)]
            combined = combined.iloc[sorted(set(indices))]

    return combined.reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Fetch 5 articles per ticker only")
    args = parser.parse_args()

    os.makedirs("data", exist_ok=True)

    # Resume: check which tickers already done
    done_tickers = set()
    if not args.test and os.path.exists(NEWS_WITH_TEXT_CSV):
        existing = pd.read_csv(NEWS_WITH_TEXT_CSV)
        for t in TICKERS:
            if (existing["Stock_symbol"] == t).sum() >= TARGET_PER_TICKER:
                done_tickers.add(t)
                print(f"  {t}: already fetched ({(existing['Stock_symbol'] == t).sum()} rows) — skipping")
        all_parts = [existing]
    else:
        all_parts = []

    for ticker in TICKERS:
        if ticker in done_tickers:
            continue
        print(f"\nFetching {ticker} …")
        df = fetch_ticker(ticker, TARGET_PER_TICKER, test=args.test)
        if df.empty:
            print(f"  WARNING: no articles found for {ticker}")
        else:
            print(f"  → {len(df)} articles kept for {ticker}")
            if args.test:
                print(f"\n  Sample texts for {ticker}:")
                for _, row in df.head(2).iterrows():
                    print(f"    [{row['Date']}] {row['Article_title'][:70]}")
                    print(f"    {row['body_text'][:300]}\n")
            all_parts.append(df)

    if not all_parts:
        print("No data fetched.")
        return

    result = pd.concat(all_parts, ignore_index=True)

    if not args.test:
        result.to_csv(NEWS_WITH_TEXT_CSV, index=False)
        print(f"\n── Final counts ──────────────────────────────")
        for t in TICKERS:
            n = (result["Stock_symbol"] == t).sum()
            print(f"  {t}: {n}")
        print(f"\nSaved {len(result)} rows → {NEWS_WITH_TEXT_CSV}")
    else:
        print(f"\n✓ Test complete. Run without --test to fetch the full dataset.")


if __name__ == "__main__":
    main()
