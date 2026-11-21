"""
Stage 5 — Embeddings and Elasticsearch indexing
1. Connects to Elasticsearch (must be running on localhost:9200).
2. Creates index 'risk_news' with the required mapping.
3. Generates embeddings for each article (headline + first ~1000 chars of body).
4. Bulk indexes all documents.
5. Prints document count and a sample document.
Re-runnable: deletes and recreates the index if it already exists.
"""

import os
import sys

import pandas as pd
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from sentence_transformers import SentenceTransformer

from config import (
    ES_HOST, INDEX_NAME, NEWS_WITH_TEXT_CSV,
    EMBEDDING_MODEL, EMBEDDING_DIMS,
)

INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "properties": {
            "ticker":           {"type": "keyword"},
            "headline":         {"type": "text", "analyzer": "english"},
            "body_text":        {"type": "text", "analyzer": "english"},
            "risk_theme_tags":  {"type": "keyword"},
            "publish_date":     {"type": "date", "format": "yyyy-MM-dd||yyyy-MM-dd'T'HH:mm:ssZ"},
            "days_to_earnings": {"type": "integer"},
            "days_from_earnings": {"type": "integer"},
            "url":              {"type": "keyword"},
            "publisher":        {"type": "keyword"},
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


def check_es(es: Elasticsearch):
    """Confirm Elasticsearch is healthy."""
    try:
        health = es.cluster.health()
        print(f"Elasticsearch status: {health['status']}  "
              f"(cluster: {health['cluster_name']})")
        return True
    except Exception as e:
        print(f"ERROR: Cannot connect to Elasticsearch at {ES_HOST}")
        print(f"  {e}")
        print("\nMake sure you ran:")
        print("  docker run -d --name elasticsearch \\")
        print("    -p 9200:9200 \\")
        print("    -e 'discovery.type=single-node' \\")
        print("    -e 'xpack.security.enabled=false' \\")
        print("    -e 'ES_JAVA_OPTS=-Xms512m -Xmx512m' \\")
        print("    docker.elastic.co/elasticsearch/elasticsearch:8.13.4")
        return False


def create_index(es: Elasticsearch):
    """Delete and recreate the index."""
    if es.indices.exists(index=INDEX_NAME):
        es.indices.delete(index=INDEX_NAME)
        print(f"Deleted existing index '{INDEX_NAME}'")
    es.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)
    print(f"Created index '{INDEX_NAME}'")


def embed_text(model: SentenceTransformer, headline: str, body: str) -> list[float]:
    """Embed headline + first ~1000 chars of body (MiniLM ~256 token limit)."""
    text = headline + ". " + body[:1000]
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def build_docs(df: pd.DataFrame, model: SentenceTransformer) -> list[dict]:
    """Convert DataFrame rows to Elasticsearch documents with embeddings."""
    docs = []
    title_col = next((c for c in df.columns if "title" in c.lower()), None)

    print(f"Generating embeddings for {len(df)} documents …")
    for i, row in df.iterrows():
        headline = str(row.get(title_col, "") or "")
        body = str(row.get("body_text", "") or "")

        # Parse risk tags from pipe-separated string
        tags_raw = str(row.get("risk_theme_tags", "general_news") or "general_news")
        tags = [t.strip() for t in tags_raw.split("|") if t.strip()]

        # Parse days safely
        def safe_int(val):
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None

        embedding = embed_text(model, headline, body)

        doc = {
            "_index": INDEX_NAME,
            "_source": {
                "ticker":             row.get("Stock_symbol", ""),
                "headline":           headline,
                "body_text":          body,
                "risk_theme_tags":    tags,
                "publish_date":       str(row.get("Date", ""))[:10] or None,
                "days_to_earnings":   safe_int(row.get("days_to_earnings")),
                "days_from_earnings": safe_int(row.get("days_from_earnings")),
                "url":                str(row.get("Url", "") or ""),
                "publisher":          str(row.get("Publisher", "") or ""),
                "finbert_sentiment":  str(row.get("finbert_sentiment", "neutral") or "neutral"),
                "finbert_score":      float(row.get("finbert_score", 0.5) or 0.5),
                "embedding":          embedding,
            }
        }
        docs.append(doc)

        if (i + 1) % 50 == 0:
            print(f"  Embedded {i + 1}/{len(df)} …")

    return docs


def main():
    # ── Connect ───────────────────────────────────────────────────────────────
    es = Elasticsearch(ES_HOST)
    if not check_es(es):
        sys.exit(1)

    # ── Create index ──────────────────────────────────────────────────────────
    create_index(es)

    # ── Load data ─────────────────────────────────────────────────────────────
    df = pd.read_csv(NEWS_WITH_TEXT_CSV)
    print(f"Loaded {len(df)} articles from {NEWS_WITH_TEXT_CSV}")

    # ── Load embedding model ──────────────────────────────────────────────────
    print(f"\nLoading embedding model '{EMBEDDING_MODEL}' …")
    model = SentenceTransformer(EMBEDDING_MODEL)
    print("Model loaded.")

    # ── Build and index documents ─────────────────────────────────────────────
    docs = build_docs(df, model)
    print(f"\nBulk indexing {len(docs)} documents …")
    success, errors = bulk(es, docs, raise_on_error=False)
    print(f"  Indexed: {success}  Errors: {len(errors) if errors else 0}")

    # Refresh so documents are immediately searchable
    es.indices.refresh(index=INDEX_NAME)

    # ── Verify ────────────────────────────────────────────────────────────────
    count = es.count(index=INDEX_NAME)["count"]
    print(f"\nDocument count in '{INDEX_NAME}': {count}")

    # Print a sample document (without the embedding vector)
    sample = es.search(index=INDEX_NAME, body={"query": {"match_all": {}}, "size": 1})
    hit = sample["hits"]["hits"][0]["_source"]
    hit_display = {k: v for k, v in hit.items() if k != "embedding"}
    print(f"\nSample document:")
    for k, v in hit_display.items():
        print(f"  {k:22s}: {str(v)[:80]}")

    print(f"\n✓ Stage 5 complete — index '{INDEX_NAME}' ready for search.")


if __name__ == "__main__":
    main()
