"""
Stage 8 — Streamlit search interface
Run with: streamlit run app.py
"""

import re
import pandas as pd
from datetime import date
import streamlit as st
from search import search
from refresh import run_refresh
from price_impact import score_article, stars_html
from analyst_estimates import (
    get_recommendation, get_price_target,
    get_eps_estimates, get_revenue_estimates,
    fmt_billions, fmt_dollars,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Earnings Risk Radar",
    page_icon="S",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>

/* Search input */
[data-testid="stTextInput"] input {
    border-radius: 8px !important;
    border: 1.5px solid #C4A882 !important;
    background: #FFFDF9 !important;
    font-size: 15px !important;
    color: #2C1A0E !important;
}
[data-testid="stTextInput"] input:focus {
    border-color: #7C4A1E !important;
    box-shadow: 0 0 0 3px rgba(124,74,30,0.12) !important;
}

/* Primary button */
[data-testid="stButton"] > button[kind="primary"] {
    background: #7C4A1E !important;
    color: #FFF8F0 !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    border: none !important;
    letter-spacing: 0.02em;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    background: #5C3414 !important;
}

/* Tabs */
[data-testid="stTabs"] button {
    font-weight: 600;
    font-size: 14px;
    letter-spacing: 0.01em;
}

/* Inline code in markdown */
p code, li code {
    background: #EDE0CC !important;
    color: #5C3414 !important;
    border-radius: 6px !important;
    font-size: 13px !important;
}
/* st.code() blocks — example queries */
[data-testid="stCode"] pre {
    background: #F0E6D8 !important;
    border-radius: 6px !important;
}
[data-testid="stCode"] code,
[data-testid="stCode"] code span {
    color: #5C3414 !important;
    background: transparent !important;
    font-size: 13px !important;
}

/* Expander */
[data-testid="stExpander"] {
    border: 1px solid #D9C4A8 !important;
    border-radius: 8px !important;
}

/* Divider */
hr { border-color: #E0CDB5 !important; }

/* Remove form border */
[data-testid="stForm"] {
    border: none !important;
    padding: 0 !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 style='font-size:4.5rem; margin-bottom:0; color:#7C4A1E;'>StockView</h1>", unsafe_allow_html=True)
st.caption("Real-time risk news for GOOGL · AVGO · TSM · NVDA — ranked by relevance, risk signal, and earnings proximity")

# ── Sidebar controls (global — always visible) ────────────────────────────────
with st.sidebar:
    st.header("How to rank")

    mode = st.radio(
        "Ranking mode",
        options=["hybrid", "bm25", "vector", "latest"],
        index=0,
        format_func=lambda m: {
            "hybrid":  "Best match",
            "bm25":    "Keyword",
            "vector":  "Meaning",
            "latest":  "Newest first",
        }[m],
    )

    num_results = st.slider("Show up to", min_value=5, max_value=100, value=10, format="%d results")

    st.divider()
    with st.expander("Narrow by stock or theme"):
        ticker = st.selectbox(
            "Stock",
            options=["All stocks", "GOOGL", "AVGO", "TSM", "NVDA"],
            index=0,
        )
        sentiment = st.selectbox(
            "Sentiment",
            options=["All", "Negative", "Neutral", "Positive"],
            index=0,
        )

    st.divider()
    st.markdown("**Refresh data**")
    st.caption("Fetches 100 latest articles per stock from Finnhub and replaces the current database.")
    if st.button("Refresh now", use_container_width=True):
        log_box = st.empty()
        messages = []
        def log(msg):
            messages.append(msg)
            log_box.code("\n".join(messages[-12:]))
        with st.spinner("Refreshing …"):
            result = run_refresh(log=log)
        log_box.empty()
        st.success(result)
        st.cache_data.clear()

    st.divider()
    st.markdown("**About the modes**")
    st.markdown(
        "- **Best match** — combines keywords, meaning, risk signals, and earnings timing\n"
        "- **Keyword** — exact words only\n"
        "- **Meaning** — finds related articles even with different wording\n"
        "- **Newest first** — chronological, no ranking"
    )

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_search, tab_calendar, tab_estimates = st.tabs(["Search", "Earnings Calendar", "Analyst Estimates"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Search
# ══════════════════════════════════════════════════════════════════════════════
with tab_search:

    # ── Search box ────────────────────────────────────────────────────────────
    with st.form("search_form"):
        col1, col2 = st.columns([7, 1])
        with col1:
            query = st.text_input(
                "Search query",
                placeholder="e.g. chip shortage, earnings miss, DOJ investigation …",
                label_visibility="collapsed",
            )
        with col2:
            search_btn = st.form_submit_button("Search", type="primary", use_container_width=True)

    # ── Run search ────────────────────────────────────────────────────────────
    has_filter = ticker != "All stocks" or sentiment != "All"
    if search_btn and (query or has_filter):
        ticker_arg    = None if ticker == "All stocks" else ticker
        sentiment_arg = None if sentiment == "All" else sentiment.lower()

        with st.spinner("Searching …"):
            try:
                results = search(
                    query,
                    ticker=ticker_arg,
                    sentiment=sentiment_arg,
                    mode=mode,
                    size=num_results,
                )
            except Exception as e:
                st.error(f"Search error: {e}")
                results = []

        mode_label = {
            "hybrid": "Best match",
            "bm25":   "Keyword",
            "vector": "Meaning",
            "latest": "Newest first",
        }[mode]

        # Filter out low-relevance results for ranking modes (skip when no query — scores are null)
        MIN_SCORE = {"hybrid": 0.65, "bm25": 0.3, "vector": 0.55}
        if query and mode in MIN_SCORE and results:
            results = [r for r in results if r["score"] >= MIN_SCORE[mode]]

        if results:
            st.markdown(
                f"**{len(results)} results** — mode: `{mode_label}`"
                + (f" · ticker: `{ticker}`" if ticker != "All stocks" else "")
                + (f" · sentiment: `{sentiment}`" if sentiment != "All" else "")
            )
        else:
            st.markdown(
                "<div style='text-align:center; padding:48px 0;'>"
                "<div style='font-size:18px; font-weight:700; color:#2C1A0E; margin-bottom:8px;'>"
                "No results found</div>"
                "<div style='font-size:14px; color:#8B6B4A;'>"
                + (f"We couldn't find anything about <b>\"{query}\"</b>.<br>" if query else "")
                + "Try different keywords, switch to a different ranking mode, or remove filters."
                "</div></div>",
                unsafe_allow_html=True,
            )

        THEME_COLORS = {
            "supply_chain":         "",
            "regulatory_antitrust": "",
            "cybersecurity":        "",
            "guidance_outlook":     "",
            "leadership":           "",
            "general_news":         "",
        }

        def highlight(text: str, q: str) -> str:
            words = [w for w in re.split(r"\s+", q.strip()) if len(w) > 2]
            for w in words:
                text = re.sub(rf"({re.escape(w)})", r"**\1**", text, flags=re.IGNORECASE)
            return text

        for i, r in enumerate(results, 1):
            tags = r["risk_theme_tags"] if isinstance(r["risk_theme_tags"], list) else [r["risk_theme_tags"]]
            tag_icons = " ".join(f"`{t}`" for t in tags)

            days = r.get("days_to_earnings")
            days_from = r.get("days_from_earnings")
            if days is not None:
                direction = "before" if (days_from is not None and days_from < 0) else "after"
                days_str = f"**{days}d {direction}** earnings"
            else:
                days_str = "—"

            with st.container():
                headline_display = highlight(r["headline"], query)
                url = r.get("url", "")

                col_main, col_meta = st.columns([4, 1])
                with col_main:
                    if url:
                        st.markdown(f"**#{i}** [{headline_display}]({url})")
                    else:
                        st.markdown(f"**#{i}** {headline_display}")
                    snippet = r.get("body_text", "")[:300]
                    if snippet:
                        st.caption(highlight(snippet, query) + " …")

                with col_meta:
                    st.markdown(
                        f"`{r['ticker']}` · {r['publish_date']}\n\n"
                        f"{days_str}"
                    )

                # ── Price impact rating ────────────────────────────────────
                impact_stars = score_article(r)
                st.markdown(
                    f"<div style='margin:6px 0 8px;'>"
                    f"<span style='font-size:11px;color:#8B6B4A;font-weight:600;"
                    f"text-transform:uppercase;letter-spacing:0.06em;'>Price Impact Risk&nbsp;&nbsp;</span>"
                    f"{stars_html(impact_stars)}</div>",
                    unsafe_allow_html=True,
                )

                st.divider()

    elif not query:
        st.markdown(
            "<p style='color:#aaa; font-size:13px; margin-top:4px;'>"
            "Type anything — a topic, a risk, a company name — and hit Search.</p>",
            unsafe_allow_html=True,
        )

        st.markdown("#### Ideas to get you started")
        examples = [
            "chip supply shortage",
            "earnings miss guidance",
            "DOJ investigation antitrust",
            "AI competition NVDA",
            "TSMC semiconductor export",
            "revenue forecast downgrade",
        ]
        cols = st.columns(3)
        for j, ex in enumerate(examples):
            with cols[j % 3]:
                st.code(ex)

        st.markdown("<div style='margin-top:24px; margin-bottom:4px; font-size:12px; color:#8B6B4A; letter-spacing:0.05em;'>COVERAGE</div>", unsafe_allow_html=True)
        st.markdown(
            """<div style="display:flex; gap:20px; align-items:center; flex-wrap:wrap;">
                <div style="display:flex;align-items:center;gap:8px;">
                    <img src="https://financialmodelingprep.com/image-stock/NVDA.png" style="width:28px;height:28px;object-fit:contain;border-radius:6px;" onerror="this.style.display='none'">
                    <span style="font-size:13px;font-weight:600;color:#2C1A0E;">NVDA</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <img src="https://financialmodelingprep.com/image-stock/GOOGL.png" style="width:28px;height:28px;object-fit:contain;border-radius:6px;" onerror="this.style.display='none'">
                    <span style="font-size:13px;font-weight:600;color:#2C1A0E;">GOOGL</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <img src="https://financialmodelingprep.com/image-stock/AVGO.png" style="width:28px;height:28px;object-fit:contain;border-radius:6px;" onerror="this.style.display='none'">
                    <span style="font-size:13px;font-weight:600;color:#2C1A0E;">AVGO</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <img src="https://financialmodelingprep.com/image-stock/TSM.png" style="width:28px;height:28px;object-fit:contain;border-radius:6px;" onerror="this.style.display='none'">
                    <span style="font-size:13px;font-weight:600;color:#2C1A0E;">TSM</span>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Earnings Calendar
# ══════════════════════════════════════════════════════════════════════════════
with tab_calendar:

    TICKER_COLORS = {
        "GOOGL": "#4285F4",
        "AVGO":  "#CC0000",
        "TSM":   "#00A86B",
        "NVDA":  "#76B900",
    }
    TICKER_LOGOS = {
        "GOOGL": "https://financialmodelingprep.com/image-stock/GOOGL.png",
        "AVGO":  "https://financialmodelingprep.com/image-stock/AVGO.png",
        "TSM":   "https://financialmodelingprep.com/image-stock/TSM.png",
        "NVDA":  "https://financialmodelingprep.com/image-stock/NVDA.png",
    }

    @st.cache_data
    def load_earnings():
        df = pd.read_csv("data/earnings_dates.csv", parse_dates=["earnings_date"])
        df["earnings_date"] = df["earnings_date"].dt.date
        return df.sort_values("earnings_date")

    df_earn = load_earnings()
    today = date.today()

    upcoming_all = df_earn[df_earn["earnings_date"] >= today].sort_values("earnings_date")

    # ── Next earnings countdown banner ────────────────────────────────────────
    if not upcoming_all.empty:
        next_row = upcoming_all.iloc[0]
        days_away = (next_row["earnings_date"] - today).days
        color = TICKER_COLORS.get(next_row["ticker"], "#888888")

        logo_url = TICKER_LOGOS.get(next_row["ticker"], "")
        logo_html = f'<img src="{logo_url}" style="width:48px;height:48px;object-fit:contain;border-radius:8px;" onerror="this.style.display=\'none\'">' if logo_url else ""
        st.markdown(
            f"""
            <div style="background:linear-gradient(135deg,{color}22,{color}0a);
                        border:1.5px solid {color}66; border-radius:14px;
                        padding:22px 32px; margin-bottom:28px; display:flex;
                        align-items:center; gap:28px;">
                <div style="font-size:56px; font-weight:800; color:{color}; line-height:1; min-width:80px; text-align:center;">
                    {days_away}
                </div>
                <div style="display:flex; align-items:center; gap:14px;">
                    {logo_html}
                    <div>
                        <div style="font-size:11px; text-transform:uppercase; letter-spacing:1.5px; opacity:0.55; margin-bottom:4px;">
                            Days until next earnings
                        </div>
                        <div style="font-size:24px; font-weight:700; color:{color}; margin-bottom:2px;">
                            {next_row["ticker"]}
                        </div>
                        <div style="font-size:14px; opacity:0.7;">
                            {next_row["earnings_date"].strftime("%A, %B %d, %Y")}
                        </div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Controls row ──────────────────────────────────────────────────────────
    col_yr, col_tk, _ = st.columns([1, 2, 2])
    with col_yr:
        year_options = sorted(df_earn["earnings_date"].apply(lambda d: d.year).unique(), reverse=True)
        selected_year = st.selectbox("Year", year_options, index=0)
    with col_tk:
        selected_tickers = st.multiselect(
            "Tickers",
            options=["GOOGL", "AVGO", "TSM", "NVDA"],
            default=["GOOGL", "AVGO", "TSM", "NVDA"],
        )

    df_filtered = df_earn[
        (df_earn["earnings_date"].apply(lambda d: d.year) == selected_year) &
        (df_earn["ticker"].isin(selected_tickers))
    ].sort_values("earnings_date")

    st.markdown(f"#### {selected_year} Earnings Schedule")

    # ── Quarter columns ───────────────────────────────────────────────────────
    def quarter(d):
        return f"Q{(d.month - 1) // 3 + 1}"

    q_cols = st.columns(4)
    for qname, qcol in zip(["Q1", "Q2", "Q3", "Q4"], q_cols):
        q_data = df_filtered[df_filtered["earnings_date"].apply(quarter) == qname]
        with qcol:
            st.markdown(f"**{qname}**")
            if q_data.empty:
                st.caption("No data")
            else:
                for _, row in q_data.iterrows():
                    d = row["earnings_date"]
                    t = row["ticker"]
                    color = TICKER_COLORS.get(t, "#888888")
                    is_past = d < today
                    is_next = (not upcoming_all.empty and
                               d == upcoming_all.iloc[0]["earnings_date"] and
                               t == upcoming_all.iloc[0]["ticker"])
                    opacity = "0.38" if is_past else "1"
                    border = f"2px solid {color}" if is_next else f"1px solid {color}44"
                    ring = f"box-shadow:0 0 0 3px {color}33;" if is_next else ""
                    badge = ""
                    past_line = "text-decoration:line-through;opacity:0.5;" if is_past else ""

                    logo_url = TICKER_LOGOS.get(t, "")
                    if logo_url:
                        logo_tag = f'<img src="{logo_url}" style="width:20px;height:20px;object-fit:contain;border-radius:4px;vertical-align:middle;margin-right:6px;" onerror="this.style.display=\'none\'">'
                    else:
                        logo_tag = f'<span style="display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:4px;background:{color};font-size:7px;font-weight:800;color:#fff;vertical-align:middle;margin-right:6px;">{t}</span>'
                    st.markdown(
                        f"""<div style="border:{border};{ring} border-radius:9px;
                                        padding:9px 13px; margin-bottom:9px;
                                        opacity:{opacity}; background:{color}0d;">
                            <span style="color:{color}; font-weight:700; font-size:13px;
                                         {past_line}">{logo_tag}{t}</span>{badge}<br>
                            <span style="font-size:12px; opacity:0.75;">{d.strftime("%b %d")}</span>
                        </div>""",
                        unsafe_allow_html=True,
                    )

    st.divider()

    # ── Full table ────────────────────────────────────────────────────────────
    with st.expander("View full table"):
        def status_label(d):
            if d < today:
                return "Past"
            if not upcoming_all.empty and d == upcoming_all.iloc[0]["earnings_date"]:
                return "Next"
            return "Upcoming"

        display_df = df_filtered.copy()
        display_df["Status"] = display_df["earnings_date"].apply(status_label)
        display_df["earnings_date"] = display_df["earnings_date"].apply(lambda d: d.strftime("%Y-%m-%d"))
        display_df.columns = ["Ticker", "Earnings Date", "Status"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Analyst Estimates
# ══════════════════════════════════════════════════════════════════════════════
with tab_estimates:

    st.markdown("#### Analyst Estimates")
    st.caption(
        "Wall Street consensus data from professional analysts — "
        "recommendations, price targets, and earnings/revenue forecasts."
    )

    # ── Stock selector pills ───────────────────────────────────────────────────
    TICKER_COLORS_EST = {"NVDA": "#76B900", "GOOGL": "#4285F4", "AVGO": "#CC0000", "TSM": "#00A86B"}
    est_ticker = st.radio(
        "Select stock",
        options=["NVDA", "GOOGL", "AVGO", "TSM"],
        horizontal=True,
        key="est_ticker",
    )

    if st.button("Load Analyst Data", type="primary", key="est_btn"):
        tc = TICKER_COLORS_EST.get(est_ticker, "#7C4A1E")

        with st.spinner(f"Fetching Finnhub analyst data for {est_ticker} …"):
            rec     = get_recommendation(est_ticker)
            pt      = get_price_target(est_ticker)
            eps_est = get_eps_estimates(est_ticker)
            rev_est = get_revenue_estimates(est_ticker)

        any_data = any([rec, pt, eps_est, rev_est])
        if not any_data:
            st.warning(
                "No data returned from Finnhub. "
                "Check that FINNHUB_API_KEY is set and restart Streamlit."
            )
        else:
            # ── Row 1: Recommendation + Price Target side by side ──────────────
            col_rec, col_pt = st.columns(2)

            with col_rec:
                st.markdown("##### Analyst Recommendation")
                if rec:
                    total_buy  = (rec.get("strongBuy") or 0) + (rec.get("buy") or 0)
                    total_hold = rec.get("hold") or 0
                    total_sell = (rec.get("sell") or 0) + (rec.get("strongSell") or 0)
                    total      = total_buy + total_hold + total_sell
                    period     = rec.get("period", "")

                    # Determine overall signal
                    if total > 0:
                        buy_pct = total_buy / total
                        if buy_pct >= 0.6:
                            signal, signal_color = "BUY", "#27ae60"
                        elif buy_pct >= 0.4:
                            signal, signal_color = "HOLD", "#f39c12"
                        else:
                            signal, signal_color = "SELL", "#e74c3c"

                        st.markdown(
                            f"<div style='background:{signal_color}18;border:1.5px solid {signal_color}44;"
                            f"border-radius:12px;padding:16px 20px;margin-bottom:12px;'>"
                            f"<div style='font-size:11px;color:#888;text-transform:uppercase;"
                            f"letter-spacing:1px;margin-bottom:4px;'>Consensus · {period}</div>"
                            f"<div style='font-size:32px;font-weight:800;color:{signal_color};"
                            f"margin-bottom:10px;'>{signal}</div>"
                            f"<div style='display:flex;height:14px;border-radius:7px;overflow:hidden;margin-bottom:8px;'>"
                            f"<div style='width:{total_buy/total*100:.1f}%;background:#27ae60;'></div>"
                            f"<div style='width:{total_hold/total*100:.1f}%;background:#f39c12;'></div>"
                            f"<div style='width:{total_sell/total*100:.1f}%;background:#e74c3c;'></div>"
                            f"</div>"
                            f"<div style='display:flex;gap:14px;font-size:12px;color:#555;'>"
                            f"<span style='color:#27ae60;'>Buy <b>{rec.get('strongBuy',0)+rec.get('buy',0)}</b></span>"
                            f"<span style='color:#f39c12;'>Hold <b>{rec.get('hold',0)}</b></span>"
                            f"<span style='color:#e74c3c;'>Sell <b>{rec.get('sell',0)+rec.get('strongSell',0)}</b></span>"
                            f"</div></div>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("Recommendation data not available.")

            with col_pt:
                st.markdown("##### Price Target")
                if pt and pt.get("targetMean"):
                    mean    = fmt_dollars(pt.get("targetMean"))
                    high    = fmt_dollars(pt.get("targetHigh"))
                    low     = fmt_dollars(pt.get("targetLow"))
                    median  = fmt_dollars(pt.get("targetMedian"))
                    cur     = pt.get("currentPrice")
                    n_anal  = pt.get("numberOfAnalysts", "")
                    upside_str = ""
                    if cur and pt.get("targetMean"):
                        upside = (pt["targetMean"] / cur - 1) * 100
                        sign = "+" if upside >= 0 else ""
                        upside_str = f"<span style='font-size:13px;color:{'#27ae60' if upside>=0 else '#e74c3c'};font-weight:700;margin-left:10px;'>{sign}{upside:.1f}% vs current {fmt_dollars(cur)}</span>"

                    st.markdown(
                        f"<div style='background:{tc}10;border:1.5px solid {tc}44;"
                        f"border-radius:12px;padding:16px 20px;margin-bottom:12px;'>"
                        f"<div style='font-size:11px;color:#888;text-transform:uppercase;"
                        f"letter-spacing:1px;margin-bottom:4px;'>Analyst consensus target · {n_anal} analysts</div>"
                        f"<div style='margin-bottom:12px;'>"
                        f"<span style='font-size:32px;font-weight:800;color:{tc};'>{mean}</span>"
                        f"{upside_str}</div>"
                        f"<div style='display:flex;gap:20px;font-size:13px;color:#555;'>"
                        f"<div><div style='font-size:11px;color:#aaa;'>HIGH</div><b>{high}</b></div>"
                        f"<div><div style='font-size:11px;color:#aaa;'>MEDIAN</div><b>{median}</b></div>"
                        f"<div><div style='font-size:11px;color:#aaa;'>LOW</div><b>{low}</b></div>"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("Price target data not available.")

            st.markdown("")

            # ── Row 2: EPS + Revenue estimates side by side ────────────────────
            col_eps, col_rev = st.columns(2)

            with col_eps:
                st.markdown("##### EPS Estimates (Next 4 Quarters)")
                if eps_est:
                    for e in eps_est:
                        period  = e.get("period", "")
                        avg     = fmt_dollars(e.get("epsAvg"))
                        high_e  = fmt_dollars(e.get("epsHigh"))
                        low_e   = fmt_dollars(e.get("epsLow"))
                        n_anal  = e.get("numberAnalysts", "")
                        st.markdown(
                            f"<div style='display:flex;align-items:center;padding:10px 0;"
                            f"border-bottom:1px solid #f0e8dc;gap:12px;'>"
                            f"<span style='font-weight:700;min-width:90px;color:#2C1A0E;'>{period}</span>"
                            f"<span style='font-size:17px;font-weight:800;color:{tc};min-width:70px;'>{avg}</span>"
                            f"<span style='font-size:12px;color:#aaa;'>Range: {low_e} – {high_e}</span>"
                            f"<span style='margin-left:auto;font-size:11px;color:#bbb;'>{n_anal} analysts</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("EPS estimate data not available.")

            with col_rev:
                st.markdown("##### Revenue Estimates (Next 4 Quarters)")
                if rev_est:
                    for r in rev_est:
                        period  = r.get("period", "")
                        avg     = fmt_billions(r.get("revenueAvg"))
                        high_r  = fmt_billions(r.get("revenueHigh"))
                        low_r   = fmt_billions(r.get("revenueLow"))
                        n_anal  = r.get("numberAnalysts", "")
                        st.markdown(
                            f"<div style='display:flex;align-items:center;padding:10px 0;"
                            f"border-bottom:1px solid #f0e8dc;gap:12px;'>"
                            f"<span style='font-weight:700;min-width:90px;color:#2C1A0E;'>{period}</span>"
                            f"<span style='font-size:17px;font-weight:800;color:{tc};min-width:80px;'>{avg}</span>"
                            f"<span style='font-size:12px;color:#aaa;'>Range: {low_r} – {high_r}</span>"
                            f"<span style='margin-left:auto;font-size:11px;color:#bbb;'>{n_anal} analysts</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("Revenue estimate data not available.")

            # ── How to use this ───────────────────────────────────────────────
            st.markdown("")
            st.markdown(
                "<div style='background:#f8f4ef;border:1px solid #E0CDB5;border-radius:10px;"
                "padding:14px 18px;font-size:13px;color:#5C3414;line-height:1.7;'>"
                "<b>How to read this together:</b> "
                "If analysts say <b>BUY</b>, the price target is above the current price, "
                "and EPS/revenue estimates are growing quarter over quarter — "
                "that is a consistent bullish signal. "
                "If the recommendation is HOLD or SELL but the price target is still above market price, "
                "analysts may expect limited upside. Always check the number of analysts — "
                "a consensus from 30 analysts is more reliable than one from 3."
                "<br><br>"
                "These are <b>estimates, not guarantees</b>. Analyst forecasts are frequently wrong. "
                "This is not financial advice."
                "</div>",
                unsafe_allow_html=True,
            )

