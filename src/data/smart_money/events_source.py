"""NSE corporate events: corporate actions + recent results + event calendar.

Per-symbol fetch via NSE's public JSON APIs. Each call is best-effort and
returns ``{}`` on failure so the aggregator can continue.

The NSE JSON endpoints typically expect a Referer + cookie set by their
homepage; without it they timeout or 401. We attempt with realistic browser
headers; if that still fails the function returns empty rather than raising.
"""

from __future__ import annotations

import httpx

from src.data.http import make_ssl_context

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(8.0, connect=4.0),
    headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    },
    follow_redirects=True,
)


def _safe_json_get(url: str) -> dict | list | None:
    try:
        r = _HTTPX.get(url)
        if r.status_code != 200 or not r.text:
            return None
        return r.json()
    except Exception:
        return None


def _normalize_corp_actions(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for r in raw[:30]:
        if not isinstance(r, dict):
            continue
        out.append({
            "subject": r.get("subject") or "",
            "ex_date": r.get("exDate") or r.get("ex_date") or "",
            "purpose": r.get("subject") or "",
            "record_date": r.get("recDate") or r.get("rec_date") or "",
            "raw": r,
        })
    return out


def _normalize_results(raw) -> list[dict]:
    if not isinstance(raw, dict):
        return []
    rows = raw.get("resCmpData") or []
    out: list[dict] = []
    for r in rows[:8]:
        if not isinstance(r, dict):
            continue
        out.append({
            "period_to": r.get("re_to_dt"),
            "period_from": r.get("re_from_dt"),
            "revenue": r.get("revenue"),
            "net_profit": r.get("netProfitLoss") or r.get("net_profit"),
            "eps": r.get("eps"),
            "raw": r,
        })
    return out


def _normalize_calendar(raw, symbol: str) -> list[dict]:
    if not isinstance(raw, list):
        return []
    sym = symbol.upper()
    out: list[dict] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        if (r.get("symbol") or "").upper() != sym:
            continue
        out.append({
            "purpose": r.get("purpose"),
            "date": r.get("bm_desc") or r.get("date"),
            "company": r.get("company"),
            "raw": r,
        })
        if len(out) >= 10:
            break
    return out


def for_symbol(symbol: str) -> dict:
    """Return ``{corporate_actions, recent_results, upcoming}`` for the symbol."""
    sym = symbol.strip().upper()
    out = {
        "corporate_actions": [],
        "recent_results": [],
        "upcoming": [],
    }
    ca = _safe_json_get(
        f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={sym}"
    )
    if ca is not None:
        out["corporate_actions"] = _normalize_corp_actions(ca)

    res = _safe_json_get(
        f"https://www.nseindia.com/api/results-comparision?index=equities&symbol={sym}"
    )
    if res is not None:
        out["recent_results"] = _normalize_results(res)

    cal = _safe_json_get("https://www.nseindia.com/api/event-calendar?index=equities")
    if cal is not None:
        out["upcoming"] = _normalize_calendar(cal, sym)

    return out
