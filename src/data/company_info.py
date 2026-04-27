"""Multi-source company description.

Pulls a 1-3 paragraph "what this company does" from:
 - yfinance Ticker.info: longBusinessSummary, sector, industry, website (most reliable)
 - Screener.in About section
 - Company IR website homepage <meta name="description"> (best-effort)

7-day disk cache because business descriptions don't change often.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
import yfinance as yf
from bs4 import BeautifulSoup

from src.data.http import make_ssl_context, yfinance_session

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "company_info_cache.json"
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(8.0, connect=5.0),
    headers={"User-Agent": "Mozilla/5.0 (live-stock-app/1.0)"},
    follow_redirects=True,
)
_YF_SESSION = yfinance_session()


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, default=str))
        tmp.replace(_CACHE_PATH)
    except Exception:
        pass


def _from_yfinance(symbol: str, exchange: str = "NSE") -> dict:
    yf_sym = f"{symbol.upper()}.{'BO' if exchange.upper() == 'BSE' else 'NS'}"
    try:
        info = yf.Ticker(yf_sym, session=_YF_SESSION).info or {}
    except Exception:
        return {}
    return {
        "summary": info.get("longBusinessSummary"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "website": info.get("website"),
        "country": info.get("country"),
        "employees": info.get("fullTimeEmployees"),
    }


def _from_screener(symbol: str) -> dict:
    sym = symbol.upper()
    for path in ("consolidated/", ""):
        url = f"https://www.screener.in/company/{sym}/{path}"
        try:
            resp = _HTTPX.get(url)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            about_el = soup.select_one(".company-profile .about p") or soup.select_one(".sub p")
            about = about_el.get_text(" ", strip=True) if about_el else None
            # Website
            website = None
            for a in soup.select(".company-links a"):
                href = a.get("href") or ""
                if href.startswith("http") and "screener.in" not in href:
                    website = href
                    break
            return {"summary": about, "website": website, "url": url}
        except Exception:
            continue
    return {}


def _from_company_website(url: str) -> dict:
    """Best-effort: fetch company homepage, parse <meta name=description>
    plus any About-page link's description."""
    if not url:
        return {}
    try:
        resp = _HTTPX.get(url)
        if resp.status_code != 200:
            return {}
        soup = BeautifulSoup(resp.text, "lxml")
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        desc = (meta.get("content") if meta else "") or ""
        title = (soup.title.string if soup.title and soup.title.string else "") or ""
        return {
            "homepage_title": title.strip(),
            "homepage_description": desc.strip(),
            "url": url,
        }
    except Exception:
        return {}


def get_company_info(symbol: str, exchange: str = "NSE", refresh: bool = False) -> dict:
    """Returns a merged dict:
        {
            summary: str | None,            # primary description
            sector, industry, website,
            country, employees,
            sources: [{name, summary, url}],   # per-source descriptions
        }
    """
    key = f"{exchange.upper()}:{symbol.upper()}"
    cache = _load_cache()
    if not refresh:
        entry = cache.get(key)
        if entry and (time.time() - entry.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
            return entry.get("data", {})

    yfd = _from_yfinance(symbol, exchange)
    scd = _from_screener(symbol)

    # Pick a website to scrape next: prefer Screener-linked, fall back to yfinance.
    site = scd.get("website") or yfd.get("website")
    web = _from_company_website(site) if site else {}

    sources: list[dict] = []
    if yfd.get("summary"):
        sources.append({"name": "yfinance", "summary": yfd["summary"], "url": None})
    if scd.get("summary"):
        sources.append({"name": "screener.in", "summary": scd["summary"], "url": scd.get("url")})
    if web.get("homepage_description"):
        sources.append({
            "name": "company website",
            "summary": web["homepage_description"],
            "url": web.get("url"),
        })

    primary_summary = (
        yfd.get("summary")
        or scd.get("summary")
        or web.get("homepage_description")
        or None
    )
    if primary_summary:
        # Trim to ~3 sentences to keep dialog compact.
        sentences = re.split(r"(?<=[\.!?])\s+", primary_summary)
        primary_summary = " ".join(sentences[:4])[:1200]

    data = {
        "summary": primary_summary,
        "sector": yfd.get("sector"),
        "industry": yfd.get("industry"),
        "website": site,
        "country": yfd.get("country"),
        "employees": yfd.get("employees"),
        "sources": sources,
    }
    cache[key] = {"fetched_at": time.time(), "data": data}
    _save_cache(cache)
    return data
