# config.py — central config for all scripts

TICKERS = ["GOOGL", "AVGO", "TSM", "NVDA"]

# File paths
RAW_NEWS_CSV      = "data/raw_news.csv"
NEWS_WITH_TEXT_CSV = "data/news_with_text.csv"
EARNINGS_CSV      = "data/earnings_dates.csv"

# Elasticsearch
ES_HOST       = "http://localhost:9200"
INDEX_NAME    = "risk_news"

# Embedding model
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMS  = 384

# Scraping
SCRAPE_DELAY    = 1       # seconds between requests
MIN_TEXT_CHARS  = 200     # drop pages with fewer characters
ARTICLES_TARGET = 120     # articles to keep per ticker before scraping

# Ranking weights (hybrid mode)
RISK_THEME_BOOST = 1.5    # multiplicative boost when article matches query theme
GAUSS_SCALE      = 14     # days — score decays to `decay` at this distance
GAUSS_DECAY      = 0.5    # fraction of score at scale distance
BM25_WEIGHT      = 1.0
KNN_WEIGHT       = 1.0

# Data source URL
FNSPID_URL = (
    "https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/"
    "Stock_news/All_external.csv"
)
