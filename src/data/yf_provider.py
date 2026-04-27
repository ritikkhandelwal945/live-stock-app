from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from src.data.http import yfinance_session

# Platform-aware: None on macOS/Windows (let yfinance manage its own session
# so Yahoo's crumb/cookie auth works); custom verify=False curl_cffi session
# on Linux (dev container) where we're behind the corp MITM proxy.
_YF_SESSION = yfinance_session()


def to_yf_symbol(symbol: str, exchange: str = "NSE") -> str:
    s = symbol.strip().upper()
    if "." in s:
        return s
    return f"{s}.BO" if exchange.upper() == "BSE" else f"{s}.NS"


def get_history(symbol: str, days: int = 365, exchange: str = "NSE") -> pd.DataFrame:
    yf_symbol = to_yf_symbol(symbol, exchange)
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=days)
    df = yf.download(
        yf_symbol,
        start=start.isoformat(),
        end=end.isoformat(),
        progress=False,
        auto_adjust=False,
        threads=False,
        session=_YF_SESSION,
    )
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    )
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)


def get_quote(symbol: str, exchange: str = "NSE") -> dict | None:
    yf_symbol = to_yf_symbol(symbol, exchange)
    try:
        ticker = yf.Ticker(yf_symbol, session=_YF_SESSION)
        fast = ticker.fast_info
        last = float(fast.get("lastPrice") or fast.get("last_price") or 0.0)
        prev = float(fast.get("previousClose") or fast.get("previous_close") or 0.0)
        if not last:
            return None
        day_change_pct = ((last - prev) / prev * 100) if prev else 0.0
        return {"last_price": last, "previous_close": prev, "day_change_percentage": day_change_pct}
    except Exception:
        return None


def get_quotes(symbols: list[str], exchange: str = "NSE") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for s in symbols:
        q = get_quote(s, exchange)
        if q:
            out[s] = q
    return out
