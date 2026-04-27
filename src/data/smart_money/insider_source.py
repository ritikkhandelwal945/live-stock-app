"""BSE insider-trading disclosures (SEBI-mandated).

Best-effort scrape. The endpoint returns HTML rather than JSON; we extract
disclosure rows when possible. If the endpoint changes shape or rejects us
the function returns ``[]`` and the aggregator omits this source.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from src.data.http import make_ssl_context

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(8.0, connect=4.0),
    headers={
        "User-Agent": "Mozilla/5.0 (live-stock-app/1.0)",
        "Accept": "text/html,application/xhtml+xml",
    },
    follow_redirects=True,
)


def _to_int(s: str) -> int | None:
    if not s:
        return None
    s = s.replace(",", "").strip()
    try:
        return int(float(s))
    except ValueError:
        return None


def _to_date_str(s: str) -> str | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s  # fall back to whatever the page printed


def recent_for_symbol(symbol: str, days: int = 30) -> list[dict]:
    """Return last ``days`` of insider/promoter trades for the symbol.

    Each row: ``{date, person, person_role, side, qty, value}``. Returns an
    empty list on any failure (including HTML schema change).
    """
    sym = symbol.strip().upper()
    today = datetime.utcnow().date()
    from_date = (today - timedelta(days=days)).strftime("%d/%m/%Y")
    to_date = today.strftime("%d/%m/%Y")

    url = (
        "https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w"
        f"?strCat=Insider%20Trading&strPrevDate={from_date}&strScrip="
        f"&strSearch=P&strToDate={to_date}&strType=C"
    )
    try:
        r = _HTTPX.get(url)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    text = r.text or ""
    if sym not in text.upper() and not text.lstrip().startswith("{"):
        # Page is generic landing — no rows for this symbol on the API call.
        return []

    # The endpoint may return JSON in a Table key or HTML. Try JSON first.
    out: list[dict] = []
    try:
        payload = r.json()
        rows = payload.get("Table") or payload.get("Insider") or []
        for row in rows[:50]:
            if not isinstance(row, dict):
                continue
            sec_code = (row.get("scrip_cd") or row.get("Scrip_Code") or "").strip()
            sec_name = (row.get("LONG_NAME") or row.get("scrip_name") or "").strip().upper()
            if sym not in sec_name and sec_code != sym:
                continue
            out.append({
                "date": _to_date_str(row.get("DT_TM") or row.get("date") or ""),
                "person": row.get("name_acquirer") or row.get("acq_name") or "",
                "person_role": row.get("category") or row.get("type_promoter") or "",
                "side": row.get("type_of_acq") or "",
                "qty": _to_int(str(row.get("no_of_securities_acq") or row.get("qty") or "")),
                "value": _to_int(str(row.get("amount") or "")),
            })
        if out:
            return out
    except Exception:
        pass

    # Fall back: parse a table from HTML if JSON didn't work
    try:
        soup = BeautifulSoup(text, "lxml")
        for tr in soup.select("table tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.select("td")]
            joined = " ".join(cells)
            if sym not in joined.upper() or len(cells) < 4:
                continue
            out.append({
                "date": _to_date_str(cells[0]),
                "person": cells[1] if len(cells) > 1 else "",
                "person_role": cells[2] if len(cells) > 2 else "",
                "side": "BUY" if "buy" in joined.lower() else ("SELL" if "sell" in joined.lower() else ""),
                "qty": _to_int(cells[3]) if len(cells) > 3 else None,
                "value": _to_int(cells[4]) if len(cells) > 4 else None,
            })
            if len(out) >= 30:
                break
    except Exception:
        return []

    return out
