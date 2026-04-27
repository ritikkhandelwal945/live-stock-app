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

## Notes

- **Kite Personal tier** gives free access to holdings, positions, orders. It does **not** include historical data or live quotes — that's why we use yfinance for those (15-min delayed, free).
- If you bought/sold today, holdings reflect Zerodha-side state instantly.
- Tech analysis uses RSI, MACD, SMA, Bollinger, Volume on daily candles.
- Fundamental and news scoring are stubs — only technical signals contribute today.
