"""
Stage 4 — Apply risk-theme tags and FinBERT sentiment to all articles.
Reads data/news_with_text.csv, tags headline + body_text,
adds finbert_sentiment (positive/negative/neutral) and finbert_score (0-1),
saves back to the same file.
"""

import os
import pandas as pd
from transformers import pipeline

from config import NEWS_WITH_TEXT_CSV
from risk_themes import tag_risks, THEMES

FINBERT_MODEL = "ProsusAI/finbert"


def score_sentiment(texts: list[str], classifier) -> list[tuple[str, float]]:
    """Run FinBERT on a list of texts. Returns list of (label, score)."""
    results = []
    batch_size = 16
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        # Truncate to 512 tokens max
        batch = [t[:512] for t in batch]
        preds = classifier(batch, truncation=True, max_length=512)
        for p in preds:
            results.append((p["label"], round(p["score"], 4)))
        print(f"  FinBERT: {min(i+batch_size, len(texts))}/{len(texts)} articles scored …")
    return results


def main():
    df = pd.read_csv(NEWS_WITH_TEXT_CSV)
    print(f"Loaded {len(df)} articles from {NEWS_WITH_TEXT_CSV}\n")

    title_col = next((c for c in df.columns if "title" in c.lower()), None)

    # Tag on headline + body_text combined
    def tag_row(row):
        headline = str(row.get(title_col, "") or "")
        body = str(row.get("body_text", "") or "")
        return tag_risks(headline + " " + body)

    df["risk_theme_tags"] = df.apply(tag_row, axis=1)

    # ── FinBERT sentiment ─────────────────────────────────────────────────────
    print(f"\nLoading FinBERT model ({FINBERT_MODEL}) …")
    classifier = pipeline("text-classification", model=FINBERT_MODEL, tokenizer="bert-base-uncased")
    print("Model loaded. Scoring articles …")

    texts = (df[title_col].fillna("") + ". " + df["body_text"].fillna("")).tolist()
    sentiments = score_sentiment(texts, classifier)
    df["finbert_sentiment"] = [s[0] for s in sentiments]
    df["finbert_score"]     = [s[1] for s in sentiments]

    print("\nFinBERT sentiment distribution:")
    print(df["finbert_sentiment"].value_counts().to_string())

    # ── Counts per theme ──────────────────────────────────────────────────────
    print("Article counts per theme (articles can have multiple tags):")
    all_themes = list(THEMES.keys()) + ["general_news"]
    for theme in all_themes:
        count = df["risk_theme_tags"].apply(lambda tags: theme in tags).sum()
        print(f"  {theme:25s}: {count}")

    # ── 3 example headlines per theme ────────────────────────────────────────
    print("\n3 example headlines per theme:")
    for theme in all_themes:
        mask = df["risk_theme_tags"].apply(lambda tags: theme in tags)
        examples = df[mask]
        if examples.empty:
            print(f"\n  [{theme}] — no matches")
            continue
        print(f"\n  [{theme}]")
        for _, row in examples.head(3).iterrows():
            headline = str(row[title_col])[:90] if title_col else "N/A"
            print(f"    • {headline}")

    # ── Save ──────────────────────────────────────────────────────────────────
    # Store tags as a pipe-separated string for easy CSV storage
    df["risk_theme_tags"] = df["risk_theme_tags"].apply(lambda t: "|".join(t))
    df.to_csv(NEWS_WITH_TEXT_CSV, index=False)
    print(f"\nSaved tagged articles → {NEWS_WITH_TEXT_CSV}")


if __name__ == "__main__":
    main()
