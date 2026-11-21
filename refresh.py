"""
refresh.py — Full pipeline refresh: fetch 100 latest articles per ticker,
tag risks, compute earnings proximity, clear old index, re-index everything.
Called by the Streamlit app's "Refresh Data" button.
"""

import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from sentence_transformers import SentenceTransformer
from transformers import pipeline as hf_pipeline

from config import (
    TICKERS, ES_HOST, INDEX_NAME, EARNINGS_CSV,
    EMBEDDING_MODEL, EMBEDDING_DIMS,
)
from risk_themes import tag_risks

FINBERT_MODEL = "ProsusAI/finbert"

FINNHUB_KEY = "dbjb6nhr01qkamq35mggdbjb6nhr01qkamq35mh0"
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"
TARGET_PER_TICKER = 1000
MIN_BODY_CHARS = 100

INDEX_MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    "mappings": {
        "properties": {
            "ticker":             {"type": "keyword"},
            "headline":           {"type": "text", "analyzer": "english"},
            "body_text":          {"type": "text", "analyzer": "english"},
            "risk_theme_tags":    {"type": "keyword"},
            "publish_date":       {"type": "date", "format": "yyyy-MM-dd"},
            "days_to_earnings":   {"type": "integer"},
            "days_from_earnings": {"type": "integer"},
            "url":                {"type": "keyword"},
            "publisher":          {"type": "keyword"},
            "finbert_sentiment": {"type": "keyword"},
            "finbert_score":     {"type": "float"},
            "embedding": {
                "type": "dense_vector",
                "dims": EMBEDDING_DIMS,
                "index": True,
                "similarity": "cosine",
            },
        }
    },
}


def _fetch_ticker(ticker: str, target: int, log) -> pd.DataFrame:
    today = datetime.today()
    all_rows = []
    window_end = today

    for _ in range(20):  # up to ~5 years back in 90-day windows
        window_start = window_end - timedelta(days=90)
        params = {
            "symbol": ticker,
            "from": window_start.strftime("%Y-%m-%d"),
            "to": window_end.strftime("%Y-%m-%d"),
            "token": FINNHUB_KEY,
        }
        try:
            resp = requests.get(FINNHUB_NEWS_URL, params=params, timeout=15)
            resp.raise_for_status()
            articles = resp.json()
        except Exception as e:
            log(f"  {ticker}: fetch error — {e}")
            break

        for a in articles:
            headline = str(a.get("headline", "")).strip()
            summary = str(a.get("summary", "")).strip()
            body_text = (headline + ". " + summary).strip() if summary else headline
            if not headline or len(body_text) < MIN_BODY_CHARS:
                continue
            all_rows.append({
                "Stock_symbol": ticker,
                "Article_title": headline,
                "Date": datetime.fromtimestamp(a.get("datetime", 0)).strftime("%Y-%m-%d"),
                "Url": a.get("url", ""),
                "Publisher": a.get("source", ""),
                "body_text": body_text,
            })

        if len(all_rows) >= target:
            break

        window_end = window_start
        time.sleep(0.5)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["Url"]).drop_duplicates(subset=["Article_title"])
    df = df.sort_values("Date", ascending=False).head(target)
    return df.reset_index(drop=True)


def _add_earnings_proximity(df: pd.DataFrame, log) -> pd.DataFrame:
    log("Computing earnings proximity …")
    try:
        earn_rows = []
        for t in TICKERS:
            ticker_obj = yf.Ticker(t)
            earn_df = ticker_obj.get_earnings_dates(limit=40)
            if earn_df is None or earn_df.empty:
                continue
            earn_df = earn_df.reset_index()
            date_col = earn_df.columns[0]
            earn_df["earnings_date"] = pd.to_datetime(earn_df[date_col], utc=True).dt.tz_localize(None)
            earn_df["ticker"] = t
            earn_rows.append(earn_df[["ticker", "earnings_date"]])

        earnings = pd.concat(earn_rows, ignore_index=True) if earn_rows else pd.DataFrame()
    except Exception as e:
        log(f"  Warning: could not fetch earnings dates — {e}")
        earnings = pd.DataFrame()

    def compute_days(row):
        if earnings.empty:
            return None, None
        ticker_dates = earnings[earnings["ticker"] == row["Stock_symbol"]]["earnings_date"]
        if ticker_dates.empty:
            return None, None
        article_date = pd.to_datetime(row["Date"])
        diffs = (ticker_dates - article_date).dt.days
        closest_idx = diffs.abs().idxmin()
        days_from = int(diffs[closest_idx])
        days_to = abs(days_from)
        return days_to, days_from

    df[["days_to_earnings", "days_from_earnings"]] = df.apply(
        lambda r: pd.Series(compute_days(r)), axis=1
    )
    return df


def run_refresh(log=print) -> str:
    """
    Full pipeline: fetch → tag → earnings → clear index → re-index.
    `log` is a callable that accepts a string status message.
    Returns a final summary string.
    """
    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    log("Connecting to Finnhub …")
    all_parts = []
    for ticker in TICKERS:
        log(f"Fetching {ticker} …")
        df = _fetch_ticker(ticker, TARGET_PER_TICKER, log)
        if df.empty:
            log(f"  {ticker}: no articles found")
        else:
            log(f"  {ticker}: {len(df)} articles")
            all_parts.append(df)

    if not all_parts:
        return "No articles fetched — check Finnhub API key or network."

    combined = pd.concat(all_parts, ignore_index=True)
    log(f"Total fetched: {len(combined)} articles")

    # ── 2. Tag risks ──────────────────────────────────────────────────────────
    log("Tagging risk themes …")
    combined["risk_theme_tags"] = combined.apply(
        lambda r: tag_risks(str(r["Article_title"]) + " " + str(r["body_text"])), axis=1
    )

    # ── 3. Earnings proximity ─────────────────────────────────────────────────
    combined = _add_earnings_proximity(combined, log)

    # ── 4. FinBERT sentiment scoring ──────────────────────────────────────────
    log("Loading FinBERT sentiment model …")
    classifier = hf_pipeline("text-classification", model=FINBERT_MODEL, tokenizer="bert-base-uncased")
    texts = (combined["Article_title"].fillna("") + ". " + combined["body_text"].fillna("")).tolist()
    sentiments, scores = [], []
    for i in range(0, len(texts), 16):
        batch = [t[:512] for t in texts[i:i+16]]
        preds = classifier(batch, truncation=True, max_length=512)
        for p in preds:
            sentiments.append(p["label"])
            scores.append(round(p["score"], 4))
        log(f"  FinBERT: {min(i+16, len(texts))}/{len(texts)} scored …")
    combined["finbert_sentiment"] = sentiments
    combined["finbert_score"] = scores

    # ── 5. Load embedding model ───────────────────────────────────────────────
    log(f"Loading embedding model …")
    model = SentenceTransformer(EMBEDDING_MODEL)

    # ── 6. Clear and recreate index ───────────────────────────────────────────
    log("Clearing old index …")
    es = Elasticsearch(ES_HOST)
    if es.indices.exists(index=INDEX_NAME):
        es.indices.delete(index=INDEX_NAME)
    es.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)
    log("Index cleared and recreated.")

    # ── 7. Build docs and index ───────────────────────────────────────────────
    log(f"Embedding and indexing {len(combined)} articles …")
    docs = []
    for i, row in combined.iterrows():
        headline = str(row.get("Article_title", "") or "")
        body = str(row.get("body_text", "") or "")
        text = headline + ". " + body[:1000]
        embedding = model.encode(text, normalize_embeddings=True).tolist()

        tags_raw = row.get("risk_theme_tags", ["general_news"])
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split("|") if t.strip()]
        else:
            tags = list(tags_raw) if tags_raw else ["general_news"]

        def safe_int(val):
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None

        docs.append({
            "_index": INDEX_NAME,
            "_source": {
                "ticker":             row.get("Stock_symbol", ""),
                "headline":           headline,
                "body_text":          body,
                "risk_theme_tags":    tags,
                "publish_date":       str(row.get("Date", ""))[:10],
                "days_to_earnings":   safe_int(row.get("days_to_earnings")),
                "days_from_earnings": safe_int(row.get("days_from_earnings")),
                "url":                str(row.get("Url", "") or ""),
                "publisher":          str(row.get("Publisher", "") or ""),
                "finbert_sentiment":  str(row.get("finbert_sentiment", "neutral") or "neutral"),
                "finbert_score":      float(row.get("finbert_score", 0.5) or 0.5),
                "embedding":          embedding,
            },
        })

    success, errors = bulk(es, docs, raise_on_error=False)
    es.indices.refresh(index=INDEX_NAME)

    count = es.count(index=INDEX_NAME)["count"]
    summary = f"Done — {count} articles indexed ({datetime.today().strftime('%Y-%m-%d %H:%M')})"
    log(summary)
    return summary
