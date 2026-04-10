"""
Stock ticker module — fetches latest quotes for configured symbols.

Uses yfinance to retrieve current price and daily change percentage.
Results are cached to avoid excessive API calls.
"""
from __future__ import annotations

import typing
from absl import logging
import time

import yfinance as yf

SYMBOLS = [
    "QQQ",
    "SPY",
    "GOOG",
]
CACHE_SECONDS = 5 * 60  # 5-minute cache

_cache = {"data": None, "timestamp": 0}
_last_error_log = 0.0


def fetch_quotes() -> list[dict[str, typing.Any]] | None:
    """
    Fetch latest quotes for configured symbols.

    Returns a list of dicts:
        [{"symbol": "QQQ", "price": 450.12, "change_pct": -1.23}, ...]
    Uses a 5-minute cache. Returns stale data on failure if available.
    """
    global _last_error_log
    now = time.time()
    if _cache["data"] is not None and now - _cache["timestamp"] < CACHE_SECONDS:
        return _cache["data"]

    try:
        tickers = yf.Tickers(" ".join(SYMBOLS))
        results = []
        for sym in SYMBOLS:
            ticker = tickers.tickers[sym]
            info = ticker.fast_info
            price = info.last_price
            prev_close = info.previous_close
            if price is not None and prev_close:
                change_pct = round((price - prev_close) / prev_close * 100, 2)
            else:
                change_pct = 0.0
            results.append({
                "symbol": sym,
                "price": round(price, 2) if price else None,
                "change_pct": change_pct,
            })
        _cache["data"] = results
        _cache["timestamp"] = time.time()
        return results

    except Exception:
        now = time.time()
        if now - _last_error_log > 60:
            logging.warning("Failed to fetch stock quotes")
            _last_error_log = now
        return _cache["data"]  # may be None on first failure
