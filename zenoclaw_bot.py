"""
ZenoClaw — Automated Crypto Trading Signal Bot for Telegram
Uses Yahoo Finance API — works from ALL servers worldwide, zero restrictions. v3
"""

import asyncio
import logging
import os
import time
from datetime import datetime, UTC

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.constants import ParseMode

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "YOUR_CHAT_ID")

SYMBOL        = "BTC-USD"
LEVERAGE      = 3
POSITION_USDT = 1200
MAX_RISK_PCT  = 2.0
VOLUME_MULT   = 2.0
CHECK_EVERY   = 15

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# DATA LAYER — Yahoo Finance (no geo-blocks ever)
# ─────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

def get_klines(limit=25):
    """Fetch 15m OHLCV candles from Yahoo Finance."""
    end   = int(time.time())
    start = end - (limit + 5) * 15 * 60   # a bit extra to ensure enough candles
    url   = f"https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}"
    params = {
        "interval":  "15m",
        "period1":   start,
        "period2":   end,
        "includePrePost": "false",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data   = resp.json()
    result = data["chart"]["result"][0]
    quotes = result["indicators"]["quote"][0]
    timestamps = result["timestamp"]

    candles = []
    for i in range(len(timestamps)):
        try:
            o = quotes["open"][i]
            h = quotes["high"][i]
            l = quotes["low"][i]
            c = quotes["close"][i]
            v = quotes["volume"][i]
            if None not in (o, h, l, c, v):
                candles.append({"open": o, "high": h, "low": l, "close": c, "volume": float(v)})
        except (IndexError, TypeError):
            continue

    # Return last `limit` complete candles (exclude the still-forming one)
    return candles[-(limit+1):-1]

def get_ticker_price():
    """Fetch current BTC price from Yahoo Finance."""
    url    = f"https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}"
    params = {"interval": "1m", "range": "1m"}
    resp   = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
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
    if rng == 0:
        return False, "flat candle"
    pos = (candle["close"] - candle["low"]) / rng
    if pos >= 0.70:
        return True, "strong close above resistance"
    elif pos >= 0.50:
        return True, "moderate close, breakout quality fair"
    else:
        return False, "weak close, breakout quality poor"

def calculate_stop_loss(candles, current_price):
    sl = min(c["low"] for c in candles[-4:-1])
    return round(min(sl, current_price * 0.997), 2)

def calculate_entry_zone(current_price, resistance):
    lower = round(resistance, 2)
    upper = round(current_price * 1.001, 2)
    return (min(lower, upper), max(lower, upper))

def calculate_risk(price, stop_loss, leverage):
    risk_pct = round(abs(price - stop_loss) / price * leverage * 100, 2)
    if risk_pct <= 1.5:   grade = "Low Risk — Excellent"
    elif risk_pct <= 2.0: grade = "Tradable"
    elif risk_pct <= 3.0: grade = "Moderate — Caution"
    else:                 grade = "High Risk — Skip"
    return (risk_pct, grade)

# ─────────────────────────────────────────────
# MESSAGE BUILDER
# ─────────────────────────────────────────────

def build_trade_message(price, resistance, vol_ratio, mom_desc,
                        stop_loss, entry_zone, risk_pct, risk_grade, timestamp):
    return (
        f"⚡ *ZenoClaw — Trade Signal*\n`{timestamp}`\n\n"
        f"📊 *Market Status*\n"
        f"• Current price: `{price:,.0f}`\n"
        f"• Key resistance: `{resistance:,.0f}`\n"
        f"• 15m candle status: {mom_desc}\n"
        f"• Volume change: current volume is `{vol_ratio}×` the average of previous 20 candles\n"
        f"• Momentum: short-term strength is positive, breakout quality looks solid\n\n"
        f"📐 *Strategy Calculation*\n"
        f"• Suggested direction: Long\n"
        f"• Suggested leverage: `{LEVERAGE}x`\n"
        f"• Suggested stop-loss: `{stop_loss:,.0f}`\n"
        f"• Suggested entry zone: `{entry_zone[0]:,.0f} – {entry_zone[1]:,.0f}`\n"
        f"• Estimated per-trade risk: `{risk_pct}%`\n"
        f"• Risk grade: *{risk_grade}*\n\n"
        f"✅ *Execution Result*\n"
        f"• Trade parameters generated by the risk model\n"
        f"• Position size: `{POSITION_USDT} USDT`\n"
        f"• Reference entry: `{price:,.0f}`\n"
        f"• Reference stop-loss: `{stop_loss:,.0f}`\n"
        f"• Follow-up plan: continue monitoring breakout; if volume fades, tighten the stop-loss\n\n"
        f"⏱ Next check in {CHECK_EVERY} minutes."
    )

def build_alert_message(price, resistance, reasons, timestamp):
    reason_lines = "\n".join(f"• {r}" for r in reasons)
    return (
        f"⚠️ *ZenoClaw — Alert Only Mode*\n`{timestamp}`\n\n"
        f"📊 Potential breakout signal detected\n"
        f"• Price: `{price:,.0f}` | Resistance: `{resistance:,.0f}`\n\n"
        f"🚫 *Risk conditions too high — no trade opened:*\n"
        f"{reason_lines}\n\n"
        f"🔍 Still monitoring. Next structural check in {CHECK_EVERY} minutes."
    )

# ─────────────────────────────────────────────
# CORE ANALYSIS LOOP
# ─────────────────────────────────────────────

async def run_analysis(bot):
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"[ZenoClaw] Running analysis at {timestamp}")
    try:
        candles    = get_klines(limit=25)
        price      = get_ticker_price()
        resistance = detect_key_resistance(candles)
        log.info(f"Price: {price:.2f} | Resistance: {resistance:.2f} | Candles: {len(candles)}")

        latest = candles[-1]
        if not is_breakout_candle(latest, resistance):
            log.info("No breakout detected — monitoring only.")
            return

        vol_ok, vol_ratio    = volume_confirmation(candles)
        mom_ok, mom_desc     = momentum_check(latest)
        stop_loss            = calculate_stop_loss(candles, price)
        entry_zone           = calculate_entry_zone(price, resistance)
        risk_pct, risk_grade = calculate_risk(price, stop_loss, LEVERAGE)
        tradeable            = risk_pct <= MAX_RISK_PCT

        if tradeable and vol_ok and mom_ok:
            msg = build_trade_message(price, resistance, vol_ratio, mom_desc,
                                      stop_loss, entry_zone, risk_pct, risk_grade, timestamp)
            log.info("✅ TRADE SIGNAL sent")
        else:
            reasons = []
            if not vol_ok:    reasons.append(f"Volume only {vol_ratio}× avg (need {VOLUME_MULT}×)")
            if not mom_ok:    reasons.append(f"Momentum weak: {mom_desc}")
            if not tradeable: reasons.append(f"Risk {risk_pct}% exceeds {MAX_RISK_PCT}% max")
            msg = build_alert_message(price, resistance, reasons, timestamp)
            log.info(f"⚠️  ALERT-ONLY — {reasons}")

        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        log.error(f"Analysis error: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"❌ ZenoClaw error: `{e}`\nBot continues running.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────

async def main():
    bot  = Bot(token=TELEGRAM_BOT_TOKEN)
    info = await bot.get_me()
    log.info(f"ZenoClaw bot started: @{info.username}")

    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            "✅ *ZenoClaw 24h monitoring is now active*\n"
            "Continuously tracking BTC/USD 15m candle structure and volume changes\n\n"
            "*Monitoring Rules*\n"
            "• Symbol: BTC/USD (perpetual)\n"
            "• Candles: 15m\n"
            "• Trigger: key-level breakout + volume expansion confirmation\n"
            "• Execution logic: after a breakout, the system automatically calculates acceptable leverage, stop-loss range, and position size\n"
            "• Risk control: if projected risk is too high, the system sends an alert only and does not open a trade\n\n"
            f"⏱ Checking every {CHECK_EVERY} minutes."
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_analysis, "interval", minutes=CHECK_EVERY, args=[bot], id="zenoclaw")
    scheduler.start()
    await run_analysis(bot)

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
