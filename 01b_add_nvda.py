"""
Stage 1b — Add NVDA to raw_news.csv
Reads the already-downloaded data/All_external.csv locally,
filters for NVDA, cleans, selects ~120, and appends to data/raw_news.csv.
"""

import os
import re
import sys
import pandas as pd

from config import RAW_NEWS_CSV, ARTICLES_TARGET

TICKER = "NVDA"
LOCAL_CSV = "data/All_external.csv"

ROUNDUP_RE = re.compile(
    r"stocks?\s+that\s+hit|biggest\s+movers?|stocks?\s+moving|stocks?\s+to\s+watch"
    r"|earnings\s+scheduled|top\s+upgrades?,?\s+downgrades?|13f\s+roundup",
    re.IGNORECASE,
)


def main():
    if not os.path.exists(LOCAL_CSV):
        print(f"ERROR: {LOCAL_CSV} not found. Run 01_collect_news.py first to download it.")
        sys.exit(1)

    # Check if NVDA already in raw_news.csv
    if os.path.exists(RAW_NEWS_CSV):
        existing = pd.read_csv(RAW_NEWS_CSV)
        if TICKER in existing["Stock_symbol"].values:
            n = (existing["Stock_symbol"] == TICKER).sum()
            print(f"{TICKER} already in {RAW_NEWS_CSV} ({n} rows) — nothing to do.")
            return
    else:
        existing = pd.DataFrame()

    print(f"Reading {LOCAL_CSV} in chunks, filtering for {TICKER} …")
    kept = []
    total_read = 0

    for chunk in pd.read_csv(LOCAL_CSV, chunksize=100_000, low_memory=False, on_bad_lines="skip"):
        chunk.columns = [c.strip() for c in chunk.columns]
        total_read += len(chunk)
        sub = chunk[chunk["Stock_symbol"] == TICKER]
        if not sub.empty:
            kept.append(sub)
        if total_read % 1_000_000 == 0:
            found = sum(len(c) for c in kept)
            print(f"  Read {total_read:,} rows … {TICKER} rows so far: {found:,}")

    if not kept:
        print(f"ERROR: {TICKER} not found in {LOCAL_CSV}.")
        print("It may be in nasdaq_exteral_data.csv. Tell me if you want to try that.")
        sys.exit(1)

    df = pd.concat(kept, ignore_index=True)
    print(f"\nTotal {TICKER} rows found: {len(df):,}")

    # Deduplicate
    before = len(df)
    df = df.drop_duplicates(subset=["Stock_symbol", "Url"])
    print(f"After dedup: {len(df):,} (removed {before - len(df):,})")

    # Remove roundup headlines
    title_col = next((c for c in df.columns if "title" in c.lower()), None)
    if title_col:
        mask = df[title_col].fillna("").apply(lambda t: bool(ROUNDUP_RE.search(t)))
        print(f"Roundup headlines removed: {mask.sum():,}")
        df = df[~mask]

    print(f"Clean rows: {len(df):,}")

    # Select ~120 spread across time
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.sort_values("Date", ascending=True)

    if len(df) <= ARTICLES_TARGET:
        selected = df
        print(f"Only {len(df)} rows — taking all.")
    else:
        indices = [round(i * (len(df) - 1) / (ARTICLES_TARGET - 1)) for i in range(ARTICLES_TARGET)]
        selected = df.iloc[sorted(set(indices))]

    print(f"Selected: {len(selected):,} rows for {TICKER}")

    # Append to raw_news.csv
    combined = pd.concat([existing, selected], ignore_index=True) if not existing.empty else selected
    combined.to_csv(RAW_NEWS_CSV, index=False)
    print(f"\nSaved {len(combined):,} total rows → {RAW_NEWS_CSV}")
    print("\nFinal counts per ticker:")
    for t in combined["Stock_symbol"].unique():
        print(f"  {t}: {(combined['Stock_symbol'] == t).sum():,}")


if __name__ == "__main__":
    main()
