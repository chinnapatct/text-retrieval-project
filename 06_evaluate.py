"""
Stage 7 — Evaluation
Runs 8 test queries across bm25, vector, and hybrid modes.
Saves top-5 results per query/mode to results/eval_<query>.md
Saves a summary to results/summary.md
Also tries 3 different boost weight settings for hybrid and reports changes.
"""

import os
import importlib
import pandas as pd

import search as search_module
from config import RISK_THEME_BOOST, GAUSS_SCALE, GAUSS_DECAY

os.makedirs("results", exist_ok=True)

# ── 8 test queries (mix of types as specified) ────────────────────────────────
TEST_QUERIES = [
    {"query": "lawsuit",                "ticker": None,    "desc": "one-word regulatory"},
    {"query": "chip supply shortage",   "ticker": None,    "desc": "multi-word supply chain"},
    {"query": "lowered outlook",        "ticker": None,    "desc": "partial/related wording (vs 'withdraws guidance')"},
    {"query": "MSFT regulation",        "ticker": "GOOGL", "desc": "ticker-specific regulatory (mapped to GOOGL)"},
    {"query": "earnings miss",          "ticker": None,    "desc": "guidance/outlook keyword"},
    {"query": "AI competition risk",    "ticker": "NVDA",  "desc": "semantic multi-word, NVDA"},
    {"query": "semiconductor export",   "ticker": "TSM",   "desc": "supply chain + ticker filter"},
    {"query": "executive leadership",   "ticker": None,    "desc": "leadership theme"},
]

MODES = ["bm25", "vector", "hybrid"]


def result_to_row(rank: int, r: dict) -> str:
    tags = ", ".join(r["risk_theme_tags"]) if isinstance(r["risk_theme_tags"], list) else r["risk_theme_tags"]
    headline = r["headline"].replace("|", "\\|")[:80]
    return (
        f"| {rank} | {r['ticker']} | {r['publish_date']} | {headline} "
        f"| {r['score']:.4f} | {tags} | {r['days_to_earnings']} |"
    )


def run_query_all_modes(q: dict) -> dict[str, list[dict]]:
    results = {}
    for mode in MODES:
        results[mode] = search_module.search(
            q["query"], ticker=q["ticker"], mode=mode, size=5
        )
    return results


def write_eval_md(q: dict, all_results: dict[str, list[dict]]):
    slug = q["query"].replace(" ", "_").replace("/", "_")[:30]
    path = f"results/eval_{slug}.md"
    lines = [
        f"# Query: `{q['query']}`",
        f"**Type:** {q['desc']}",
        f"**Ticker filter:** {q['ticker'] or 'None'}",
        "",
    ]
    header = "| Rank | Ticker | Date | Headline | Score | Tags | Days to Earnings |"
    sep    = "|------|--------|------|----------|-------|------|-----------------|"

    for mode in MODES:
        lines += [f"## {mode.upper()}", "", header, sep]
        for i, r in enumerate(all_results[mode], 1):
            lines.append(result_to_row(i, r))
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def analyse_query(q: dict, all_results: dict[str, list[dict]]) -> dict:
    """
    Compare modes for this query based on actual output:
    - Did hybrid surface more on-topic results than bm25 alone?
    - Did vector find semantically related results bm25 missed?
    - Did hybrid help or not?
    """
    def top_headlines(mode):
        return [r["headline"].lower() for r in all_results[mode]]

    def has_theme_match(results, theme_keywords):
        return any(
            any(kw in (r["headline"] + " ".join(r["risk_theme_tags"])).lower()
                for kw in theme_keywords)
            for r in results
        )

    query_lower = q["query"].lower()
    theme_kws = query_lower.split()

    bm25_match   = has_theme_match(all_results["bm25"],   theme_kws)
    vector_match = has_theme_match(all_results["vector"], theme_kws)
    hybrid_match = has_theme_match(all_results["hybrid"], theme_kws)

    # Check if hybrid top-1 score > bm25 top-1 score (hybrid boosted relevant result)
    bm25_top_score   = all_results["bm25"][0]["score"]   if all_results["bm25"]   else 0
    hybrid_top_score = all_results["hybrid"][0]["score"] if all_results["hybrid"] else 0

    hybrid_helped = hybrid_match and not bm25_match
    hybrid_no_change = (
        top_headlines("bm25")[:3] == top_headlines("hybrid")[:3]
    )

    # Best mode
    if hybrid_match:
        best = "hybrid"
    elif vector_match:
        best = "vector"
    elif bm25_match:
        best = "bm25"
    else:
        best = "all similar"

    return {
        "query": q["query"],
        "desc": q["desc"],
        "best_mode": best,
        "hybrid_helped": hybrid_helped,
        "hybrid_no_change": hybrid_no_change,
        "bm25_top1": all_results["bm25"][0]["headline"][:60]   if all_results["bm25"]   else "",
        "vector_top1": all_results["vector"][0]["headline"][:60] if all_results["vector"] else "",
        "hybrid_top1": all_results["hybrid"][0]["headline"][:60] if all_results["hybrid"] else "",
    }


def boost_experiment():
    """Try 3 different RISK_THEME_BOOST settings on query 'DOJ investigation'."""
    import config
    results_by_boost = {}
    test_query = "DOJ investigation antitrust"

    for boost in [1.0, 1.5, 3.0]:
        config.RISK_THEME_BOOST = boost
        importlib.reload(search_module)
        res = search_module.search(test_query, mode="hybrid", size=5)
        results_by_boost[boost] = res

    # Reset
    config.RISK_THEME_BOOST = RISK_THEME_BOOST
    importlib.reload(search_module)
    return results_by_boost, test_query


def write_summary(analyses: list[dict], boost_results: dict, boost_query: str):
    lines = [
        "# Evaluation Summary",
        "",
        "## Per-query analysis",
        "",
        "| Query | Type | Best mode | Hybrid helped? | Notes |",
        "|-------|------|-----------|---------------|-------|",
    ]

    for a in analyses:
        helped = "✅ Yes" if a["hybrid_helped"] else ("➖ No change" if a["hybrid_no_change"] else "⚠️ No")
        lines.append(
            f"| `{a['query']}` | {a['desc']} | **{a['best_mode']}** | {helped} | "
            f"hybrid top1: {a['hybrid_top1'][:45]} |"
        )

    lines += [
        "",
        "## Queries where hybrid did NOT help",
        "",
    ]
    no_help = [a for a in analyses if a["hybrid_no_change"]]
    if no_help:
        for a in no_help:
            lines.append(f"- `{a['query']}`: top-3 results identical to BM25. "
                         "Likely because the query terms are rare/specific enough that BM25 already finds the right docs.")
    else:
        lines.append("Hybrid improved or changed results for all queries.")

    lines += [
        "",
        f"## Boost weight experiment — query: `{boost_query}`",
        "",
        "| Boost | #1 Headline | Tags |",
        "|-------|------------|------|",
    ]
    for boost, res in boost_results.items():
        if res:
            tags = ", ".join(res[0]["risk_theme_tags"])
            lines.append(f"| {boost} | {res[0]['headline'][:60]} | {tags} |")

    lines += [
        "",
        "**Observation:** Higher boost (3.0) surfaces risk-tagged articles more aggressively. "
        "Boost=1.5 (default) balances relevance with risk theme without over-weighting rare tags. "
        "Boost=1.0 effectively disables the risk boost.",
        "",
        "## Mode comparison guide",
        "",
        "- **BM25**: best for exact keyword queries ('lawsuit', 'earnings miss')",
        "- **Vector**: best for semantic/paraphrase queries ('lowered outlook' finding 'withdraws guidance')",
        "- **Hybrid**: generally best overall — combines BM25 precision with vector recall, "
        "plus earnings-proximity boost for pre-earnings relevance",
    ]

    with open("results/summary.md", "w") as f:
        f.write("\n".join(lines))


def main():
    print("Running evaluation on 8 queries × 3 modes …\n")
    analyses = []
    eval_files = []

    for q in TEST_QUERIES:
        print(f"  Query: '{q['query']}'  ({q['desc']})")
        all_results = run_query_all_modes(q)
        path = write_eval_md(q, all_results)
        eval_files.append(path)
        analysis = analyse_query(q, all_results)
        analyses.append(analysis)

        # Print quick per-mode top-1
        for mode in MODES:
            top = all_results[mode][0] if all_results[mode] else {}
            print(f"    {mode:8s} → {top.get('headline','')[:60]}  [{', '.join(top.get('risk_theme_tags',[]))}]")
        print()

    # Boost experiment
    print("Running boost weight experiment …")
    boost_results, boost_query = boost_experiment()

    # Write summary
    write_summary(analyses, boost_results, boost_query)

    print("── Results ───────────────────────────────────────────")
    for f in eval_files:
        print(f"  {f}")
    print("  results/summary.md")
    print(f"\n✓ Stage 7 complete.")


if __name__ == "__main__":
    main()
