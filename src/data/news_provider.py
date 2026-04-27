import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.data.http import make_ssl_context, yfinance_session

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "news_cache.json"
_CACHE_TTL_SECONDS = 30 * 60  # 30 minutes

_SSL_CONTEXT = make_ssl_context()
_HTTPX = httpx.Client(
    verify=_SSL_CONTEXT,
    timeout=httpx.Timeout(5.0, connect=5.0),
    headers={"User-Agent": "Mozilla/5.0 live-stock-app/1.0"},
)
_YF_SESSION = yfinance_session()


def _to_yf_symbol(symbol: str, exchange: str = "NSE") -> str:
    s = symbol.strip().upper()
    if "." in s:
        return s
    return f"{s}.BO" if exchange.upper() == "BSE" else f"{s}.NS"


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(_CACHE_PATH)
    except Exception:
        pass


def _from_yfinance(symbol: str, exchange: str, limit: int) -> list[dict]:
    try:
        import yfinance as yf
        yf_sym = _to_yf_symbol(symbol, exchange)
        ticker = yf.Ticker(yf_sym, session=_YF_SESSION)
        raw = ticker.news or []
    except Exception:
        return []

    out: list[dict] = []
    for item in raw[:limit * 2]:
        # yfinance >= 0.2.40 returns either a flat dict or {"content": {...}} wrapper.
        content = item.get("content") if isinstance(item, dict) else None
        if content:
            headline = content.get("title") or ""
            url = (content.get("clickThroughUrl") or {}).get("url") if isinstance(content.get("clickThroughUrl"), dict) else (content.get("canonicalUrl") or {}).get("url", "")
            provider = (content.get("provider") or {}).get("displayName", "Yahoo Finance")
            published = content.get("pubDate")
        else:
            headline = item.get("title", "")
            url = item.get("link", "")
            provider = item.get("publisher", "Yahoo Finance")
            ts = item.get("providerPublishTime")
            published = (
                datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                if ts else None
            )
        if not headline:
            continue
        out.append({
            "headline": headline,
            "source": provider or "Yahoo Finance",
            "url": url or "",
            "published_at": published,
        })
    return out


def _from_google_news(symbol: str, limit: int) -> list[dict]:
    # Quoted symbol forces an exact-token match so we don't drift to the NSE
    # index or unrelated companies. "share price" biases toward stock news.
    query = f'"{symbol}" share price'
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    )
    try:
        resp = _HTTPX.get(url)
        if resp.status_code != 200 or not resp.content:
            return []
        root = ET.fromstring(resp.content)
    except Exception:
        return []

    out: list[dict] = []
    for item in list(root.iterfind(".//item"))[: limit * 2]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = (source_el.text if source_el is not None and source_el.text else "Google News").strip()
        if not title:
            continue
        # Google News titles are often "<actual headline> - <source>"; strip the trailing source.
        if " - " in title and title.rsplit(" - ", 1)[-1] == source:
            title = title.rsplit(" - ", 1)[0]
        out.append({
            "headline": title,
            "source": source,
            "url": link,
            "published_at": pub or None,
        })
    return out


def _dedupe(items: list[dict], limit: int) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = (it.get("headline") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= limit:
            break
    return out


def get_news_for_symbol(
    symbol: str,
    exchange: str = "NSE",
    limit: int = 5,
    refresh: bool = False,
) -> list[dict]:
    """Fetch recent news headlines for a symbol from yfinance + Google News.

    Returns a list of dicts shaped for `analyze_from_items` and the
    `NewsItem` Pydantic model.

    Cached on disk for 30 minutes per (symbol, exchange) key.
    """
    key = f"{exchange.upper()}:{symbol.upper()}"
    cache = _load_cache()

    if not refresh:
        entry = cache.get(key)
        if entry and (time.time() - entry.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
            return entry.get("items", [])[:limit]

    yf_items = _from_yfinance(symbol, exchange, limit)
    gn_items = _from_google_news(symbol, limit)
    merged = _dedupe(yf_items + gn_items, limit)

    cache[key] = {"fetched_at": time.time(), "items": merged}
    _save_cache(cache)
    return merged
