from dataclasses import dataclass, field

import httpx


@dataclass
class FundamentalMetric:
    name: str
    value: str
    signal: str  # "positive", "negative", "neutral"
    score: float  # -1.0 to +1.0
    detail: str = ""


@dataclass
class FundamentalSignals:
    metrics: list[FundamentalMetric] = field(default_factory=list)
    overall_score: float = 0.0
    raw_data: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if self.overall_score > 0.15:
            return "POSITIVE"
        elif self.overall_score < -0.15:
            return "NEGATIVE"
        return "NEUTRAL"


def _score_pe_ratio(pe: float, sector_avg_pe: float = 25.0) -> FundamentalMetric:
    if pe <= 0:
        return FundamentalMetric("P/E Ratio", str(pe), "neutral", 0.0, "Negative or zero P/E (loss-making)")
    ratio = pe / sector_avg_pe
    if ratio < 0.7:
        return FundamentalMetric("P/E Ratio", f"{pe:.1f}", "positive", 0.6, f"P/E {pe:.1f} significantly below sector avg {sector_avg_pe:.1f}")
    elif ratio < 0.9:
        return FundamentalMetric("P/E Ratio", f"{pe:.1f}", "positive", 0.3, f"P/E {pe:.1f} below sector avg {sector_avg_pe:.1f}")
    elif ratio > 1.5:
        return FundamentalMetric("P/E Ratio", f"{pe:.1f}", "negative", -0.5, f"P/E {pe:.1f} significantly above sector avg {sector_avg_pe:.1f}")
    elif ratio > 1.2:
        return FundamentalMetric("P/E Ratio", f"{pe:.1f}", "negative", -0.3, f"P/E {pe:.1f} above sector avg {sector_avg_pe:.1f}")
    return FundamentalMetric("P/E Ratio", f"{pe:.1f}", "neutral", 0.0, f"P/E {pe:.1f} near sector avg {sector_avg_pe:.1f}")


def _score_debt_to_equity(de: float) -> FundamentalMetric:
    if de < 0.3:
        return FundamentalMetric("Debt/Equity", f"{de:.2f}", "positive", 0.5, f"Low debt (D/E: {de:.2f})")
    elif de < 1.0:
        return FundamentalMetric("Debt/Equity", f"{de:.2f}", "positive", 0.2, f"Manageable debt (D/E: {de:.2f})")
    elif de < 2.0:
        return FundamentalMetric("Debt/Equity", f"{de:.2f}", "negative", -0.3, f"High debt (D/E: {de:.2f})")
    return FundamentalMetric("Debt/Equity", f"{de:.2f}", "negative", -0.6, f"Very high debt (D/E: {de:.2f})")


def _score_roe(roe: float) -> FundamentalMetric:
    if roe > 20:
        return FundamentalMetric("ROE", f"{roe:.1f}%", "positive", 0.6, f"Excellent ROE ({roe:.1f}%)")
    elif roe > 15:
        return FundamentalMetric("ROE", f"{roe:.1f}%", "positive", 0.3, f"Good ROE ({roe:.1f}%)")
    elif roe > 10:
        return FundamentalMetric("ROE", f"{roe:.1f}%", "neutral", 0.0, f"Average ROE ({roe:.1f}%)")
    return FundamentalMetric("ROE", f"{roe:.1f}%", "negative", -0.3, f"Low ROE ({roe:.1f}%)")


def _score_eps_growth(growth: float) -> FundamentalMetric:
    if growth > 20:
        return FundamentalMetric("EPS Growth", f"{growth:+.1f}%", "positive", 0.7, f"Strong EPS growth ({growth:+.1f}%)")
    elif growth > 10:
        return FundamentalMetric("EPS Growth", f"{growth:+.1f}%", "positive", 0.4, f"Good EPS growth ({growth:+.1f}%)")
    elif growth > 0:
        return FundamentalMetric("EPS Growth", f"{growth:+.1f}%", "positive", 0.1, f"Moderate EPS growth ({growth:+.1f}%)")
    elif growth > -10:
        return FundamentalMetric("EPS Growth", f"{growth:+.1f}%", "negative", -0.3, f"Slight EPS decline ({growth:+.1f}%)")
    return FundamentalMetric("EPS Growth", f"{growth:+.1f}%", "negative", -0.6, f"Significant EPS decline ({growth:+.1f}%)")


def _score_promoter_holding(holding_pct: float, change_pct: float) -> FundamentalMetric:
    if change_pct > 1:
        return FundamentalMetric("Promoter Holding", f"{holding_pct:.1f}% ({change_pct:+.1f}%)", "positive", 0.5, f"Promoter holding increased to {holding_pct:.1f}%")
    elif change_pct < -2:
        return FundamentalMetric("Promoter Holding", f"{holding_pct:.1f}% ({change_pct:+.1f}%)", "negative", -0.5, f"Promoter holding decreased to {holding_pct:.1f}%")
    elif holding_pct > 60:
        return FundamentalMetric("Promoter Holding", f"{holding_pct:.1f}%", "positive", 0.2, f"High promoter holding ({holding_pct:.1f}%)")
    return FundamentalMetric("Promoter Holding", f"{holding_pct:.1f}%", "neutral", 0.0, f"Stable promoter holding ({holding_pct:.1f}%)")


def analyze_from_data(data: dict) -> FundamentalSignals:
    """Analyze fundamental data from a pre-fetched dictionary.

    Expected keys (all optional):
        pe_ratio, sector_avg_pe, debt_to_equity, roe, eps_growth,
        promoter_holding, promoter_holding_change, revenue_growth
    """
    metrics: list[FundamentalMetric] = []

    if "pe_ratio" in data:
        sector_pe = data.get("sector_avg_pe", 25.0)
        metrics.append(_score_pe_ratio(data["pe_ratio"], sector_pe))

    if "debt_to_equity" in data:
        metrics.append(_score_debt_to_equity(data["debt_to_equity"]))

    if "roe" in data:
        metrics.append(_score_roe(data["roe"]))

    if "eps_growth" in data:
        metrics.append(_score_eps_growth(data["eps_growth"]))

    if "promoter_holding" in data:
        change = data.get("promoter_holding_change", 0.0)
        metrics.append(_score_promoter_holding(data["promoter_holding"], change))

    if "revenue_growth" in data:
        rg = data["revenue_growth"]
        if rg > 15:
            metrics.append(FundamentalMetric("Revenue Growth", f"{rg:+.1f}%", "positive", 0.4, f"Strong revenue growth ({rg:+.1f}%)"))
        elif rg > 5:
            metrics.append(FundamentalMetric("Revenue Growth", f"{rg:+.1f}%", "positive", 0.2, f"Moderate revenue growth ({rg:+.1f}%)"))
        elif rg > -5:
            metrics.append(FundamentalMetric("Revenue Growth", f"{rg:+.1f}%", "neutral", 0.0, f"Flat revenue ({rg:+.1f}%)"))
        else:
            metrics.append(FundamentalMetric("Revenue Growth", f"{rg:+.1f}%", "negative", -0.4, f"Revenue decline ({rg:+.1f}%)"))

    overall = sum(m.score for m in metrics) / len(metrics) if metrics else 0.0

    return FundamentalSignals(
        metrics=metrics,
        overall_score=round(overall, 4),
        raw_data=data,
    )
