"""
ZenoClaw — Public Multi-User Crypto Trading Signal Bot
Anyone who sends /start receives BTC signals automatically.
Uses Yahoo Finance API — works from all servers worldwide.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, UTC
from pathlib import Path

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")

LEVERAGE      = 3
POSITION_USDT = 1200
MAX_RISK_PCT  = 2.0
VOLUME_MULT   = 2.0
CHECK_EVERY   = 15

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# USER STORAGE — save subscribers in a file
# ─────────────────────────────────────────────

USERS_FILE = "subscribers.json"

def load_users() -> set:
    if Path(USERS_FILE).exists():
        with open(USERS_FILE) as f:
            return set(json.load(f))
    return set()

def save_users(users: set):
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)

subscribers = load_users()

# ─────────────────────────────────────────────
# TELEGRAM COMMANDS
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anyone who sends /start gets added to subscribers."""
    chat_id   = update.effective_chat.id
    user_name = update.effective_user.first_name or "Trader"
    subscribers.add(chat_id)
    save_users(subscribers)
    log.info(f"New subscriber: {chat_id} ({user_name}) | Total: {len(subscribers)}")
    await update.message.reply_text(
        f"👋 Welcome to *ZenoClaw*, {user_name}!\n\n"
        f"✅ You are now subscribed to BTC/USD trade signals.\n\n"
        f"📊 *What you will receive:*\n"
        f"• ⚡ Trade signals when BTC breaks key levels\n"
        f"• ⚠️ Alert-only messages when risk is too high\n"
        f"• Checks every {CHECK_EVERY} minutes, 24/7\n\n"
        f"*Commands:*\n"
        f"/start — Subscribe to signals\n"
        f"/stop — Unsubscribe\n"
        f"/status — Check current BTC price\n\n"
        f"_Sit back and let ZenoClaw watch the market for you!_ 🚀",
        parse_mode=ParseMode.MARKDOWN,
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe from signals."""
    chat_id = update.effective_chat.id
    subscribers.discard(chat_id)
    save_users(subscribers)
    log.info(f"Unsubscribed: {chat_id} | Total: {len(subscribers)}")
    await update.message.reply_text(
        "❌ You have been unsubscribed from ZenoClaw signals.\n"
        "Send /start anytime to resubscribe.",
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current BTC price and market status."""
    await update.message.reply_text("🔍 Fetching current BTC price...")
    try:
        candles    = get_klines(limit=25)
        price      = get_ticker_price()
        resistance = detect_key_resistance(candles)
        diff_pct   = round((resistance - price) / price * 100, 2)
        await update.message.reply_text(
            f"📊 *ZenoClaw — Market Status*\n\n"
            f"• BTC Price: `${price:,.2f}`\n"
            f"• Key Resistance: `${resistance:,.2f}`\n"
            f"• Distance to breakout: `{diff_pct}%`\n"
            f"• Status: {'🟢 Near breakout!' if diff_pct < 0.5 else '🟡 Monitoring...'}\n\n"
            f"_Next check in {CHECK_EVERY} minutes_",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching price: {e}")

# ─────────────────────────────────────────────
# DATA LAYER — Yahoo Finance
# ─────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

def get_klines(limit=25):
    end    = int(time.time())
    start  = end - (limit + 5) * 15 * 60
    url    = "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
    params = {"interval": "15m", "period1": start, "period2": end, "includePrePost": "false"}
    resp   = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data   = resp.json()
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
    url    = "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
    params = {"interval": "1m", "range": "1m"}
    resp   = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return float(resp.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])

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
    if rng == 0:
        return False, "flat candle"
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
        f"⏱ Next check in {CHECK_EVERY} minutes."
    )

def build_alert_message(price, resistance, reasons, timestamp):
    return (
        f"⚠️ *ZenoClaw — Alert Only Mode*\n`{timestamp}`\n\n"
        f"📊 Potential breakout detected\n"
        f"• Price: `{price:,.0f}` | Resistance: `{resistance:,.0f}`\n\n"
        f"🚫 *No trade opened:*\n"
        + "\n".join(f"• {r}" for r in reasons) +
        f"\n\n🔍 Still monitoring. Next check in {CHECK_EVERY} minutes."
    )

# ─────────────────────────────────────────────
# CORE ANALYSIS — broadcasts to ALL subscribers
# ─────────────────────────────────────────────

async def run_analysis(bot: Bot):
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
            msg = build_trade_message(price, resistance, vol_ratio, mom_desc, stop_loss, entry_zone, risk_pct, risk_grade, timestamp)
            log.info("✅ TRADE SIGNAL — broadcasting to all subscribers")
        else:
            reasons = []
            if not vol_ok:    reasons.append(f"Volume only {vol_ratio}× avg (need {VOLUME_MULT}×)")
            if not mom_ok:    reasons.append(f"Momentum weak: {mom_desc}")
            if not tradeable: reasons.append(f"Risk {risk_pct}% exceeds {MAX_RISK_PCT}% max")
            msg = build_alert_message(price, resistance, reasons, timestamp)
            log.info(f"⚠️ ALERT — broadcasting to all subscribers")

        # Send to ALL subscribers
        failed = []
        for chat_id in list(subscribers):
            try:
                await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.warning(f"Failed to send to {chat_id}: {e}")
                failed.append(chat_id)

        # Remove users who blocked the bot
        for chat_id in failed:
            subscribers.discard(chat_id)
        if failed:
            save_users(subscribers)

    except Exception as e:
        log.error(f"Analysis error: {e}", exc_info=True)

# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────

async def post_init(application):
    """Start the scheduler after the bot initializes."""
    bot = application.bot
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_analysis, "interval", minutes=CHECK_EVERY, args=[bot], id="zenoclaw")
    scheduler.start()
    await run_analysis(bot)
    log.info(f"ZenoClaw scheduler started. Subscribers: {len(subscribers)}")

def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop",  stop))
    app.add_handler(CommandHandler("status", status))

    log.info("ZenoClaw starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
