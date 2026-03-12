# ZenoClaw — Automated BTC Trade Signal Bot

A Telegram bot that monitors BTC/USDT 15m candles 24/7, detects
key-level breakouts, calculates risk, and sends trade signals or
alert-only messages — just like GetClaw.

---

## What it does

1. **Monitors** BTC/USDT 15m candles every 15 minutes via Binance API
2. **Detects** breakouts above the highest high of the last 20 candles
3. **Confirms** with: volume expansion (2×+ average) + strong candle close
4. **Calculates**: leverage, stop-loss (recent swing low), entry zone, risk %
5. **Sends** to Telegram:
   - ✅ Full trade signal if risk ≤ 2%
   - ⚠️  Alert-only if risk is too high, volume weak, or momentum poor

---

## Quick Setup (Step by step)

### Step 1 — Create your Telegram bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot`
3. Choose a name: e.g. `ZenoClaw`
4. Choose a username: e.g. `zenoclaw_bot`
5. Copy the **bot token** you receive (looks like `7112345678:AAF...`)

### Step 2 — Get your chat ID

**Option A — Private channel:**
1. Create a Telegram channel
2. Add your bot as an administrator
3. Forward any message from the channel to **@userinfobot**
4. It will show the chat ID (e.g. `-1001234567890`)

**Option B — Group:**
1. Create or use an existing group
2. Add your bot to the group
3. Send a message in the group, then visit:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id": -123456789}` in the response

### Step 3 — Install Python & dependencies

```bash
# Requires Python 3.11+
python --version

# Install dependencies
pip install -r requirements.txt
```

### Step 4 — Configure the bot

```bash
# Copy the example config
cp .env.example .env

# Edit with your values
nano .env
```

Fill in:
```
TELEGRAM_BOT_TOKEN=7112345678:AAFxxxxxx
TELEGRAM_CHAT_ID=-1001234567890
```

### Step 5 — Run the bot

```bash
python zenoclaw_bot.py
```

You should see in the terminal:
```
2026-03-12 14:36:00 | INFO | ZenoClaw bot started: @zenoclaw_bot
2026-03-12 14:36:01 | INFO | [ZenoClaw] Running analysis at ...
```

And on Telegram:
```
✅ ZenoClaw 24h monitoring is now active
Continuously tracking BTCUSDT 15m candle structure...
```

---

## Running 24/7 on a server (VPS)

### Option A — Screen (simplest)
```bash
screen -S zenoclaw
python zenoclaw_bot.py
# Press Ctrl+A then D to detach
# Reconnect with: screen -r zenoclaw
```

### Option B — systemd service (recommended for VPS)
Create `/etc/systemd/system/zenoclaw.service`:
```ini
[Unit]
Description=ZenoClaw Trading Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/zenoclaw
ExecStart=/usr/bin/python3 zenoclaw_bot.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/zenoclaw/.env

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable zenoclaw
sudo systemctl start zenoclaw
sudo systemctl status zenoclaw
```

### Option C — Railway / Render (cloud, free tier)
1. Push code to GitHub
2. Create new project on railway.app or render.com
3. Add environment variables in the dashboard
4. Deploy — it runs 24/7 automatically

---

## Customizing ZenoClaw

All key settings are at the top of `zenoclaw_bot.py`:

| Variable | Default | What it does |
|---|---|---|
| `SYMBOL` | `BTCUSDT` | Which pair to monitor |
| `INTERVAL` | `15m` | Candle timeframe |
| `LEVERAGE` | `3` | Base leverage for signals |
| `POSITION_USDT` | `1200` | Position size in USDT |
| `MAX_RISK_PCT` | `2.0` | Max risk before alert-only mode |
| `VOLUME_MULT` | `2.0` | Volume threshold (× 20-candle avg) |
| `CHECK_EVERY` | `15` | Check frequency in minutes |

---

## Adding more pairs

To monitor ETH, SOL, etc. — run multiple instances with different `.env` files:

```bash
# In one terminal
SYMBOL=ETHUSDT python zenoclaw_bot.py

# In another
SYMBOL=SOLUSDT python zenoclaw_bot.py
```

Or modify the code to loop over a list of symbols.

---

## Understanding the signal messages

**Trade Signal (✅)**
- Breakout confirmed + volume + momentum all pass
- Position size, entry, stop-loss, and risk % calculated automatically
- Use the reference entry and SL — don't blindly enter at market

**Alert-Only (⚠️)**
- Breakout detected but one or more conditions failed
- Lists exactly which condition failed and why
- Bot does NOT suggest a trade — you decide

---

## Important disclaimer

This bot provides **informational signals only**. It does not connect
to any exchange, place orders, or manage funds. All trading decisions
are yours. Crypto trading involves significant risk of loss.
