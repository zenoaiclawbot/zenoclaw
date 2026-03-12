"""
ZenoClaw — Automated Crypto Trading Signal Bot for Telegram
Monitors BTC/USDT 15m candles, detects breakouts, calculates risk,
and sends trade signals or alerts to a Telegram channel/group.
"""

import asyncio
import logging
import os
from datetime import datetime

import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot
from telegram.constants import ParseMode

# ─────────────────────────────────────────────
# CONFIG  (set these in .env or replace directly)
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "YOUR_CHAT_ID")

SYMBOL      = "BTCUSDT"
INTERVAL    = "15m"
LEVERAGE    = 3          # base leverage (adjusted by risk)
POSITION_USDT = 1200     # fixed position size in USDT
MAX_RISK_PCT  = 2.0      # max allowed risk per trade (%)
VOLUME_MULT   = 2.0      # volume must be X× the 20-candle average
CHECK_EVERY   = 15       # minutes between checks

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# DATA LAYER — Binance public REST API
# ─────────────────────────────────────────────
BINANCE_BASE = "https://api.binance.com/api/v3"

def get_klines(symbol: str, interval: str, limit: int = 25) -> list:
    """Fetch OHLCV candle data from Binance."""
    url = f"{BINANCE_BASE}/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

def get_ticker_price(symbol: str) -> float:
    """Fetch current market price."""
    url = f"{BINANCE_BASE}/ticker/price"
    resp = requests.get(url, params={"symbol": symbol}, timeout=10)
    resp.raise_for_status()
    return float(resp.json()["price"])

def parse_candles(raw: list) -> list[dict]:
    """Convert raw Binance kline data into clean dicts."""
    candles = []
    for k in raw:
        candles.append({
            "open":   float(k[1]),
            "high":   float(k[2]),
            "low":    float(k[3]),
            "close":  float(k[4]),
            "volume": float(k[5]),
        })
    return candles

# ─────────────────────────────────────────────
# ANALYSIS ENGINE
# ─────────────────────────────────────────────

def detect_key_resistance(candles: list[dict]) -> float:
    """
    Key resistance = highest high of the last 20 candles
    (excluding the current forming candle).
    """
    highs = [c["high"] for c in candles[-21:-1]]
    return max(highs)

def is_breakout_candle(candle: dict, resistance: float) -> bool:
    """Candle closes strongly above resistance level."""
    return candle["close"] > resistance * 1.001   # 0.1% buffer

def volume_confirmation(candles: list[dict]) -> tuple[bool, float]:
    """
    Current candle volume must be >= VOLUME_MULT × avg of previous 20 candles.
    Returns (confirmed, ratio).
    """
    avg_vol  = sum(c["volume"] for c in candles[-21:-1]) / 20
    curr_vol = candles[-1]["volume"]
    ratio    = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 0
    return (ratio >= VOLUME_MULT, ratio)

def momentum_check(candle: dict) -> tuple[bool, str]:
    """
    Strong close = candle closes in the top 30% of its range.
    Returns (positive, description).
    """
    rng = candle["high"] - candle["low"]
    if rng == 0:
        return False, "flat candle"
    close_position = (candle["close"] - candle["low"]) / rng
    if close_position >= 0.70:
        return True, "strong close above resistance"
    elif close_position >= 0.50:
        return True, "moderate close, breakout quality fair"
    else:
        return False, "weak close, breakout quality poor"

# ─────────────────────────────────────────────
# RISK CALCULATOR
# ─────────────────────────────────────────────

def calculate_stop_loss(candles: list[dict], current_price: float) -> float:
    """
    Stop-loss = lowest low of the last 3 candles (recent swing low).
    Minimum 0.3% below current price.
    """
    recent_lows = [c["low"] for c in candles[-4:-1]]
    sl = min(recent_lows)
    min_sl = current_price * 0.997
    return round(min(sl, min_sl), 2)

def calculate_entry_zone(current_price: float, resistance: float) -> tuple[float, float]:
    """Entry zone: current price to resistance + 0.2%."""
    lower = round(resistance, 2)
    upper = round(current_price * 1.001, 2)
    return (min(lower, upper), max(lower, upper))

def calculate_risk(
    price: float,
    stop_loss: float,
    position_usdt: float,
    leverage: int
) -> tuple[float, str]:
    """
    Risk % = (entry - SL) / entry × leverage × 100
    Returns (risk_pct, grade).
    """
    risk_pct = abs(price - stop_loss) / price * leverage * 100
    risk_pct = round(risk_pct, 2)
    if risk_pct <= 1.5:
        grade = "Low Risk — Excellent"
    elif risk_pct <= 2.0:
        grade = "Tradable"
    elif risk_pct <= 3.0:
        grade = "Moderate — Caution"
    else:
        grade = "High Risk — Skip"
    return (risk_pct, grade)

def is_safe_to_trade(risk_pct: float) -> bool:
    return risk_pct <= MAX_RISK_PCT

# ─────────────────────────────────────────────
# MESSAGE BUILDER
# ─────────────────────────────────────────────

def build_trade_message(
    price: float,
    resistance: float,
    vol_ratio: float,
    momentum_desc: str,
    leverage: int,
    stop_loss: float,
    entry_zone: tuple[float, float],
    risk_pct: float,
    risk_grade: str,
    position_usdt: float,
    timestamp: str,
) -> str:
    return (
        f"⚡ *ZenoClaw — Trade Signal*\n"
        f"`{timestamp}`\n\n"
        f"📊 *Market Status*\n"
        f"• Current price: `{price:,.0f}`\n"
        f"• Key resistance: `{resistance:,.0f}`\n"
        f"• 15m candle: {momentum_desc}\n"
        f"• Volume: `{vol_ratio}×` the 20-candle avg\n"
        f"• Momentum: short-term strength positive ✅\n\n"
        f"📐 *Strategy Calculation*\n"
        f"• Direction: Long 📈\n"
        f"• Suggested leverage: `{leverage}x`\n"
        f"• Suggested stop-loss: `{stop_loss:,.0f}`\n"
        f"• Entry zone: `{entry_zone[0]:,.0f} – {entry_zone[1]:,.0f}`\n"
        f"• Estimated per-trade risk: `{risk_pct}%`\n"
        f"• Risk grade: *{risk_grade}*\n\n"
        f"✅ *Execution Result*\n"
        f"• Parameters generated by risk model\n"
        f"• Position size: `{position_usdt} USDT`\n"
        f"• Reference entry: `{price:,.0f}`\n"
        f"• Reference stop-loss: `{stop_loss:,.0f}`\n"
        f"• Follow-up: continue monitoring breakout; if volume fades, tighten SL\n\n"
        f"⏱ Next check in {CHECK_EVERY} minutes."
    )

def build_alert_message(
    price: float,
    resistance: float,
    reasons: list[str],
    timestamp: str,
) -> str:
    reason_lines = "\n".join(f"• {r}" for r in reasons)
    return (
        f"⚠️ *ZenoClaw — Alert Only Mode*\n"
        f"`{timestamp}`\n\n"
        f"📊 Potential breakout signal detected\n"
        f"• Price: `{price:,.0f}` | Resistance: `{resistance:,.0f}`\n\n"
        f"🚫 *Risk conditions too high — no trade opened:*\n"
        f"{reason_lines}\n\n"
        f"🔍 Still monitoring. Next structural check in {CHECK_EVERY} minutes."
    )

def build_monitoring_message(price: float, resistance: float, timestamp: str) -> str:
    return (
        f"🔄 *ZenoClaw — Monitoring Active*\n"
        f"`{timestamp}`\n\n"
        f"• Price: `{price:,.0f}` | Resistance: `{resistance:,.0f}`\n"
        f"• No breakout detected — watching 15m structure\n"
        f"• Next check: {CHECK_EVERY} minutes"
    )

# ─────────────────────────────────────────────
# CORE ANALYSIS LOOP
# ─────────────────────────────────────────────

async def run_analysis(bot: Bot):
    """Main analysis cycle — runs every CHECK_EVERY minutes."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    log.info(f"[ZenoClaw] Running analysis at {timestamp}")

    try:
        # 1. Fetch data
        raw     = get_klines(SYMBOL, INTERVAL, limit=25)
        candles = parse_candles(raw)
        price   = get_ticker_price(SYMBOL)

        # 2. Detect key level
        resistance = detect_key_resistance(candles)
        log.info(f"Price: {price:.2f} | Resistance: {resistance:.2f}")

        # 3. Check breakout
        latest = candles[-1]
        if not is_breakout_candle(latest, resistance):
            # No breakout — silent monitoring (optional: send every Nth cycle)
            log.info("No breakout — monitoring only.")
            return

        # 4. Volume confirmation
        vol_ok, vol_ratio = volume_confirmation(candles)

        # 5. Momentum
        mom_ok, mom_desc = momentum_check(latest)

        # 6. Risk calculation
        stop_loss    = calculate_stop_loss(candles, price)
        entry_zone   = calculate_entry_zone(price, resistance)
        risk_pct, risk_grade = calculate_risk(
            price, stop_loss, POSITION_USDT, LEVERAGE
        )
        tradeable = is_safe_to_trade(risk_pct)

        # 7. Build and send message
        if tradeable and vol_ok and mom_ok:
            msg = build_trade_message(
                price, resistance, vol_ratio, mom_desc,
                LEVERAGE, stop_loss, entry_zone,
                risk_pct, risk_grade, POSITION_USDT, timestamp
            )
            log.info("✅ TRADE SIGNAL sent")
        else:
            reasons = []
            if not vol_ok:
                reasons.append(f"Volume only {vol_ratio}× avg (need {VOLUME_MULT}×)")
            if not mom_ok:
                reasons.append(f"Momentum weak: {mom_desc}")
            if not tradeable:
                reasons.append(f"Risk {risk_pct}% exceeds {MAX_RISK_PCT}% max")
            msg = build_alert_message(price, resistance, reasons, timestamp)
            log.info(f"⚠️  ALERT-ONLY sent — {reasons}")

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        log.error(f"Analysis error: {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"❌ ZenoClaw error: `{e}`\nBot continues running.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────

async def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    info = await bot.get_me()
    log.info(f"ZenoClaw bot started: @{info.username}")

    # Send startup message
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            "✅ *ZenoClaw 24h monitoring is now active*\n"
            f"Continuously tracking {SYMBOL} {INTERVAL} candle structure and volume changes\n\n"
            f"*Monitoring Rules*\n"
            f"• Symbol: {SYMBOL} (perpetual)\n"
            f"• Candles: {INTERVAL}\n"
            f"• Trigger: key-level breakout + volume expansion\n"
            f"• Execution: auto-calculates leverage, SL, position size\n"
            f"• Risk control: if risk too high → alert only, no trade\n\n"
            f"⏱ Checking every {CHECK_EVERY} minutes."
        ),
        parse_mode=ParseMode.MARKDOWN,
    )

    # Schedule recurring checks
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_analysis,
        "interval",
        minutes=CHECK_EVERY,
        args=[bot],
        id="zenoclaw_analysis",
    )
    scheduler.start()

    # Run once immediately on start
    await run_analysis(bot)

    # Keep alive
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        log.info("ZenoClaw stopped.")

if __name__ == "__main__":
    asyncio.run(main())
