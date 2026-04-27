from datetime import date, datetime
from pydantic import BaseModel


class Holding(BaseModel):
    tradingsymbol: str
    exchange: str = "NSE"
    instrument_token: int = 0
    quantity: int = 0
    average_price: float = 0.0
    last_price: float = 0.0
    pnl: float = 0.0
    day_change_percentage: float = 0.0
    product: str = ""


class Position(BaseModel):
    tradingsymbol: str
    exchange: str = "NSE"
    quantity: int = 0
    buy_price: float = 0.0
    sell_price: float = 0.0
    pnl: float = 0.0
    product: str = ""
    day_buy_quantity: int = 0
    day_sell_quantity: int = 0


class StockQuote(BaseModel):
    tradingsymbol: str
    last_price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    lower_circuit_limit: float = 0.0
    upper_circuit_limit: float = 0.0
    net_change: float = 0.0


class OHLCCandle(BaseModel):
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class NewsItem(BaseModel):
    headline: str
    source: str = ""
    url: str = ""
    sentiment: str = "neutral"  # positive | negative | neutral
    score: float = 0.0  # -1.0 to +1.0
    published_at: str | None = None


class TargetEntry(BaseModel):
    source: str
    target: float
    recommendation: str | None = None
    as_of: str | None = None


class ForecastBand(BaseModel):
    forecast: float | None = None  # ARIMA mean
    low: float | None = None
    high: float | None = None
    horizon_days: int = 30
    model_aic: float | None = None


class MonteCarloBand(BaseModel):
    p5: float | None = None
    p50: float | None = None
    p95: float | None = None
    horizon_days: int = 252
    sample_size: int | None = None


class Recommendation(BaseModel):
    tradingsymbol: str
    action: str  # STRONG BUY, BUY, HOLD, SELL, STRONG SELL
    score: float  # -1.0 to +1.0
    confidence: float  # 0-100%
    current_price: float = 0.0
    headline_reason: str = ""  # most-impactful single reason for UI "Why" column
    reasons: list[str] = []
    technical_score: float = 0.0
    fundamental_score: float = 0.0
    news_score: float = 0.0
    news_items: list[NewsItem] = []
    # Fundamentals (cross-source)
    pe_ratio: float | None = None
    debt_to_equity: float | None = None
    roe: float | None = None
    revenue_growth: float | None = None
    market_cap: float | None = None
    dividend_yield: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    # Technical-derived risk levels
    atr: float | None = None
    # Trade plan
    buy_upto: float | None = None
    target_price_consensus: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    target_confidence: str = "unknown"  # high | medium | low | unknown
    target_price_sources: list[TargetEntry] = []
    stop_loss: float | None = None
    # Analyst consensus
    analyst_count: int | None = None
    analyst_recommendation: str | None = None
    # Forecasts
    forecast_30d: ForecastBand | None = None
    forecast_12m: MonteCarloBand | None = None
    fundamental_sources: list[str] = []
    # Risks / downside scenarios
    risks: list[str] = []
    # Company info
    business_summary: str | None = None
    sector: str | None = None
    industry: str | None = None
    company_website: str | None = None
    # Live-price metadata
    price_updated_at: str | None = None
    price_source: str | None = None  # "kite" | "yfinance"
    # Promoter holding (from Screener.in)
    promoter_holding: float | None = None             # latest %
    promoter_holding_change_qoq: float | None = None  # percentage-points QoQ
    promoter_holding_change_yoy: float | None = None  # percentage-points YoY
    promoter_holding_history: list[float] = []
    # Profit margin trend (from Screener.in)
    operating_margin_latest: float | None = None      # latest %
    operating_margin_history: list[float] = []        # annual %, oldest→newest
    sales_cagr_5y: float | None = None
    profit_cagr_5y: float | None = None
    # Smart-money signals
    bulk_deals_30d: list[dict] = []
    insider_trades_30d: list[dict] = []
    corporate_actions: list[dict] = []
    recent_results: list[dict] = []
    upcoming_events: list[dict] = []
    smart_money_sources: list[str] = []
    # Historical metrics
    one_year_return: float | None = None
    three_year_return: float | None = None  # annualized
    five_year_return: float | None = None   # annualized
    annualized_volatility: float | None = None
    max_drawdown_1y: float | None = None
    sharpe_1y: float | None = None
    beta_vs_nifty: float | None = None
