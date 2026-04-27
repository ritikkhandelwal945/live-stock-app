"""Discover hot stocks: screen NIFTY 500 for short-term BUY candidates.

Two-stage scan to keep runtime manageable:
 1. **Cheap pre-filter** — yfinance fast_info + info to find stocks with
    STRONG_BUY/BUY analyst consensus + meaningful upside to consensus target.
    ~30-90s for 500 stocks at max_workers=8.
 2. **Deep analyze** — top ~25 candidates only get the full multi-source
    treatment (fundamentals, news, ARIMA, MC). Adds ~1 minute.

Result is cached for 1h on disk so the next request returns instantly.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yfinance as yf

from src.client.models import Holding, Recommendation
from src.data.http import yfinance_session
from src.data.universe import get_index_constituents

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "discover_cache.json"
_CACHE_TTL_SECONDS = 60 * 60  # 1h

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


_REC_RANK = {
    "strong_buy": 0,
    "buy": 1,
    "outperform": 1,
    "hold": 2,
    "underperform": 3,
    "sell": 3,
    "strong_sell": 4,
    None: 5,
}


def _quick_score(symbol: str) -> dict | None:
    """Pre-filter call: only yfinance Ticker.info for analyst consensus + 1y trend."""
    try:
        ticker = yf.Ticker(f"{symbol}.NS", session=_YF_SESSION)
        info = ticker.info or {}
    except Exception:
        return None
    if not info:
        return None

    rec_key = info.get("recommendationKey")
    n_analysts = info.get("numberOfAnalystOpinions") or 0
    target_mean = info.get("targetMeanPrice")
    current = info.get("currentPrice") or info.get("regularMarketPrice")
    yr_low = info.get("fiftyTwoWeekLow")
    yr_high = info.get("fiftyTwoWeekHigh")

    if not (current and target_mean and rec_key):
        return None

    # Need bullish-leaning consensus + at least 5 analysts + meaningful upside.
    if rec_key not in {"strong_buy", "buy"}:
        return None
    if n_analysts < 5:
        return None
    upside_pct = (target_mean - current) / current * 100
    if upside_pct < 8:
        return None  # not enough room

    # Position in 52-week range — prefer pull-backs (40-80%) over near-tops.
    pos_in_range = None
    if yr_low and yr_high and yr_high > yr_low:
        pos_in_range = (current - yr_low) / (yr_high - yr_low)

    # Composite "hotness" score — higher = more interesting short-term play.
    rec_bonus = 1.0 if rec_key == "strong_buy" else 0.5
    range_penalty = 0.0
    if pos_in_range is not None:
        # near-high = more risk; near-low = potentially extended downtrend
        if pos_in_range > 0.85:
            range_penalty = -0.3
        elif pos_in_range < 0.20:
            range_penalty = -0.2
    hotness = rec_bonus + min(upside_pct / 50, 1.0) + range_penalty

    return {
        "symbol": symbol,
        "current_price": float(current),
        "target_mean": float(target_mean),
        "upside_pct": float(upside_pct),
        "rec_key": rec_key,
        "n_analysts": int(n_analysts),
        "pos_in_range": float(pos_in_range) if pos_in_range is not None else None,
        "hotness": float(hotness),
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
    }


def screen_universe(
    index: str = "NIFTY500",
    deep_analyze_top: int = 20,
    max_workers: int = 8,
    refresh: bool = False,
) -> dict:
    """Returns:
        {
            scanned_at: iso timestamp,
            universe: <index name>,
            scanned_count: int,
            screened_count: int,                # passed pre-filter
            picks: [Recommendation, ...]        # top deep-analyzed picks
            shortlist: [{...quick-score...}],   # all pre-filter candidates with metadata
        }
    """
    key = f"{index.upper()}:top{deep_analyze_top}"
    cache = _load_cache()
    if not refresh:
        entry = cache.get(key)
        if entry and (time.time() - entry.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
            return entry.get("data", {})

    constituents = get_index_constituents(index)
    if not constituents:
        return {"scanned_at": None, "universe": index, "scanned_count": 0, "picks": [], "shortlist": []}

    # Stage 1: cheap pre-filter
    candidates: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_quick_score, c["symbol"]): c for c in constituents}
        for fut in as_completed(futures, timeout=600):
            try:
                res = fut.result(timeout=15)
            except Exception:
                continue
            if res is not None:
                meta = futures[fut]
                res["industry_label"] = meta.get("industry") or res.get("industry")
                candidates.append(res)

    # Sort by hotness, take top N for deep analysis
    candidates.sort(key=lambda x: -x["hotness"])
    deep_top = candidates[:deep_analyze_top]

    # Stage 2: deep-analyze the top picks (lazy import to avoid circular)
    from src.api.main import _analyze_one

    picks_models: list[Recommendation] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(_analyze_one, Holding(tradingsymbol=c["symbol"], exchange="NSE", quantity=0, average_price=0.0), 365, False): c
            for c in deep_top
        }
        for fut in as_completed(futures, timeout=600):
            try:
                rec = fut.result(timeout=30)
            except Exception:
                continue
            if rec is not None:
                picks_models.append(rec)

    # Order picks by combined recommendation strength: STRONG BUY first, then BUY,
    # then by target upside.
    action_order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}
    def _sort_key(r: Recommendation) -> tuple:
        upside = (
            (r.target_price_consensus / r.current_price - 1) * 100
            if r.target_price_consensus and r.current_price
            else -999
        )
        return (action_order.get(r.action, 99), -upside)
    picks_models.sort(key=_sort_key)

    # Group picks by sector for sector-tabbed UI
    by_sector: dict[str, list[dict]] = {}
    for r in picks_models:
        sector = r.sector or "Unknown"
        by_sector.setdefault(sector, []).append(r.model_dump())
    # Sort sectors by total picks count desc
    sector_groups = [
        {"sector": s, "count": len(v), "picks": v}
        for s, v in sorted(by_sector.items(), key=lambda kv: -len(kv[1]))
    ]

    out = {
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "universe": index,
        "scanned_count": len(constituents),
        "screened_count": len(candidates),
        "picks": [r.model_dump() for r in picks_models],
        "sector_groups": sector_groups,
        "shortlist": candidates,
    }
    cache[key] = {"fetched_at": time.time(), "data": out}
    _save_cache(cache)
    return out
