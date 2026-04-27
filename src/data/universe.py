"""Index-constituent loaders (NIFTY 50/100/500), cached for 7 days."""

from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

import httpx

from src.data.http import make_ssl_context

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "universe_cache.json"
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

_INDEX_URLS = {
    # Broad-market
    "NIFTY50": "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "NIFTY100": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "NIFTY200": "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
    "NIFTY500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    "NIFTY_NEXT50": "https://archives.nseindia.com/content/indices/ind_niftynext50list.csv",
    "NIFTY_LARGEMIDCAP250": "https://archives.nseindia.com/content/indices/ind_niftylargemidcap250list.csv",
    # Mid + small
    "NIFTY_MIDCAP100": "https://archives.nseindia.com/content/indices/ind_niftymidcap100list.csv",
    "NIFTY_MIDCAP150": "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "NIFTY_SMALLCAP100": "https://archives.nseindia.com/content/indices/ind_niftysmallcap100list.csv",
    "NIFTY_SMALLCAP250": "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    # Sectoral
    "NIFTY_BANK": "https://archives.nseindia.com/content/indices/ind_niftybanklist.csv",
    "NIFTY_PSU_BANK": "https://archives.nseindia.com/content/indices/ind_niftypsubanklist.csv",
    "NIFTY_FINANCIAL_25_50": "https://archives.nseindia.com/content/indices/ind_niftyfinancialservices25_50list.csv",
    "NIFTY_AUTO": "https://archives.nseindia.com/content/indices/ind_niftyautolist.csv",
    "NIFTY_PHARMA": "https://archives.nseindia.com/content/indices/ind_niftypharmalist.csv",
    "NIFTY_HEALTHCARE": "https://archives.nseindia.com/content/indices/ind_niftyhealthcarelist.csv",
    "NIFTY_IT": "https://archives.nseindia.com/content/indices/ind_niftyitlist.csv",
    "NIFTY_ENERGY": "https://archives.nseindia.com/content/indices/ind_niftyenergylist.csv",
    "NIFTY_OIL_GAS": "https://archives.nseindia.com/content/indices/ind_niftyoilgaslist.csv",
    "NIFTY_FMCG": "https://archives.nseindia.com/content/indices/ind_niftyfmcglist.csv",
    "NIFTY_METAL": "https://archives.nseindia.com/content/indices/ind_niftymetallist.csv",
    "NIFTY_REALTY": "https://archives.nseindia.com/content/indices/ind_niftyrealtylist.csv",
    "NIFTY_CONSUMER_DURABLES": "https://archives.nseindia.com/content/indices/ind_niftyconsumerdurableslist.csv",
    # Thematic
    "NIFTY_INDIA_DEFENCE": "https://archives.nseindia.com/content/indices/ind_niftyindiadefence_list.csv",
    "NIFTY_MIDSMALL_HEALTHCARE": "https://archives.nseindia.com/content/indices/ind_niftymidsmallhealthcare_list.csv",
}

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(15.0, connect=5.0),
    headers={"User-Agent": "Mozilla/5.0 (live-stock-app/1.0)"},
    follow_redirects=True,
)


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


def get_index_constituents(index: str = "NIFTY500", refresh: bool = False) -> list[dict]:
    """Return [{symbol, name, industry, isin}, ...] for the given index."""
    index = index.upper()
    if index not in _INDEX_URLS:
        raise ValueError(f"Unknown index {index}. Known: {list(_INDEX_URLS)}")

    cache = _load_cache()
    if not refresh:
        entry = cache.get(index)
        if entry and (time.time() - entry.get("fetched_at", 0)) < _CACHE_TTL_SECONDS:
            return entry.get("data", [])

    try:
        resp = _HTTPX.get(_INDEX_URLS[index])
        if resp.status_code != 200 or not resp.text:
            return cache.get(index, {}).get("data", [])  # serve stale rather than fail
    except Exception:
        return cache.get(index, {}).get("data", [])

    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        sym = (row.get("Symbol") or "").strip()
        if not sym:
            continue
        rows.append({
            "symbol": sym,
            "name": (row.get("Company Name") or "").strip(),
            "industry": (row.get("Industry") or "").strip(),
            "isin": (row.get("ISIN Code") or "").strip(),
        })

    cache[index] = {"fetched_at": time.time(), "data": rows}
    _save_cache(cache)
    return rows
