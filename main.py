import os
import sys
import time
import json
import math
import hmac
import hashlib
import urllib.request
from datetime import datetime

# ================= CONFIGURATION =================
API_KEY = os.getenv("DELTA_API_KEY", "JLsvFhqsAq4w69dHBoXKIXSHIbG3C8")
API_SECRET = os.getenv("DELTA_API_SECRET", "7VPNutubQI7vfmRvXMtZcYkTi1nzXUQHFtEMYR40lbbVZ7VPDi6WvkDTozSc")
BASE_URL = "https://api.india.delta.exchange"
PRODUCT_ID = 131253  # XAUTUSD
PRODUCT_SYMBOL = "XAUTUSD"

STATE_FILE = "bot_state.json"

# Risk & Order Rules
RISK_PER_TRADE = 1.00      # $1 max loss
SL_POINTS = 14.0           # $14 move in gold = stop
CONTRACT_SIZE = 72         # 72 contracts at 60x leverage = ~$4.95 margin used (Target $5)
LEVERAGE = 60              # 60x Leverage

MAX_DAILY_LOSSES = 2
MAX_DAILY_WINS = 3
ZONE2_PROFIT = 0.50        # $0.50 profit -> Break-Even SL
ZONE3_PROFIT = 1.20        # $1.20 profit -> Trailing SL ($10 distance)
TRAIL_POINTS = 10.0

def api_request(method, path, payload=None):
    timestamp = str(int(time.time()))
    signature_data = method + timestamp + path
    data_bytes = None
    if payload:
        payload_str = json.dumps(payload)
        signature_data += payload_str
        data_bytes = payload_str.encode('utf-8')
        
    signature = hmac.new(API_SECRET.encode('utf-8'), signature_data.encode('utf-8'), hashlib.sha256).hexdigest()
    headers = {
        'api-key': API_KEY,
        'signature': signature,
        'timestamp': timestamp,
        'Content-Type': 'application/json',
        'User-Agent': 'DeltaBot-Cloud'
    }
    
    req = urllib.request.Request(BASE_URL + path, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] API Error on {path}: {e}")
        return None

def get_positions():
    res = api_request("GET", "/v2/positions/margined")
    if res and res.get("success"):
        for pos in res.get("result", []):
            if pos.get("product_id") == PRODUCT_ID and int(pos.get("size", 0)) > 0:
                return pos
    return None

def get_ticker():
    req = urllib.request.Request(f"{BASE_URL}/v2/tickers/{PRODUCT_SYMBOL}")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode('utf-8'))
            return data.get("result", {})
    except Exception as e:
        return {}

def get_l2_orderbook():
    req = urllib.request.Request(f"{BASE_URL}/v2/l2orderbook/{PRODUCT_SYMBOL}")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode('utf-8'))
            return data.get("result", {})
    except Exception as e:
        return {}

def place_market_order(side, size):
    payload = {
        "product_id": PRODUCT_ID,
        "size": size,
        "order_type": "market_order",
        "side": side
    }
    return api_request("POST", "/v2/orders", payload)

def run_cycle():
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except:
        state = {
            "today": today_str,
            "daily_wins": 0,
            "daily_losses": 0,
            "daily_pnl": 0.0,
            "in_position": False,
            "position": None
        }

    if state.get("today") != today_str:
        state["today"] = today_str
        state["daily_wins"] = 0
        state["daily_losses"] = 0
        state["daily_pnl"] = 0.0

    if state["daily_losses"] >= MAX_DAILY_LOSSES:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 2 LOSSES REACHED TODAY. TRADING STOPPED.")
        return
    if state["daily_wins"] >= MAX_DAILY_WINS:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🏆 3 WINS REACHED TODAY. DAY CLOSED WITH PROFIT!")
        return

    live_pos = get_positions()
    ticker = get_ticker()
    mark_price = float(ticker.get("mark_price", 0) or ticker.get("close", 0) or 0)
    if mark_price == 0:
        return

    # 1. POSITION MANAGEMENT (Trailing Stop Loss)
    if live_pos:
        state["in_position"] = True
        size = int(live_pos["size"])
        entry_price = float(live_pos["entry_price"])
        side = "buy"
        
        pos_data = state.get("position") or {
            "side": side,
            "entry_price": entry_price,
            "sl_price": entry_price - SL_POINTS,
            "zone": 1,
            "highest_price": entry_price
        }

        pnl = (mark_price - entry_price) * size * 0.001
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 IN POSITION | Entry: ${entry_price:.2f} | Current: ${mark_price:.2f} | PnL: ${pnl:+.4f} | SL: ${pos_data['sl_price']:.2f}")

        if mark_price > pos_data.get("highest_price", entry_price):
            pos_data["highest_price"] = mark_price

        if pnl >= ZONE3_PROFIT:
            new_sl = mark_price - TRAIL_POINTS
            if new_sl > pos_data["sl_price"]:
                pos_data["sl_price"] = new_sl
                pos_data["zone"] = 3
                print(f"🚀 ZONE 3 ACTIVE! Trailing SL moved to ${new_sl:.2f}")
        elif pnl >= ZONE2_PROFIT and pos_data.get("zone", 1) < 2:
            pos_data["sl_price"] = entry_price
            pos_data["zone"] = 2
            print(f"🛡️ ZONE 2 ACTIVE! SL moved to Break-Even: ${entry_price:.2f}")

        if mark_price <= pos_data["sl_price"]:
            print(f"🚨 STOP LOSS / TRAILING EXIT TRIGGERED at ${mark_price:.2f}! Closing position...")
            close_res = place_market_order("sell", size)
            if close_res and close_res.get("success"):
                if pnl > 0.05:
                    state["daily_wins"] += 1
                elif pnl < -0.05:
                    state["daily_losses"] += 1
                state["daily_pnl"] += pnl
                state["in_position"] = False
                state["position"] = None
                print(f"✅ Closed Position. Realized PnL: ${pnl:+.4f}")
            else:
                print("❌ Failed to close position!")
        else:
            state["position"] = pos_data

        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        return

    state["in_position"] = False
    state["position"] = None

    # 2. ENTRY LOGIC
    ob = get_l2_orderbook()
    bids = ob.get("buy", [])
    asks = ob.get("sell", [])

    if not bids or not asks:
        return

    bid_vol = sum(float(b.get("size", 0)) for b in bids[:5])
    ask_vol = sum(float(a.get("size", 0)) for a in asks[:5])
    ratio = bid_vol / max(ask_vol, 1)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 SCANNING | Mark: ${mark_price:.2f} | Bids: {bid_vol:.0f} vs Asks: {ask_vol:.0f} (Ratio: {ratio:.2f})")

    if ratio >= 2.0:
        print(f"🔥 BUY SETUP FOUND! Ratio {ratio:.1f}x. Placing BUY order for {CONTRACT_SIZE} contracts at 60x...")
        res = place_market_order("buy", CONTRACT_SIZE)
        if res and res.get("success"):
            avg_price = float(res["result"].get("average_fill_price", mark_price))
            print(f"🎉 BUY ORDER EXECUTED @ ${avg_price:.2f}!")
            state["in_position"] = True
            state["position"] = {
                "side": "buy",
                "entry_price": avg_price,
                "sl_price": avg_price - SL_POINTS,
                "zone": 1,
                "highest_price": avg_price
            }
        else:
            print("❌ Order placement failed:", res)
    else:
        print(f"⏳ Waiting for setup... Ratio: {ratio:.2f} (Need >= 2.0)")

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 DELTA EXCHANGE CLOUD BOT STARTED (24x7 AUTO-RUN)")
    print("=" * 60)
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"Error in cycle: {e}")
        # Har 15 second mein check karega taaki fast momentum miss na ho!
        time.sleep(15)
