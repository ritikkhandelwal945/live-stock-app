"""Direct Indian financial-news RSS aggregation.

Pulls from a curated list of channel-specific feeds (ET, CNBC TV18,
MoneyControl, Livemint, Business Standard) every 30 minutes, builds a
single in-memory + disk-cached master index, and exposes per-symbol
filtering against article title + description.

Adds breadth over Google News RSS (which aggregates these too but can be
flaky on which sources surface). Zee Business is deliberately omitted —
their RSS endpoint returns 0 items as of 2026.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from src.data.http import make_ssl_context

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "news_master_index.json"
_CACHE_TTL_SECONDS = 30 * 60  # match news_provider.py

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(8.0, connect=4.0),
    headers={"User-Agent": "Mozilla/5.0 (live-stock-app/1.0)"},
    follow_redirects=True,
)

# Curated feed list. Keys are the source label that flows through to the UI.
RSS_FEEDS: dict[str, str] = {
    # Economic Times — 4 feeds, ~50 items each
    "Economic Times — Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Economic Times — Stock Recos": "https://economictimes.indiatimes.com/markets/stocks/recos/rssfeeds/2146843.cms",
    "Economic Times — Stock News": "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146842.cms",
    "Economic Times — Company News": "https://economictimes.indiatimes.com/companies/rssfeeds/13352306.cms",
    # CNBC TV18 — large feeds (200 items each)
    "CNBC TV18 — Markets": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml",
    "CNBC TV18 — Business": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/business.xml",
    # MoneyControl
    "MoneyControl — Market Reports": "https://www.moneycontrol.com/rss/marketreports.xml",
    "MoneyControl — Business": "https://www.moneycontrol.com/rss/business.xml",
    # Livemint
    "Livemint — Markets": "https://www.livemint.com/rss/markets",
    # Business Standard
    "Business Standard — Markets": "https://www.business-standard.com/rss/markets-106.rss",
}


def _parse_feed(xml_bytes: bytes, source: str) -> list[dict]:
    out: list[dict] = []
    if not xml_bytes:
        return out
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        # Strip HTML tags from description to make text-matching reliable.
        desc_clean = re.sub(r"<[^>]+>", " ", desc).strip()
        if not title:
            continue
        out.append({
            "headline": title,
            "url": link,
            "source": source,
            "published_at": pub or None,
            "description": desc_clean[:500],  # cap to keep cache size sane
        })
    return out


def _fetch_one(source: str, url: str) -> list[dict]:
    try:
        r = _HTTPX.get(url)
        if r.status_code != 200:
            return []
        return _parse_feed(r.content, source)
    except Exception:
        return []


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {"fetched_at": 0, "articles": []}


def _save_cache(payload: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=str))
        tmp.replace(_CACHE_PATH)
    except Exception:
        pass


def _refresh_master_index() -> list[dict]:
    """Refresh all feeds concurrently, dedup by URL+headline, persist."""
    cache = _load_cache()
    now = time.time()
    if (now - cache.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
        return cache.get("articles", [])

    all_articles: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_fetch_one, src, url): src for src, url in RSS_FEEDS.items()}
        for fut in as_completed(futures, timeout=30):
            try:
                all_articles.extend(fut.result(timeout=10))
            except Exception:
                continue

    # Dedup by (lowercased title, link)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for a in all_articles:
        key = ((a.get("headline") or "").strip().lower(), a.get("url") or "")
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(a)

    _save_cache({"fetched_at": now, "articles": deduped})
    return deduped


def articles_matching(
    symbol: str,
    company_name: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """Return articles whose title or description mentions the symbol or
    the company name (case-insensitive). Newest first when published_at is
    parseable; otherwise feed order."""
    articles = _refresh_master_index()
    if not articles:
        return []

    needles: list[str] = []
    sym = (symbol or "").upper().strip()
    if sym:
        # Exact-token match: "RELIANCE" but not "MEDRELIANCE"
        needles.append(re.compile(rf"\b{re.escape(sym)}\b", re.IGNORECASE))
    if company_name:
        # First two words of company name (typical: "Reliance Industries", "Larsen Toubro")
        words = re.findall(r"[A-Za-z]+", company_name)[:2]
        if words:
            phrase = " ".join(words)
            needles.append(re.compile(re.escape(phrase), re.IGNORECASE))

    if not needles:
        return []

    matched: list[dict] = []
    for a in articles:
        haystack = f"{a.get('headline','')} {a.get('description','')}"
        if any(p.search(haystack) for p in needles):
            matched.append({
                "headline": a["headline"],
                "url": a.get("url", ""),
                "source": a.get("source", ""),
                "published_at": a.get("published_at"),
            })
            if len(matched) >= limit:
                break
    return matched


def list_active_sources() -> list[str]:
    """Returns the list of channel labels that contributed to the most
    recent index. Useful for UI source attribution."""
    cache = _load_cache()
    arts = cache.get("articles", [])
    return sorted({a.get("source", "") for a in arts if a.get("source")})
