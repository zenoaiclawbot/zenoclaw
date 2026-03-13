"""
ZenoClaw — Public Multi-User Crypto Trading Signal Bot
Uses only basic Python asyncio + direct HTTP calls.
No telegram library conflicts. Works on Python 3.14.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, UTC
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")

LEVERAGE      = 3
POSITION_USDT = 1200
MAX_RISK_PCT  = 2.0
VOLUME_MULT   = 2.0
CHECK_EVERY   = 15 * 60  # 15 minutes in seconds

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ─────────────────────────────────────────────
# USER STORAGE
# ─────────────────────────────────────────────

USERS_FILE = "subscribers.json"

def load_users():
    if Path(USERS_FILE).exists():
        with open(USERS_FILE) as f:
            return set(json.load(f))
    return set()

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)

subscribers = load_users()

# ─────────────────────────────────────────────
# TELEGRAM HTTP FUNCTIONS (no library needed)
# ─────────────────────────────────────────────

def tg_request(method, data=None):
    """Make a direct HTTP request to Telegram API."""
    url = f"{TELEGRAM_API}/{method}"
    if data:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload,
              headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"Telegram API error ({method}): {e}")
        return None

def send_message(chat_id, text):
    """Send a message to a Telegram chat."""
    return tg_request("sendMessage", {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "Markdown",
    })

def get_updates(offset=None):
    """Get new messages from Telegram."""
    data = {"timeout": 30, "allowed_updates": ["message"]}
    if offset:
        data["offset"] = offset
    return tg_request("getUpdates", data)

def get_me():
    return tg_request("getMe")

# ─────────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────────

def handle_start(chat_id, first_name):
    subscribers.add(chat_id)
    save_users(subscribers)
    log.info(f"New subscriber: {chat_id} ({first_name}) | Total: {len(subscribers)}")
    send_message(chat_id,
        f"👋 Welcome to *ZenoClaw*, {first_name}!\n\n"
        f"✅ You are now subscribed to BTC/USD trade signals.\n\n"
        f"📊 *What you will receive:*\n"
        f"• ⚡ Trade signals when BTC breaks key levels\n"
        f"• ⚠️ Alert-only messages when risk is too high\n"
        f"• Checks every 15 minutes, 24/7\n\n"
        f"*Commands:*\n"
        f"/start — Subscribe to signals\n"
        f"/stop — Unsubscribe\n"
        f"/status — Check current BTC price\n\n"
        f"_Sit back and let ZenoClaw watch the market for you!_ 🚀"
    )

def handle_stop(chat_id):
    subscribers.discard(chat_id)
    save_users(subscribers)
    send_message(chat_id,
        "❌ You have been unsubscribed from ZenoClaw signals.\n"
        "Send /start anytime to resubscribe."
    )

def handle_status(chat_id):
    send_message(chat_id, "🔍 Fetching current BTC price...")
    try:
        candles    = get_klines(limit=25)
        price      = get_ticker_price()
        resistance = detect_key_resistance(candles)
        diff_pct   = round((resistance - price) / price * 100, 2)
        send_message(chat_id,
            f"📊 *ZenoClaw — Market Status*\n\n"
            f"• BTC Price: `${price:,.2f}`\n"
            f"• Key Resistance: `${resistance:,.2f}`\n"
            f"• Distance to breakout: `{diff_pct}%`\n"
            f"• Status: {'🟢 Near breakout!' if diff_pct < 0.5 else '🟡 Monitoring...'}\n\n"
            f"_Next check in 15 minutes_"
        )
    except Exception as e:
        send_message(chat_id, f"❌ Error fetching price: {e}")

def process_update(update):
    """Process a single Telegram update."""
    try:
        msg  = update.get("message", {})
        text = msg.get("text", "")
        chat = msg.get("chat", {})
        user = msg.get("from", {})
        chat_id    = chat.get("id")
        first_name = user.get("first_name", "Trader")
        if not chat_id or not text:
            return
        cmd = text.split()[0].lower().replace(f"@{BOT_USERNAME}", "")
        if cmd == "/start":   handle_start(chat_id, first_name)
        elif cmd == "/stop":  handle_stop(chat_id)
        elif cmd == "/status": handle_status(chat_id)
    except Exception as e:
        log.error(f"Error processing update: {e}")

# ─────────────────────────────────────────────
# DATA LAYER — Yahoo Finance
# ─────────────────────────────────────────────

YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

def yf_get(url, params):
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers=YF_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def get_klines(limit=25):
    end    = int(time.time())
    start  = end - (limit + 5) * 15 * 60
    data   = yf_get("https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD",
                    {"interval": "15m", "period1": start, "period2": end, "includePrePost": "false"})
    result = data["chart"]["result"][0]
    quotes = result["indicators"]["quote"][0]
    candles = []
    for i in range(len(result["timestamp"])):
        try:
            o, h, l, c, v = quotes["open"][i], quotes["high"][i], quotes["low"][i], quotes["close"][i], quotes["volume"][i]
            if None not in (o, h, l, c, v):
                candles.append({"open": o, "high": h, "low": l, "close": c, "volume": float(v)})
        except (IndexError, TypeError):
            continue
    return candles[-(limit+1):-1]

def get_ticker_price():
    data = yf_get("https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD",
                  {"interval": "1m", "range": "1m"})
    return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])

# ─────────────────────────────────────────────
# ANALYSIS ENGINE
# ─────────────────────────────────────────────

def detect_key_resistance(candles):
    return max(c["high"] for c in candles[-21:-1])

def is_breakout_candle(candle, resistance):
    return candle["close"] > resistance * 1.001

def volume_confirmation(candles):
    avg_vol  = sum(c["volume"] for c in candles[-21:-1]) / 20
    curr_vol = candles[-1]["volume"]
    ratio    = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 0
    return (ratio >= VOLUME_MULT, ratio)

def momentum_check(candle):
    rng = candle["high"] - candle["low"]
    if rng == 0: return False, "flat candle"
    pos = (candle["close"] - candle["low"]) / rng
    if pos >= 0.70:   return True,  "strong close above resistance"
    elif pos >= 0.50: return True,  "moderate close, breakout quality fair"
    else:             return False, "weak close, breakout quality poor"

def calculate_stop_loss(candles, price):
    return round(min(min(c["low"] for c in candles[-4:-1]), price * 0.997), 2)

def calculate_entry_zone(price, resistance):
    return (round(min(resistance, price), 2), round(max(resistance, price * 1.001), 2))

def calculate_risk(price, stop_loss):
    risk_pct = round(abs(price - stop_loss) / price * LEVERAGE * 100, 2)
    if risk_pct <= 1.5:   grade = "Low Risk — Excellent"
    elif risk_pct <= 2.0: grade = "Tradable"
    elif risk_pct <= 3.0: grade = "Moderate — Caution"
    else:                 grade = "High Risk — Skip"
    return (risk_pct, grade)

# ─────────────────────────────────────────────
# MESSAGE BUILDER
# ─────────────────────────────────────────────

def build_trade_message(price, resistance, vol_ratio, mom_desc, stop_loss, entry_zone, risk_pct, risk_grade, timestamp):
    return (
        f"⚡ *ZenoClaw — Trade Signal*\n`{timestamp}`\n\n"
        f"📊 *Market Status*\n"
        f"• Current price: `{price:,.0f}`\n"
        f"• Key resistance: `{resistance:,.0f}`\n"
        f"• 15m candle status: {mom_desc}\n"
        f"• Volume: `{vol_ratio}×` the 20-candle average\n"
        f"• Momentum: short-term strength positive ✅\n\n"
        f"📐 *Strategy Calculation*\n"
        f"• Direction: Long 📈\n"
        f"• Suggested leverage: `{LEVERAGE}x`\n"
        f"• Suggested stop-loss: `{stop_loss:,.0f}`\n"
        f"• Entry zone: `{entry_zone[0]:,.0f} – {entry_zone[1]:,.0f}`\n"
        f"• Per-trade risk: `{risk_pct}%`\n"
        f"• Risk grade: *{risk_grade}*\n\n"
        f"✅ *Execution Result*\n"
        f"• Position size: `{POSITION_USDT} USDT`\n"
        f"• Reference entry: `{price:,.0f}`\n"
        f"• Reference stop-loss: `{stop_loss:,.0f}`\n"
        f"• Follow-up: monitor breakout; if volume fades, tighten SL\n\n"
        f"⏱ Next check in 15 minutes."
    )

def build_alert_message(price, resistance, reasons, timestamp):
    return (
        f"⚠️ *ZenoClaw — Alert Only Mode*\n`{timestamp}`\n\n"
        f"📊 Potential breakout detected\n"
        f"• Price: `{price:,.0f}` | Resistance: `{resistance:,.0f}`\n\n"
        f"🚫 *No trade opened:*\n"
        + "\n".join(f"• {r}" for r in reasons) +
        f"\n\n🔍 Still monitoring. Next check in 15 minutes."
    )

# ─────────────────────────────────────────────
# CORE ANALYSIS
# ─────────────────────────────────────────────

def run_analysis():
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"[ZenoClaw] Analysis at {timestamp} | Subscribers: {len(subscribers)}")
    if not subscribers:
        log.info("No subscribers yet.")
        return
    try:
        candles    = get_klines(limit=25)
        price      = get_ticker_price()
        resistance = detect_key_resistance(candles)
        log.info(f"Price: {price:.2f} | Resistance: {resistance:.2f}")

        latest = candles[-1]
        if not is_breakout_candle(latest, resistance):
            log.info("No breakout — monitoring only.")
            return

        vol_ok, vol_ratio    = volume_confirmation(candles)
        mom_ok, mom_desc     = momentum_check(latest)
        stop_loss            = calculate_stop_loss(candles, price)
        entry_zone           = calculate_entry_zone(price, resistance)
        risk_pct, risk_grade = calculate_risk(price, stop_loss)
        tradeable            = risk_pct <= MAX_RISK_PCT

        if tradeable and vol_ok and mom_ok:
            msg = build_trade_message(price, resistance, vol_ratio, mom_desc,
                                      stop_loss, entry_zone, risk_pct, risk_grade, timestamp)
            log.info("✅ TRADE SIGNAL — broadcasting to all subscribers")
        else:
            reasons = []
            if not vol_ok:    reasons.append(f"Volume only {vol_ratio}× avg (need {VOLUME_MULT}×)")
            if not mom_ok:    reasons.append(f"Momentum weak: {mom_desc}")
            if not tradeable: reasons.append(f"Risk {risk_pct}% exceeds {MAX_RISK_PCT}% max")
            msg = build_alert_message(price, resistance, reasons, timestamp)
            log.info(f"⚠️ ALERT — broadcasting to all subscribers")

        failed = []
        for chat_id in list(subscribers):
            result = send_message(chat_id, msg)
            if not result or not result.get("ok"):
                log.warning(f"Failed to send to {chat_id}")
                failed.append(chat_id)
        for chat_id in failed:
            subscribers.discard(chat_id)
        if failed:
            save_users(subscribers)

    except Exception as e:
        log.error(f"Analysis error: {e}", exc_info=True)

# ─────────────────────────────────────────────
# MAIN LOOP — pure Python, no libraries
# ─────────────────────────────────────────────

BOT_USERNAME = ""

def main():
    global BOT_USERNAME

    # Get bot info
    me = get_me()
    if me and me.get("ok"):
        BOT_USERNAME = me["result"]["username"]
        log.info(f"ZenoClaw started: @{BOT_USERNAME}")
    else:
        log.error("Could not connect to Telegram. Check your bot token.")
        return

    # Send startup message to existing subscribers
    for chat_id in list(subscribers):
        send_message(chat_id,
            "✅ *ZenoClaw 24h monitoring is now active*\n"
            "Continuously tracking BTC/USD 15m candle structure and volume changes\n\n"
            "*Monitoring Rules*\n"
            "• Symbol: BTC/USD\n"
            "• Candles: 15m\n"
            "• Trigger: key-level breakout + volume expansion\n"
            "• Risk control: if risk too high → alert only\n\n"
            "⏱ Checking every 15 minutes."
        )

    offset         = None
    last_analysis  = 0

    log.info("Entering main loop — listening for commands and monitoring market...")

    while True:
        # 1. Check for new Telegram messages
        try:
            updates = get_updates(offset)
            if updates and updates.get("ok"):
                for update in updates.get("result", []):
                    offset = update["update_id"] + 1
                    process_update(update)
        except Exception as e:
            log.error(f"Update polling error: {e}")

        # 2. Run market analysis every 15 minutes
        now = time.time()
        if now - last_analysis >= CHECK_EVERY:
            run_analysis()
            last_analysis = now

        # Small sleep to avoid hammering Telegram API
        time.sleep(2)

if __name__ == "__main__":
    main()
