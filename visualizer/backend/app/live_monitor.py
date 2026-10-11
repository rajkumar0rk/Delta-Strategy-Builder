"""Signal-only five-minute BTC breakout scanner; deliberately separate from backtest execution."""
from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

BINANCE_URL = "https://fapi.binance.com/fapi/v1/klines"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"
CANDLE_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000}


@dataclass(frozen=True)
class Bar:
    open_ms: int
    close_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def parse_closed_bars(raw: list[list[Any]], interval: str, now_ms: int) -> list[Bar]:
    """Ignore forming candles; fail closed on missing/reordered historical bars."""
    period = CANDLE_MS[interval]
    bars: list[Bar] = []
    for row in raw:
        opened, closed = int(row[0]), int(row[6])
        if closed >= now_ms - 1500:
            continue
        if closed - opened + 1 != period or opened % period:
            raise ValueError("Non-standard candle boundary")
        prices = [float(row[i]) for i in (1, 2, 3, 4, 5)]
        if any(not math.isfinite(x) or x < 0 for x in prices):
            raise ValueError("Invalid market values")
        o, h, l, c, v = prices
        if min(o, h, l, c) <= 0 or h < max(o, c, l) or l > min(o, c, h):
            raise ValueError("Invalid OHLC")
        bars.append(Bar(opened, closed, o, h, l, c, v))
    if len(bars) < 80:
        raise ValueError("Insufficient completed market candles")
    if any(b.open_ms - a.open_ms != period for a, b in zip(bars[:-1], bars[1:])):
        raise ValueError("Missing, duplicate or out-of-order market candles")
    return bars


def ema(values: list[float], period: int) -> float:
    if len(values) < period:
        raise ValueError("Insufficient EMA warmup")
    out = sum(values[:period]) / period
    alpha = 2 / (period + 1)
    for price in values[period:]:
        out += alpha * (price - out)
    return out


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) < period + 1:
        raise ValueError("Insufficient RSI warmup")
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gain = sum(max(0.0, d) for d in deltas[:period]) / period
    loss = sum(max(0.0, -d) for d in deltas[:period]) / period
    for change in deltas[period:]:
        gain = (gain * (period - 1) + max(0.0, change)) / period
        loss = (loss * (period - 1) + max(0.0, -change)) / period
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def screen(bars5: list[Bar], bars15: list[Bar], bars1h: list[Bar], now_ms: int) -> dict[str, Any]:
    """Return a mechanical CANDIDATE or NO_SETUP, never a BUY decision."""
    for period, bars, max_age in [("5m", bars5, 7 * 60_000), ("15m", bars15, 17 * 60_000), ("1h", bars1h, 67 * 60_000)]:
        if now_ms - bars[-1].close_ms > max_age:
            raise ValueError(f"Stale {period} feed")
    last = bars15[-1]
    prior = bars15[-25:-1]
    high = max(b.high for b in prior)
    low = min(b.low for b in prior)
    avg_volume = sum(b.volume for b in bars15[-21:-1]) / 20
    vol_ratio = last.volume / avg_volume if avg_volume > 0 else 0.0
    close15 = [b.close for b in bars15]
    close1h = [b.close for b in bars1h]
    e9, e20, e50 = (ema(close15, n) for n in (9, 20, 50))
    h20, h50 = ema(close1h, 20), ema(close1h, 50)
    r15, r1h = rsi(close15), rsi(close1h)
    direction = None
    if (last.close > high and bars5[-1].close > high and vol_ratio >= 1.5 and
        r15 >= 55 and e9 > e20 > e50 and h20 > h50 and r1h >= 50):
        direction = "CALL"
    elif (last.close < low and bars5[-1].close < low and vol_ratio >= 1.5 and
          r15 <= 45 and e9 < e20 < e50 and h20 < h50 and r1h <= 50):
        direction = "PUT"
    return {
        "state": "CANDIDATE" if direction else "NO_SETUP",
        "direction": direction,
        "candle_close_utc": utc_iso(last.close_ms + 1),
        "candle_id": last.close_ms,
        "underlying": "BINANCE_BTCUSDT_USDM_FUTURES",
        "latest_completed_5m_close": round(bars5[-1].close, 2),
        "last_15m_close": round(last.close, 2),
        "prior_24_high": round(high, 2),
        "prior_24_low": round(low, 2),
        "volume_ratio": round(vol_ratio, 3),
        "rsi_15m": round(r15, 2),
        "rsi_1h": round(r1h, 2),
        "ema_15m_9": round(e9, 2),
        "ema_15m_20": round(e20, 2),
        "ema_15m_50": round(e50, 2),
        "ema_1h_20": round(h20, 2),
        "ema_1h_50": round(h50, 2),
        "breakout_level": round(high if direction == "CALL" else low, 2) if direction else None,
        "explanation": "Mechanical criteria passed; option entry NOT validated" if direction else "No confirmed high-volume 15m breakout aligned with 1h trend",
    }


def gemini_review(signal: dict[str, Any]) -> dict[str, str]:
    """Small-model quality gate. The model cannot create/override mechanical signals."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set; refusing AI review")
    model = os.environ.get("BTC_MONITOR_GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
    if not model or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._" for c in model):
        raise ValueError("Invalid Gemini model name")
    url = f"{GEMINI_URL}/{model}:generateContent"
    prompt = (
        "You are a conservative signal quality auditor, NOT an order execution agent. "
        "This is Binance BTCUSDT futures, NOT a priced Delta India option. "
        "Review this mechanically confirmed breakout for obvious contradictions or excessive extension. "
        'Return JSON only: {"verdict":"PASS" or "REJECT","reason":"brief reason"}. '
        "PASS merely permits a candidate notification, never a BUY instruction. "
        "Do not invent prices, strikes, Delta liquidity, expiry, IV, fills or bid/ask. "
        "Reject if you cannot confidently assess the supplied values. "
        "Signal: " + json.dumps(signal, separators=(",", ":"))
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0, "maxOutputTokens": 200},
    }
    with httpx.Client(timeout=18) as client:
        response = client.post(url, headers={"x-goog-api-key": key}, json=payload)
        response.raise_for_status()
        body = response.json()
    content = body["candidates"][0]["content"]["parts"][0]["text"]
    verdict = json.loads(content)
    if not isinstance(verdict, dict) or verdict.get("verdict") not in ("PASS", "REJECT"):
        raise ValueError("Gemini returned an invalid verdict")
    reason = verdict.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Gemini returned no reason")
    return {"verdict": verdict["verdict"], "reason": reason.strip()[:400], "model": model}


def telegram_send(message: str) -> str:
    token = os.environ.get("BTC_MONITOR_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("BTC_MONITOR_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "NOT_CONFIGURED"
    with httpx.Client(timeout=10) as client:
        response = client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        )
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError("Telegram rejected notification")
    return "SENT"


class LiveMonitor:
    """Single-process, explicit start/stop. Not enabled by default."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tick_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_candle: int | None = None
        self._state: dict[str, Any] = {
            "last_checked_utc": None,
            "last_screen": None,
            "last_error": None,
            "signals": [],
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "interval_minutes": 5,
                "gemini_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
                "gemini_model": os.environ.get("BTC_MONITOR_GEMINI_MODEL", "gemini-2.5-flash-lite"),
                "telegram_configured": bool(os.environ.get("BTC_MONITOR_TELEGRAM_BOT_TOKEN") and os.environ.get("BTC_MONITOR_TELEGRAM_CHAT_ID")),
                **dict(self._state),
                "signals": list(self._state["signals"]),
            }

    def start(self) -> dict[str, Any]:
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            raise ValueError("Set GEMINI_API_KEY in the backend environment first")
        with self._lock:
            if self._running:
                return self._status_unlocked()
            if self._thread and self._thread.is_alive():
                raise ValueError("Previous monitor run is still shutting down")
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._running = True
            self._thread = threading.Thread(target=self._loop, args=(stop_event,), daemon=True, name="btc-live-monitor")
            self._thread.start()
        return self.status()

    def _status_unlocked(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "interval_minutes": 5,
            "gemini_configured": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
            "gemini_model": os.environ.get("BTC_MONITOR_GEMINI_MODEL", "gemini-2.5-flash-lite"),
            "telegram_configured": bool(os.environ.get("BTC_MONITOR_TELEGRAM_BOT_TOKEN") and os.environ.get("BTC_MONITOR_TELEGRAM_CHAT_ID")),
            **dict(self._state),
            "signals": list(self._state["signals"]),
        }

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
            self._stop_event.set()
        return self.status()

    def _loop(self, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                self.check_once()
                now = time.time()
                # Six seconds after each 5m UTC boundary, giving finalized bars time to arrive.
                next_tick = (int(now // 300) + 1) * 300 + 6
                stop_event.wait(max(1, next_tick - now))
        finally:
            with self._lock:
                if self._stop_event is stop_event:
                    self._running = False

    def check_once(self) -> dict[str, Any]:
        if not self._tick_lock.acquire(blocking=False):
            raise ValueError("A market check is already in progress")
        try:
            now_ms = int(time.time() * 1000)
            result: dict[str, Any] | None = None
            for interval in ("5m", "15m", "1h"):
                with httpx.Client(timeout=12) as client:
                    resp = client.get(BINANCE_URL, params={"symbol": "BTCUSDT", "interval": interval, "limit": 180})
                    resp.raise_for_status()
                    raw = resp.json()
                bars = parse_closed_bars(raw, interval, now_ms)
                if interval == "5m":
                    bars5 = bars
                elif interval == "15m":
                    bars15 = bars
                else:
                    bars1h = bars
            result = screen(bars5, bars15, bars1h, now_ms)
            with self._lock:
                already_seen = result["candle_id"] == self._last_candle
                self._last_candle = result["candle_id"]
                self._state["last_screen"] = result
                self._state["last_checked_utc"] = utc_iso(now_ms)
                self._state["last_error"] = None
            if result["state"] != "CANDIDATE" or already_seen or self._stop_event.is_set():
                return self.status()
            try:
                ai = gemini_review(result)
            except Exception as exc:
                with self._lock:
                    self._state["last_screen"] = {**result, "state": "AI_UNAVAILABLE", "explanation": "Gemini review unavailable; no actionable candidate"}
                raise
            result = {**result, "ai": ai}
            with self._lock:
                self._state["last_screen"] = result
            if ai["verdict"] != "PASS" or self._stop_event.is_set():
                with self._lock:
                    self._state["last_screen"] = {**result, "state": "REJECTED", "explanation": ai["reason"]}
                return self.status()
            result["state"] = "MANUAL_REVIEW_ONLY"
            result["disclaimer"] = "Not a BUY signal. Delta India option bid/ask, expiry, fees, lot and <=$100 budget unverified."
            msg = (
                f"BTC {result['direction']} CANDIDATE ONLY, not a BUY signal\n"
                f"15m candle: {result['candle_close_utc']}\n"
                f"Breakout: {result['breakout_level']}\n"
                f"Close: {result['last_15m_close']} Volume ratio: {result['volume_ratio']}\n"
                "Review with ChatGPT Plus and current Delta option quotes before any manual action."
            )
            if not self._stop_event.is_set():
                try:
                    result["telegram_delivery"] = telegram_send(msg)
                except (httpx.HTTPError, RuntimeError) as exc:
                    result["telegram_delivery"] = "FAILED"
                    result["telegram_error"] = type(exc).__name__  # Never leak secrets from HTTP errors.
            with self._lock:
                self._state["signals"] = ([result] + self._state["signals"])[:25]
                self._state["last_screen"] = result
            return self.status()
        except Exception as exc:  # A monitoring failure must never publish a trade alert.
            with self._lock:
                self._state["last_checked_utc"] = utc_iso(int(time.time() * 1000))
                self._state["last_error"] = f"{type(exc).__name__}: {str(exc)[:180] if not isinstance(exc, httpx.HTTPError) else 'network/API request failed'}"
                if self._state["last_screen"] and self._state["last_screen"].get("state") == "CANDIDATE":
                    self._state["last_screen"] = {**self._state["last_screen"], "state": "AI_UNAVAILABLE", "explanation": "Screen incomplete: do not act"}
            return self.status()
        finally:
            self._tick_lock.release()


live_monitor = LiveMonitor()
