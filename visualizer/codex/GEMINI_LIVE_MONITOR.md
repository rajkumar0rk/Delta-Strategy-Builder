# Gemini BTC Live Monitor (signal-only prototype)

The BTC Strategy Lab `visualizer/` now has an opt-in live screen that fetches Binance USD-M BTCUSDT candles every five minutes, evaluates a deterministic 15m 24-candle breakout plus 1h trend, and asks Gemini Flash-Lite for a **candidate-only** quality assessment. It does not place orders. It does not automatically invoke ChatGPT Plus, and Binance futures data are NOT Delta India option quotes.

## Setup: Windows PowerShell

Create a free-tier Gemini API key at https://aistudio.google.com/app/apikey . The free tier is quota-limited, available only where Google supports it, and can change. Never paste API keys into the browser or commit them to Git.

In a new PowerShell session, before starting Strategy Lab:

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder
$env:GEMINI_API_KEY = "PASTE_YOUR_API_KEY_HERE"
$env:BTC_MONITOR_GEMINI_MODEL = "gemini-2.5-flash-lite"
Set-Location .\visualizer
powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
```

NOTE: `start-dev.ps1` spawns the API as a child PowerShell window; environment variables are inherited from the parent terminal. Enter the API key into the parent terminal, not the browser. The key is not persisted when the terminal exits.

Open http://127.0.0.1:5174, go to **Live BTC Monitor**, click **Check once** to test the feed, and **Start monitor** to begin five-minute checks. The worker stops when the Python server terminates. Because the dev script uses uvicorn `--reload`, code changes/reloads can stop monitoring and reset its in-memory history. Start it again afterward.

Optional Telegram alerts:

```powershell
$env:BTC_MONITOR_TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"
$env:BTC_MONITOR_TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"
```

Set these before starting the API. When omitted, qualifying candidate alerts remain visible in the dashboard. Telegram may require initiating a conversation with your bot first.

### How screening works

- Each 5m UTC boundary plus about six seconds, fetch 180 5m, 15m, and hourly Binance futures candles.
- Ignore any not-yet-closed bar and reject stale, invalid, duplicate or missing data.
- Find prior 24 completed 15m highs/lows. Require a 15m CLOSE above/below, 1.5x volume, matching EMA 9/20/50 and 1h EMA trend and RSI confirmation.
- When the same 15m candle is revisited in further 5m checks, do not call Gemini a second time.
- Gemini is only a veto/quality screen. Missing key, rate limits, network errors or invalid response must never lead to a buy signal.
- Candidate signals are in memory, maximum 25, and do not survive server restarts.
- Alerts do not prove that there is a liquid/affordable Delta BTC CALL/PUT. No options order routing exists in this module.

### Manual ChatGPT Plus review

Click **Copy ChatGPT Plus review prompt** next to the candidate. Open ChatGPT with higher thinking effort, paste it, and ask it to verify *fresh* Binance and Delta India options data. Include actual expiry, strike, bid/ask, depth, minimum size, fee/GST, and current cash. There is no guarantee of profitable trades.

### Backend tests

```powershell
Set-Location C:\projects\workspace\Delta-Strategy-Builder\visualizer\backend
& "..\..\.venv\Scripts\python.exe" -m pytest -q tests/test_live_monitor.py
& "..\..\.venv\Scripts\python.exe" -m pytest -q
Set-Location ..\frontend
npm run build
npm run test
```

Important limitations for production: no durable monitoring events, no persisted duplicate suppression across restarts, no independently verified Delta option-chain price or account funds, no cross-exchange basis filter, no authenticated network deployment, no notification-delivery retry queue, no guaranteed 5m delivery. Keep for research and manual review, not unattended execution.
