"""Multi-source fundamentals aggregator.

Calls every source concurrently with per-source try/except + 5s timeout, then
returns a single dict that downstream code (engine, API) can consume:

    {
        "ratios": {"pe_ratio": ..., "debt_to_equity": ..., "roe": ..., "revenue_growth": ..., ...},
        "ratios_by_source": {"yfinance": {...}, "screener": {...}, ...},
        "target_prices": [{"source": "yfinance", "target": 1500.0, ...}, ...],
        "target_consensus": float | None,   # median of target_prices
        "target_high": float | None,        # max
        "target_low": float | None,         # min
        "target_confidence": "high" | "medium" | "low" | "unknown",
        "analyst_count": int | None,
        "analyst_recommendation": str | None,  # buy/strong_buy/hold/sell/strong_sell
        "market_cap": float | None,
        "dividend_yield": float | None,
        "fifty_two_week_high": float | None,
        "fifty_two_week_low": float | None,
        "fundamental_sources": ["yfinance", "screener", ...],
        "raw_per_source": {<source>: {<raw>}},
    }

Caches per (symbol, exchange) for 24h on disk at data/fundamentals_cache.json.
"""

from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.data.fundamentals import (
    moneycontrol_source,
    screener_source,
    tickertape_source,
    yf_source,
)

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "fundamentals_cache.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h


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


def _aggregate(per_source: dict[str, dict]) -> dict:
    """Merge dicts from each source into a single normalized payload.

    Each source dict may contain:
      - ratios: {pe_ratio, debt_to_equity, roe, revenue_growth, eps_growth, ...}
      - target_price: float
      - target_recommendation: str
      - market_cap, dividend_yield, fifty_two_week_high, fifty_two_week_low
      - analyst_count, analyst_recommendation
      - raw: dict (kept verbatim for debugging)
    """
    contributors = sorted(k for k, v in per_source.items() if v)

    target_prices: list[dict] = []
    ratios_by_source: dict[str, dict] = {}
    raw_per_source: dict[str, dict] = {}

    # Aggregated ratios = median across sources where present
    ratio_keys = ("pe_ratio", "debt_to_equity", "roe", "revenue_growth", "eps_growth")
    ratio_lists: dict[str, list[float]] = {k: [] for k in ratio_keys}

    market_cap = None
    dividend_yield = None
    week_high = None
    week_low = None
    analyst_count = None
    analyst_rec = None

    for src, data in per_source.items():
        if not data:
            continue
        ratios = data.get("ratios") or {}
        if ratios:
            ratios_by_source[src] = ratios
            for k in ratio_keys:
                v = ratios.get(k)
                if isinstance(v, (int, float)) and v == v:  # not NaN
                    ratio_lists[k].append(float(v))
        if data.get("target_price") is not None:
            try:
                target_prices.append({
                    "source": src,
                    "target": float(data["target_price"]),
                    "recommendation": data.get("target_recommendation"),
                    "as_of": data.get("as_of"),
                })
            except (TypeError, ValueError):
                pass
        if market_cap is None and data.get("market_cap"):
            market_cap = data["market_cap"]
        if dividend_yield is None and data.get("dividend_yield"):
            dividend_yield = data["dividend_yield"]
        if week_high is None and data.get("fifty_two_week_high"):
            week_high = data["fifty_two_week_high"]
        if week_low is None and data.get("fifty_two_week_low"):
            week_low = data["fifty_two_week_low"]
        if analyst_count is None and data.get("analyst_count"):
            analyst_count = data["analyst_count"]
        if analyst_rec is None and data.get("analyst_recommendation"):
            analyst_rec = data["analyst_recommendation"]
        raw_per_source[src] = data.get("raw") or {}

    aggregated_ratios: dict[str, float | None] = {}
    for k in ratio_keys:
        vals = ratio_lists[k]
        aggregated_ratios[k] = statistics.median(vals) if vals else None

    if target_prices:
        targets = [t["target"] for t in target_prices]
        consensus = statistics.median(targets)
        # Confidence: # of sources + dispersion
        spread = (max(targets) - min(targets)) / consensus if consensus else 1.0
        if len(targets) >= 3 and spread <= 0.20:
            confidence = "high"
        elif len(targets) >= 2 and spread <= 0.35:
            confidence = "medium"
        elif len(targets) >= 1:
            confidence = "low"
        else:
            confidence = "unknown"
        target_high = max(targets)
        target_low = min(targets)
    else:
        consensus = None
        confidence = "unknown"
        target_high = None
        target_low = None

    return {
        "ratios": aggregated_ratios,
        "ratios_by_source": ratios_by_source,
        "target_prices": target_prices,
        "target_consensus": consensus,
        "target_high": target_high,
        "target_low": target_low,
        "target_confidence": confidence,
        "analyst_count": analyst_count,
        "analyst_recommendation": analyst_rec,
        "market_cap": market_cap,
        "dividend_yield": dividend_yield,
        "fifty_two_week_high": week_high,
        "fifty_two_week_low": week_low,
        "fundamental_sources": contributors,
        "raw_per_source": raw_per_source,
    }


def get_fundamentals(symbol: str, exchange: str = "NSE", refresh: bool = False) -> dict:
    """Aggregate fundamentals across sources. Always returns a dict (possibly
    with mostly nulls for SME/illiquid stocks)."""
    key = f"{exchange.upper()}:{symbol.upper()}"
    cache = _load_cache()

    if not refresh:
        entry = cache.get(key)
        if entry and (time.time() - entry.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
            return entry.get("data", {})

    sources = {
        "yfinance": (yf_source.fetch, (symbol, exchange)),
        "screener": (screener_source.fetch, (symbol,)),
        "moneycontrol": (moneycontrol_source.fetch, (symbol,)),
        "tickertape": (tickertape_source.fetch, (symbol,)),
    }

    per_source: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fn, *args): name for name, (fn, args) in sources.items()}
        for fut in as_completed(futures, timeout=20):
            name = futures[fut]
            try:
                per_source[name] = fut.result(timeout=8) or {}
            except Exception:
                per_source[name] = {}

    aggregated = _aggregate(per_source)
    cache[key] = {"fetched_at": time.time(), "data": aggregated}
    _save_cache(cache)
    return aggregated
