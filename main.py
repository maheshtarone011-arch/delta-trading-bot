import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

APP_MODE = os.getenv("APP_MODE", "READ_ONLY").upper()
SYMBOL = os.getenv("DELTA_SYMBOL", "BTCUSD")
DELTA_BASE_URL = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange").rstrip("/")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Safety invariant: this Phase-1 service has no order-placement code or trading routes.
if APP_MODE != "READ_ONLY":
    raise RuntimeError("Only APP_MODE=READ_ONLY is supported in this build.")

app = FastAPI(title="BTC AI Trading Dashboard", version="0.1.0")


def get_json(url: str, timeout: int = 12) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "BTC-AI-ReadOnly/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Upstream API request failed: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or data.get("success") is False:
        raise HTTPException(status_code=502, detail="Delta API returned an unsuccessful response.")
    return data


def delta_ticker() -> dict[str, Any]:
    data = get_json(f"{DELTA_BASE_URL}/v2/tickers/{urllib.parse.quote(SYMBOL)}")
    result = data.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Unexpected Delta ticker response.")
    return result


def delta_candles(resolution: str, limit: int = 120) -> list[dict[str, Any]]:
    allowed = {"5m": 300, "15m": 900, "1h": 3600}
    if resolution not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported timeframe.")
    end = int(time.time())
    start = end - allowed[resolution] * limit
    query = urllib.parse.urlencode({"resolution": resolution, "symbol": SYMBOL, "start": start, "end": end})
    data = get_json(f"{DELTA_BASE_URL}/v2/history/candles?{query}")
    result = data.get("result")
    if not isinstance(result, list):
        raise HTTPException(status_code=502, detail="Unexpected Delta candles response.")
    return result[-limit:]


def build_market_snapshot() -> dict[str, Any]:
    ticker = delta_ticker()
    candles = {tf: delta_candles(tf) for tf in ("1h", "15m", "5m")}
    return {
        "mode": APP_MODE,
        "symbol": SYMBOL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker,
        "candles": candles,
    }


def ask_gemini(snapshot: dict[str, Any]) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured on the server.")
    # Only send a compact public-market snapshot; never send exchange credentials or account data.
    compact = {
        "symbol": snapshot["symbol"],
        "ticker": {k: snapshot["ticker"].get(k) for k in ("close", "mark_price", "open", "high", "low", "volume", "oi", "ltp_change_24h")},
        "candles": {
            tf: rows[-30:] for tf, rows in snapshot["candles"].items()
        },
    }
    prompt = (
        "You are a cautious market-analysis assistant, not an execution engine. "
        "Analyze this BTCUSD market snapshot using 1h trend, 15m setup, and 5m confirmation. "
        "Return: trend, setup, confirmation, risks, and a cautious conclusion. "
        "If data is insufficient, say so. Do not claim certainty, win rate, or guaranteed profit. "
        "Do not instruct an automated order. Data JSON:\n" + json.dumps(compact, separators=(",", ":"))
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(GEMINI_MODEL)}:generateContent?key={urllib.parse.quote(GEMINI_API_KEY)}"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Gemini request failed: {type(exc).__name__}") from exc
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Gemini returned an unexpected response.") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": APP_MODE}


@app.get("/api/status")
def status() -> dict[str, Any]:
    ticker = delta_ticker()
    return {
        "mode": APP_MODE,
        "symbol": SYMBOL,
        "price": ticker.get("mark_price") or ticker.get("close"),
        "change_24h": ticker.get("ltp_change_24h"),
        "volume": ticker.get("volume"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "orders_enabled": False,
    }


@app.get("/api/candles")
def candles() -> dict[str, Any]:
    return {tf: delta_candles(tf) for tf in ("1h", "15m", "5m")}


@app.post("/api/analyze")
def analyze() -> dict[str, Any]:
    snapshot = build_market_snapshot()
    return {"mode": APP_MODE, "orders_enabled": False, "analysis": ask_gemini(snapshot)}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD


DASHBOARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC AI Trading Dashboard</title>
<style>
:root{color-scheme:dark}body{margin:0;background:#0b1020;color:#e8edf7;font:15px system-ui}
main{max-width:980px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.card{background:#151d31;border:1px solid #293550;border-radius:14px;padding:18px;margin:14px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
small,.muted{color:#aab6cc}.value{font-size:26px;font-weight:700;margin-top:8px}
button{background:#78a7ff;color:#071226;border:0;border-radius:9px;padding:12px 16px;font-weight:700}
pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5} .pill{border:1px solid #c9a64d;color:#ffd76a;border-radius:20px;padding:6px 10px}
</style></head><body><main>
<div class="top"><div><h1>BTC AI Trading Dashboard</h1><div class="muted">Delta Exchange India · BTCUSD · Gemini analysis</div></div><span class="pill">READ-ONLY · ORDERS DISABLED</span></div>
<div class="grid">
<div class="card"><small>BTC Mark / Last Price</small><div class="value" id="price">Loading…</div></div>
<div class="card"><small>24h Change</small><div class="value" id="change">—</div></div>
<div class="card"><small>24h Volume</small><div class="value" id="volume">—</div></div>
<div class="card"><small>System Mode</small><div class="value">READ-ONLY</div></div>
</div>
<div class="card"><h2>AI Market Analysis</h2><p class="muted">Uses 1H trend, 15M setup and 5M confirmation. Analysis only; no orders can be placed.</p>
<button onclick="analyze()">Analyze with Gemini</button><pre id="analysis">Press Analyze to request an AI review.</pre></div>
<div class="card"><small id="updated">Waiting for market data…</small><p class="muted">This dashboard does not connect to private account data and cannot submit or cancel orders.</p></div>
</main><script>
async function refresh(){try{const r=await fetch('/api/status');if(!r.ok)throw Error('API '+r.status);const d=await r.json();document.getElementById('price').textContent=d.price??'—';document.getElementById('change').textContent=d.change_24h??'—';document.getElementById('volume').textContent=d.volume??'—';document.getElementById('updated').textContent='Updated: '+d.updated_at;}catch(e){document.getElementById('updated').textContent='Market data unavailable: '+e.message;}}
async function analyze(){const el=document.getElementById('analysis');el.textContent='Requesting Gemini analysis…';try{const r=await fetch('/api/analyze',{method:'POST'});const d=await r.json();if(!r.ok)throw Error(d.detail||'Analysis failed');el.textContent=d.analysis;}catch(e){el.textContent='Analysis unavailable: '+e.message;}}
refresh();setInterval(refresh,15000);
</script></body></html>"""
