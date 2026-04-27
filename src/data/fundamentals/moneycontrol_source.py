"""MoneyControl scraper — broker recommendations + price targets.

MoneyControl URLs are slug-based (e.g. /india/stockpricequote/refineries/relianceindustries/RI).
We resolve symbol → URL via their search endpoint, then scrape the broker
recommendations card from the stock page.
"""

from __future__ import annotations

import re
import statistics

import httpx
from bs4 import BeautifulSoup

from src.data.http import make_ssl_context

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(5.0, connect=5.0),
    headers={
        "User-Agent": "Mozilla/5.0 (live-stock-app/1.0)",
        "Accept": "text/html,application/xhtml+xml",
    },
    follow_redirects=True,
)


def _resolve_url(symbol: str) -> str | None:
    """Hit MoneyControl search → first equity result URL."""
    try:
        r = _HTTPX.get(
            "https://www.moneycontrol.com/mccode/common/autosuggesion.php",
            params={"query": symbol, "type": 1, "format": "json"},
        )
        if r.status_code != 200:
            return None
        data = r.json() if r.text else []
        for item in data:
            link = item.get("link_src") or item.get("url")
            if link and "stockpricequote" in link:
                return link if link.startswith("http") else f"https://www.moneycontrol.com{link}"
    except Exception:
        return None
    return None


def fetch(symbol: str) -> dict | None:
    url = _resolve_url(symbol)
    if not url:
        return None
    try:
        resp = _HTTPX.get(url)
    except Exception:
        return None
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    targets = _parse_broker_targets(soup)
    consensus_target = statistics.median(targets) if targets else None

    fund = _parse_overview(soup)

    return {
        "ratios": {
            "pe_ratio": fund.get("pe"),
            "debt_to_equity": None,
            "roe": None,
            "revenue_growth": None,
            "eps_growth": None,
        },
        "target_price": consensus_target,
        "target_high": max(targets) if targets else None,
        "target_low": min(targets) if targets else None,
        "raw": {"broker_targets": targets, "url": url, "overview": fund},
    }


def _parse_broker_targets(soup: BeautifulSoup) -> list[float]:
    """Find broker-recommendation cards / sections containing target prices."""
    targets: list[float] = []
    # Approach 1: look for "broker" sections with explicit price targets
    text = soup.get_text(" ", strip=True)
    # Pattern: "target ... 1500" or "target price 1500" or "TP ₹1500"
    for m in re.finditer(
        r"(?:target(?:\s+price)?|TP)\s*[:\-]?\s*(?:₹|Rs\.?)?\s*([1-9]\d{1,5}(?:[.,]\d+)?)",
        text,
        flags=re.IGNORECASE,
    ):
        try:
            val = float(m.group(1).replace(",", ""))
            if 1.0 < val < 1_000_000:  # sanity bounds in INR
                targets.append(val)
        except ValueError:
            continue
    # Dedup near-equal values
    targets = sorted(set(round(t, 2) for t in targets))
    # Trim outliers if too many — keep most central 5
    if len(targets) > 5:
        med = statistics.median(targets)
        targets = sorted(targets, key=lambda t: abs(t - med))[:5]
    return targets


def _parse_overview(soup: BeautifulSoup) -> dict:
    """Parse the stock overview metric tiles for P/E etc."""
    out: dict[str, float] = {}
    for label_el in soup.select("div"):
        cls = " ".join(label_el.get("class", []))
        if "ovr_keytable" in cls or "overview_value" in cls:
            text = label_el.get_text(" ", strip=True)
            m = re.search(r"P/?E\s*[:\-]?\s*([\d\.]+)", text, flags=re.IGNORECASE)
            if m:
                try:
                    out["pe"] = float(m.group(1))
                except ValueError:
                    pass
    return out
