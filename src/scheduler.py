"""Background daily refresh scheduler.

Pre-computes recommendations + Discover scans so the user gets instant data
when opening the UI. Times are explicit IST.

Jobs:
    full_refresh        — 8:00 AM IST  · holdings + watchlist deep-analysis
    discover_refresh    — 8:30 AM IST  · NIFTY 500 hot-picks scan
    intraday_refresh    — every 30 min · 9:15 AM – 3:30 PM IST · holdings only
    morning_cache_clear — 6:00 AM IST  · drop news cache (Zerodha tokens
                                          expire here too; user re-auths fresh)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("live-stock-app.scheduler")
log.setLevel(logging.INFO)

_IST = ZoneInfo("Asia/Kolkata")
_DAILY_PATH = Path(__file__).resolve().parent.parent / "data" / "daily_recommendations.json"


def _save(payload: dict) -> None:
    try:
        _DAILY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DAILY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=str))
        tmp.replace(_DAILY_PATH)
    except Exception as e:
        log.warning("failed to save daily payload: %s", e)


def load_daily() -> dict | None:
    try:
        return json.loads(_DAILY_PATH.read_text())
    except Exception:
        return None


# ─────────────────────────────────────────── jobs ──────────────────────────


def job_morning_cache_clear() -> None:
    """At 6 AM IST, drop the 30-minute news cache so the day starts with
    fresh headlines once the user logs in."""
    log.info("morning_cache_clear running")
    cache = Path(__file__).resolve().parent.parent / "data" / "news_cache.json"
    try:
        if cache.exists():
            cache.unlink()
    except Exception:
        pass


def job_full_refresh() -> None:
    """At 8 AM IST, deep-analyze every portfolio holding + the NIFTY 500 top-30
    by analyst consensus. Result is written to data/daily_recommendations.json."""
    log.info("full_refresh running")
    started = time.time()

    # Lazy imports — avoid circular deps at module load
    from src.api.main import _analyze_one, _resolve_holdings_for_analysis
    from src.client.models import Holding

    holdings = _resolve_holdings_for_analysis()
    holdings_recs = []
    for h in holdings:
        try:
            rec = _analyze_one(h, days=400, refresh=False)
            if rec is not None:
                holdings_recs.append(rec.model_dump())
        except Exception as e:
            log.warning("analyze %s failed: %s", h.tradingsymbol, e)

    payload = {
        "generated_at": datetime.now(_IST).isoformat(),
        "holdings": holdings_recs,
    }
    _save(payload)
    log.info("full_refresh done in %.1fs (%d holdings)", time.time() - started, len(holdings_recs))


def job_discover_refresh() -> None:
    """At 8:30 AM IST, run a NIFTY 500 Discover scan to warm its 1h cache."""
    log.info("discover_refresh running")
    try:
        from src.api.discover import screen_universe
        screen_universe(index="NIFTY500", deep_analyze_top=30, refresh=True)
    except Exception as e:
        log.warning("discover_refresh failed: %s", e)


def job_intraday_refresh() -> None:
    """Every 30 min during market hours, refresh holdings only (light)."""
    log.info("intraday_refresh running")
    try:
        from src.api.main import _resolve_holdings_for_analysis, _enrich_with_yfinance
        holdings = _resolve_holdings_for_analysis()
        _enrich_with_yfinance(holdings)
    except Exception as e:
        log.warning("intraday_refresh failed: %s", e)


_JOBS = {
    "morning_cache_clear": job_morning_cache_clear,
    "full_refresh": job_full_refresh,
    "discover_refresh": job_discover_refresh,
    "intraday_refresh": job_intraday_refresh,
}


def run_job(name: str) -> dict:
    """Invoke a job by name (used by the admin endpoint)."""
    fn = _JOBS.get(name)
    if fn is None:
        return {"status": "error", "detail": f"unknown job: {name}", "valid": list(_JOBS)}
    started = time.time()
    try:
        fn()
        return {"status": "ok", "job": name, "elapsed_s": round(time.time() - started, 2)}
    except Exception as e:
        return {"status": "error", "job": name, "detail": str(e)}


# ─────────────────────────────────────────── lifecycle ─────────────────────


_SCHEDULER = None


def start() -> None:
    global _SCHEDULER
    if _SCHEDULER is not None:
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BackgroundScheduler(timezone=_IST)

    sched.add_job(
        job_morning_cache_clear,
        CronTrigger(hour=6, minute=0, timezone=_IST),
        id="morning_cache_clear",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    sched.add_job(
        job_full_refresh,
        CronTrigger(hour=8, minute=0, timezone=_IST),
        id="full_refresh",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    sched.add_job(
        job_discover_refresh,
        CronTrigger(hour=8, minute=30, timezone=_IST),
        id="discover_refresh",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    sched.add_job(
        job_intraday_refresh,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/30",
            timezone=_IST,
        ),
        id="intraday_refresh",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )

    sched.start()
    _SCHEDULER = sched
    log.info("Scheduler started — jobs: %s", [j.id for j in sched.get_jobs()])


def stop() -> None:
    global _SCHEDULER
    if _SCHEDULER is not None:
        _SCHEDULER.shutdown(wait=False)
        _SCHEDULER = None
        log.info("Scheduler stopped")


def jobs_summary() -> list[dict]:
    if _SCHEDULER is None:
        return []
    return [
        {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
        for j in _SCHEDULER.get_jobs()
    ]
