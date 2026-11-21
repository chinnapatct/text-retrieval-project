"""
Stage 3 — Earnings dates and days_to_earnings
1. Fetches earnings dates for all 4 tickers via yfinance.
2. Checks overlap with article dates.
3. Computes days_to_earnings (absolute) and days_from_earnings (signed, negative = before).
4. Saves data/earnings_dates.csv and updates data/news_with_text.csv with the new columns.
Re-runnable: skips download if earnings_dates.csv already exists.
"""

import os
import numpy as np
import pandas as pd
import yfinance as yf

from config import TICKERS, EARNINGS_CSV, NEWS_WITH_TEXT_CSV


def fetch_earnings(tickers: list[str], limit: int = 40) -> pd.DataFrame:
    """Fetch upcoming + past earnings dates for each ticker."""
    all_rows = []
    for t in tickers:
        print(f"  Fetching earnings dates for {t} …", end=" ")
        try:
            ticker = yf.Ticker(t)
            df = ticker.get_earnings_dates(limit=limit)
            if df is None or df.empty:
                print("NO DATA")
                continue
            df = df.reset_index()
            # Column name varies by yfinance version — normalise
            date_col = df.columns[0]
            df = df.rename(columns={date_col: "earnings_date"})
            df["earnings_date"] = pd.to_datetime(df["earnings_date"], utc=True).dt.tz_localize(None)
            df["ticker"] = t
            all_rows.append(df[["ticker", "earnings_date"]])
            print(f"{len(df)} dates  ({df['earnings_date'].min().date()} → {df['earnings_date'].max().date()})")
        except Exception as e:
            print(f"ERROR: {e}")

    if not all_rows:
        return pd.DataFrame()
    return pd.concat(all_rows, ignore_index=True).drop_duplicates()


def nearest_earnings(article_date: pd.Timestamp, dates: pd.Series):
    """Return (nearest_date, days_from_earnings) for a given article date."""
    if dates.empty:
        return pd.NaT, np.nan
    deltas = (dates - article_date).dt.total_seconds() / 86400  # signed days
    idx = deltas.abs().idxmin()
    return dates[idx], deltas[idx]


def main():
    os.makedirs("data", exist_ok=True)

    # ── Step 1: fetch earnings dates ─────────────────────────────────────────
    if os.path.exists(EARNINGS_CSV):
        print(f"Loading existing {EARNINGS_CSV}")
        earnings_df = pd.read_csv(EARNINGS_CSV, parse_dates=["earnings_date"])
    else:
        print("Fetching earnings dates from yfinance …")
        earnings_df = fetch_earnings(TICKERS, limit=40)
        if earnings_df.empty:
            print("ERROR: could not fetch any earnings dates.")
            return
        earnings_df.to_csv(EARNINGS_CSV, index=False)
        print(f"Saved {len(earnings_df)} earnings dates → {EARNINGS_CSV}")

    print(f"\nEarnings date coverage per ticker:")
    for t in TICKERS:
        sub = earnings_df[earnings_df["ticker"] == t]["earnings_date"]
        if sub.empty:
            print(f"  {t}: NO DATA")
        else:
            print(f"  {t}: {len(sub)} dates  {sub.min().date()} → {sub.max().date()}")

    # ── Step 2: load articles and check overlap ───────────────────────────────
    news_df = pd.read_csv(NEWS_WITH_TEXT_CSV)
    news_df["Date"] = pd.to_datetime(news_df["Date"], errors="coerce")

    print(f"\nArticle date coverage per ticker:")
    for t in TICKERS:
        sub = news_df[news_df["Stock_symbol"] == t]["Date"].dropna()
        if sub.empty:
            print(f"  {t}: NO DATES")
        else:
            print(f"  {t}: {len(sub)} articles  {sub.min().date()} → {sub.max().date()}")

    # Check overlap
    print(f"\nOverlap check:")
    bad_tickers = []
    for t in TICKERS:
        art_dates = news_df[news_df["Stock_symbol"] == t]["Date"].dropna()
        earn_dates = pd.to_datetime(
            earnings_df[earnings_df["ticker"] == t]["earnings_date"]
        )
        if art_dates.empty or earn_dates.empty:
            print(f"  {t}: ⚠️  missing data — skipping")
            bad_tickers.append(t)
            continue
        art_min, art_max = art_dates.min(), art_dates.max()
        earn_min, earn_max = earn_dates.min(), earn_dates.max()
        overlap = not (earn_max < art_min or earn_min > art_max)
        # Also check: any earnings within 90 days of any article
        close = any(
            abs((e - a).days) <= 90
            for e in earn_dates
            for a in art_dates.sample(min(10, len(art_dates)), random_state=1)
        )
        status = "✅ overlap" if overlap or close else "⚠️  NO OVERLAP"
        print(f"  {t}: articles {art_min.date()}→{art_max.date()}  |  "
              f"earnings {earn_min.date()}→{earn_max.date()}  |  {status}")
        if not overlap and not close:
            bad_tickers.append(t)

    if bad_tickers:
        print(f"\n⚠️  Tickers with no earnings overlap: {bad_tickers}")
        print("Restricting those tickers to articles within ±180 days of nearest earnings date.")

    # ── Step 3: compute days_to_earnings and days_from_earnings ──────────────
    print(f"\nComputing days_to_earnings …")
    nearest_dates = []
    days_from = []
    days_to = []

    for _, row in news_df.iterrows():
        t = row["Stock_symbol"]
        art_date = row["Date"]
        earn_dates = pd.to_datetime(
            earnings_df[earnings_df["ticker"] == t]["earnings_date"]
        )
        if pd.isna(art_date) or earn_dates.empty:
            nearest_dates.append(pd.NaT)
            days_from.append(np.nan)
            days_to.append(np.nan)
            continue
        nd, df_val = nearest_earnings(art_date, earn_dates)
        nearest_dates.append(nd)
        days_from.append(round(df_val))        # signed: negative = before earnings
        days_to.append(round(abs(df_val)))     # absolute distance

    news_df["nearest_earnings_date"] = nearest_dates
    news_df["days_from_earnings"] = days_from   # signed
    news_df["days_to_earnings"] = days_to       # absolute

    # ── Step 4: print sanity-check examples ──────────────────────────────────
    print(f"\nSample rows (article date → nearest earnings → days):")
    sample = news_df.dropna(subset=["days_to_earnings"]).sample(8, random_state=42)
    for _, row in sample.iterrows():
        title_col = next((c for c in news_df.columns if "title" in c.lower()), "Url")
        print(f"  {row['Stock_symbol']}  {str(row['Date'].date())}  "
              f"nearest_earnings={str(row['nearest_earnings_date'])[:10]}  "
              f"days_from={int(row['days_from_earnings']):+d}  "
              f"days_to={int(row['days_to_earnings'])}  "
              f"| {str(row[title_col])[:55]}")

    print(f"\ndays_to_earnings stats:")
    print(news_df["days_to_earnings"].describe().to_string())

    # ── Step 5: save updated news file ───────────────────────────────────────
    news_df.to_csv(NEWS_WITH_TEXT_CSV, index=False)
    print(f"\nUpdated {NEWS_WITH_TEXT_CSV} with days_to_earnings columns.")


if __name__ == "__main__":
    main()
