import json
import os
from datetime import date

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("zerodha-portfolio", instructions=(
    "Stock analysis and portfolio management tools connected to Zerodha Kite Connect. "
    "Use these tools to fetch portfolio data, analyze stocks with technical indicators, "
    "and get buy/sell/hold recommendations."
))

# Lazy-initialized client (auth required)
_client = None


def _get_client():
    global _client
    if _client is None:
        from src.client.kite_client import KiteClient
        _client = KiteClient()
    return _client


@mcp.tool()
def get_holdings() -> str:
    """Fetch current portfolio holdings from Zerodha.

    Returns a list of all stocks in the portfolio with quantity, average price,
    last price, P&L, and day change percentage.
    """
    client = _get_client()
    holdings = client.get_holdings()
    if not holdings:
        return "No holdings found."

    total_invested = sum(h.quantity * h.average_price for h in holdings)
    total_current = sum(h.quantity * h.last_price for h in holdings)
    total_pnl = sum(h.pnl for h in holdings)

    result = {
        "holdings": [h.model_dump() for h in holdings],
        "summary": {
            "total_stocks": len(holdings),
            "total_invested": round(total_invested, 2),
            "total_current_value": round(total_current, 2),
            "total_pnl": round(total_pnl, 2),
            "overall_return_pct": round((total_pnl / total_invested * 100) if total_invested > 0 else 0, 2),
        },
    }
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def get_positions() -> str:
    """Fetch current open positions (intraday and delivery) from Zerodha."""
    client = _get_client()
    positions = client.get_positions()
    if not positions:
        return "No open positions."
    return json.dumps([p.model_dump() for p in positions], indent=2, default=str)


@mcp.tool()
def get_orders() -> str:
    """Fetch today's order history from Zerodha."""
    client = _get_client()
    orders = client.get_orders()
    if not orders:
        return "No orders today."
    return json.dumps(orders, indent=2, default=str)


@mcp.tool()
def get_stock_quote(symbol: str) -> str:
    """Get current market quote for a stock symbol (e.g., RELIANCE, INFY, TCS).

    Args:
        symbol: NSE trading symbol (e.g., RELIANCE, INFY, TCS, HDFCBANK)
    """
    client = _get_client()
    quotes = client.get_quote([symbol.upper()])
    quote = quotes.get(symbol.upper())
    if not quote:
        return f"Quote not found for {symbol}"
    return json.dumps(quote.model_dump(), indent=2, default=str)


@mcp.tool()
def get_historical_data(symbol: str, days: int = 365, interval: str = "day") -> str:
    """Fetch historical OHLCV (Open/High/Low/Close/Volume) candle data for a stock.

    Args:
        symbol: NSE trading symbol (e.g., RELIANCE, INFY)
        days: Number of days of historical data (default: 365)
        interval: Candle interval - day, 15minute, 60minute, etc. (default: day)
    """
    client = _get_client()
    df = client.get_historical_data(symbol.upper(), days=days, interval=interval)
    if df.empty:
        return f"No historical data found for {symbol}"

    summary = {
        "symbol": symbol.upper(),
        "candles": len(df),
        "from": str(df["date"].iloc[0]),
        "to": str(df["date"].iloc[-1]),
        "latest_close": float(df["close"].iloc[-1]),
        "high_52w": float(df["high"].max()) if len(df) >= 252 else float(df["high"].max()),
        "low_52w": float(df["low"].min()) if len(df) >= 252 else float(df["low"].min()),
        "avg_volume": int(df["volume"].mean()),
    }
    # Include last 10 candles for context
    recent = df.tail(10).to_dict("records")
    summary["recent_candles"] = [{k: str(v) if k == "date" else v for k, v in r.items()} for r in recent]
    return json.dumps(summary, indent=2, default=str)


@mcp.tool()
def analyze_stock(symbol: str, days: int = 365) -> str:
    """Run full technical analysis on a stock and return a buy/sell/hold recommendation.

    Computes RSI, MACD, SMA/EMA crossovers, Bollinger Bands, volume analysis,
    and 52-week position to generate a recommendation with confidence score.

    Args:
        symbol: NSE trading symbol (e.g., RELIANCE, INFY, TCS)
        days: Historical data lookback days (default: 365)
    """
    from src.analysis.technical import analyze as tech_analyze
    from src.analysis.fundamental import FundamentalSignals
    from src.analysis.news import NewsSignals
    from src.recommendation.engine import score_stock

    client = _get_client()
    symbol = symbol.upper()

    df = client.get_historical_data(symbol, days=days)
    quotes = client.get_quote([symbol])
    quote = quotes.get(symbol)
    current_price = quote.last_price if quote else (float(df["close"].iloc[-1]) if not df.empty else 0)

    tech = tech_analyze(df)

    # Build result with full indicator detail
    indicators = []
    for ind in tech.indicators:
        indicators.append({
            "name": ind.name,
            "value": ind.value,
            "signal": ind.signal,
            "score": ind.score,
            "detail": ind.detail,
        })

    fund = FundamentalSignals()
    news = NewsSignals()
    rec = score_stock(symbol, current_price, tech, fund, news)

    result = {
        "symbol": symbol,
        "current_price": current_price,
        "recommendation": {
            "action": rec.action,
            "score": rec.score,
            "confidence": rec.confidence,
            "reasons": rec.reasons,
        },
        "technical_analysis": {
            "overall_score": tech.overall_score,
            "summary": tech.summary,
            "indicators": indicators,
        },
        "note": "Fundamental and news analysis require web search. Use search_stock_news() and provide fundamental data via analyze_portfolio_with_research() for a complete picture.",
    }
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def analyze_portfolio(days: int = 365) -> str:
    """Analyze ALL stocks in the portfolio and generate buy/sell/hold recommendations.

    Runs technical analysis on each holding and returns sorted recommendations.
    For the most comprehensive analysis, combine this with web research on each stock.

    Args:
        days: Historical data lookback days (default: 365)
    """
    from src.analysis.technical import analyze as tech_analyze
    from src.analysis.fundamental import FundamentalSignals
    from src.analysis.news import NewsSignals
    from src.recommendation.engine import score_stock
    from src.recommendation.report import save_recommendations

    client = _get_client()
    holdings = client.get_holdings()

    if not holdings:
        return "No holdings found in portfolio."

    recommendations = []
    errors = []

    for stock in holdings:
        symbol = stock.tradingsymbol
        try:
            df = client.get_historical_data(symbol, days=days)
            tech = tech_analyze(df)
            current_price = stock.last_price or (float(df["close"].iloc[-1]) if not df.empty else 0)
            fund = FundamentalSignals()
            news = NewsSignals()
            rec = score_stock(symbol, current_price, tech, fund, news)
            recommendations.append(rec)
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})

    # Save results
    if recommendations:
        save_recommendations(recommendations)

    # Sort by score
    order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}
    recommendations.sort(key=lambda r: order.get(r.action, 2))

    result = {
        "total_stocks": len(holdings),
        "analyzed": len(recommendations),
        "errors": errors,
        "recommendations": [
            {
                "symbol": r.tradingsymbol,
                "price": r.current_price,
                "action": r.action,
                "score": r.score,
                "confidence": r.confidence,
                "technical_score": r.technical_score,
                "reasons": r.reasons,
            }
            for r in recommendations
        ],
        "summary": {
            "strong_buy": sum(1 for r in recommendations if r.action == "STRONG BUY"),
            "buy": sum(1 for r in recommendations if r.action == "BUY"),
            "hold": sum(1 for r in recommendations if r.action == "HOLD"),
            "sell": sum(1 for r in recommendations if r.action == "SELL"),
            "strong_sell": sum(1 for r in recommendations if r.action == "STRONG SELL"),
        },
    }
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def search_stock_news(symbol: str) -> str:
    """Search for recent news about a stock and analyze sentiment.

    This returns news search queries you should use with web search to find
    the latest information about the stock. After searching, pass the results
    to analyze_with_research() for a comprehensive recommendation.

    Args:
        symbol: NSE trading symbol (e.g., RELIANCE, INFY)
    """
    symbol = symbol.upper()
    queries = [
        f"{symbol} NSE quarterly results 2026",
        f"{symbol} stock analyst target price recommendation",
        f"{symbol} company latest news",
        f"{symbol} promoter holding change",
        f"{symbol} sector outlook India",
    ]
    return json.dumps({
        "symbol": symbol,
        "suggested_search_queries": queries,
        "instructions": (
            "Search the web for each of these queries, then use analyze_with_research() "
            "to combine the findings with technical analysis for a complete recommendation."
        ),
    }, indent=2)


@mcp.tool()
def analyze_with_research(
    symbol: str,
    fundamental_data: str = "{}",
    news_headlines: str = "[]",
    days: int = 365,
) -> str:
    """Generate a comprehensive recommendation combining technical analysis with
    fundamental data and news that you've researched via web search.

    Args:
        symbol: NSE trading symbol
        fundamental_data: JSON string with keys: pe_ratio, sector_avg_pe, debt_to_equity,
                         roe, eps_growth, promoter_holding, promoter_holding_change, revenue_growth
        news_headlines: JSON string - list of objects with 'headline' and optionally 'source' keys
        days: Historical data lookback days
    """
    from src.analysis.technical import analyze as tech_analyze
    from src.analysis.fundamental import analyze_from_data
    from src.analysis.news import analyze_from_items
    from src.recommendation.engine import score_stock

    client = _get_client()
    symbol = symbol.upper()

    df = client.get_historical_data(symbol, days=days)
    quotes = client.get_quote([symbol])
    quote = quotes.get(symbol)
    current_price = quote.last_price if quote else (float(df["close"].iloc[-1]) if not df.empty else 0)

    tech = tech_analyze(df)

    try:
        fund_data = json.loads(fundamental_data)
    except json.JSONDecodeError:
        fund_data = {}
    fund = analyze_from_data(fund_data)

    try:
        news_items = json.loads(news_headlines)
    except json.JSONDecodeError:
        news_items = []
    news = analyze_from_items(news_items)

    rec = score_stock(symbol, current_price, tech, fund, news)

    result = {
        "symbol": symbol,
        "current_price": current_price,
        "recommendation": {
            "action": rec.action,
            "score": rec.score,
            "confidence": rec.confidence,
            "reasons": rec.reasons,
        },
        "technical": {
            "score": tech.overall_score,
            "summary": tech.summary,
            "indicators": [
                {"name": i.name, "signal": i.signal, "score": i.score, "detail": i.detail}
                for i in tech.indicators
            ],
        },
        "fundamental": {
            "score": fund.overall_score,
            "summary": fund.summary,
            "metrics": [
                {"name": m.name, "value": m.value, "signal": m.signal, "detail": m.detail}
                for m in fund.metrics
            ],
        },
        "news": {
            "score": news.overall_score,
            "summary": news.summary,
            "items": [
                {"headline": n.headline, "sentiment": n.sentiment, "score": n.score}
                for n in news.items
            ],
        },
    }
    return json.dumps(result, indent=2, default=str)


if __name__ == "__main__":
    mcp.run()
