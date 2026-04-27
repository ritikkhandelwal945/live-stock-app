"""Screener.in scraper for Indian fundamentals."""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from src.data.http import make_ssl_context

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(5.0, connect=5.0),
    headers={"User-Agent": "Mozilla/5.0 (live-stock-app/1.0)"},
    follow_redirects=True,
)


def _to_float(s: str) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "").replace("₹", "").replace("%", "").replace("Cr.", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch(symbol: str) -> dict | None:
    sym = symbol.strip().upper()
    for path in ("consolidated/", ""):
        url = f"https://www.screener.in/company/{sym}/{path}"
        try:
            resp = _HTTPX.get(url)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        soup = BeautifulSoup(resp.text, "lxml")
        ratios = _parse_top_ratios(soup)
        if not ratios:
            continue

        promoter = _parse_promoter_history(soup)
        opm_annual = _parse_named_row(soup, "#profit-loss", "OPM %")
        opm_quarterly = _parse_named_row(soup, "#quarters", "OPM %")
        sales_growth = _parse_growth_section(soup, "Sales Growth")
        profit_growth = _parse_growth_section(soup, "Profit Growth")

        # Best-available revenue growth: latest year-on-year (last two annual sales)
        revenue_growth_pct = _yoy_growth(_parse_named_row(soup, "#profit-loss", "Sales"))

        return {
            "ratios": {
                "pe_ratio": ratios.get("Stock P/E"),
                "roe": ratios.get("ROE") or ratios.get("Return on equity"),
                "debt_to_equity": _debt_to_equity(ratios),
                "revenue_growth": revenue_growth_pct,
                "eps_growth": None,
            },
            "market_cap": _crores_to_inr(ratios.get("Market Cap")),
            "dividend_yield": ratios.get("Dividend Yield"),
            "fifty_two_week_high": ratios.get("High"),
            "fifty_two_week_low": ratios.get("Low"),
            "target_price": None,
            # New fields surfaced for the engine + UI
            "promoter_holding": promoter.get("latest"),
            "promoter_holding_change_qoq": promoter.get("change_qoq"),
            "promoter_holding_change_yoy": promoter.get("change_yoy"),
            "promoter_holding_history": promoter.get("history"),
            "opm_latest": opm_quarterly[-1] if opm_quarterly else (opm_annual[-1] if opm_annual else None),
            "opm_annual_history": opm_annual,
            "opm_quarterly_history": opm_quarterly,
            "sales_cagr_5y": sales_growth.get("5 Years") if isinstance(sales_growth, dict) else None,
            "profit_cagr_5y": profit_growth.get("5 Years") if isinstance(profit_growth, dict) else None,
            "raw": {
                "top_ratios": ratios,
                "promoter": promoter,
                "opm_annual": opm_annual,
                "opm_quarterly": opm_quarterly,
                "sales_growth": sales_growth,
                "profit_growth": profit_growth,
                "url": url,
            },
        }
    return None


def _parse_top_ratios(soup: BeautifulSoup) -> dict[str, float]:
    out: dict[str, float] = {}
    block = soup.select_one("#top-ratios")
    if not block:
        return out
    for li in block.select("li"):
        name_el = li.select_one(".name") or li.find("span")
        val_el = li.select_one(".value") or li.find_all("span")[-1] if li.find_all("span") else None
        if not name_el or not val_el:
            continue
        name = name_el.get_text(strip=True)
        val_text = val_el.get_text(" ", strip=True)
        m = re.search(r"-?\d[\d,\.]*", val_text)
        v = _to_float(m.group(0)) if m else None
        if v is not None:
            out[name] = v
    return out


def _parse_named_row(soup: BeautifulSoup, section_id: str, row_label: str) -> list[float] | None:
    """Pull every numeric cell from the row matching `row_label` in the named
    Screener section (e.g. '#profit-loss', '#quarters'). Returns chronological
    list (oldest → newest). Returns None if the section or row isn't found."""
    sect = soup.select_one(section_id)
    if not sect:
        return None
    table = sect.select_one("table")
    if not table:
        return None
    target = row_label.lower().strip()
    for tr in table.select("tr"):
        cells = tr.select("th, td")
        if not cells:
            continue
        head = cells[0].get_text(" ", strip=True).rstrip("+").strip().lower()
        if head == target:
            vals: list[float] = []
            for c in cells[1:]:
                v = _to_float(c.get_text(" ", strip=True))
                if v is not None:
                    vals.append(v)
            return vals
    return None


def _parse_promoter_history(soup: BeautifulSoup) -> dict:
    """Parse the Shareholding section's Promoters row. Returns latest %, QoQ
    change, YoY change, and the full ordered history."""
    sect = soup.select_one("#shareholding")
    if not sect:
        return {}
    table = sect.select_one("table")
    if not table:
        return {}

    history: list[float] = []
    for tr in table.select("tr"):
        cells = tr.select("th, td")
        if not cells:
            continue
        head = cells[0].get_text(" ", strip=True).lower()
        if head.startswith("promoter"):
            for c in cells[1:]:
                v = _to_float(c.get_text(" ", strip=True))
                if v is not None:
                    history.append(v)
            break
    if not history:
        return {}

    out: dict = {"history": history, "latest": history[-1]}
    if len(history) >= 2:
        out["change_qoq"] = history[-1] - history[-2]
    if len(history) >= 5:
        out["change_yoy"] = history[-1] - history[-5]
    return out


def _parse_growth_section(soup: BeautifulSoup, label: str) -> dict | list[float] | None:
    """Screener's 'Compounded Sales/Profit Growth' tables list 10/5/3/1 yr CAGRs.
    Returns a dict like {'10 Years': 12.5, '5 Years': 18.2, ...}."""
    out: dict[str, float] = {}
    target = label.lower()
    for tbl in soup.select("table.ranges-table"):
        first_row = tbl.select_one("tr")
        if not first_row:
            continue
        first_cell = first_row.get_text(" ", strip=True).lower()
        if target not in first_cell:
            continue
        for tr in tbl.select("tr")[1:]:
            cells = tr.select("td")
            if len(cells) < 2:
                continue
            key = cells[0].get_text(" ", strip=True)
            v = _to_float(cells[1].get_text(" ", strip=True))
            if v is not None:
                out[key] = v
        if out:
            return out
    return out or None


def _yoy_growth(history: list[float] | None) -> float | None:
    if not history or len(history) < 2:
        return None
    prev = history[-2]
    if prev == 0:
        return None
    return (history[-1] - prev) / abs(prev) * 100


def _percent_to_decimal(v: float | None) -> float | None:
    return None if v is None else v / 100.0


def _crores_to_inr(v: float | None) -> float | None:
    return None if v is None else v * 1e7


def _debt_to_equity(ratios: dict[str, float]) -> float | None:
    for key in ("Debt to equity", "DE Ratio"):
        v = ratios.get(key)
        if v is not None:
            return v
    return None
