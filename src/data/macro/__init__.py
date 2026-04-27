"""Macro-event analyzer: rule-based theme detection + optional Gemini layer.

Pulls articles from the existing news_sources master index (no extra fetches),
runs both layers, caches the result for 1 hour at data/macro_cache.json.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.data import news_sources
from src.data.macro import llm_gemini
from src.data.macro.themes import THEMES, _sector_matches_any, detect_themes

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "macro_cache.json"
_CACHE_TTL_SECONDS = 60 * 60  # 1h


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_cache(payload: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=str))
        tmp.replace(_CACHE_PATH)
    except Exception:
        pass


def _enrich_gemini_with_universe(
    gemini_themes: list[dict],
    universe_stocks: list[dict],
    portfolio_symbols: set[str],
) -> list[dict]:
    """Gemini doesn't know our stock universe — fill ``impacted_positive``/
    ``impacted_negative`` lists by joining its sector strings against ours."""
    out: list[dict] = []
    for t in gemini_themes:
        sec_pos = t.get("sectors_positive") or []
        sec_neg = t.get("sectors_negative") or []
        impacted_positive: list[dict] = []
        impacted_negative: list[dict] = []
        for s in universe_stocks:
            sector = s.get("sector") or s.get("industry") or ""
            sym = (s.get("symbol") or "").upper()
            entry = {
                "symbol": sym,
                "sector": sector,
                "name": s.get("name"),
                "in_portfolio": sym in portfolio_symbols,
            }
            if sec_pos and _sector_matches_any(sector, sec_pos):
                impacted_positive.append(entry)
            if sec_neg and _sector_matches_any(sector, sec_neg):
                impacted_negative.append(entry)
        impacted_positive.sort(key=lambda x: (not x["in_portfolio"], x["symbol"]))
        impacted_negative.sort(key=lambda x: (not x["in_portfolio"], x["symbol"]))
        t = dict(t)
        t["impacted_positive"] = impacted_positive[:25]
        t["impacted_negative"] = impacted_negative[:25]
        out.append(t)
    return out


def get_active_themes(refresh: bool = False) -> dict:
    """Return ``{themes: [...], generated_at, sources_used}``.

    Layer 1 always runs. Layer 2 (Gemini) runs when ``GEMINI_API_KEY`` is
    set. Cached for 1h.
    """
    cache = _load_cache()
    now = time.time()
    if not refresh and cache and now - cache.get("generated_at_ts", 0) < _CACHE_TTL_SECONDS:
        return cache.get("data", {"themes": []})

    articles = news_sources._refresh_master_index()
    universe = _build_universe(articles)
    portfolio_symbols = _portfolio_symbols()

    rule_themes = detect_themes(articles, universe_stocks=universe, portfolio_symbols=portfolio_symbols)
    try:
        gemini_themes = llm_gemini.analyze_with_gemini(articles)
    except Exception:
        gemini_themes = []
    gemini_themes = _enrich_gemini_with_universe(gemini_themes, universe, portfolio_symbols)

    sources_used = ["rule_based"]
    if gemini_themes:
        sources_used.append("gemini")

    # Merge: keep rule-based themes (deterministic + joinable) and add
    # Gemini themes that don't duplicate by id.
    seen_ids = {t["theme"] for t in rule_themes}
    merged = list(rule_themes)
    for t in gemini_themes:
        if t["theme"] not in seen_ids:
            merged.append(t)
            seen_ids.add(t["theme"])

    out = {
        "themes": merged,
        "sources_used": sources_used,
        "article_count": len(articles),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
    }
    _save_cache({"generated_at_ts": now, "data": out})
    return out


_UNIVERSE_INDICES = [
    "NIFTY500",
    "NIFTY_INDIA_DEFENCE",
    "NIFTY_BANK",
    "NIFTY_AUTO",
    "NIFTY_PHARMA",
    "NIFTY_IT",
    "NIFTY_ENERGY",
    "NIFTY_OIL_GAS",
    "NIFTY_FMCG",
    "NIFTY_METAL",
    "NIFTY_REALTY",
]


def _build_universe(articles_unused) -> list[dict]:
    """Universe = union of NIFTY 500 + sectoral indices, dedup by symbol,
    annotated with yfinance sector from the fundamentals cache when present
    (no network calls — best-effort)."""
    try:
        from src.data.universe import get_index_constituents
    except Exception:
        return []
    fund_cache = _load_fundamentals_cache()
    by_symbol: dict[str, dict] = {}
    for index in _UNIVERSE_INDICES:
        try:
            constituents = get_index_constituents(index) or []
        except Exception:
            continue
        for c in constituents:
            sym = (c.get("symbol") or "").upper()
            if not sym or sym in by_symbol:
                continue
            key = f"NSE:{sym}"
            entry = (fund_cache.get(key) or {}).get("data") or {}
            raw_yf = (entry.get("raw_per_source") or {}).get("yfinance") or {}
            # Use industry first (more specific, e.g. "Aerospace & Defense")
            # then fall back to sector ("Industrials"), then NSE's industry CSV.
            yf_sector = raw_yf.get("sector") or ""
            yf_industry = raw_yf.get("industry") or ""
            nse_industry = c.get("industry") or ""
            sector = yf_industry or yf_sector or nse_industry
            industry = yf_industry or nse_industry
            by_symbol[sym] = {
                "symbol": sym,
                "name": c.get("name", ""),
                "sector": sector,
                "industry": industry,
            }
    return list(by_symbol.values())


def _load_fundamentals_cache() -> dict:
    p = Path(__file__).resolve().parent.parent.parent.parent / "data" / "fundamentals_cache.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _portfolio_symbols() -> set[str]:
    """Best-effort portfolio symbols from the daily-cache; empty set if not
    populated yet (during fresh boot)."""
    p = Path(__file__).resolve().parent.parent.parent.parent / "data" / "daily_recommendations.json"
    try:
        data = json.loads(p.read_text())
        return {(h.get("tradingsymbol") or "").upper() for h in (data.get("holdings") or [])}
    except Exception:
        return set()
