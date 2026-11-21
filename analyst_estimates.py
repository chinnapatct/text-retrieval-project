"""
analyst_estimates.py — Analyst data for StockView
  1. /stock/recommendation  — Finnhub (free): consensus Buy/Hold/Sell counts
  2. price target           — yfinance (free): mean/high/low/median + current price
  3. EPS estimates          — yfinance (free): next 2 quarters + 2 annual
  4. Revenue estimates      — yfinance (free): next 2 quarters + 2 annual
Finnhub API key from env var FINNHUB_API_KEY or refresh.py fallback — never hardcoded here.
"""

import os
import requests
import yfinance as yf

BASE = "https://finnhub.io/api/v1"


def _finnhub_get(path: str, params: dict) -> list | dict | None:
    from refresh import FINNHUB_KEY as _fallback_key
    key = os.environ.get("FINNHUB_API_KEY", "") or _fallback_key
    if not key:
        return None
    try:
        r = requests.get(BASE + path, params={**params, "token": key}, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data == [] or data == {}:
                return None
            return data
    except Exception:
        pass
    return None


def get_recommendation(ticker: str) -> dict | None:
    data = _finnhub_get("/stock/recommendation", {"symbol": ticker})
    if not data or not isinstance(data, list):
        return None
    return data[0]


def get_price_target(ticker: str) -> dict | None:
    """Returns {targetMean, targetHigh, targetLow, targetMedian, currentPrice, numberOfAnalysts}."""
    try:
        info = yf.Ticker(ticker).info
        mean = info.get("targetMeanPrice")
        if mean is None:
            return None
        return {
            "targetMean":    mean,
            "targetHigh":    info.get("targetHighPrice"),
            "targetLow":     info.get("targetLowPrice"),
            "targetMedian":  info.get("targetMedianPrice"),
            "currentPrice":  info.get("currentPrice"),
            "numberOfAnalysts": info.get("numberOfAnalystOpinions"),
        }
    except Exception:
        return None


def get_eps_estimates(ticker: str) -> list[dict]:
    """Returns list of {period, avg, low, high, numberOfAnalysts, growth}."""
    try:
        df = yf.Ticker(ticker).earnings_estimate
        if df is None or df.empty:
            return []
        rows = []
        for period, row in df.iterrows():
            rows.append({
                "period":           str(period),
                "epsAvg":           row.get("avg"),
                "epsLow":           row.get("low"),
                "epsHigh":          row.get("high"),
                "numberAnalysts":   int(row.get("numberOfAnalysts", 0) or 0),
                "growth":           row.get("growth"),
            })
        return rows[:4]
    except Exception:
        return []


def get_revenue_estimates(ticker: str) -> list[dict]:
    """Returns list of {period, revenueAvg, revenueLow, revenueHigh, numberOfAnalysts, growth}."""
    try:
        df = yf.Ticker(ticker).revenue_estimate
        if df is None or df.empty:
            return []
        rows = []
        for period, row in df.iterrows():
            rows.append({
                "period":           str(period),
                "revenueAvg":       row.get("avg"),
                "revenueLow":       row.get("low"),
                "revenueHigh":      row.get("high"),
                "numberAnalysts":   int(row.get("numberOfAnalysts", 0) or 0),
                "growth":           row.get("growth"),
            })
        return rows[:4]
    except Exception:
        return []


def fmt_billions(value) -> str:
    if value is None:
        return "N/A"
    try:
        v = float(value)
        if abs(v) >= 1e9:
            return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6:
            return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except (ValueError, TypeError):
        return "N/A"


def fmt_dollars(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"${float(value):.2f}"
    except (ValueError, TypeError):
        return "N/A"
