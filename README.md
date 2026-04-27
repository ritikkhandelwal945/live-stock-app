# Live Stock App

Stock analysis & recommendation app for Zerodha holdings. **Free to run** — uses Zerodha's free **Kite Connect Personal** tier for portfolio sync, and Yahoo Finance for live prices and historical data.

## Setup

```
uv sync
cd web && npm install
```

### Connect to Zerodha (recommended)

1. Create a free Kite Connect app at https://developers.kite.trade/apps:
   - **Type:** Personal (free)
   - **Redirect URL:** `http://127.0.0.1:5678/callback`
2. Copy the API Key and API Secret into `.env`:
   ```
   cp .env.example .env
   # then edit .env
   ```
3. Authenticate (saves a token for the day):
   ```
   uv run stock-app auth
   ```
   The token is cached at `data/.kite_token.json` and reused across uvicorn restarts. Zerodha invalidates all access tokens daily at **6 AM IST** regardless — that's a SEBI security mandate, not something we can override. Set `KITE_TOKEN_FILE=/path/to/shared.json` in `.env` to share the cache across machines via a synced folder.

### Or upload a CSV (no Kite needed)

Skip the Kite setup. Use the **Upload CSV** button in the UI with your Zerodha Console export (`https://console.zerodha.com/portfolio/holdings` → Download → CSV).

## Run

Two terminals:

**Terminal 1 — API**
```
uv run uvicorn src.api.main:app --reload --port 8000
```

**Terminal 2 — Web**
```
cd web && npm start
```

Open http://localhost:4200.

## Daily flow

1. Each morning Zerodha tokens expire (~6 AM IST). Re-run `uv run stock-app auth`.
2. Open the UI. Holdings auto-sync from Zerodha (badge shows "Live · Zerodha").
3. **Recommendations** tab runs technical analysis on every holding using free yfinance daily candles.

If the Kite token expires or is missing, the UI falls back to your last CSV upload (if any).

## API endpoints

| Endpoint                          | Description                                   |
| --------------------------------- | --------------------------------------------- |
| `GET /api/health`                 | Status (Kite + CSV state)                     |
| `GET /api/auth/status`            | Whether the API is configured & authenticated |
| `POST /api/auth/logout`           | Clear stored Kite token                       |
| `GET /api/holdings`               | Holdings (Kite if available, else CSV)        |
| `GET /api/positions`              | Open positions (Kite only)                    |
| `POST /api/holdings/upload`       | Upload Zerodha CSV/XLSX export                |
| `DELETE /api/holdings`            | Clear stored CSV holdings                     |
| `GET /api/recommendations`        | Score + action for every holding              |
| `GET /api/analyze/{symbol}`       | Score + action for a single NSE symbol        |

Interactive docs: http://localhost:8000/docs.

## Daily email report (GitHub Actions)

Pre-wired workflow at `.github/workflows/daily-email.yml` runs every weekday at 09:30 AM IST, generates a PDF of recommendations, and emails it to you.

**One-time setup:**

1. Add these GitHub Secrets at `Settings → Secrets and variables → Actions`:
   | Secret | Value |
   |---|---|
   | `SMTP_USER` | your gmail address |
   | `SMTP_PASSWORD` | a 16-char Gmail [App Password](https://myaccount.google.com/apppasswords) (needs 2FA on) |
   | `REPORT_EMAIL_TO` | where to send the report (usually same as SMTP_USER) |
   | `SMTP_HOST` | optional, default `smtp.gmail.com` |
   | `SMTP_PORT` | optional, default `465` |

2. (Optional) Customize the watchlist by committing `data/watchlist.json`:
   ```
   cp data/watchlist.json.example data/watchlist.json
   # edit, commit, push
   ```
   If absent, falls back to a NIFTY-50-like default set in `scripts/daily_email.py`.

3. Trigger a test run from the Actions tab → Daily stock recommendations email → Run workflow. Check your inbox in ~5 minutes.

**Why this works without your laptop:** GitHub Actions runs in the cloud daily on its own. It does **not** include your live Zerodha portfolio — the daily email is for the public watchlist only (Kite tokens can't survive headless cloud auth). Your local app continues to give live portfolio analysis.

## Notes

- **Kite Personal tier** gives free access to holdings, positions, orders. It does **not** include historical data or live quotes — that's why we use yfinance for those (15-min delayed, free).
- If you bought/sold today, holdings reflect Zerodha-side state instantly.
- Tech analysis uses RSI, MACD, SMA, Bollinger, Volume on daily candles.
- Fundamental and news scoring are stubs — only technical signals contribute today.
