from src.analysis.fundamental import FundamentalSignals, analyze_from_data
from src.analysis.news import NewsSignals
from src.analysis.technical import TechnicalSignals
from src.client.models import (
    ForecastBand,
    MonteCarloBand,
    Recommendation,
    TargetEntry,
)


WEIGHTS = {
    "technical": 0.40,
    "fundamental": 0.35,
    "news": 0.15,
    "volume": 0.10,
}


def _action_from_score(score: float) -> str:
    if score > 0.4:
        return "STRONG BUY"
    elif score > 0.15:
        return "BUY"
    elif score > -0.15:
        return "HOLD"
    elif score > -0.4:
        return "SELL"
    return "STRONG SELL"


def _collect_reasons(
    technical: TechnicalSignals,
    fundamental: FundamentalSignals,
    news: NewsSignals,
    fundamentals_payload: dict | None,
) -> list[str]:
    reasons: list[str] = []

    # If news has a strongly-leaning headline, lead with it.
    if news.items:
        leader = max(news.items, key=lambda n: abs(n.score))
        if abs(leader.score) >= 0.3:
            tone = "bullish" if leader.score > 0 else "bearish"
            src = f" ({leader.source})" if leader.source else ""
            reasons.append(f"News {tone}: \"{leader.headline}\"{src}")

    # Analyst-consensus headline reason
    if fundamentals_payload:
        rec = fundamentals_payload.get("analyst_recommendation")
        n_analyst = fundamentals_payload.get("analyst_count")
        target = fundamentals_payload.get("target_consensus")
        if rec and n_analyst and target:
            reasons.append(
                f"Analyst consensus: {rec.replace('_', ' ').upper()} "
                f"from {n_analyst} analysts, target ₹{target:,.0f}"
            )

    # Top technical signals (strongest absolute scores)
    sorted_tech = sorted(technical.indicators, key=lambda x: abs(x.score), reverse=True)
    for ind in sorted_tech[:3]:
        if abs(ind.score) > 0.1:
            reasons.append(ind.detail)

    # Top fundamental signals
    sorted_fund = sorted(fundamental.metrics, key=lambda x: abs(x.score), reverse=True)
    for m in sorted_fund[:3]:
        if abs(m.score) > 0.1:
            reasons.append(m.detail)

    # Promoter holding moves are a strong "what insiders are doing" signal
    fp = fundamentals_payload or {}
    screener = (fp.get("raw_per_source") or {}).get("screener") or {}
    promoter = screener.get("promoter") or {}
    qoq = promoter.get("change_qoq")
    if isinstance(qoq, (int, float)):
        if qoq >= 0.5:
            reasons.append(f"Promoters increased holding {qoq:+.1f} pp QoQ to {promoter.get('latest', 0):.1f}% — bullish insider signal")
        elif qoq <= -0.5:
            reasons.append(f"Promoters reduced holding {qoq:+.1f} pp QoQ to {promoter.get('latest', 0):.1f}% — caution")

    # Operating margin trend
    opm_q = screener.get("opm_quarterly") or []
    if len(opm_q) >= 4:
        recent = opm_q[-1]
        prior = opm_q[-4]
        delta = recent - prior
        if abs(delta) >= 1.0:
            tone = "expanding" if delta > 0 else "contracting"
            reasons.append(f"Operating margin {tone}: {prior:.0f}% → {recent:.0f}% over last 4 quarters")

    # News sentiment summary
    if news.items:
        pos = sum(1 for n in news.items if n.sentiment == "positive")
        neg = sum(1 for n in news.items if n.sentiment == "negative")
        if pos > neg:
            reasons.append(f"News sentiment positive ({pos} positive vs {neg} negative headlines)")
        elif neg > pos:
            reasons.append(f"News sentiment negative ({neg} negative vs {pos} positive headlines)")
        else:
            reasons.append(f"News sentiment mixed ({pos} positive, {neg} negative headlines)")

    return reasons


def _extract_volume_score(technical: TechnicalSignals) -> float:
    for ind in technical.indicators:
        if ind.name == "Volume":
            return ind.score
    return 0.0


def _collect_risks(
    current_price: float,
    technical: TechnicalSignals,
    fundamentals_payload: dict | None,
    news,
    forecast_12m: dict | None,
) -> list[str]:
    """Honest list of "what could go wrong" — synthesized from existing data."""
    risks: list[str] = []
    fp = fundamentals_payload or {}

    # Most-bearish news headline
    if news.items:
        worst = min(news.items, key=lambda n: n.score)
        if worst.score <= -0.3:
            src = f" ({worst.source})" if worst.source else ""
            risks.append(f"Bearish headline: \"{worst.headline}\"{src}")

    # 12-month downside scenario
    if forecast_12m and forecast_12m.get("p5") is not None and current_price > 0:
        p5 = forecast_12m["p5"]
        downside_pct = (p5 - current_price) / current_price * 100
        if downside_pct < -10:
            risks.append(
                f"Worst-case 12m: ₹{p5:,.0f} ({downside_pct:+.0f}%) — 5th-percentile Monte Carlo outcome"
            )

    # Analyst low target as a downside reference
    target_low = fp.get("target_low")
    if target_low and target_low < current_price * 0.95:
        downside_pct = (target_low - current_price) / current_price * 100
        risks.append(
            f"Lowest analyst target: ₹{target_low:,.0f} ({downside_pct:+.0f}%) — bear-case from analyst dispersion"
        )

    # Fundamental red flags
    ratios = fp.get("ratios") or {}
    pe = ratios.get("pe_ratio")
    de = ratios.get("debt_to_equity")
    roe = ratios.get("roe")
    rev_g = ratios.get("revenue_growth")

    if isinstance(pe, (int, float)) and pe > 50:
        risks.append(f"Stretched valuation: P/E {pe:.1f} (well above sector avg ~25); little room for disappointment")
    if isinstance(de, (int, float)) and de > 2.0:
        risks.append(f"High leverage: Debt/Equity {de:.2f} (>2 typically risky in a downturn)")
    if isinstance(roe, (int, float)) and roe < 5:
        risks.append(f"Low profitability: ROE {roe:.1f}% (below cost of capital ~10%)")
    if isinstance(rev_g, (int, float)) and rev_g < -5:
        risks.append(f"Revenue contraction: {rev_g:+.1f}% YoY")

    # Volatility / momentum risks
    atr = technical.atr_value
    if atr and current_price > 0:
        atr_pct = (atr / current_price) * 100
        if atr_pct > 5:
            risks.append(f"High intraday volatility: ATR ~{atr_pct:.1f}% of price (single bad day could swing position)")

    # Overbought / near-high warnings
    for ind in technical.indicators:
        if ind.name == "RSI" and ind.value > 75:
            risks.append(f"RSI {ind.value:.0f} — overbought; mean-reversion pullback common from these levels")
        if ind.name == "52WeekRange" and ind.value > 0.95:
            risks.append("Trading near 52-week high — limited room to grow before profit-taking")

    return risks


def _build_trade_plan(
    current_price: float,
    technical: TechnicalSignals,
    fundamentals_payload: dict | None,
) -> dict:
    """Compute buy_upto, target_price_consensus, stop_loss using ATR + analyst targets.

    All fields can be None when inputs are missing.
    """
    atr = technical.atr_value
    fp = fundamentals_payload or {}
    target_consensus = fp.get("target_consensus")
    target_high = fp.get("target_high")
    target_low = fp.get("target_low")
    week_low = fp.get("fifty_two_week_low")

    # buy_upto: don't pay more than 8% below the analyst consensus AND no more
    # than 5% above current price.
    if target_consensus and target_consensus > current_price:
        buy_upto = min(target_consensus * 0.92, current_price * 1.05)
    elif current_price > 0:
        buy_upto = current_price * 1.02  # neutral: don't chase, slim margin
    else:
        buy_upto = None

    # stop_loss: 2× ATR below current; clamped to never go deeper than 5% above
    # 52-week low (so we don't suggest exiting at all-time-low territory).
    stop_candidates: list[float] = []
    if atr and current_price:
        stop_candidates.append(current_price - 2 * atr)
    if week_low:
        stop_candidates.append(week_low * 1.05)
    stop_loss = max(stop_candidates) if stop_candidates else None
    if stop_loss is not None and stop_loss <= 0:
        stop_loss = None

    return {
        "buy_upto": round(buy_upto, 2) if buy_upto else None,
        "target_price_consensus": round(target_consensus, 2) if target_consensus else None,
        "target_high": round(target_high, 2) if target_high else None,
        "target_low": round(target_low, 2) if target_low else None,
        "stop_loss": round(stop_loss, 2) if stop_loss else None,
    }


def _fundamentals_signals(fundamentals_payload: dict | None) -> FundamentalSignals:
    """Score the cross-source fundamentals into a FundamentalSignals object."""
    if not fundamentals_payload:
        return FundamentalSignals()
    ratios = fundamentals_payload.get("ratios") or {}
    payload = {k: v for k, v in ratios.items() if v is not None}
    if not payload:
        return FundamentalSignals()
    try:
        return analyze_from_data(payload)
    except Exception:
        return FundamentalSignals()


def score_stock(
    symbol: str,
    current_price: float,
    technical: TechnicalSignals,
    fundamental: FundamentalSignals | None,
    news: NewsSignals,
    fundamentals_payload: dict | None = None,
    forecast_30d: dict | None = None,
    forecast_12m: dict | None = None,
    smart_money: dict | None = None,
    historical: dict | None = None,
) -> Recommendation:
    if fundamental is None or len(fundamental.metrics) == 0:
        # Build a fundamental signal from the cross-source payload if available.
        fundamental = _fundamentals_signals(fundamentals_payload)

    tech_score = technical.overall_score
    fund_score = fundamental.overall_score
    news_score = news.overall_score
    vol_score = _extract_volume_score(technical)

    has_fundamental = len(fundamental.metrics) > 0
    if has_fundamental:
        w_tech = WEIGHTS["technical"]
        w_fund = WEIGHTS["fundamental"]
    else:
        w_tech = WEIGHTS["technical"] + WEIGHTS["fundamental"] * 0.7
        w_fund = 0.0

    has_news = len(news.items) > 0
    if has_news:
        w_news = WEIGHTS["news"]
    else:
        w_news = 0.0
        w_tech += WEIGHTS["news"] * 0.5

    w_vol = WEIGHTS["volume"]

    total_w = w_tech + w_fund + w_news + w_vol
    if total_w > 0:
        final_score = (
            w_tech * tech_score
            + w_fund * fund_score
            + w_news * news_score
            + w_vol * vol_score
        ) / total_w
    else:
        final_score = 0.0

    final_score = max(-1.0, min(1.0, final_score))
    action = _action_from_score(final_score)
    confidence = round(abs(final_score) * 100, 1)
    reasons = _collect_reasons(technical, fundamental, news, fundamentals_payload)
    headline_reason = reasons[0] if reasons else "Insufficient signal — flat trend, no fresh news."

    plan = _build_trade_plan(current_price, technical, fundamentals_payload)
    fp = fundamentals_payload or {}
    sm = smart_money or {}
    hm = historical or {}
    risks = _collect_risks(current_price, technical, fundamentals_payload, news, forecast_12m)

    # Smart-money signals → reasons + risks
    bulk_30d = sm.get("bulk_deals_30d") or []
    smart_buys = [d for d in bulk_30d if d.get("smart_money_tag") and d.get("side") == "BUY"]
    smart_sells = [d for d in bulk_30d if d.get("smart_money_tag") and d.get("side") == "SELL"]
    if smart_buys:
        top = max(smart_buys, key=lambda d: d.get("value") or 0)
        reasons.append(
            f"Institutional buying: {top['smart_money_tag']} bought "
            f"{(top.get('qty') or 0):,} shares (₹{(top.get('value') or 0)/1e7:.1f} Cr) on {top.get('date')}"
        )
    if smart_sells:
        top = max(smart_sells, key=lambda d: d.get("value") or 0)
        risks.append(
            f"Institutional selling: {top['smart_money_tag']} sold "
            f"₹{(top.get('value') or 0)/1e7:.1f} Cr on {top.get('date')}"
        )

    insider_buys = [t for t in (sm.get("insider_trades_30d") or []) if (t.get("side") or "").upper().startswith("BUY")]
    insider_sells = [t for t in (sm.get("insider_trades_30d") or []) if (t.get("side") or "").upper().startswith("SELL")]
    if insider_buys:
        reasons.append(f"Insiders bought {len(insider_buys)} times in last 30 days — bullish signal")
    if insider_sells:
        risks.append(f"Insiders sold {len(insider_sells)} times in last 30 days")

    upcoming = sm.get("events", {}).get("upcoming") if isinstance(sm.get("events"), dict) else (sm.get("upcoming_events") or [])
    if upcoming:
        nxt = upcoming[0]
        reasons.append(f"Upcoming event: {nxt.get('purpose', 'corporate action')}")

    # Historical-metrics signals
    sharpe = hm.get("sharpe_1y")
    mdd = hm.get("max_drawdown_1y")
    one_y = hm.get("one_year_return")
    if isinstance(sharpe, (int, float)) and sharpe > 1.0:
        reasons.append(f"Strong risk-adjusted return: 1Y Sharpe {sharpe:.2f}")
    elif isinstance(sharpe, (int, float)) and sharpe < 0:
        risks.append(f"Negative risk-adjusted return: 1Y Sharpe {sharpe:.2f}")
    if isinstance(mdd, (int, float)) and mdd <= -25:
        risks.append(f"Severe 1Y drawdown: {mdd:.0f}% from peak")
    if isinstance(one_y, (int, float)) and one_y >= 30:
        reasons.append(f"1Y price return {one_y:+.0f}% — strong momentum")
    elif isinstance(one_y, (int, float)) and one_y <= -20:
        risks.append(f"1Y price return {one_y:+.0f}% — sustained underperformance")
    yf_raw = (fp.get("raw_per_source") or {}).get("yfinance") or {}
    sc_payload = (fp.get("raw_per_source") or {}).get("screener") or {}
    promoter_block = sc_payload.get("promoter") or {}
    opm_quarterly = sc_payload.get("opm_quarterly") or []
    opm_annual = sc_payload.get("opm_annual") or []
    sales_growth_block = sc_payload.get("sales_growth") or {}
    profit_growth_block = sc_payload.get("profit_growth") or {}

    # Append promoter-exit risk if QoQ promoter selling is meaningful
    if isinstance(promoter_block.get("change_qoq"), (int, float)) and promoter_block["change_qoq"] <= -1.0:
        risks.append(
            f"Promoters cut holding {promoter_block['change_qoq']:+.1f} pp QoQ — insider selling can pressure price"
        )
    # Append margin-compression risk
    if len(opm_quarterly) >= 4 and (opm_quarterly[-1] - opm_quarterly[-4]) <= -2:
        risks.append(
            f"Operating margin compressed {opm_quarterly[-4]:.0f}% → {opm_quarterly[-1]:.0f}% over last 4 quarters"
        )

    target_entries = [
        TargetEntry(
            source=t.get("source", "unknown"),
            target=float(t.get("target")),
            recommendation=t.get("recommendation"),
            as_of=t.get("as_of"),
        )
        for t in fp.get("target_prices", [])
        if isinstance(t.get("target"), (int, float))
    ]

    fb_30d = ForecastBand(**forecast_30d) if forecast_30d else None
    mc_12m = MonteCarloBand(**forecast_12m) if forecast_12m else None

    return Recommendation(
        tradingsymbol=symbol,
        action=action,
        score=round(final_score, 4),
        confidence=confidence,
        current_price=current_price,
        headline_reason=headline_reason,
        reasons=reasons,
        technical_score=round(tech_score, 4),
        fundamental_score=round(fund_score, 4),
        news_score=round(news_score, 4),
        news_items=list(news.items),
        # Fundamentals
        pe_ratio=fp.get("ratios", {}).get("pe_ratio"),
        debt_to_equity=fp.get("ratios", {}).get("debt_to_equity"),
        roe=fp.get("ratios", {}).get("roe"),
        revenue_growth=fp.get("ratios", {}).get("revenue_growth"),
        market_cap=fp.get("market_cap"),
        dividend_yield=fp.get("dividend_yield"),
        fifty_two_week_high=fp.get("fifty_two_week_high"),
        fifty_two_week_low=fp.get("fifty_two_week_low"),
        # Trade plan
        atr=technical.atr_value,
        buy_upto=plan["buy_upto"],
        target_price_consensus=plan["target_price_consensus"],
        target_high=plan["target_high"],
        target_low=plan["target_low"],
        target_confidence=fp.get("target_confidence", "unknown"),
        target_price_sources=target_entries,
        stop_loss=plan["stop_loss"],
        # Analyst consensus
        analyst_count=fp.get("analyst_count"),
        analyst_recommendation=fp.get("analyst_recommendation"),
        # Forecasts
        forecast_30d=fb_30d,
        forecast_12m=mc_12m,
        fundamental_sources=fp.get("fundamental_sources", []),
        risks=risks,
        sector=yf_raw.get("sector"),
        industry=yf_raw.get("industry"),
        promoter_holding=promoter_block.get("latest"),
        promoter_holding_change_qoq=promoter_block.get("change_qoq"),
        promoter_holding_change_yoy=promoter_block.get("change_yoy"),
        promoter_holding_history=promoter_block.get("history") or [],
        operating_margin_latest=opm_quarterly[-1] if opm_quarterly else (opm_annual[-1] if opm_annual else None),
        operating_margin_history=opm_annual or [],
        sales_cagr_5y=(sales_growth_block.get("5 Years") if isinstance(sales_growth_block, dict) else None),
        profit_cagr_5y=(profit_growth_block.get("5 Years") if isinstance(profit_growth_block, dict) else None),
        bulk_deals_30d=bulk_30d,
        insider_trades_30d=sm.get("insider_trades_30d", []),
        corporate_actions=(sm.get("events", {}) or {}).get("corporate_actions", []),
        recent_results=(sm.get("events", {}) or {}).get("recent_results", []),
        upcoming_events=(sm.get("events", {}) or {}).get("upcoming", []),
        smart_money_sources=sm.get("sources_used", []),
        one_year_return=hm.get("one_year_return"),
        three_year_return=hm.get("three_year_return"),
        five_year_return=hm.get("five_year_return"),
        annualized_volatility=hm.get("annualized_volatility"),
        max_drawdown_1y=hm.get("max_drawdown_1y"),
        sharpe_1y=hm.get("sharpe_1y"),
        beta_vs_nifty=hm.get("beta_vs_nifty"),
    )
