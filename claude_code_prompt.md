# Prompt for Claude Code: ITCS 441 Project 2 (Pre-Earnings Risk News Search Engine)

Copy everything below the line into Claude Code, run from an empty project folder.

---

You are helping me build a university project: a prototype vertical search engine called **"Search Engine for Pre-Earnings Risk News"** for ITCS 441 (Information Retrieval and Text Mining). The final demo is on Nov 17, 2026 and the submission is due Nov 29, 2026. Work in the stages below. After each stage, run a check, show me the result, and stop for my go-ahead if something looks wrong. Never invent data or fake results. If something fails, tell me plainly and propose a fallback.

## Project summary

- **Goal:** users search news about a few tech stocks and get results ranked by (1) text relevance, (2) semantic similarity, (3) risk-theme match, and (4) how close the article is to the company's earnings date.
- **Target users:** retail investors and finance students doing pre-earnings due diligence.
- **Scope (set by my professor):** only 4 stocks: **GOOGL, AVGO, TSM, MSFT** (TSMC's US ticker is TSM). About 100+ news articles per stock. Article text is fetched **directly from the URL column** of the dataset. No other heavy preprocessing.
- **Hard requirement from the course:** must be a real search engine (not a SQL/database lookup). Components needed: document collection and processing, indexing, ranking, search interface.

## Tech stack

- Python 3.10+, pandas, requests, beautifulsoup4, yfinance, sentence-transformers, elasticsearch (Python client 8.x), streamlit
- Elasticsearch 8.x running locally in Docker, security disabled, single node (give me the exact docker command)
- Embedding model: `all-MiniLM-L6-v2` (384 dimensions, normalized, cosine similarity)
- My machine: macOS, Apple Silicon, 16 GB RAM

## Data source

FNSPID on Hugging Face, file `Stock_news/All_external.csv` (5.73 GB):
`https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_news/All_external.csv`

Known columns: `Date, Article_title, Stock_symbol, Url, Publisher, Author, Article, Lsa_summary, Luhn_summary, Textrank_summary, Lexrank_summary`. The `Article` column appeared null in every preview row I saw, which is why we fetch text from `Url` (mostly Benzinga links). The preview suggests the file is sorted by ticker, then by date descending, so do not assume you can stop reading early. Do NOT load the whole file into memory: read in chunks and filter to the 4 tickers. If `All_external.csv` lacks one of the tickers, check `nasdaq_exteral_data.csv` (23.2 GB) the same way, and tell me before downloading anything that large.

## Stages

### Stage 1: Data collection
1. Write `01_collect_news.py`: stream/chunk-read FNSPID, keep only the 4 tickers, save the raw filtered rows to `data/raw_news.csv`. Print row counts per ticker.
2. Clean the list: drop duplicates on (`Stock_symbol`, `Url`), and remove roundup/market-wide headlines that are not about one company (e.g. titles containing "stocks that hit", "biggest movers", "stocks moving", "stocks to watch", "earnings scheduled", "top upgrades, downgrades", "13f roundup"). Print how many rows each filter removed.
3. Select about 120 articles per ticker (so about 100+ survive scraping). Prefer a spread across time rather than only the newest. If a ticker has fewer than 120, take what exists and tell me.

### Stage 2: Scrape article text (test first)
1. Write `02_scrape_text.py` with a function that fetches a URL (realistic User-Agent, 10 s timeout) and extracts the article body with BeautifulSoup. Remove `script/style/nav/footer/header/aside`, take paragraph text, collapse whitespace.
2. **First test on 10 URLs only**, print the cleaned text for 3 of them, and report the success rate. Look for junk (cookie notices, "related articles", disclaimers) and strip recurring boilerplate phrases. If more than half fail or the text is mostly junk (blocked, paywalled, JavaScript-rendered), STOP and tell me, and suggest fallbacks (for example headline plus whatever text is available, or trying the Wayback Machine, or a different article source). Do not try to bypass blocking or paywalls.
3. If the test is fine, scrape everything with `time.sleep(1)` between requests, retry once on failure, save progress to disk every 25 rows so a crash does not lose work, drop failures and pages with fewer than 200 characters, and print the final count per ticker. I need about 100+ per ticker. Save to `data/news_with_text.csv`.

### Stage 3: Earnings dates and days_to_earnings
1. Write `03_earnings.py` using `yfinance` (`Ticker(t).get_earnings_dates(limit=...)`) for the 4 tickers. Save to `data/earnings_dates.csv`.
2. Check what date range yfinance actually covers versus my article dates. **If they do not overlap well, tell me** and restrict the articles to the covered range instead of silently producing bad numbers.
3. Compute for each article the nearest earnings date for its ticker and `days_to_earnings` (absolute number of days). Also keep a signed version `days_from_earnings` (negative = before earnings). Print a few examples to sanity-check.

### Stage 4: Risk-theme tagging (keyword rules, headline + body)
Create `risk_themes.py` with keyword lists and a `tag_risks(text)` function that returns a list of tags, or `["general_news"]` if none match. Themes (tech-specific):
- `supply_chain`: shortage, supply chain, chip shortage, semiconductor shortage, manufacturing disruption, delayed shipment, capacity constraints, export controls
- `regulatory_antitrust`: lawsuit, sued, antitrust, investigation, probe, fine, settlement, regulators, DOJ, FTC, European Commission
- `cybersecurity`: data breach, hack, cyberattack, ransomware, vulnerability, security incident
- `guidance_outlook`: cuts guidance, lowered forecast, withdraws guidance, misses estimates, profit warning, downgrade, weak outlook, lowers price target
- `leadership`: CEO resigns, steps down, names new CEO, executive departure, CFO, management shakeup
Use case-insensitive matching with word boundaries. Print the count of articles per theme and 3 example headlines per theme so I can judge quality. Note that matching is on text we have, and keyword rules will miss paraphrases (that is what the semantic search is for).

### Stage 5: Embeddings and indexing
1. Start Elasticsearch in Docker and confirm it is healthy.
2. Write `04_index.py`: create index `risk_news` with this mapping: `ticker` (keyword), `headline` (text, english analyzer), `body_text` (text, english analyzer), `risk_theme_tags` (keyword), `publish_date` (date), `days_to_earnings` (integer), `url` (keyword), `embedding` (dense_vector, dims 384, index true, similarity cosine).
3. Embedding text = headline + ". " + first ~1000 characters of the body (MiniLM truncates at ~256 tokens). Use `normalize_embeddings=True`.
4. Bulk index with `elasticsearch.helpers.bulk`, refresh, then print the document count and a sample document.

### Stage 6: Hybrid ranking
Write `search.py` exposing `search(query, ticker=None, theme=None, mode="hybrid", size=10)` that returns results with score and source fields. Support three modes so I can compare them: `bm25`, `vector`, `hybrid`.
- **BM25:** `multi_match` on `headline^2` and `body_text`.
- **Vector:** `knn` on `embedding` with the query embedded by the same model.
- **Hybrid (default):** BM25 `query` and `knn` in the same request (scores are summed), with `function_score` around the BM25 query adding (a) a weight boost when `risk_theme_tags` match the theme (use the explicit theme filter if given, otherwise detect a theme from the query using the same keyword lists) and (b) a `gauss` decay on `days_to_earnings` (origin 0, scale around 14, decay 0.5). Make the boost weights configurable constants at the top of the file.
- **RRF:** Check whether `retriever: {rrf: ...}` works on my free license. Do not assume. If it errors with a license message, tell me; I will then describe the method as a weighted sum of BM25 and kNN scores in my slides. Implement RRF only as an optional mode, clearly labeled, and keep weighted-sum hybrid as the default.
- Optional ticker filter via a `term` filter.

### Stage 7: Evaluation (this becomes report and presentation material)
Write `05_evaluate.py`. Use about 8 test queries, a mix of: one-word ("lawsuit"), multi-word ("chip supply shortage"), partial/related wording ("lowered outlook" vs headlines like "withdraws guidance"), and ticker-specific ("MSFT regulation"). For each query run bm25, vector, and hybrid, and save the top 5 for each to `results/eval_<query>.md` as tables (rank, ticker, date, headline, score, tags). Then write `results/summary.md` listing, per query, which mode surfaced the most relevant results and why, **based only on the actual output**. Flag any query where hybrid did not help. Also try 2 or 3 different boost weight settings and report what changed.

### Stage 8: Search interface
Build `app.py` with Streamlit: search box, ticker dropdown (All + 4 tickers), risk-theme multiselect, mode selector (BM25 / Vector / Hybrid), results list showing headline (linked to URL), ticker, date, risk tags, days to earnings, score, and a short snippet with the query terms highlighted if easy. Show the result count and which mode was used. Keep it clean and simple; it needs to demo well in 8 minutes.

### Stage 9: Docs and packaging
- `README.md`: setup steps (Docker command, `pip install -r requirements.txt`, order of scripts, how to run the app).
- `requirements.txt` and `docker-compose.yml` (optional) for Elasticsearch.
- `docs/report_notes.md`: a factual draft of the report sections I will need: data statistics (articles per ticker, date range, theme counts, scrape success rate), tools and software, system diagram in text or Mermaid, limitations found, difficulties actually encountered, and lessons learned. Use real numbers from the runs. Leave clearly marked TODO placeholders where screenshots go.
- Do not commit large raw data. Do not put any secrets or keys in files.

## Working rules

- Keep code simple and commented in plain English, because I must explain every part in my presentation and answer questions about it.
- Use a `config.py` for tickers, paths, index name, model name, and weights.
- Make each script re-runnable (skip work already done where reasonable).
- After each stage, print a short status: what was produced, counts, and anything surprising.
- If you hit a decision that changes the project (blocked scraping, missing tickers, no earnings overlap, RRF license), stop and ask me instead of working around it silently.

Start with Stage 1.
