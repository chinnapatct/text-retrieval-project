"""
search.py — core search function for risk_news index
Supports modes: bm25, vector, hybrid, latest, risk_date
Usage:
  from search import search
  results = search("chip shortage", ticker="NVDA", mode="hybrid")
"""

from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer

from config import (
    ES_HOST, INDEX_NAME, EMBEDDING_MODEL,
    RISK_THEME_BOOST, GAUSS_SCALE, GAUSS_DECAY,
    BM25_WEIGHT, KNN_WEIGHT,
)
from risk_themes import tag_risks, THEMES

# ── Module-level singletons (loaded once) ─────────────────────────────────────
_es = None
_model = None


def _get_es() -> Elasticsearch:
    global _es
    if _es is None:
        _es = Elasticsearch(ES_HOST)
    return _es


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _embed(text: str) -> list[float]:
    return _get_model().encode(text, normalize_embeddings=True).tolist()


def _detect_theme(query: str) -> str | None:
    """Detect a risk theme from the query using the same keyword rules."""
    tags = tag_risks(query)
    non_general = [t for t in tags if t != "general_news"]
    return non_general[0] if non_general else None


def _ticker_filter(ticker: str | None) -> list[dict] | None:
    if not ticker or ticker.upper() == "ALL":
        return None
    return [{"term": {"ticker": ticker.upper()}}]


def _theme_filter(theme: str | None) -> list[dict] | None:
    if not theme or theme == "all":
        return None
    return [{"term": {"risk_theme_tags": theme}}]


def _sentiment_filter(sentiment: str | None) -> list[dict] | None:
    if not sentiment or sentiment == "all":
        return None
    return [{"term": {"finbert_sentiment": sentiment.lower()}}]


def search(
    query: str,
    ticker: str | None = None,
    theme: str | None = None,
    sentiment: str | None = None,
    mode: str = "hybrid",
    size: int = 10,
) -> list[dict]:
    """
    Search risk_news index.

    Parameters
    ----------
    query     : free-text search query
    ticker    : optional ticker filter ("GOOGL", "NVDA", etc.)
    theme     : optional risk theme filter ("supply_chain", etc.)
    sentiment : optional FinBERT sentiment filter ("negative", "neutral", "positive")
    mode      : "bm25" | "vector" | "hybrid" | "latest" | "risk_date"
    size      : number of results to return

    Returns list of dicts with keys: score, ticker, headline, body_text,
    publish_date, days_to_earnings, days_from_earnings, risk_theme_tags,
    url, publisher
    """
    es = _get_es()
    mode = mode.lower()

    ticker_f    = _ticker_filter(ticker)
    theme_f     = _theme_filter(theme)
    sentiment_f = _sentiment_filter(sentiment)
    filters     = (ticker_f or []) + (theme_f or []) + (sentiment_f or [])

    # Empty query — fall back to latest mode so filters still work
    if not query or not query.strip():
        mode = "latest"

    # ── Latest: sort by date descending ──────────────────────────────────────
    if mode == "latest":
        body = {
            "query": {
                "bool": {
                    "must": [{"match_all": {}}],
                    "filter": filters,
                }
            },
            "sort": [{"publish_date": {"order": "desc"}}],
            "size": size,
        }
        resp = es.search(index=INDEX_NAME, body=body)
        return _format(resp)

    # ── Risk+Date: tagged articles first, then by date ────────────────────────
    if mode == "risk_date":
        detected_theme = theme or _detect_theme(query)
        target_theme = detected_theme or "regulatory_antitrust"  # default to show tagged first

        body = {
            "query": {
                "bool": {
                    "must": [{"match_all": {}}],
                    "filter": filters,
                }
            },
            "sort": [
                {
                    "_script": {
                        "type": "number",
                        "script": {
                            "lang": "painless",
                            "source": "doc['risk_theme_tags'].contains(params.theme) ? 1 : 0",
                            "params": {"theme": target_theme},
                        },
                        "order": "desc",
                    }
                },
                {"publish_date": {"order": "desc"}},
            ],
            "size": size,
        }
        resp = es.search(index=INDEX_NAME, body=body)
        return _format(resp)

    # ── BM25: multi_match on headline (boosted) and body ─────────────────────
    if mode == "bm25":
        bm25_query = {
            "multi_match": {
                "query": query,
                "fields": ["headline^2", "body_text"],
                "type": "best_fields",
            }
        }
        body = {
            "query": {
                "bool": {
                    "must": [bm25_query],
                    "filter": filters,
                }
            },
            "size": size,
        }
        resp = es.search(index=INDEX_NAME, body=body)
        return _format(resp)

    # ── Vector: kNN on embedding ──────────────────────────────────────────────
    if mode == "vector":
        query_vec = _embed(query)
        body = {
            "knn": {
                "field": "embedding",
                "query_vector": query_vec,
                "k": size,
                "num_candidates": size * 5,
                "filter": filters if filters else None,
            },
            "size": size,
        }
        if not filters:
            del body["knn"]["filter"]
        resp = es.search(index=INDEX_NAME, body=body)
        return _format(resp)

    # ── Hybrid (default): BM25 + kNN + risk boost + earnings decay ────────────
    if mode == "hybrid":
        detected_theme = theme or _detect_theme(query)
        query_vec = _embed(query)

        # BM25 part wrapped in function_score for risk boost + earnings decay
        bm25_query = {
            "multi_match": {
                "query": query,
                "fields": ["headline^2", "body_text"],
                "type": "best_fields",
            }
        }

        functions = []

        # FinBERT boost: negative sentiment articles (risk signals) rank higher
        functions.append({
            "filter": {"term": {"finbert_sentiment": "negative"}},
            "weight": RISK_THEME_BOOST,
        })

        # Risk theme boost for query-matched theme
        if detected_theme:
            functions.append({
                "filter": {"term": {"risk_theme_tags": detected_theme}},
                "weight": RISK_THEME_BOOST,
            })

        # Gaussian decay on days_to_earnings (closer = higher score)
        functions.append({
            "gauss": {
                "days_to_earnings": {
                    "origin": 0,
                    "scale": GAUSS_SCALE,
                    "decay": GAUSS_DECAY,
                    "offset": 0,
                }
            }
        })

        function_score_query = {
            "function_score": {
                "query": bm25_query,
                "functions": functions,
                "score_mode": "multiply",
                "boost_mode": "multiply",
                "boost": BM25_WEIGHT,
            }
        }

        body = {
            "query": {
                "bool": {
                    "must": [function_score_query],
                    "filter": filters,
                }
            },
            "knn": {
                "field": "embedding",
                "query_vector": query_vec,
                "k": size * 2,
                "num_candidates": size * 10,
                "boost": KNN_WEIGHT,
                "filter": filters if filters else None,
            },
            "size": size,
        }
        if not filters:
            del body["knn"]["filter"]

        resp = es.search(index=INDEX_NAME, body=body)
        return _format(resp)

    raise ValueError(f"Unknown mode: {mode}. Use bm25, vector, hybrid, latest, or risk_date.")


def _format(resp: dict) -> list[dict]:
    """Extract clean result dicts from an ES response."""
    results = []
    for hit in resp["hits"]["hits"]:
        src = hit["_source"]
        results.append({
            "score":               round(hit.get("_score") or 0, 4),
            "ticker":              src.get("ticker", ""),
            "headline":            src.get("headline", ""),
            "body_text":           src.get("body_text", ""),
            "publish_date":        src.get("publish_date", ""),
            "days_to_earnings":    src.get("days_to_earnings"),
            "days_from_earnings":  src.get("days_from_earnings"),
            "risk_theme_tags":     src.get("risk_theme_tags", []),
            "finbert_sentiment":   src.get("finbert_sentiment", ""),
            "url":                 src.get("url", ""),
            "publisher":           src.get("publisher", ""),
        })
    return results
