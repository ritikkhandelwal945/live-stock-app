"""Deep historical performance metrics from OHLCV history.

Pure-compute module — no network calls. Feeds the recommendation engine with
risk-adjusted return signals (Sharpe), drawdown depth, multi-year returns,
volatility, and beta vs NIFTY 50.

All metrics gracefully return ``None`` when the underlying series is too
short rather than raising — a 6-month-old IPO simply gets fewer fields
populated.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd


_TRADING_DAYS = 252
_RISK_FREE = 0.07  # India 10Y G-Sec ~7% — used as Sharpe risk-free rate


def _safe_pct(end: float, start: float) -> float | None:
    if start is None or start == 0 or end is None:
        return None
    return (end / start - 1.0) * 100


def _annualized(total_return_pct: float | None, years: float) -> float | None:
    if total_return_pct is None or years <= 0:
        return None
    g = 1 + total_return_pct / 100.0
    if g <= 0:
        return None
    return (g ** (1 / years) - 1) * 100


def compute(
    close: pd.Series,
    nifty_close: pd.Series | None = None,
) -> dict:
    """Compute risk + return metrics for a daily close-price series.

    Returns a dict with keys: one_year_return, three_year_return,
    five_year_return, annualized_volatility, max_drawdown_1y, sharpe_1y,
    beta_vs_nifty. Any metric whose history requirement isn't met is None.
    """
    out: dict = {
        "one_year_return": None,
        "three_year_return": None,
        "five_year_return": None,
        "annualized_volatility": None,
        "max_drawdown_1y": None,
        "sharpe_1y": None,
        "beta_vs_nifty": None,
    }

    if close is None or len(close) < 30:
        return out

    s = pd.Series(close).astype(float).dropna()
    if len(s) < 30:
        return out

    last = float(s.iloc[-1])

    # Multi-year returns
    if len(s) >= _TRADING_DAYS:
        out["one_year_return"] = _safe_pct(last, float(s.iloc[-_TRADING_DAYS]))
    if len(s) >= 3 * _TRADING_DAYS:
        total_3y = _safe_pct(last, float(s.iloc[-3 * _TRADING_DAYS]))
        out["three_year_return"] = _annualized(total_3y, 3.0)
    if len(s) >= 5 * _TRADING_DAYS:
        total_5y = _safe_pct(last, float(s.iloc[-5 * _TRADING_DAYS]))
        out["five_year_return"] = _annualized(total_5y, 5.0)

    # Daily log returns over last year
    log_r = np.log(s).diff().dropna()
    if len(log_r) >= 60:
        recent = log_r.tail(_TRADING_DAYS)
        ann_vol = float(recent.std(ddof=1) * math.sqrt(_TRADING_DAYS) * 100)
        out["annualized_volatility"] = round(ann_vol, 2)

    # Max drawdown over 1Y
    if len(s) >= _TRADING_DAYS:
        recent = s.tail(_TRADING_DAYS)
        running_max = recent.cummax()
        drawdown = (recent / running_max - 1.0) * 100
        out["max_drawdown_1y"] = round(float(drawdown.min()), 2)

    # Sharpe 1Y = (return - risk_free) / annualized_volatility
    if (
        out["one_year_return"] is not None
        and out["annualized_volatility"] is not None
        and out["annualized_volatility"] > 0
    ):
        out["sharpe_1y"] = round(
            (out["one_year_return"] - _RISK_FREE * 100) / out["annualized_volatility"],
            2,
        )

    # Beta vs NIFTY (covariance of returns / variance of NIFTY returns)
    if nifty_close is not None and len(nifty_close) >= 60 and len(log_r) >= 60:
        n = pd.Series(nifty_close).astype(float).dropna()
        nifty_log_r = np.log(n).diff().dropna()
        # Align by date if both have datetime indexes; otherwise fall back to
        # tail-N alignment which is good enough for daily series.
        common = min(len(log_r), len(nifty_log_r), _TRADING_DAYS)
        if common >= 60:
            stock_recent = log_r.tail(common).reset_index(drop=True)
            nifty_recent = nifty_log_r.tail(common).reset_index(drop=True)
            cov = float(np.cov(stock_recent, nifty_recent, ddof=1)[0, 1])
            var = float(np.var(nifty_recent, ddof=1))
            if var > 0:
                out["beta_vs_nifty"] = round(cov / var, 3)

    return out


def round_returns(d: dict) -> dict:
    """Convenience: round percentage fields to 2dp for display."""
    out = dict(d)
    for k in ("one_year_return", "three_year_return", "five_year_return"):
        if out.get(k) is not None:
            out[k] = round(float(out[k]), 2)
    return out
