"""
Stage 2c — Playwright test on 5 Benzinga URLs
Uses a headless Chromium browser to render JS-heavy pages,
then extracts clean article text with BeautifulSoup.
Tests 5 Benzinga URLs and reports success rate + 2 sample texts.
"""

import re
import time
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import RAW_NEWS_CSV, MIN_TEXT_CHARS

BOILERPLATE_RE = re.compile(
    r"subscribe\s+to\s+(our\s+)?newsletter"
    r"|sign\s+up\s+for\s+(our\s+)?newsletter"
    r"|cookies?\s+(help\s+us|policy|settings)"
    r"|by\s+clicking\s+.{0,40}\s+you\s+agree"
    r"|all\s+rights\s+reserved|©\s*\d{4}"
    r"|related\s+articles?|read\s+more\s*:"
    r"|advertisement|sponsored\s+content"
    r"|sign\s+in\s+to\s+access"
    r"|create\s+(a\s+)?free\s+account",
    re.IGNORECASE,
)


def extract_text(html: str) -> str | None:
    """Parse rendered HTML and return clean article text."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise tags
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "figure", "figcaption", "form", "noscript",
                     "iframe", "button", "svg"]):
        tag.decompose()

    # Try article-specific containers first (common on Benzinga)
    article_body = (
        soup.find("div", class_=re.compile(r"article[_-]body|article[_-]content|story[_-]body|post[_-]content", re.I))
        or soup.find("article")
        or soup.find("main")
    )
    container = article_body if article_body else soup

    paragraphs = [
        p.get_text(separator=" ", strip=True)
        for p in container.find_all("p")
        if len(p.get_text(strip=True)) > 40
    ]

    if not paragraphs:
        # Fallback: all visible text
        paragraphs = [container.get_text(separator=" ", strip=True)]

    combined = re.sub(r"\s+", " ", " ".join(paragraphs)).strip()

    # Strip boilerplate sentences
    sentences = re.split(r"(?<=[.!?])\s+", combined)
    combined = " ".join(s for s in sentences if not BOILERPLATE_RE.search(s)).strip()

    return combined if len(combined) >= MIN_TEXT_CHARS else None


def scrape_with_playwright(urls: list[str], headless: bool = True) -> list[dict]:
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            java_script_enabled=True,
        )
        page = context.new_page()

        # Block images, fonts, media to speed up loading
        page.route("**/*.{png,jpg,jpeg,gif,svg,mp4,woff,woff2,ttf}", lambda r: r.abort())

        for url in urls:
            print(f"  Fetching: {url[:80]}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                # Wait a moment for JS to render content
                page.wait_for_timeout(2000)
                html = page.content()
                text = extract_text(html)
                if text:
                    print(f"    → OK  ({len(text)} chars)")
                    results.append({"url": url, "status": "ok", "text": text})
                else:
                    print(f"    → FAIL  (page loaded but text too short)")
                    results.append({"url": url, "status": "fail_short", "text": None})
            except PWTimeout:
                print(f"    → TIMEOUT")
                results.append({"url": url, "status": "timeout", "text": None})
            except Exception as e:
                print(f"    → ERROR: {e}")
                results.append({"url": url, "status": "error", "text": None})

            time.sleep(1)

        browser.close()

    return results


def main():
    df = pd.read_csv(RAW_NEWS_CSV)

    # Pick 5 Benzinga URLs spread across tickers
    benzinga = df[df["Url"].str.contains("benzinga", na=False)]
    sample = (
        benzinga.groupby("Stock_symbol", group_keys=False)
                .apply(lambda g: g.sample(min(2, len(g)), random_state=7), include_groups=False)
                .head(5)
    )
    sample = df.loc[
        benzinga.groupby("Stock_symbol", group_keys=False)
                .apply(lambda g: g.sample(min(2, len(g)), random_state=7), include_groups=False)
                .head(5)
                .index
    ].reset_index(drop=True)

    title_col = next((c for c in df.columns if "title" in c.lower()), "Url")

    print(f"Testing {len(sample)} Benzinga URLs with Playwright (headless Chromium) …\n")
    for _, row in sample.iterrows():
        print(f"  {row['Stock_symbol']} — {str(row[title_col])[:70]}")

    print()
    urls = sample["Url"].tolist()
    results = scrape_with_playwright(urls)

    # Summary
    ok      = [r for r in results if r["status"] == "ok"]
    failed  = [r for r in results if r["status"] != "ok"]

    print(f"\n── Test summary ──────────────────────────────")
    print(f"  Success : {len(ok)}/{len(results)}  ({len(ok)/len(results)*100:.0f}%)")
    for r in failed:
        print(f"  {r['status'].upper():12} {r['url'][:70]}")

    # Print 2 sample texts
    print(f"\n── Sample texts ──────────────────────────────")
    for r in ok[:2]:
        print(f"\nURL: {r['url']}")
        print(f"Text ({len(r['text'])} chars):\n  {r['text'][:600]} …\n")

    if len(ok) / len(results) >= 0.5:
        print("✓ Playwright works — ready to scrape all 480 URLs.")
    else:
        print("✗ Still failing — likely paywalled even with JS. Will need alternative.")


if __name__ == "__main__":
    main()
