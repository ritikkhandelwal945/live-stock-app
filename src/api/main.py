import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from src.analysis.fundamental import FundamentalSignals
from src.analysis.forecast import forecast_arima_30d, forecast_monte_carlo_12m
from src.analysis.news import NewsSignals, analyze_from_items
from src.analysis.technical import analyze as tech_analyze
from src.api.csv_import import parse_holdings_csv
from src.auth.token_store import clear_token, load_token
from src.client.models import Holding, Position, Recommendation
from src.analysis.historical_metrics import compute as compute_historical
from src.data.company_info import get_company_info
from src.data.fundamentals import get_fundamentals
from src.data.news_provider import get_news_for_symbol
from src.data.smart_money import get_smart_money
from src.data.yf_provider import get_history, get_quote
from src.recommendation.engine import score_stock
from src.storage.holdings_store import clear_holdings, load_holdings, save_holdings

@asynccontextmanager
async def _lifespan(app):
    # Start the daily-refresh scheduler. Failures are logged but don't block
    # uvicorn from starting (we still want the API up even if APScheduler can't
    # boot for some reason).
    try:
        from src import scheduler
        scheduler.start()
    except Exception:
        pass
    yield
    try:
        from src import scheduler
        scheduler.stop()
    except Exception:
        pass


app = FastAPI(title="Live Stock App API", version="0.4.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthStatus(BaseModel):
    api_configured: bool
    authenticated: bool
    message: str


class HoldingsResponse(BaseModel):
    source: str  # "kite" | "csv" | "none"
    uploaded_at: str | None
    holdings: list[Holding]


class UploadResult(BaseModel):
    uploaded_at: str
    count: int


_LAST_KITE_ERROR: str | None = None
_NIFTY_CACHE: tuple[float, object] | None = None  # (fetched_at, close-series)


def _nifty_history():
    """Daily-close series for NIFTY 50, cached for 12 hours so beta + relative
    strength calcs don't refetch on every per-stock analysis call."""
    import time as _time
    global _NIFTY_CACHE
    now = _time.time()
    if _NIFTY_CACHE and now - _NIFTY_CACHE[0] < 12 * 3600:
        return _NIFTY_CACHE[1]
    try:
        import yfinance as yf
        from src.data.http import yfinance_session
        ticker = yf.Ticker("^NSEI", session=yfinance_session())
        hist = ticker.history(period="5y")
        series = hist["Close"] if not hist.empty else None
    except Exception:
        series = None
    _NIFTY_CACHE = (now, series)
    return series


def _kite_client():
    """Return an authenticated KiteClient or None if not authed/credentials missing."""
    global _LAST_KITE_ERROR
    if not os.environ.get("KITE_API_KEY"):
        return None
    if not load_token():
        return None
    try:
        from src.client.kite_client import KiteClient
        return KiteClient()
    except Exception as e:
        _LAST_KITE_ERROR = f"KiteClient init failed: {e}"
        return None


def _enrich_with_yfinance(holdings: list[Holding]) -> None:
    """Fill in missing/stale LTP and day-change from Yahoo Finance.

    Runs in parallel with a short timeout so a slow/missing symbol doesn't
    stall the whole portfolio response. Note: Kite Personal tier doesn't
    include live quotes, so for Kite-sourced holdings ``last_price`` may be
    a previous-close snapshot — we treat any zero / unchanged value as needing
    a refresh from yfinance.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    targets = [h for h in holdings if h.last_price <= 0 or h.day_change_percentage == 0]
    if not targets:
        return

    def _fetch(h: Holding):
        return h, get_quote(h.tradingsymbol, h.exchange)

    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch, h): h for h in targets}
        for fut in as_completed(futures, timeout=15):
            try:
                h, quote = fut.result(timeout=5)
            except Exception:
                continue
            if quote:
                h.last_price = quote["last_price"]
                h.day_change_percentage = quote["day_change_percentage"]
                h.pnl = (h.last_price - h.average_price) * h.quantity


@app.get("/api/health")
def health() -> dict:
    csv_holdings, uploaded_at = load_holdings()
    return {
        "status": "ok",
        "csv_uploaded_at": uploaded_at,
        "csv_holdings_count": len(csv_holdings),
        "kite_api_configured": bool(os.environ.get("KITE_API_KEY")),
        "kite_authenticated": bool(load_token()),
    }


@app.get("/api/auth/status", response_model=AuthStatus)
def auth_status() -> AuthStatus:
    has_key = bool(os.environ.get("KITE_API_KEY"))
    has_token = bool(load_token())
    if not has_key:
        return AuthStatus(
            api_configured=False,
            authenticated=False,
            message="KITE_API_KEY not set in .env.",
        )
    if not has_token:
        return AuthStatus(
            api_configured=True,
            authenticated=False,
            message="Run `uv run stock-app auth --manual` in a terminal to log in to Zerodha.",
        )
    # Validate the token by hitting Zerodha's profile endpoint (cheap call).
    try:
        kite = _kite_client()
        if kite is None:
            return AuthStatus(
                api_configured=True,
                authenticated=False,
                message=f"Kite client init failed: {_LAST_KITE_ERROR or 'unknown'}",
            )
        kite._kite.profile()
    except Exception as e:
        # Token rejected by Zerodha (typically expired after 6 AM IST).
        return AuthStatus(
            api_configured=True,
            authenticated=False,
            message=f"Token rejected by Zerodha — re-auth required. Reason: {e}",
        )
    return AuthStatus(
        api_configured=True,
        authenticated=True,
        message="Connected to Zerodha.",
    )


@app.post("/api/auth/logout")
def auth_logout() -> dict:
    clear_token()
    return {"status": "ok"}


@app.get("/api/holdings", response_model=HoldingsResponse)
def holdings() -> HoldingsResponse:
    global _LAST_KITE_ERROR
    kite = _kite_client()
    if kite is not None:
        try:
            kite_holdings = kite.get_holdings()
            _enrich_with_yfinance(kite_holdings)
            return HoldingsResponse(source="kite", uploaded_at=None, holdings=kite_holdings)
        except Exception as e:
            _LAST_KITE_ERROR = f"kite.holdings() failed: {e}"
            # Surface the actual error so the UI doesn't show a misleading
            # empty state when Zerodha is the problem.
            raise HTTPException(
                status_code=502,
                detail=f"Zerodha holdings call failed: {e}. "
                       f"Token may be expired (Zerodha invalidates tokens daily at 6 AM IST). "
                       f"Run `uv run stock-app auth --manual` to re-authenticate.",
            )

    csv_holdings, uploaded_at = load_holdings()
    if csv_holdings:
        _enrich_with_yfinance(csv_holdings)
        return HoldingsResponse(source="csv", uploaded_at=uploaded_at, holdings=csv_holdings)

    return HoldingsResponse(source="none", uploaded_at=None, holdings=[])


@app.get("/api/positions", response_model=list[Position])
def positions() -> list[Position]:
    kite = _kite_client()
    if kite is None:
        return []
    try:
        return kite.get_positions()
    except Exception:
        return []


@app.post("/api/holdings/upload", response_model=UploadResult)
async def upload_holdings(file: UploadFile = File(...)) -> UploadResult:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        parsed = parse_holdings_csv(content, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")
    if not parsed:
        raise HTTPException(status_code=400, detail="No holdings found in file")
    uploaded_at = save_holdings(parsed)
    return UploadResult(uploaded_at=uploaded_at, count=len(parsed))


@app.delete("/api/holdings")
def delete_holdings() -> dict:
    clear_holdings()
    return {"status": "ok"}


def _resolve_holdings_for_analysis() -> list[Holding]:
    kite = _kite_client()
    if kite is not None:
        try:
            return kite.get_holdings()
        except Exception:
            pass
    csv_holdings, _ = load_holdings()
    return csv_holdings


def _analyze_one(holding: Holding, days: int, refresh: bool = False) -> Recommendation | None:
    try:
        df = get_history(holding.tradingsymbol, days=days, exchange=holding.exchange)
        if df.empty:
            return None
        tech = tech_analyze(df)
        current_price = holding.last_price or float(df["close"].iloc[-1])

        # Fundamentals (cached 24h, multi-source) — fetched first so we can
        # pull the company name and pass it to direct-source news matching.
        try:
            fundamentals = get_fundamentals(
                holding.tradingsymbol, exchange=holding.exchange, refresh=refresh
            )
        except Exception:
            fundamentals = {}

        # News (cached 30min)
        company_name = (
            ((fundamentals.get("raw_per_source") or {}).get("yfinance") or {}).get("longName")
            or ((fundamentals.get("raw_per_source") or {}).get("yfinance") or {}).get("shortName")
        )
        try:
            raw_news = get_news_for_symbol(
                holding.tradingsymbol,
                exchange=holding.exchange,
                refresh=refresh,
                company_name=company_name,
            )
        except Exception:
            raw_news = []
        news = analyze_from_items(raw_news)

        # Forecasts (cheap to recompute; not cached)
        try:
            f30 = forecast_arima_30d(df["close"])
        except Exception:
            f30 = None
        try:
            f12 = forecast_monte_carlo_12m(df["close"])
        except Exception:
            f12 = None

        # Smart-money signals (cached 24h, multi-source)
        try:
            sm = get_smart_money(holding.tradingsymbol, exchange=holding.exchange, refresh=refresh)
        except Exception:
            sm = {}

        # Historical metrics (pure compute on existing OHLCV; NIFTY benchmark fetched lazily)
        try:
            nifty_close = _nifty_history()
            historical = compute_historical(df["close"], nifty_close)
        except Exception:
            historical = {}

        rec = score_stock(
            holding.tradingsymbol,
            current_price,
            tech,
            None,  # let engine score from fundamentals_payload
            news,
            fundamentals_payload=fundamentals,
            forecast_30d=f30,
            forecast_12m=f12,
            smart_money=sm,
            historical=historical,
        )
        # Enrich with company info (cheap, 7-day cache)
        try:
            info = get_company_info(holding.tradingsymbol, exchange=holding.exchange)
            rec.business_summary = info.get("summary")
            rec.sector = info.get("sector") or rec.sector
            rec.industry = info.get("industry") or rec.industry
            rec.company_website = info.get("website")
        except Exception:
            pass
        return rec
    except Exception:
        return None


@app.get("/api/recommendations", response_model=list[Recommendation])
def recommendations(
    days: int = Query(365, ge=30, le=2000),
    refresh: bool = Query(False, description="Bypass news cache"),
) -> list[Recommendation]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    holdings_list = _resolve_holdings_for_analysis()
    if not holdings_list:
        return []

    results: list[Recommendation] = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {
            ex.submit(_analyze_one, h, days, refresh): h for h in holdings_list
        }
        for fut in as_completed(futures, timeout=120):
            try:
                rec = fut.result(timeout=15)
            except Exception:
                continue
            if rec is not None:
                results.append(rec)

    order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}
    results.sort(key=lambda r: (order.get(r.action, 2), -r.score))
    return results


@app.get("/api/analyze/{symbol}", response_model=Recommendation)
def analyze_symbol(symbol: str, days: int = Query(365, ge=30, le=2000)) -> Recommendation:
    symbol = symbol.upper()
    h = Holding(tradingsymbol=symbol, exchange="NSE", quantity=0, average_price=0.0)
    rec = _analyze_one(h, days, refresh=False)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")
    return rec


@app.get("/api/company/{symbol}")
def company(symbol: str, exchange: str = Query("NSE")) -> dict:
    return get_company_info(symbol.upper(), exchange=exchange)


@app.get("/api/discover")
def discover(
    universe: str = Query("NIFTY500"),
    top: int = Query(20, ge=5, le=100),
    refresh: bool = Query(False),
) -> dict:
    from src.api.discover import screen_universe
    return screen_universe(index=universe, deep_analyze_top=top, refresh=refresh)


@app.get("/api/daily")
def daily() -> dict:
    """Returns the most recent pre-computed daily recommendations payload.
    Falls back to the live /api/recommendations if no cache exists yet."""
    from src.scheduler import load_daily
    payload = load_daily()
    if payload and payload.get("holdings"):
        return payload
    return {"generated_at": None, "holdings": [], "message": "Cache not yet populated. The scheduler refreshes daily at 8 AM IST."}


@app.get("/api/admin/jobs")
def admin_jobs() -> list[dict]:
    from src.scheduler import jobs_summary
    return jobs_summary()


@app.post("/api/admin/run-job")
def admin_run_job(name: str = Query(...)) -> dict:
    from src.scheduler import run_job
    return run_job(name)


@app.get("/api/universes")
def universes() -> dict:
    """List available stock universes for the Discover dropdown."""
    from src.data.universe import _INDEX_URLS
    groups = [
        {"label": "Broad market", "indices": [
            "NIFTY50", "NIFTY100", "NIFTY200", "NIFTY500",
            "NIFTY_NEXT50", "NIFTY_LARGEMIDCAP250",
        ]},
        {"label": "Mid + small cap", "indices": [
            "NIFTY_MIDCAP100", "NIFTY_MIDCAP150",
            "NIFTY_SMALLCAP100", "NIFTY_SMALLCAP250",
        ]},
        {"label": "Sectoral", "indices": [
            "NIFTY_BANK", "NIFTY_PSU_BANK", "NIFTY_FINANCIAL_25_50",
            "NIFTY_AUTO", "NIFTY_IT", "NIFTY_PHARMA", "NIFTY_HEALTHCARE",
            "NIFTY_ENERGY", "NIFTY_OIL_GAS", "NIFTY_FMCG", "NIFTY_METAL",
            "NIFTY_REALTY", "NIFTY_CONSUMER_DURABLES",
        ]},
        {"label": "Thematic", "indices": [
            "NIFTY_INDIA_DEFENCE", "NIFTY_MIDSMALL_HEALTHCARE",
        ]},
    ]
    # Filter to only indices we actually have URLs for
    return {
        "groups": [
            {"label": g["label"], "indices": [i for i in g["indices"] if i in _INDEX_URLS]}
            for g in groups
        ]
    }
