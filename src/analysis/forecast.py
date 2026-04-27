"""Price forecasting helpers.

Two complementary models:
 - 30-day ARIMA: best-(p,d,q) by AIC over a small grid; mean + 80% CI band.
 - 12-month Monte Carlo: bootstrap of historical daily log returns; honest
   wide bands. The 12-month single-point projection is not meaningful on its
   own — the *band* is what should be shown to the user.

Both functions return ``None`` on failure; the caller is responsible for
displaying graceful "insufficient history" copy.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd


def forecast_arima_30d(close: pd.Series, horizon_days: int = 30) -> dict | None:
    """Best-AIC ARIMA(p,d,q) over a small grid.

    Returns ``{forecast, low, high, model_aic, horizon_days}`` (80% CI) or
    ``None`` if no model converges or there's insufficient history.
    """
    if close is None or len(close) < 60:
        return None

    s = pd.Series(close).astype(float).dropna()
    if len(s) < 60:
        return None

    log_s = np.log(s)

    # Tiny grid — keep it fast (~1-2s per stock).
    best = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # silences ConvergenceWarning + UserWarning
        try:
            from statsmodels.tsa.arima.model import ARIMA
            from statsmodels.tools.sm_exceptions import ConvergenceWarning
            warnings.simplefilter("ignore", ConvergenceWarning)
        except Exception:
            return None

        for p in (0, 1, 2):
            for d in (0, 1):
                for q in (0, 1, 2):
                    try:
                        model = ARIMA(log_s, order=(p, d, q))
                        res = model.fit()
                        if best is None or res.aic < best[0]:
                            best = (res.aic, res, (p, d, q))
                    except Exception:
                        continue

    if best is None:
        return None

    aic, res, _order = best
    try:
        fcst = res.get_forecast(steps=horizon_days)
        mean_log = fcst.predicted_mean.iloc[-1]
        ci = fcst.conf_int(alpha=0.20)  # 80% interval
        low_log = ci.iloc[-1, 0]
        high_log = ci.iloc[-1, 1]
        if not all(np.isfinite([mean_log, low_log, high_log])):
            return None
        return {
            "forecast": float(np.exp(mean_log)),
            "low": float(np.exp(low_log)),
            "high": float(np.exp(high_log)),
            "horizon_days": horizon_days,
            "model_aic": float(aic),
        }
    except Exception:
        return None


def forecast_monte_carlo_12m(
    close: pd.Series,
    horizon_days: int = 252,
    sims: int = 1000,
    seed: int | None = 42,
) -> dict | None:
    """Bootstrap daily log returns to project a distribution at horizon.

    Returns ``{p5, p50, p95, current_price, horizon_days, sample_size}`` or
    ``None`` if insufficient history.
    """
    if close is None or len(close) < 60:
        return None

    s = pd.Series(close).astype(float).dropna()
    if len(s) < 60:
        return None

    log_returns = np.log(s).diff().dropna().to_numpy()
    if len(log_returns) < 30:
        return None

    rng = np.random.default_rng(seed)
    # Sample matrix: (sims, horizon_days) bootstrap with replacement.
    draws = rng.choice(log_returns, size=(sims, horizon_days), replace=True)
    cumulative_log = draws.sum(axis=1)
    final_prices = float(s.iloc[-1]) * np.exp(cumulative_log)

    p5, p50, p95 = np.percentile(final_prices, [5, 50, 95])
    if not all(np.isfinite([p5, p50, p95])):
        return None

    return {
        "p5": float(p5),
        "p50": float(p50),
        "p95": float(p95),
        "current_price": float(s.iloc[-1]),
        "horizon_days": horizon_days,
        "sample_size": int(len(log_returns)),
    }
