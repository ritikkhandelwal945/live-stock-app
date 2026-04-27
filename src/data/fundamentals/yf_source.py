"""yfinance fundamentals + analyst consensus."""

from __future__ import annotations

import contextlib
import io
import logging

import yfinance as yf

from src.data.http import yfinance_session

# yfinance writes 401/403 errors directly to stdout/stderr instead of raising.
# We silence its noisy logger so a single rate-limited stock doesn't spam the
# console with screen-fulls of HTTP 401 lines. The exception path stays intact.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

_SESSION = yfinance_session()


def _to_yf_symbol(symbol: str, exchange: str) -> str:
    s = symbol.strip().upper()
    if "." in s:
        return s
    return f"{s}.BO" if exchange.upper() == "BSE" else f"{s}.NS"


_REC_NORMALIZE = {
    "strong_buy": "strong_buy",
    "buy": "buy",
    "hold": "hold",
    "sell": "sell",
    "strong_sell": "strong_sell",
    "underperform": "sell",
    "outperform": "buy",
    "none": None,
    None: None,
}


def fetch(symbol: str, exchange: str = "NSE") -> dict | None:
    yf_sym = _to_yf_symbol(symbol, exchange)
    try:
        ticker = yf.Ticker(yf_sym, session=_SESSION)
        # Some yfinance versions print "HTTP 401" to stderr instead of raising;
        # swallow that noise. If Yahoo blocks the call, info ends up empty.
        with contextlib.redirect_stderr(io.StringIO()):
            info = ticker.info or {}
    except Exception:
        return None

    if not info:
        return None

    def _g(k):
        v = info.get(k)
        if isinstance(v, (int, float)) and v == v:
            return float(v)
        return None

    pe = _g("trailingPE")
    de = _g("debtToEquity")
    if de is not None:
        de = de / 100.0  # yfinance reports D/E in percent → convert to ratio
    # Convert decimal-as-percent → percent so analyze_from_data scoring works
    roe_decimal = _g("returnOnEquity")
    roe = roe_decimal * 100 if roe_decimal is not None else None
    rev_g_decimal = _g("revenueGrowth")
    rev_g = rev_g_decimal * 100 if rev_g_decimal is not None else None
    eps_g_decimal = _g("earningsGrowth")
    eps_g = eps_g_decimal * 100 if eps_g_decimal is not None else None
    div_y_decimal = _g("dividendYield")
    div_y = div_y_decimal * 100 if div_y_decimal is not None else None

    target_mean = _g("targetMeanPrice")
    target_high = _g("targetHighPrice")
    target_low = _g("targetLowPrice")
    n_analysts = info.get("numberOfAnalystOpinions")
    rec_key = info.get("recommendationKey")

    return {
        "ratios": {
            "pe_ratio": pe,
            "debt_to_equity": de,
            "roe": roe,
            "revenue_growth": rev_g,
            "eps_growth": eps_g,
        },
        "target_price": target_mean,
        "target_high": target_high,
        "target_low": target_low,
        "target_recommendation": _REC_NORMALIZE.get(rec_key, rec_key),
        "analyst_count": int(n_analysts) if isinstance(n_analysts, (int, float)) else None,
        "analyst_recommendation": _REC_NORMALIZE.get(rec_key, rec_key),
        "market_cap": _g("marketCap"),
        "dividend_yield": div_y,  # percent
        "fifty_two_week_high": _g("fiftyTwoWeekHigh"),
        "fifty_two_week_low": _g("fiftyTwoWeekLow"),
        "raw": {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "trailingPE": pe,
            "forwardPE": _g("forwardPE"),
            "priceToBook": _g("priceToBook"),
            "profitMargins": _g("profitMargins"),
            "freeCashflow": _g("freeCashflow"),
        },
    }
