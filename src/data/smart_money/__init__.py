"""Smart-money signals: institutional bulk/block trades, insider trading,
corporate events. Mirrors the fundamentals/ aggregator pattern.

Free Indian-market sources only:
  - NSE bulk + block deals CSV (per-stock institutional activity)
  - NSE corporate-actions / results-comparison / event-calendar JSON
  - BSE insider-trading disclosures (best-effort scrape)

Per-symbol aggregator with 24h disk cache.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.data.smart_money import bulk_deals_source, events_source, insider_source

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "smart_money_cache.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60


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


def get_smart_money(symbol: str, exchange: str = "NSE", refresh: bool = False) -> dict:
    """Return cross-source smart-money payload for a symbol.

    Shape:
        {
            "bulk_deals_30d": [{date, counterparty, side, qty, price, value, smart_money_tag}, ...],
            "insider_trades_30d": [{date, person, person_role, side, qty, value}, ...],
            "events": {
                "corporate_actions": [...],
                "recent_results": [...],
                "upcoming": [...],
            },
            "sources_used": ["nse_bulk", "nse_events", "bse_insider"],
        }

    Each section is empty when its source is down/blocked. ``sources_used`` is
    the list that *did* contribute.
    """
    key = f"{exchange.upper()}:{symbol.upper()}"
    cache = _load_cache()
    if not refresh:
        entry = cache.get(key)
        if entry and (time.time() - entry.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
            return entry.get("data", {})

    sources = {
        "nse_bulk": (bulk_deals_source.recent_for_symbol, (symbol,)),
        "nse_events": (events_source.for_symbol, (symbol,)),
        "bse_insider": (insider_source.recent_for_symbol, (symbol,)),
    }

    result: dict = {
        "bulk_deals_30d": [],
        "insider_trades_30d": [],
        "events": {"corporate_actions": [], "recent_results": [], "upcoming": []},
        "sources_used": [],
    }

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fn, *args): name for name, (fn, args) in sources.items()}
        for fut in as_completed(futures, timeout=30):
            name = futures[fut]
            try:
                data = fut.result(timeout=12)
            except Exception:
                continue
            if not data:
                continue
            result["sources_used"].append(name)
            if name == "nse_bulk":
                result["bulk_deals_30d"] = data
            elif name == "nse_events":
                result["events"] = data
            elif name == "bse_insider":
                result["insider_trades_30d"] = data

    cache[key] = {"fetched_at": time.time(), "data": result}
    _save_cache(cache)
    return result
