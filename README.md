# Pre-Earnings Risk News Search Engine

A vertical search engine for pre-earnings risk news on four tech stocks:
**GOOGL · AVGO · TSM · NVDA**

Built for ITCS 441 — Information Retrieval and Text Mining.

---

## System requirements

- macOS (Apple Silicon recommended), 16 GB RAM
- Python 3.10+
- Docker Desktop

---

## Setup

### 1. Start Elasticsearch

**Option A — Docker run (quick start):**
```bash
docker run -d --name elasticsearch \
  -p 9200:9200 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
  docker.elastic.co/elasticsearch/elasticsearch:8.13.4
```

**Option B — Docker Compose:**
```bash
docker compose up -d
```

Verify it is running:
```bash
curl http://localhost:9200
```
You should see `"tagline": "You Know, for Search"`.

---

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

---

### 3. Run the pipeline (in order)

```bash
# Stage 1 — collect and filter FNSPID data (requires ~5.7 GB download)
python3 01_collect_news.py

# Stage 1b — add NVDA articles (reads already-downloaded file)
python3 01b_add_nvda.py

# Stage 2 — fetch article text from Finnhub API
python3 02_fetch_finnhub.py

# Stage 3 — fetch earnings dates and compute days_to_earnings
python3 03_earnings.py

# Stage 4 — apply risk-theme keyword tags
python3 04_tag_risks.py

# Stage 5 — generate embeddings and index into Elasticsearch
python3 05_index.py

# Stage 6 — (no script to run; search.py is the library)

# Stage 7 — evaluation: run 8 test queries, save results/
python3 06_evaluate.py
```

Each script is re-runnable: it skips work already done where possible.

---

### 4. Launch the search app

```bash
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

---

## Project structure

```
.
├── config.py               # Central config (tickers, paths, weights)
├── risk_themes.py          # Risk-theme keyword rules and tag_risks()
├── search.py               # Core search function (all modes)
│
├── 01_collect_news.py      # Stage 1: collect & filter FNSPID
├── 01b_add_nvda.py         # Stage 1b: add NVDA to raw_news.csv
├── 02_fetch_finnhub.py     # Stage 2: fetch article text via Finnhub
├── 03_earnings.py          # Stage 3: earnings dates + days_to_earnings
├── 04_tag_risks.py         # Stage 4: risk-theme tagging
├── 05_index.py             # Stage 5: embed + index into Elasticsearch
├── 06_evaluate.py          # Stage 7: evaluation
├── app.py                  # Stage 8: Streamlit UI
│
├── data/
│   ├── raw_news.csv        # 480 filtered articles (4 tickers × 120)
│   ├── news_with_text.csv  # + body text + earnings + risk tags
│   └── earnings_dates.csv  # yfinance earnings dates for 4 tickers
│
├── results/
│   ├── eval_*.md           # Per-query evaluation tables
│   └── summary.md          # Mode comparison summary
│
├── docs/
│   └── report_notes.md     # Report draft with real numbers
│
├── requirements.txt
└── docker-compose.yml
```

---

## Search modes

| Mode | Description |
|------|-------------|
| **Hybrid** | BM25 + vector + risk-theme boost + earnings decay (recommended) |
| **BM25** | Keyword matching on headline (×2) and body text |
| **Vector** | Semantic similarity via `all-MiniLM-L6-v2` embeddings |
| **Latest** | Sort by publish date descending |
| **Risk theme first** | Risk-tagged articles bubble to top, then by date |

---

## Configuration

Edit `config.py` to change:
- `TICKERS` — which stocks to include
- `RISK_THEME_BOOST` — weight for risk-theme match in hybrid mode
- `GAUSS_SCALE` / `GAUSS_DECAY` — earnings-proximity decay parameters
- `BM25_WEIGHT` / `KNN_WEIGHT` — relative weight of BM25 vs vector

---

## Notes

- Elasticsearch must be running before `05_index.py` and `app.py`
- The Finnhub free tier provides ~240 articles per ticker per 90-day window
- The `all-MiniLM-L6-v2` model is downloaded automatically on first run (~90 MB)
- Do not commit `data/All_external.csv` (5.7 GB) to git
