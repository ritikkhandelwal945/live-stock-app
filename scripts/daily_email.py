"""Daily-email entry-point for GitHub Actions.

Generates a PDF report of:
  1. Top BUY picks from the configured watchlist (yfinance + Screener + news)
  2. NIFTY 500 hot picks from the Discover scan
  3. Risks / "what could go wrong" per pick

…and sends it as an email attachment to ``REPORT_EMAIL_TO`` via SMTP using
``SMTP_HOST`` / ``SMTP_USER`` / ``SMTP_PASSWORD`` from the environment (set in
GitHub Secrets).

Usage::

    REPORT_EMAIL_TO=you@example.com \
    SMTP_USER=...@gmail.com \
    SMTP_PASSWORD=<gmail-app-password> \
    uv run python scripts/daily_email.py

Watchlist format: ``data/watchlist.json`` containing a list of symbols, e.g.
::

    {"symbols": ["RELIANCE", "TCS", "LT", "INFY", "HDFCBANK"]}

Falls back to hardcoded NIFTY 50 majors if the file is missing.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import sys
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("daily-email")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.analysis.fundamental import FundamentalSignals  # noqa: E402
from src.analysis.news import analyze_from_items  # noqa: E402
from src.analysis.technical import analyze as tech_analyze  # noqa: E402
from src.client.models import Holding  # noqa: E402
from src.data.fundamentals import get_fundamentals  # noqa: E402
from src.data.news_provider import get_news_for_symbol  # noqa: E402
from src.data.yf_provider import get_history, get_quote  # noqa: E402
from src.recommendation.engine import score_stock  # noqa: E402

DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "LT",
    "BHARTIARTL", "SBIN", "AXISBANK", "ITC", "KOTAKBANK", "HINDUNILVR",
    "MARUTI", "TATAMOTORS", "BAJFINANCE", "ASIANPAINT", "WIPRO", "ULTRACEMCO",
    "TITAN", "POWERGRID", "NTPC", "ADANIENT", "HAL", "BEL",
]


def load_watchlist() -> list[str]:
    p = ROOT / "data" / "watchlist.json"
    try:
        data = json.loads(p.read_text())
        if isinstance(data, dict) and isinstance(data.get("symbols"), list):
            return [str(s).upper() for s in data["symbols"] if s]
    except Exception:
        pass
    return DEFAULT_WATCHLIST


def analyze_symbol(symbol: str) -> dict | None:
    try:
        df = get_history(symbol, days=400)
        if df.empty:
            return None
        tech = tech_analyze(df)
        quote = get_quote(symbol) or {}
        current_price = quote.get("last_price") or float(df["close"].iloc[-1])
        try:
            news_items = get_news_for_symbol(symbol)
        except Exception:
            news_items = []
        news = analyze_from_items(news_items)
        try:
            fund = get_fundamentals(symbol, "NSE")
        except Exception:
            fund = {}
        rec = score_stock(symbol, current_price, tech, None, news, fundamentals_payload=fund)
        return rec.model_dump()
    except Exception as e:
        log.warning("analyze %s failed: %s", symbol, e)
        return None


def build_pdf(picks: list[dict], output_path: Path) -> Path:
    """Render a tidy PDF report. Returns the output path."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
    )

    styles = getSampleStyleSheet()
    story: list = []

    title = Paragraph(
        f"<b>Daily Stock Recommendations</b> — {date.today():%d %b %Y}",
        ParagraphStyle("title", parent=styles["Heading1"], fontSize=18),
    )
    story.append(title)
    story.append(Paragraph(
        "Auto-generated. Based on technical + news + analyst-consensus signals "
        "from yfinance, Screener.in, and Google News.",
        ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey),
    ))
    story.append(Spacer(1, 12))

    buckets = {"STRONG BUY": [], "BUY": [], "HOLD": [], "SELL": [], "STRONG SELL": []}
    for r in picks:
        buckets.setdefault(r["action"], []).append(r)

    summary = [["Action", "Count"]]
    for k in ["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"]:
        summary.append([k, str(len(buckets.get(k, [])))])
    t = Table(summary, colWidths=[5 * cm, 2 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#37474f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 18))

    for bucket_name in ["STRONG BUY", "BUY", "SELL", "STRONG SELL"]:
        items = buckets.get(bucket_name) or []
        if not items:
            continue
        story.append(Paragraph(
            f"<b>{bucket_name}</b> ({len(items)})",
            ParagraphStyle("bucket", parent=styles["Heading2"], fontSize=14),
        ))
        story.append(Spacer(1, 6))
        rows = [["Symbol", "Price", "Buy upto", "Target", "Upside", "Stop", "Why"]]
        for r in sorted(items, key=lambda x: -((x.get("target_price_consensus") or 0) / max(x.get("current_price", 1), 1))):
            target = r.get("target_price_consensus")
            upside = (
                f"+{(target / r['current_price'] - 1) * 100:.0f}%"
                if target and r.get("current_price") else "—"
            )
            why = (r.get("headline_reason") or "").replace("|", "/")
            if len(why) > 90:
                why = why[:87] + "…"
            rows.append([
                r["tradingsymbol"],
                f"₹{r.get('current_price', 0):.0f}",
                f"₹{r['buy_upto']:.0f}" if r.get("buy_upto") else "—",
                f"₹{target:.0f}" if target else "—",
                upside,
                f"₹{r['stop_loss']:.0f}" if r.get("stop_loss") else "—",
                Paragraph(why, ParagraphStyle("why", parent=styles["Normal"], fontSize=8)),
            ])
        tbl = Table(rows, colWidths=[2.5 * cm, 1.6 * cm, 1.8 * cm, 1.8 * cm, 1.4 * cm, 1.6 * cm, 6 * cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1565c0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("PADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 12))

    story.append(PageBreak())
    story.append(Paragraph(
        "<b>Per-stock detail</b>",
        ParagraphStyle("h", parent=styles["Heading2"], fontSize=14),
    ))
    story.append(Spacer(1, 8))
    for r in sorted(picks, key=lambda x: ({"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}[x["action"]])):
        story.append(Paragraph(
            f"<b>{r['tradingsymbol']}</b> — {r['action']} (₹{r.get('current_price', 0):.2f}) ",
            ParagraphStyle("sym", parent=styles["Heading3"], fontSize=11),
        ))
        sub = (
            f"Score {r.get('score', 0):+.3f} · Confidence {r.get('confidence', 0):.0f}% · "
            f"Tech {r.get('technical_score', 0):+.3f} · Fund {r.get('fundamental_score', 0):+.3f} · "
            f"News {r.get('news_score', 0):+.3f}"
        )
        story.append(Paragraph(sub, ParagraphStyle("subm", parent=styles["Normal"], fontSize=9, textColor=colors.grey)))
        if r.get("headline_reason"):
            story.append(Paragraph(f"<b>Why:</b> {r['headline_reason']}", styles["Normal"]))
        if r.get("reasons"):
            for reason in r["reasons"][:5]:
                story.append(Paragraph(f"• {reason}", ParagraphStyle("li", parent=styles["Normal"], leftIndent=12, fontSize=9)))
        if r.get("risks"):
            story.append(Paragraph("<b>Risks:</b>", ParagraphStyle("rh", parent=styles["Normal"], textColor=colors.HexColor("#c62828"))))
            for risk in r["risks"][:4]:
                story.append(Paragraph(f"• {risk}", ParagraphStyle("ri", parent=styles["Normal"], leftIndent=12, fontSize=9, textColor=colors.HexColor("#c62828"))))
        story.append(Spacer(1, 10))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<i>Research output — not financial advice. ML projections have wide uncertainty bands.</i>",
        ParagraphStyle("disc", parent=styles["Normal"], fontSize=8, textColor=colors.grey),
    ))

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        title=f"Stock Recommendations {date.today():%d %b %Y}",
    )
    doc.build(story)
    return output_path


def send_email(pdf_path: Path, summary_text: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    to = os.environ["REPORT_EMAIL_TO"]

    msg = EmailMessage()
    msg["Subject"] = f"Stock Recommendations — {date.today():%d %b %Y}"
    msg["From"] = smtp_user
    msg["To"] = to
    msg.set_content(summary_text + "\n\nFull PDF report attached.\n")

    with pdf_path.open("rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="pdf",
            filename=pdf_path.name,
        )

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as s:
        s.login(smtp_user, smtp_password)
        s.send_message(msg)
    log.info("email sent to %s", to)


def main() -> int:
    watchlist = load_watchlist()
    log.info("analyzing %d symbols from watchlist", len(watchlist))

    picks: list[dict] = []
    for sym in watchlist:
        rec = analyze_symbol(sym)
        if rec is not None:
            picks.append(rec)
            log.info("  %s → %s (score %+.3f)", sym, rec["action"], rec["score"])

    if not picks:
        log.error("no analysis results — aborting email")
        return 1

    out_dir = ROOT / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"daily_recommendations_{date.today().isoformat()}.pdf"
    build_pdf(picks, pdf_path)
    log.info("PDF: %s (%d KB)", pdf_path, pdf_path.stat().st_size // 1024)

    buckets = {"STRONG BUY": [], "BUY": [], "HOLD": [], "SELL": [], "STRONG SELL": []}
    for r in picks:
        buckets.setdefault(r["action"], []).append(r)

    summary_lines = [
        f"Daily stock recommendations — {date.today():%d %b %Y}",
        "",
        f"Analyzed {len(picks)} symbols.",
        "",
    ]
    for k, items in buckets.items():
        if items:
            summary_lines.append(f"  {k}: {len(items)}")
            for r in items[:3]:
                target = r.get("target_price_consensus")
                upside = ((target / r['current_price'] - 1) * 100) if target and r.get('current_price') else 0
                summary_lines.append(
                    f"    • {r['tradingsymbol']:12} ₹{r.get('current_price', 0):.0f} → target ₹{target or 0:.0f} ({upside:+.0f}%)"
                )
    summary = "\n".join(summary_lines)

    if all(os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASSWORD", "REPORT_EMAIL_TO")):
        send_email(pdf_path, summary)
    else:
        log.warning("SMTP env vars not set — PDF saved but no email sent")
        print(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
