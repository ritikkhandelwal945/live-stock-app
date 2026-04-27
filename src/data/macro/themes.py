"""Rule-based macro-event theme detection.

Maps news headlines → high-level themes (war / trade deal / RBI / oil / etc.)
and themes → impacted Indian-market sectors. Pure data + pure compute, no
network calls; consumes the article list produced by ``news_sources``.
"""

from __future__ import annotations

import math
import re

# Curated themes. Sectors are matched loosely (substring, case-insensitive)
# against yfinance's `sector` and `industry` strings.
THEMES: dict[str, dict] = {
    "middle_east_conflict": {
        "label": "Middle East conflict",
        "emoji": "🛡️",
        "keywords": [
            "iran", "israel", "gaza", "houthi", "tehran", "middle east",
            "strike on", "drone attack", "hezbollah", "syria", "yemen",
        ],
        "sectors_positive": [
            "Aerospace & Defense", "Defense", "Defence",
            "Oil & Gas E&P", "Oil & Gas Refining", "Energy",
        ],
        "sectors_negative": [
            "Airlines", "Travel Services", "Hotels", "Information Technology Services",
        ],
    },
    "war_general": {
        "label": "Geopolitical conflict",
        "emoji": "⚔️",
        "keywords": [
            "war", "ceasefire", "military strike", "armed conflict",
            "border tension", "missile",
        ],
        "sectors_positive": ["Aerospace & Defense", "Defense", "Defence"],
        "sectors_negative": ["Airlines", "Travel Services"],
    },
    "trade_deal_india": {
        "label": "Trade deal / tariffs",
        "emoji": "🤝",
        "keywords": [
            "trade deal", "fta", "free trade agreement", "tariff", "mou signed",
            "bilateral pact", "india-nz", "india-eu", "india-uk", "india-us trade",
            "india australia trade", "trade pact",
        ],
        "sectors_positive": [
            "Packaged Foods", "Apparel", "Textile", "Auto Parts",
            "Specialty Chemicals", "Agricultural", "Dairy",
        ],
        "sectors_negative": [],
    },
    "rbi_policy": {
        "label": "RBI monetary policy",
        "emoji": "🏦",
        "keywords": [
            "rbi", "repo rate", "monetary policy", "rate cut", "rate hike",
            "mpc", "shaktikanta", "reserve bank", "lending rate",
        ],
        "sectors_positive": [
            "Banks", "Bank", "Real Estate", "Capital Markets",
            "Insurance", "NBFC", "Asset Management",
        ],
        "sectors_negative": [],
    },
    "oil_shock_up": {
        "label": "Oil price spike",
        "emoji": "🛢️",
        "keywords": [
            "crude rises", "oil surges", "opec", "brent climbs",
            "oil rally", "oil price jump", "crude jumps",
        ],
        "sectors_positive": ["Oil & Gas E&P", "Energy"],
        "sectors_negative": [
            "Airlines", "Refineries", "Travel Services", "Auto",
            "Paint", "Specialty Chemicals",
        ],
    },
    "oil_shock_down": {
        "label": "Oil price drop",
        "emoji": "🛢️",
        "keywords": [
            "crude falls", "oil plunges", "oil tumbles", "brent slumps",
        ],
        "sectors_positive": [
            "Refineries", "Refining", "Airlines", "Auto", "Paint",
            "Specialty Chemicals",
        ],
        "sectors_negative": ["Oil & Gas E&P"],
    },
    "rupee_weakness": {
        "label": "Rupee depreciation",
        "emoji": "💱",
        "keywords": [
            "rupee falls", "rupee weak", "rupee hits low", "rupee record low",
            "usd/inr", "currency depreciation", "rupee slips",
        ],
        "sectors_positive": [
            "Information Technology Services", "Drug Manufacturers",
            "Pharmaceuticals",
        ],
        "sectors_negative": ["Airlines", "Capital Goods", "Oil & Gas Refining"],
    },
    "rupee_strength": {
        "label": "Rupee strength",
        "emoji": "💱",
        "keywords": [
            "rupee strengthens", "rupee gains", "rupee rises against dollar",
        ],
        "sectors_positive": ["Airlines", "Capital Goods"],
        "sectors_negative": ["Information Technology Services", "Pharmaceuticals"],
    },
    "fii_inflow": {
        "label": "FII inflows",
        "emoji": "📈",
        "keywords": [
            "fii inflow", "foreign inflow", "fpi inflow", "foreign investors buy",
            "fii buying", "foreign portfolio investors",
        ],
        "sectors_positive": [
            "Banks", "Information Technology Services", "Capital Markets",
        ],
        "sectors_negative": [],
    },
    "fii_outflow": {
        "label": "FII outflows",
        "emoji": "📉",
        "keywords": [
            "fii outflow", "fii selling", "foreign investors sell",
            "fpi outflow", "fii pulled out", "foreign sell",
        ],
        "sectors_positive": [],
        "sectors_negative": [
            "Banks", "Information Technology Services", "Capital Markets",
        ],
    },
    "defence_orders": {
        "label": "Defence order pipeline",
        "emoji": "🚀",
        "keywords": [
            "defence order", "moc clears defence", "defense contract",
            "defence procurement", "indigenous defence", "acquisitions council",
            "defence deal", "defense purchase",
        ],
        "sectors_positive": ["Aerospace & Defense", "Defense", "Defence"],
        "sectors_negative": [],
    },
    "el_nino_monsoon": {
        "label": "Monsoon / weather",
        "emoji": "🌧️",
        "keywords": [
            "monsoon", "el nino", "la nina", "rainfall deficit", "imd forecast",
            "kharif", "rabi", "drought",
        ],
        "sectors_positive": [
            "Fertilizers", "Tractor", "Agricultural", "Consumer Defensive",
        ],
        "sectors_negative": [],
    },
    "ev_push": {
        "label": "EV / clean energy push",
        "emoji": "🔋",
        "keywords": [
            "ev policy", "electric vehicle", "fame", "battery storage",
            "solar capacity", "renewable energy", "green hydrogen",
        ],
        "sectors_positive": [
            "Auto", "Auto Manufacturers", "Electrical", "Renewable",
            "Power", "Utilities",
        ],
        "sectors_negative": [],
    },
    "infra_spending": {
        "label": "Infrastructure / capex",
        "emoji": "🏗️",
        "keywords": [
            "infrastructure spending", "capex push", "highway project",
            "metro project", "national infrastructure", "gati shakti",
        ],
        "sectors_positive": [
            "Engineering & Construction", "Cement", "Capital Goods",
            "Industrials", "Steel",
        ],
        "sectors_negative": [],
    },
}


_MIN_ARTICLES_FOR_ACTIVE = 3
_MAX_SAMPLES_PER_THEME = 5


def _haystack(article: dict) -> str:
    return f"{article.get('headline','')} {article.get('description','')}".lower()


def _matches_theme(article_text: str, keywords: list[str]) -> bool:
    for kw in keywords:
        # Allow multi-word phrases (use substring match) but enforce word
        # boundaries for short tokens to avoid false positives
        # ("rate" matching "operate" etc.)
        if " " in kw or len(kw) > 6:
            if kw in article_text:
                return True
        else:
            if re.search(rf"\b{re.escape(kw)}\b", article_text):
                return True
    return False


def _sector_matches_any(stock_sector: str, theme_sectors: list[str]) -> bool:
    if not stock_sector:
        return False
    s = stock_sector.lower()
    return any(t.lower() in s or s in t.lower() for t in theme_sectors)


def detect_themes(
    articles: list[dict],
    universe_stocks: list[dict] | None = None,
    portfolio_symbols: set[str] | None = None,
) -> list[dict]:
    """Identify active macro themes from a master news index.

    Args:
        articles: list of dicts with at least ``headline`` and ``description``
            (the shape produced by ``src.data.news_sources``).
        universe_stocks: optional list of ``{symbol, sector, industry, name}``
            dicts to compute impacted-stock lists per theme.
        portfolio_symbols: optional set of symbols the user holds — those
            stocks are flagged ``in_portfolio: true`` in the output.

    Returns:
        Sorted list of active themes (highest score first), each with
        matched articles, impacted-positive and impacted-negative stocks,
        and the source label ``"rule_based"``.
    """
    if not articles:
        return []

    portfolio_symbols = set((s or "").upper() for s in (portfolio_symbols or set()))
    universe_stocks = universe_stocks or []

    out: list[dict] = []
    for theme_id, cfg in THEMES.items():
        kws = cfg["keywords"]
        matched: list[dict] = []
        for art in articles:
            text = _haystack(art)
            if _matches_theme(text, kws):
                matched.append(art)
                if len(matched) >= 30:
                    break
        if len(matched) < _MIN_ARTICLES_FOR_ACTIVE:
            continue

        score = round(math.log(len(matched) + 1), 3)

        impacted_positive: list[dict] = []
        impacted_negative: list[dict] = []
        sec_pos = cfg.get("sectors_positive") or []
        sec_neg = cfg.get("sectors_negative") or []
        for s in universe_stocks:
            sector = s.get("sector") or s.get("industry") or ""
            sym = (s.get("symbol") or "").upper()
            entry = {
                "symbol": sym,
                "sector": sector,
                "name": s.get("name"),
                "in_portfolio": sym in portfolio_symbols,
            }
            if sec_pos and _sector_matches_any(sector, sec_pos):
                impacted_positive.append(entry)
            if sec_neg and _sector_matches_any(sector, sec_neg):
                impacted_negative.append(entry)

        # Portfolio holdings first, then alphabetical
        impacted_positive.sort(key=lambda x: (not x["in_portfolio"], x["symbol"]))
        impacted_negative.sort(key=lambda x: (not x["in_portfolio"], x["symbol"]))

        out.append({
            "theme": theme_id,
            "label": cfg["label"],
            "emoji": cfg.get("emoji", ""),
            "source": "rule_based",
            "score": score,
            "article_count": len(matched),
            "matched_articles": [
                {
                    "headline": a.get("headline"),
                    "source": a.get("source"),
                    "url": a.get("url"),
                    "published_at": a.get("published_at"),
                }
                for a in matched[:_MAX_SAMPLES_PER_THEME]
            ],
            "sectors_positive": sec_pos,
            "sectors_negative": sec_neg,
            "impacted_positive": impacted_positive[:25],
            "impacted_negative": impacted_negative[:25],
        })

    out.sort(key=lambda t: -t["score"])
    return out


def theme_alignment_for_stock(sector: str, active_themes: list[dict]) -> list[dict]:
    """Given a stock's sector, return active themes whose positive/negative
    sector lists include it. Each entry: ``{theme, label, emoji, side}`` where
    side is 'positive' or 'negative'."""
    if not sector:
        return []
    out: list[dict] = []
    for t in active_themes:
        sp = t.get("sectors_positive") or []
        sn = t.get("sectors_negative") or []
        if _sector_matches_any(sector, sp):
            out.append({
                "theme": t["theme"],
                "label": t["label"],
                "emoji": t.get("emoji", ""),
                "side": "positive",
                "article_count": t.get("article_count", 0),
            })
        elif _sector_matches_any(sector, sn):
            out.append({
                "theme": t["theme"],
                "label": t["label"],
                "emoji": t.get("emoji", ""),
                "side": "negative",
                "article_count": t.get("article_count", 0),
            })
    return out
