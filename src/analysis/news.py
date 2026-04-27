from dataclasses import dataclass, field

from src.client.models import NewsItem


@dataclass
class NewsSignals:
    items: list[NewsItem] = field(default_factory=list)
    overall_score: float = 0.0

    @property
    def summary(self) -> str:
        if self.overall_score > 0.15:
            return "POSITIVE"
        elif self.overall_score < -0.15:
            return "NEGATIVE"
        return "MIXED"


POSITIVE_KEYWORDS = [
    "upgrade", "buy", "outperform", "beat", "profit", "growth", "record",
    "surge", "rally", "breakout", "strong", "bullish", "dividend", "bonus",
    "expansion", "approval", "partnership", "acquisition", "target raised",
    "overweight", "accumulate", "positive", "upside", "wins", "won", "order",
    "contract", "launch", "expand",
]

NEGATIVE_KEYWORDS = [
    "downgrade", "sell", "underperform", "miss", "loss", "decline", "cut",
    "crash", "fall", "drop", "weak", "bearish", "debt", "default", "fraud",
    "investigation", "downside", "underweight", "reduce", "negative",
    "warning", "risk", "concern", "trouble", "slump", "probe", "raid",
    "scam",
]


def score_headline(headline: str) -> tuple[str, float]:
    headline_lower = headline.lower()
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in headline_lower)
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in headline_lower)

    if pos_count > neg_count:
        score = min(0.3 + 0.2 * (pos_count - neg_count), 1.0)
        return "positive", score
    elif neg_count > pos_count:
        score = max(-0.3 - 0.2 * (neg_count - pos_count), -1.0)
        return "negative", score
    return "neutral", 0.0


def analyze_from_items(items: list[dict]) -> NewsSignals:
    """Analyze news from a list of headline dicts.

    Each dict should have at least: headline, and optionally source, url,
    published_at.
    """
    news_items: list[NewsItem] = []
    for item in items:
        headline = item.get("headline", "")
        if not headline:
            continue
        sentiment, score = score_headline(headline)
        news_items.append(NewsItem(
            headline=headline,
            source=item.get("source", ""),
            url=item.get("url", ""),
            sentiment=sentiment,
            score=score,
            published_at=item.get("published_at"),
        ))

    overall = sum(n.score for n in news_items) / len(news_items) if news_items else 0.0

    return NewsSignals(items=news_items, overall_score=round(overall, 4))
