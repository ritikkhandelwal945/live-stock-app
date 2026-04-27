"""NSE bulk + block deals — daily CSVs from `archives.nseindia.com`.

The NSE archive endpoint (`bulk.csv` / `block.csv`) only carries the *current
day's* deals. We accumulate them into a persistent rolling 60-day index so
``recent_for_symbol`` can return last-30-day activity. The accumulation runs
on every fetch (idempotent: each (date, symbol, counterparty, side, qty)
tuple is deduped).
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from src.data.http import make_ssl_context

_CACHE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "bulk_deals_index.json"
_KEEP_DAYS = 60
_DAILY_FETCH_TTL = 60 * 60  # don't refetch the same daily CSV more than hourly

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(10.0, connect=5.0),
    headers={"User-Agent": "Mozilla/5.0 (live-stock-app/1.0)"},
    follow_redirects=True,
)

_BULK_URL = "https://archives.nseindia.com/content/equities/bulk.csv"
_BLOCK_URL = "https://archives.nseindia.com/content/equities/block.csv"

# Substrings that mark a deal counterparty as "smart money" worth surfacing
_SMART_MONEY_KEYWORDS = [
    "GOLDMAN SACHS", "MORGAN STANLEY", "BLACKROCK", "VANGUARD", "JP MORGAN",
    "JPMORGAN", "FIDELITY", "NORGES", "CITIGROUP", "DEUTSCHE BANK", "BARCLAYS",
    "UBS", "HSBC", "MERRILL", "TROWE", "T. ROWE", "INVESCO",
    "LIC OF INDIA", "LIFE INSURANCE CORPORATION",
    "SBI MUTUAL FUND", "ICICI PRUDENTIAL", "HDFC MUTUAL", "AXIS MUTUAL",
    "KOTAK MUTUAL", "MIRAE", "NIPPON LIFE", "DSP MUTUAL",
    "FOREIGN PORTFOLIO INVESTOR", "FPI", "QIB",
    "MAURITIUS", "SINGAPORE", "LUXEMBOURG",  # geography clues for FII vehicles
]


def _smart_money_tag(counterparty: str) -> str | None:
    cp = (counterparty or "").upper()
    for kw in _SMART_MONEY_KEYWORDS:
        if kw in cp:
            return kw.title()
    return None


def _parse_csv(text: str, kind: str) -> list[dict]:
    out: list[dict] = []
    if not text or text.startswith("NO RECORDS"):
        return out
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        sym = (row.get("Symbol") or "").strip().upper()
        if not sym or sym == "NO RECORDS":
            continue
        side = (row.get("Buy/Sell") or "").strip().upper()
        try:
            qty = int((row.get("Quantity Traded") or "0").replace(",", ""))
        except (ValueError, TypeError):
            qty = 0
        try:
            price = float((row.get("Trade Price / Wght. Avg. Price") or "0").replace(",", ""))
        except (ValueError, TypeError):
            price = 0.0
        cp = (row.get("Client Name") or "").strip()
        date_raw = (row.get("Date") or "").strip()
        try:
            date_iso = datetime.strptime(date_raw, "%d-%b-%Y").date().isoformat()
        except ValueError:
            date_iso = date_raw
        out.append({
            "date": date_iso,
            "symbol": sym,
            "counterparty": cp,
            "side": side,
            "qty": qty,
            "price": price,
            "value": qty * price,
            "smart_money_tag": _smart_money_tag(cp),
            "kind": kind,  # "bulk" or "block"
        })
    return out


def _load_index() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {"last_fetched_at": 0, "deals": []}


def _save_index(idx: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, default=str))
        tmp.replace(_CACHE_PATH)
    except Exception:
        pass


def _refresh_if_stale() -> dict:
    """Fetch today's CSVs and merge into the rolling index."""
    idx = _load_index()
    now = time.time()
    if (now - idx.get("last_fetched_at", 0)) < _DAILY_FETCH_TTL:
        return idx

    new_deals: list[dict] = []
    for url, kind in ((_BULK_URL, "bulk"), (_BLOCK_URL, "block")):
        try:
            r = _HTTPX.get(url)
            if r.status_code == 200:
                new_deals.extend(_parse_csv(r.text, kind))
        except Exception:
            continue

    # Merge with existing, dedup by (date, symbol, counterparty, side, qty)
    seen = set()
    merged: list[dict] = []
    for d in idx.get("deals", []) + new_deals:
        key = (d.get("date"), d.get("symbol"), d.get("counterparty"), d.get("side"), d.get("qty"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(d)

    # Trim to last KEEP_DAYS
    cutoff = (datetime.utcnow().date() - timedelta(days=_KEEP_DAYS)).isoformat()
    merged = [d for d in merged if (d.get("date") or "") >= cutoff]

    idx = {"last_fetched_at": now, "deals": merged}
    _save_index(idx)
    return idx


def recent_for_symbol(symbol: str, days: int = 30) -> list[dict]:
    """Return bulk + block deals for ``symbol`` in the last ``days``, newest first."""
    idx = _refresh_if_stale()
    sym = symbol.strip().upper()
    cutoff = (datetime.utcnow().date() - timedelta(days=days)).isoformat()
    rows = [d for d in idx.get("deals", []) if d.get("symbol") == sym and (d.get("date") or "") >= cutoff]
    rows.sort(key=lambda r: (r.get("date") or "", r.get("value") or 0), reverse=True)
    return rows
