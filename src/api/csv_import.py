import io

import pandas as pd

from src.client.models import Holding


_SYMBOL_HINTS = ["instrument", "tradingsymbol", "symbol", "scrip", "name", "stock"]
_QTY_HINTS = ["qty", "quantity", "shares"]
_AVG_HINTS = ["avg", "average", "buy price", "cost"]
_LTP_HINTS = ["ltp", "last", "current price", "cmp"]
_PNL_HINTS = ["p&l", "pnl", "profit", "gain"]
_DAY_HINTS = ["day chg", "day change", "net chg", "% chg", "day %"]


def _find_col(cols: list[str], hints: list[str]) -> str | None:
    lowered = {c: c.lower().strip() for c in cols}
    for hint in hints:
        for orig, low in lowered.items():
            if hint in low:
                return orig
    return None


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v) if not pd.isna(v) else 0.0
    s = str(v).strip().replace(",", "").replace("₹", "").replace("%", "").replace("+", "")
    if not s or s.lower() in {"nan", "-", "n/a"}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_holdings_csv(content: bytes, filename: str = "") -> list[Holding]:
    """Parse a Zerodha Console holdings export (CSV or XLSX) into Holding objects."""
    name = filename.lower()
    buf = io.BytesIO(content)

    if name.endswith(".xlsx") or name.endswith(".xls"):
        df = pd.read_excel(buf)
    else:
        df = _read_csv_skipping_preamble(content)

    if df.empty:
        return []

    cols = [str(c) for c in df.columns]
    sym_col = _find_col(cols, _SYMBOL_HINTS)
    qty_col = _find_col(cols, _QTY_HINTS)
    avg_col = _find_col(cols, _AVG_HINTS)
    ltp_col = _find_col(cols, _LTP_HINTS)
    pnl_col = _find_col(cols, _PNL_HINTS)
    day_col = _find_col(cols, _DAY_HINTS)

    if not sym_col or not qty_col:
        raise ValueError(
            f"CSV missing required columns. Found: {cols}. "
            "Need at minimum a symbol/instrument column and a quantity column."
        )

    holdings: list[Holding] = []
    for _, row in df.iterrows():
        symbol = str(row[sym_col]).strip().upper()
        if not symbol or symbol == "NAN" or symbol.startswith("TOTAL"):
            continue
        qty = int(_to_float(row[qty_col]))
        if qty <= 0:
            continue
        avg = _to_float(row[avg_col]) if avg_col else 0.0
        ltp = _to_float(row[ltp_col]) if ltp_col else 0.0
        pnl = _to_float(row[pnl_col]) if pnl_col else (ltp - avg) * qty
        day_pct = _to_float(row[day_col]) if day_col else 0.0
        holdings.append(Holding(
            tradingsymbol=symbol,
            quantity=qty,
            average_price=avg,
            last_price=ltp,
            pnl=pnl,
            day_change_percentage=day_pct,
            product="CNC",
        ))
    return holdings


def _read_csv_skipping_preamble(content: bytes) -> pd.DataFrame:
    text = content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        low = line.lower()
        if any(h in low for h in _SYMBOL_HINTS) and any(h in low for h in _QTY_HINTS):
            header_idx = i
            break
    return pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
