"""Optional Gemini-powered macro analyst.

When ``GEMINI_API_KEY`` is set, sends the last 30 macro headlines to
``gemini-2.0-flash`` with a structured prompt and parses the JSON response.
Returns ``[]`` on missing key, network error, quota exhaustion, or parse
failure — the rule-based layer always works as a fallback.

Gemini free tier: 15 RPM / 1500 RPD on flash. Plenty for hourly refresh.
Get a key at https://aistudio.google.com/app/apikey (no credit card).
"""

from __future__ import annotations

import json
import logging
import os
import re

import httpx

from src.data.http import make_ssl_context

log = logging.getLogger(__name__)

_HTTPX = httpx.Client(
    verify=make_ssl_context(),
    timeout=httpx.Timeout(30.0, connect=8.0),
    headers={"User-Agent": "live-stock-app/1.0"},
)

_MODEL = "gemini-2.0-flash"
_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{_MODEL}:generateContent"
)


_PROMPT_TEMPLATE = """You are a sober Indian-equity macro analyst. Read these {n} recent Indian \
financial-news headlines and identify the top 3 macro themes currently impacting \
Indian markets.

For each theme:
- "id": short snake_case identifier (e.g. "middle_east_conflict")
- "label": 2-4 word human label (e.g. "Middle East tensions")
- "summary": one sentence on what is happening
- "sectors_positive": 3-5 NSE sector names that benefit
- "sectors_negative": 1-3 NSE sector names that suffer
- "confidence": "high" | "medium" | "low"

Return ONLY valid JSON of this shape (no prose, no markdown):
{{"themes": [{{...}}, {{...}}, {{...}}]}}

Use sector names typical of yfinance (e.g. "Aerospace & Defense",
"Information Technology Services", "Banks", "Oil & Gas E&P", "Airlines").

Headlines:
{headlines}
"""


def analyze_with_gemini(articles: list[dict]) -> list[dict]:
    """Return a list of theme dicts (or ``[]`` on any failure)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return []
    if not articles:
        return []

    sample = articles[:30]
    headlines_block = "\n".join(
        f"- [{a.get('source','?')}] {a.get('headline','').strip()}"
        for a in sample if a.get("headline")
    )
    if not headlines_block:
        return []

    prompt = _PROMPT_TEMPLATE.format(n=len(sample), headlines=headlines_block)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    try:
        r = _HTTPX.post(
            f"{_ENDPOINT}?key={api_key}",
            headers={"Content-Type": "application/json"},
            json=payload,
        )
        if r.status_code != 200:
            log.warning("Gemini %s: %s", r.status_code, r.text[:200])
            return []
        data = r.json()
    except Exception as e:
        log.warning("Gemini call failed: %s", e)
        return []

    # Extract the text part — model is instructed to return JSON,
    # but defend against wrapping in markdown fences anyway.
    text = ""
    try:
        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = parts[0].get("text", "") if parts else ""
    except Exception:
        return []
    if not text:
        return []
    text = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.MULTILINE)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Gemini returned non-JSON: %s", text[:200])
        return []

    raw_themes = parsed.get("themes") or []
    out: list[dict] = []
    for t in raw_themes[:5]:
        if not isinstance(t, dict):
            continue
        out.append({
            "theme": (t.get("id") or t.get("label", "")).strip().lower().replace(" ", "_") or "unknown",
            "label": t.get("label", ""),
            "emoji": "🔮",  # marks Gemini-derived themes in UI
            "source": "gemini",
            "score": {"high": 2.0, "medium": 1.5, "low": 1.0}.get(
                str(t.get("confidence", "")).lower(), 1.5
            ),
            "summary": t.get("summary", ""),
            "sectors_positive": t.get("sectors_positive") or [],
            "sectors_negative": t.get("sectors_negative") or [],
            "matched_articles": [],  # Gemini themes don't carry source headlines
            "impacted_positive": [],
            "impacted_negative": [],
            "confidence": t.get("confidence"),
        })
    return out
