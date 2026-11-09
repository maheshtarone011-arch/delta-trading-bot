# BTC AI Trading Dashboard — Phase 1 (Read-only)

A small FastAPI dashboard for Delta Exchange India public BTCUSD market data and optional Gemini analysis.

## Safety status
- **READ-ONLY ONLY**: no order placement, cancellation, leverage setting, or private account endpoints exist.
- Do not add Delta API keys. Public ticker/candle endpoints do not require them.
- Gemini key is read from the server environment only; never commit it.
- This is not a live trading bot and must not be treated as one.

## Features
- BTCUSD ticker from Delta India public REST API.
- 1h, 15m and 5m historical candles.
- Optional Gemini market commentary.
- Dashboard at `/`, health endpoint at `/health`.

## Run locally
1. Copy `.env.example` to `.env`.
2. Add your Gemini API key to `.env` (optional for market data; required for AI analysis).
3. Run:
   ```bash
   docker compose up --build -d
   ```
4. Open `http://127.0.0.1:8000` on the server or use an SSH tunnel. Do not expose port 8000 publicly without HTTPS and authentication.

## Environment
- `APP_MODE=READ_ONLY` (the application refuses other modes)
- `DELTA_SYMBOL=BTCUSD`
- `GEMINI_API_KEY`
- `GEMINI_MODEL=gemini-2.5-flash`

## Important credential incident
The previous public version of `main.py` contained hard-coded Delta credentials. Replacing this file does not erase old Git commits. Revoke those exposed credentials in Delta immediately, review API-key activity, and create new credentials only after the system has been reviewed. Do not reuse the exposed keys.

## Next phases
1. Validate public API data and Gemini response on the user's VPS.
2. Add paper trading with a separate simulator and durable state.
3. Test risk calculations, both long and short position handling, exchange-side protective orders and failure recovery.
4. Any real-order functionality requires a separate explicit approval after testing.
