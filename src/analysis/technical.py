from dataclasses import dataclass, field

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator, EMAIndicator
from ta.volatility import AverageTrueRange, BollingerBands


@dataclass
class IndicatorSignal:
    name: str
    value: float
    signal: str  # "bullish", "bearish", "neutral"
    score: float  # -1.0 to +1.0
    detail: str = ""


@dataclass
class TechnicalSignals:
    indicators: list[IndicatorSignal] = field(default_factory=list)
    overall_score: float = 0.0
    atr_value: float | None = None  # ATR(14) — used for stop/target zones

    @property
    def summary(self) -> str:
        if self.overall_score > 0.15:
            return "BULLISH"
        elif self.overall_score < -0.15:
            return "BEARISH"
        return "NEUTRAL"


def analyze(df: pd.DataFrame) -> TechnicalSignals:
    if df.empty or len(df) < 30:
        return TechnicalSignals(
            indicators=[IndicatorSignal("data", 0, "neutral", 0.0, "Insufficient data")],
            overall_score=0.0,
        )

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    current_price = close.iloc[-1]

    signals: list[IndicatorSignal] = []

    # --- SMA 20/50/200 ---
    for window in [20, 50, 200]:
        if len(df) < window:
            continue
        sma = SMAIndicator(close, window=window).sma_indicator()
        sma_val = sma.iloc[-1]
        if pd.isna(sma_val):
            continue
        diff_pct = (current_price - sma_val) / sma_val * 100
        if diff_pct > 2:
            score, sig = 0.5, "bullish"
        elif diff_pct < -2:
            score, sig = -0.5, "bearish"
        else:
            score, sig = 0.0, "neutral"
        signals.append(IndicatorSignal(
            f"SMA{window}", round(sma_val, 2), sig, score,
            f"Price {diff_pct:+.1f}% vs SMA{window} ({sma_val:.2f})"
        ))

    # --- Golden/Death Cross (SMA50 vs SMA200) ---
    if len(df) >= 200:
        sma50 = SMAIndicator(close, window=50).sma_indicator()
        sma200 = SMAIndicator(close, window=200).sma_indicator()
        s50, s200 = sma50.iloc[-1], sma200.iloc[-1]
        s50_prev, s200_prev = sma50.iloc[-2], sma200.iloc[-2]
        if not (pd.isna(s50) or pd.isna(s200) or pd.isna(s50_prev) or pd.isna(s200_prev)):
            if s50_prev < s200_prev and s50 > s200:
                signals.append(IndicatorSignal("GoldenCross", 0, "bullish", 0.8, "SMA50 crossed above SMA200"))
            elif s50_prev > s200_prev and s50 < s200:
                signals.append(IndicatorSignal("DeathCross", 0, "bearish", -0.8, "SMA50 crossed below SMA200"))

    # --- EMA 12/26 Crossover ---
    if len(df) >= 26:
        ema12 = EMAIndicator(close, window=12).ema_indicator()
        ema26 = EMAIndicator(close, window=26).ema_indicator()
        e12, e26 = ema12.iloc[-1], ema26.iloc[-1]
        if not (pd.isna(e12) or pd.isna(e26)):
            diff = (e12 - e26) / e26 * 100
            if diff > 1:
                score, sig = 0.4, "bullish"
            elif diff < -1:
                score, sig = -0.4, "bearish"
            else:
                score, sig = 0.0, "neutral"
            signals.append(IndicatorSignal(
                "EMA12/26", round(diff, 2), sig, score,
                f"EMA12 {'above' if diff > 0 else 'below'} EMA26 by {abs(diff):.1f}%"
            ))

    # --- RSI (14) ---
    rsi = RSIIndicator(close, window=14).rsi()
    rsi_val = rsi.iloc[-1]
    if not pd.isna(rsi_val):
        if rsi_val < 30:
            score, sig = 0.7, "bullish"
            detail = f"RSI {rsi_val:.1f} - OVERSOLD (buy signal)"
        elif rsi_val > 70:
            score, sig = -0.7, "bearish"
            detail = f"RSI {rsi_val:.1f} - OVERBOUGHT (sell signal)"
        elif rsi_val < 40:
            score, sig = 0.3, "bullish"
            detail = f"RSI {rsi_val:.1f} - approaching oversold"
        elif rsi_val > 60:
            score, sig = -0.3, "bearish"
            detail = f"RSI {rsi_val:.1f} - approaching overbought"
        else:
            score, sig = 0.0, "neutral"
            detail = f"RSI {rsi_val:.1f} - neutral zone"
        signals.append(IndicatorSignal("RSI", round(rsi_val, 2), sig, score, detail))

    # --- MACD ---
    if len(df) >= 35:
        macd_ind = MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_line = macd_ind.macd().iloc[-1]
        signal_line = macd_ind.macd_signal().iloc[-1]
        macd_hist = macd_ind.macd_diff().iloc[-1]
        macd_hist_prev = macd_ind.macd_diff().iloc[-2]
        if not (pd.isna(macd_line) or pd.isna(signal_line)):
            if macd_hist > 0 and macd_hist_prev <= 0:
                score, sig = 0.6, "bullish"
                detail = "MACD crossed above signal line (bullish crossover)"
            elif macd_hist < 0 and macd_hist_prev >= 0:
                score, sig = -0.6, "bearish"
                detail = "MACD crossed below signal line (bearish crossover)"
            elif macd_hist > 0:
                score, sig = 0.3, "bullish"
                detail = f"MACD above signal line (histogram: {macd_hist:.2f})"
            elif macd_hist < 0:
                score, sig = -0.3, "bearish"
                detail = f"MACD below signal line (histogram: {macd_hist:.2f})"
            else:
                score, sig = 0.0, "neutral"
                detail = "MACD at signal line"
            signals.append(IndicatorSignal("MACD", round(macd_hist, 2), sig, score, detail))

    # --- Bollinger Bands ---
    if len(df) >= 20:
        bb = BollingerBands(close, window=20, window_dev=2)
        bb_high = bb.bollinger_hband().iloc[-1]
        bb_low = bb.bollinger_lband().iloc[-1]
        bb_mid = bb.bollinger_mavg().iloc[-1]
        if not (pd.isna(bb_high) or pd.isna(bb_low)):
            bb_width = bb_high - bb_low
            if bb_width > 0:
                position = (current_price - bb_low) / bb_width
                if position > 0.95:
                    score, sig = -0.5, "bearish"
                    detail = f"Price near upper Bollinger Band ({position:.0%})"
                elif position < 0.05:
                    score, sig = 0.5, "bullish"
                    detail = f"Price near lower Bollinger Band ({position:.0%})"
                else:
                    score, sig = 0.0, "neutral"
                    detail = f"Price at {position:.0%} of Bollinger range"
                signals.append(IndicatorSignal("Bollinger", round(position, 2), sig, score, detail))

    # --- Volume Analysis ---
    if len(df) >= 20:
        avg_vol = volume.rolling(window=20).mean().iloc[-1]
        curr_vol = volume.iloc[-1]
        if not pd.isna(avg_vol) and avg_vol > 0:
            vol_ratio = curr_vol / avg_vol
            price_change = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
            if vol_ratio > 1.5 and price_change > 0:
                score, sig = 0.4, "bullish"
                detail = f"High volume ({vol_ratio:.1f}x avg) with price rise"
            elif vol_ratio > 1.5 and price_change < 0:
                score, sig = -0.4, "bearish"
                detail = f"High volume ({vol_ratio:.1f}x avg) with price drop"
            else:
                score, sig = 0.0, "neutral"
                detail = f"Volume {vol_ratio:.1f}x average"
            signals.append(IndicatorSignal("Volume", round(vol_ratio, 2), sig, score, detail))

    # --- 52-Week High/Low ---
    if len(df) >= 252:
        year_data = df.tail(252)
        high_52w = year_data["high"].max()
        low_52w = year_data["low"].min()
        range_52w = high_52w - low_52w
        if range_52w > 0:
            position = (current_price - low_52w) / range_52w
            if position > 0.95:
                score, sig = 0.3, "bullish"
                detail = f"Near 52-week high ({current_price:.2f} vs {high_52w:.2f})"
            elif position < 0.05:
                score, sig = -0.3, "bearish"
                detail = f"Near 52-week low ({current_price:.2f} vs {low_52w:.2f})"
            else:
                score, sig = 0.0, "neutral"
                detail = f"At {position:.0%} of 52-week range ({low_52w:.2f} - {high_52w:.2f})"
            signals.append(IndicatorSignal("52WeekRange", round(position, 2), sig, score, detail))

    # --- ATR(14) — used downstream for stop/target zones, not scored here ---
    atr_value: float | None = None
    if len(df) >= 15:
        try:
            atr = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
            v = atr.iloc[-1]
            if not pd.isna(v):
                atr_value = float(v)
        except Exception:
            atr_value = None

    # --- Overall Score ---
    if signals:
        overall = sum(s.score for s in signals) / len(signals)
    else:
        overall = 0.0

    return TechnicalSignals(
        indicators=signals,
        overall_score=round(overall, 4),
        atr_value=atr_value,
    )
