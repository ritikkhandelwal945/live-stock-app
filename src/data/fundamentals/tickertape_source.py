"""Tickertape scraper — DVM scores + forecast.

Tickertape stock pages live at /stocks/<slug-with-suffix> e.g.
/stocks/reliance-industries-RELI. We fetch via its public search API to
resolve the slug, then parse the page metadata.
"""

from __future__ import annotations

import json
import re

import httpx
from bs4 import BeautifulSoup

from src.data.http import make_ssl_context

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(10.0, connect=5.0),
    headers={"User-Agent": "Mozilla/5.0 (live-stock-app/1.0)"},
    follow_redirects=True,
)


def _resolve_slug(symbol: str) -> tuple[str | None, str | None]:
    """Return (slug_path, sid). Slug path already starts with /stocks/."""
    try:
        r = _HTTPX.get(
            "https://api.tickertape.in/search",
            params={"text": symbol, "types": "stock", "pageNumber": 0},
        )
        if r.status_code != 200:
            return None, None
        data = r.json()
        for item in (data or {}).get("data", {}).get("stocks", []):
            slug = item.get("slug")
            sid = item.get("sid")
            if slug:
                return slug, sid
    except Exception:
        return None, None
    return None, None


def fetch(symbol: str) -> dict | None:
    slug, sid = _resolve_slug(symbol)
    if not slug:
        return None
    # slug already starts with /stocks/...
    url = f"https://www.tickertape.in{slug}"
    try:
        resp = _HTTPX.get(url)
    except Exception:
        return None
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    target = _parse_consensus_target(soup, resp.text)
    if target is None and sid:
        target = _fetch_forecast_api(sid)
    pe = _parse_pe(soup)

    return {
        "ratios": {
            "pe_ratio": pe,
            "debt_to_equity": None,
            "roe": None,
            "revenue_growth": None,
            "eps_growth": None,
        },
        "target_price": target,
        "raw": {"url": url, "slug": slug, "sid": sid},
    }


def _fetch_forecast_api(sid: str) -> float | None:
    """Tickertape exposes a forecast endpoint with broker target medians."""
    for path in (
        f"https://api.tickertape.in/stocks/forecasts/{sid}",
        f"https://api.tickertape.in/stocks/{sid}/price-forecast",
    ):
        try:
            r = _HTTPX.get(path)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        try:
            data = r.json() or {}
        except Exception:
            continue
        # Walk the response shallowly looking for plausible target keys
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for k, v in node.items():
                    if k.lower() in {"target", "targetprice", "consensustarget", "median", "mean"}:
                        try:
                            val = float(v)
                            if 1.0 < val < 1_000_000:
                                return val
                        except (TypeError, ValueError):
                            pass
                    stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
    return None


def _parse_consensus_target(soup: BeautifulSoup, raw_html: str) -> float | None:
    # Tickertape ships data via a Next.js __NEXT_DATA__ script tag — easier than DOM walking
    next_tag = soup.select_one("#__NEXT_DATA__")
    if next_tag and next_tag.string:
        try:
            payload = json.loads(next_tag.string)
            stack = [payload]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    for key, val in node.items():
                        if key in {"forecastTarget", "consensusTarget", "targetPrice", "priceTarget"}:
                            try:
                                v = float(val)
                                if 1.0 < v < 1_000_000:
                                    return v
                            except (TypeError, ValueError):
                                continue
                        stack.append(val)
                elif isinstance(node, list):
                    stack.extend(node)
        except Exception:
            pass

    # Fallback: regex over rendered HTML
    m = re.search(r"target\s*price[:\s]*(?:₹|Rs\.?)?\s*([1-9]\d{1,5}(?:[.,]\d+)?)", raw_html, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _parse_pe(soup: BeautifulSoup) -> float | None:
    # PE often appears in the metric tiles; conservative regex over visible text
    text = soup.get_text(" ", strip=True)
    m = re.search(r"P\s*/\s*E\s*[:\-]?\s*([\d\.]+)", text)
    if m:
        try:
            v = float(m.group(1))
            if 0 < v < 1_000:
                return v
        except ValueError:
            pass
    return None
