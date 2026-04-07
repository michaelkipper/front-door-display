"""
Water meter module — fetches readings from an ESP32-CAM Prometheus endpoint.

Stores a rolling 30-minute history of readings in memory and exposes
helper functions consumed by the main server routes.
"""

from absl import logging
import re
import time

import requests

METER_URL = "http://192.168.2.206/metrics"
FETCH_TIMEOUT_SECONDS = 5
HISTORY_SECONDS = 30 * 60  # 30 minutes of history
RAW_TO_CUBIC_METRES = 10_000

# Rolling history: list of (timestamp, cubic_metres) tuples, oldest first.
_reading_history = []

# Last successful reading for display.
_last_reading = {"cubic_metres": None, "timestamp": 0}

# Throttle error logging to once per minute.
_last_error_log = 0.0


def _parse_reading(text):
    """Extract water_meter_reading_total from Prometheus metrics text."""
    match = re.search(r'^water_meter_reading_total\{[^}]*\}\s+(\d+)', text, re.MULTILINE)
    if match:
        return int(match.group(1))
    return None


def fetch_reading():
    """
    Fetch the current water meter reading from the ESP32-CAM.

    Returns the reading in cubic metres (float), or None on failure.
    Stores each successful reading in the rolling history.
    """
    global _last_error_log
    try:
        resp = requests.get(METER_URL, timeout=FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        raw = _parse_reading(resp.text)
        if raw is None:
            return _last_reading["cubic_metres"]

        cubic_metres = raw / RAW_TO_CUBIC_METRES
        now = time.time()

        _last_reading["cubic_metres"] = cubic_metres
        _last_reading["timestamp"] = now

        _reading_history.append((now, cubic_metres))
        _trim_history()

        return cubic_metres

    except Exception:
        now = time.time()
        if now - _last_error_log > 60:
            logging.warning("Failed to fetch water meter reading from %s", METER_URL)
            _last_error_log = now
        return _last_reading["cubic_metres"]


def _trim_history():
    """Remove readings older than HISTORY_SECONDS."""
    cutoff = time.time() - HISTORY_SECONDS
    while _reading_history and _reading_history[0][0] < cutoff:
        _reading_history.pop(0)


def get_current_reading():
    """Return the latest reading in cubic metres, or None."""
    return _last_reading["cubic_metres"]


def get_history():
    """
    Return the 30-minute reading history.

    Returns a list of {"t": epoch_seconds, "value": cubic_metres} dicts.
    """
    _trim_history()
    return [{"t": t, "value": v} for t, v in _reading_history]
