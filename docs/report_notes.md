# Report Notes — Pre-Earnings Risk News Search Engine
ITCS 441 — Information Retrieval and Text Mining

---

## 1. Data statistics

### Article collection

| Ticker | Raw rows in FNSPID | After dedup/clean | Selected |
|--------|-------------------|-------------------|----------|
| GOOGL | 1,676 | 1,329 | 120 |
| AVGO | 3,945 | 3,704 | 120 |
| TSM | 2,434 | 2,087 | 120 |
| NVDA | 3,146 | 2,905 | 120 |
| **Total** | **11,201** | **11,025** | **480** |

Filters applied:
- Duplicate removal on (Stock_symbol, URL): removed 25 rows (GOOGL/AVGO/TSM), 0 rows (NVDA)
- Roundup/market-wide headline filter: removed 347 rows (GOOGL/AVGO/TSM), 241 rows (NVDA)

### Article text source

The FNSPID `Article`, `Lsa_summary`, `Luhn_summary`, `Textrank_summary`, and `Lexrank_summary` columns were all null for our 4 tickers in `All_external.csv`. The source URLs (predominantly benzinga.com, 67%) are JavaScript-rendered and blocked by Cloudflare, making scraping infeasible without bypassing bot protection.

**Solution adopted:** Article text was fetched from the Finnhub company news API (free tier), which returns headline + article summary for each ticker. This provides 150–300 characters of real article content per document — sufficient for BM25, semantic embeddings, and risk-theme keyword matching.

### Article date range

| Ticker | Date range | Articles |
|--------|-----------|----------|
| GOOGL | 2026-10-30 → 2026-11-01 | 120 |
| AVGO | 2026-10-26 → 2026-11-01 | 120 |
| TSM | 2026-10-16 → 2026-11-01 | 120 |
| NVDA | 2026-10-30 → 2026-11-01 | 120 |

### Earnings dates

Fetched via `yfinance.Ticker.get_earnings_dates(limit=40)`:

| Ticker | Dates available | Coverage |
|--------|----------------|----------|
| GOOGL | 50 | 2014-10-16 → 2027-02-03 |
| AVGO | 50 | 2014-08-28 → 2026-12-09 |
| TSM | 50 | 2013-01-17 → 2027-01-14 |
| NVDA | 50 | 2014-08-07 → 2026-11-17 |

All 4 tickers have earnings dates overlapping the article date range. ✅

### days_to_earnings statistics

Computed as absolute days between article publish date and nearest earnings date:

| Stat | Value |
|------|-------|
| Count | 480 |
| Mean | 17.6 days |
| Std | 15.9 days |
| Min | 1 day |
| 25th percentile | 2 days |
| Median | 17 days |
| 75th percentile | 24 days |
| Max | 45 days |

### Risk theme counts

Articles can match multiple themes:

| Theme | Articles matched |
|-------|-----------------|
| supply_chain | 6 |
| regulatory_antitrust | 3 |
| cybersecurity | 4 |
| guidance_outlook | 8 |
| leadership | 0 |
| general_news | 459 |

Note: The low theme-match rate (4%) reflects the short document length of Finnhub summaries. Keyword rules are designed for longer article text; the vector/semantic search component compensates for paraphrase misses.

---

## 2. Tools and software

| Component | Tool / Library | Version |
|-----------|---------------|---------|
| Data source | FNSPID (Hugging Face) | — |
| News API | Finnhub (free tier) | — |
| Earnings dates | yfinance | 1.7.0 |
| Text processing | pandas, beautifulsoup4 | 2.3.3, 4.13.5 |
| Embedding model | all-MiniLM-L6-v2 (sentence-transformers) | 6.2.0 |
| Search engine | Elasticsearch | 8.13.4 |
| ES Python client | elasticsearch | 8.13.2 |
| Search interface | Streamlit | 1.51.0 |
| Language | Python | 3.13.9 |
| Platform | macOS Apple Silicon | — |

---

## 3. System diagram

```
┌─────────────────────────────────────────────────────────┐
│                    DATA PIPELINE                        │
│                                                         │
│  FNSPID CSV          Finnhub API      yfinance          │
│  (5.7 GB)            (news text)      (earnings dates)  │
│      │                    │                │            │
│      ▼                    ▼                ▼            │
│  01_collect_news   02_fetch_finnhub   03_earnings       │
│      │                    │                │            │
│      └────────────────────┴────────────────┘            │
│                           │                             │
│                    news_with_text.csv                   │
│                           │                             │
│                    04_tag_risks                         │
│                    (keyword rules)                      │
│                           │                             │
│                    05_index                             │
│              ┌────────────┴──────────┐                  │
│         BM25 index             Dense vector index       │
│         (english analyzer)     (MiniLM 384-dim)         │
│              └────────────┬──────────┘                  │
│                    Elasticsearch                        │
│                    Index: risk_news                     │
└─────────────────────────┬───────────────────────────────┘
                          │
              ┌───────────▼───────────┐
              │      search.py        │
              │  ┌─────────────────┐  │
              │  │ BM25 query      │  │
              │  │ kNN vector      │  │
              │  │ Risk boost      │  │
              │  │ Earnings decay  │  │
              │  └─────────────────┘  │
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │      app.py           │
              │  (Streamlit UI)       │
              │  localhost:8501       │
              └───────────────────────┘
```

---

## 4. Limitations found

1. **Short document length**: Finnhub summaries average ~200 characters. This limits BM25 term frequency statistics and embedding quality compared to full article text. A longer corpus would improve retrieval precision.

2. **Keyword rule coverage**: Risk-theme tagging matched only 4% of articles (21/480). The rules were designed for longer news articles; short summaries use different phrasing. The semantic search component partially compensates.

3. **No leadership-theme articles**: None of the 480 articles (Oct–Nov 2026 window) matched the leadership keyword rules. This reflects the specific news cycle during that period, not a flaw in the rules.

4. **Ticker mismatch in FNSPID**: MSFT was absent from `All_external.csv` (13M rows scanned). Replaced with NVDA. MSFT may exist in `nasdaq_exteral_data.csv` (23.2 GB) but was not verified.

5. **Historical URL rot**: 67% of FNSPID URLs point to benzinga.com which now uses Cloudflare bot protection and JavaScript rendering. Direct scraping and Wayback Machine retrieval both yielded <20% success rate.

6. **Evaluation without ground truth**: The evaluation in Stage 7 compares modes by top-1 headline relevance only. A proper IR evaluation would require human-annotated relevance judgements (TREC-style), which was outside the project scope.

---

## 5. Difficulties actually encountered

1. **FNSPID download**: The 5.7 GB file caused HTTP stream disconnections when reading via `requests` directly into pandas. Fixed by downloading to disk first with resume support, then reading locally.

2. **MSFT missing from dataset**: Discovered after streaming all 13M rows. Replaced with NVDA which had 3,146 rows.

3. **Article scraping failure**: Three approaches failed — direct HTTP (Cloudflare blocks), Playwright headless browser (Cloudflare fingerprinting), Wayback Machine (20% success). Pivoted to Finnhub API.

4. **`risk_date` sort mode**: Initial Elasticsearch script sort used wrong Painless syntax for keyword array field. Fixed by using `doc['risk_theme_tags'].contains(params.theme)`.

5. **Python stdout buffering**: Background processes showed no output until completion because Python buffers stdout when not connected to a terminal. Added `-u` flag to `python3` invocations.

---

## 6. Lessons learned

1. **Dataset quality assumptions**: The FNSPID dataset's `Article` column was null for all rows in `All_external.csv`. Always inspect the actual data before building a pipeline around it.

2. **Web scraping fragility**: Modern financial news sites (Benzinga, Seeking Alpha) use aggressive bot protection. Plan for API alternatives from the start.

3. **Hybrid search outperforms single-mode for semantic queries**: Searching `"lowered outlook"` with BM25 alone found articles with exact phrase "Lowers Price Target". Vector search found related articles without the exact words. Hybrid combines both.

4. **Short documents limit retrieval quality**: The MiniLM model was pre-trained on sentence pairs and works well on short text. However, 200-character summaries leave little room for BM25 term frequency weighting. Longer documents would produce better-separated relevance scores.

5. **Earnings proximity as a ranking signal**: The Gaussian decay function on `days_to_earnings` successfully surfaces articles published close to earnings dates. Articles 1–5 days from earnings consistently scored higher in hybrid mode.

---

## 7. TODO — screenshots for final report

- [ ] Screenshot: Streamlit app landing page
- [ ] Screenshot: Search results for `"chip shortage"` in Hybrid mode
- [ ] Screenshot: Search results for `"DOJ investigation"` — showing regulatory tag
- [ ] Screenshot: Mode comparison for `"earnings miss"` (BM25 vs Vector vs Hybrid)
- [ ] Screenshot: Elasticsearch index stats (`http://localhost:9200/risk_news/_stats`)
- [ ] Diagram: System architecture (see text diagram in Section 3 above)
