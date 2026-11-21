"""
Stage 1 — Data collection
Streams FNSPID All_external.csv in chunks, keeps only GOOGL / AVGO / TSM / MSFT,
cleans headlines, selects ~120 articles per ticker, saves data/raw_news.csv.
Re-runnable: if data/raw_news.csv already exists the script skips the download.
"""

import os
import re
import sys
import pandas as pd
import requests

from config import TICKERS, RAW_NEWS_CSV, FNSPID_URL, ARTICLES_TARGET

# ── headline patterns that indicate roundup / market-wide articles ──────────
ROUNDUP_PATTERNS = [
    r"stocks?\s+that\s+hit",
    r"biggest\s+movers?",
    r"stocks?\s+moving",
    r"stocks?\s+to\s+watch",
    r"earnings\s+scheduled",
    r"top\s+upgrades?,?\s+downgrades?",
    r"13f\s+roundup",
]
ROUNDUP_RE = re.compile("|".join(ROUNDUP_PATTERNS), re.IGNORECASE)


LOCAL_CACHE = "data/All_external.csv"


def download_file(url: str, dest: str):
    """Download url to dest with a progress indicator, resuming if partially downloaded."""
    existing_size = os.path.getsize(dest) if os.path.exists(dest) else 0
    headers = {"Range": f"bytes={existing_size}-"} if existing_size > 0 else {}

    resp = requests.get(url, stream=True, timeout=60, headers=headers)

    # 416 = Range Not Satisfiable means file is already complete
    if resp.status_code == 416:
        print(f"  File already fully downloaded ({existing_size / 1e9:.2f} GB)")
        return

    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0)) + existing_size
    mode = "ab" if existing_size > 0 else "wb"

    print(f"  Downloading to {dest} (total ~{total / 1e9:.1f} GB) …")
    downloaded = existing_size
    with open(dest, mode) as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 1 MB chunks
            f.write(chunk)
            downloaded += len(chunk)
            pct = downloaded / total * 100 if total else 0
            print(f"  {downloaded / 1e9:.2f} GB / {total / 1e9:.1f} GB  ({pct:.1f}%)", end="\r")
    print(f"\n  Download complete: {downloaded / 1e9:.2f} GB")


def stream_filter(url: str, tickers: list[str], chunk_size: int = 100_000) -> pd.DataFrame:
    """Download (if needed) then chunk-read the CSV locally, keep target tickers."""
    print(f"Source: {url}")

    # Download to local file if remote
    if url.startswith("http"):
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(LOCAL_CACHE):
            print(f"Downloading to {LOCAL_CACHE} first (avoids mid-stream disconnects) …")
            download_file(url, LOCAL_CACHE)
        else:
            size_gb = os.path.getsize(LOCAL_CACHE) / 1e9
            print(f"Found local cache: {LOCAL_CACHE} ({size_gb:.2f} GB) — skipping download")
        source_path = LOCAL_CACHE
    else:
        source_path = url

    print(f"\nChunk-reading {source_path} …\n")

    kept_chunks = []
    total_read = 0

    reader = pd.read_csv(
        source_path,
        chunksize=chunk_size,
        low_memory=False,
        on_bad_lines="skip",
    )

    for chunk in reader:
        total_read += len(chunk)

        # Normalise column names
        chunk.columns = [c.strip() for c in chunk.columns]

        if "Stock_symbol" not in chunk.columns:
            # Try to detect ticker column
            sym_col = next(
                (c for c in chunk.columns if "symbol" in c.lower() or "ticker" in c.lower()),
                None,
            )
            if sym_col:
                chunk = chunk.rename(columns={sym_col: "Stock_symbol"})
            else:
                print(f"  WARNING: no Stock_symbol column found in this chunk. Columns: {list(chunk.columns)[:10]}")
                continue

        filtered = chunk[chunk["Stock_symbol"].isin(tickers)].copy()
        if not filtered.empty:
            kept_chunks.append(filtered)

        if total_read % 1_000_000 == 0:
            kept_so_far = sum(len(c) for c in kept_chunks)
            print(f"  Read {total_read:,} rows … kept {kept_so_far:,} rows for target tickers")

    if not kept_chunks:
        return pd.DataFrame()

    df = pd.concat(kept_chunks, ignore_index=True)
    print(f"\nTotal rows read : {total_read:,}")
    print(f"Rows kept (4 tickers): {len(df):,}")
    return df


def clean_and_select(df: pd.DataFrame, target: int) -> pd.DataFrame:
    """Deduplicate, remove roundup headlines, select ~target rows per ticker."""

    # ── Step 1: deduplicate on (Stock_symbol, Url) ──────────────────────────
    before = len(df)
    df = df.drop_duplicates(subset=["Stock_symbol", "Url"])
    print(f"\nDrop duplicates (Stock_symbol + Url): removed {before - len(df):,} rows")

    # ── Step 2: remove roundup / market-wide headlines ───────────────────────
    title_col = next(
        (c for c in df.columns if "title" in c.lower() or "headline" in c.lower()),
        None,
    )
    if title_col is None:
        print("WARNING: no title/headline column found — skipping roundup filter")
        removed_roundup = 0
    else:
        mask_roundup = df[title_col].fillna("").apply(lambda t: bool(ROUNDUP_RE.search(t)))
        removed_roundup = mask_roundup.sum()
        df = df[~mask_roundup]
        print(f"Drop roundup/market-wide headlines:  removed {removed_roundup:,} rows")

    # ── Step 3: per-ticker counts after cleaning ─────────────────────────────
    print("\nRow counts per ticker after cleaning:")
    for t in TICKERS:
        n = (df["Stock_symbol"] == t).sum()
        print(f"  {t}: {n:,}")

    # ── Step 4: select ~target articles per ticker, spread across time ───────
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.sort_values("Date", ascending=True)  # oldest first so we can pick evenly

    selected_parts = []
    for t in TICKERS:
        sub = df[df["Stock_symbol"] == t].copy()
        if len(sub) == 0:
            print(f"WARNING: no rows for {t} — will check secondary file")
            continue
        if len(sub) <= target:
            print(f"  {t}: only {len(sub)} rows — taking all (less than target {target})")
            selected_parts.append(sub)
        else:
            # Even-index sampling to spread across time
            indices = [round(i * (len(sub) - 1) / (target - 1)) for i in range(target)]
            indices = sorted(set(indices))
            selected_parts.append(sub.iloc[indices])

    result = pd.concat(selected_parts, ignore_index=True)

    print(f"\nFinal selection (~{target} per ticker):")
    for t in TICKERS:
        n = (result["Stock_symbol"] == t).sum()
        print(f"  {t}: {n:,}")

    return result


def main():
    os.makedirs("data", exist_ok=True)

    if os.path.exists(RAW_NEWS_CSV):
        print(f"{RAW_NEWS_CSV} already exists — skipping download/filter step.")
        df = pd.read_csv(RAW_NEWS_CSV)
        print(f"Loaded {len(df):,} rows from existing file.")
        print("\nRow counts per ticker:")
        for t in TICKERS:
            print(f"  {t}: {(df['Stock_symbol'] == t).sum():,}")
        return

    # Check if the file exists locally (user might have downloaded manually)
    local_path = "data/All_external.csv"
    source = local_path if os.path.exists(local_path) else FNSPID_URL

    raw_df = stream_filter(source, TICKERS)

    if raw_df.empty:
        print("\nERROR: No rows found for any of the target tickers.")
        print("Possible causes:")
        print("  - The CSV uses different ticker symbols (check column names above)")
        print("  - The download failed partway through")
        print("  - GOOGL/AVGO/TSM/MSFT are not present in All_external.csv")
        print("\nFallback option: download nasdaq_exteral_data.csv (23.2 GB) instead.")
        print("Tell me and I will update the script before you start that download.")
        sys.exit(1)

    # Check which tickers are missing
    found = set(raw_df["Stock_symbol"].unique())
    missing = [t for t in TICKERS if t not in found]
    if missing:
        print(f"\nWARNING: These tickers not found in All_external.csv: {missing}")
        print("They may be in nasdaq_exteral_data.csv — tell me before downloading that file (23.2 GB).")

    cleaned_df = clean_and_select(raw_df, ARTICLES_TARGET)
    cleaned_df.to_csv(RAW_NEWS_CSV, index=False)
    print(f"\nSaved {len(cleaned_df):,} rows → {RAW_NEWS_CSV}")


if __name__ == "__main__":
    main()
