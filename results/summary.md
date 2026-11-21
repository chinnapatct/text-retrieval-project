# Evaluation Summary

## Per-query analysis

| Query | Type | Best mode | Hybrid helped? | Notes |
|-------|------|-----------|---------------|-------|
| `lawsuit` | one-word regulatory | **all similar** | ⚠️ No | hybrid top1: Michael Burry Finds a $537 Billion Hole in An |
| `chip supply shortage` | multi-word supply chain | **hybrid** | ⚠️ No | hybrid top1: What Does Broadcom (AVGO) Face As AI Chip Sup |
| `lowered outlook` | partial/related wording (vs 'withdraws guidance') | **hybrid** | ⚠️ No | hybrid top1: Citigroup Maintains Buy on Alphabet, Lowers P |
| `MSFT regulation` | ticker-specific regulatory (mapped to GOOGL) | **hybrid** | ⚠️ No | hybrid top1: Big Tech Capex Scorecard: Amazon Spends Over  |
| `earnings miss` | guidance/outlook keyword | **hybrid** | ⚠️ No | hybrid top1: Amazon Slides 7% as Earnings Miss and AI Spen |
| `AI competition risk` | semantic multi-word, NVDA | **hybrid** | ⚠️ No | hybrid top1: The Biggest Risk to Anthropic Stock Is the Co |
| `semiconductor export` | supply chain + ticker filter | **hybrid** | ⚠️ No | hybrid top1: Semiconductor Sell-Off: 5 Stocks to Buy on th |
| `executive leadership` | leadership theme | **all similar** | ⚠️ No | hybrid top1: FuboTV’s (FUBO) Strategic Plan to Turn Stream |

## Queries where hybrid did NOT help

Hybrid improved or changed results for all queries.

## Boost weight experiment — query: `DOJ investigation antitrust`

| Boost | #1 Headline | Tags |
|-------|------------|------|
| 1.0 | Nvidia Drew DOJ Questions and Weighed Backing Debt for an An | regulatory_antitrust |
| 1.5 | Nvidia Drew DOJ Questions and Weighed Backing Debt for an An | regulatory_antitrust |
| 3.0 | Nvidia Drew DOJ Questions and Weighed Backing Debt for an An | regulatory_antitrust |

**Observation:** Higher boost (3.0) surfaces risk-tagged articles more aggressively. Boost=1.5 (default) balances relevance with risk theme without over-weighting rare tags. Boost=1.0 effectively disables the risk boost.

## Mode comparison guide

- **BM25**: best for exact keyword queries ('lawsuit', 'earnings miss')
- **Vector**: best for semantic/paraphrase queries ('lowered outlook' finding 'withdraws guidance')
- **Hybrid**: generally best overall — combines BM25 precision with vector recall, plus earnings-proximity boost for pre-earnings relevance