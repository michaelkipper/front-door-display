"""
Front Door Display — Flask backend.

Serves the kiosk UI and provides /api/state with weather, calendar,
and background image data. Generates new images hourly via Gemini.
"""

from __future__ import annotations

import typing

from absl import app
from absl import flags
from absl import logging
import collections
import datetime
import google.cloud.logging  # type: ignore[import-not-found]
import logging as py_logging
import os
import requests
import threading
import time

import flask

import announcements
import image_gen
import stocks
import water_meter

_PORT = flags.DEFINE_integer("port", 8080, "Port to listen on")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

try:
    import config  # type: ignore[import-not-found]
    GEMINI_API_KEY = config.GEMINI_API_KEY
except ImportError:
    GEMINI_API_KEY = ""

# Vaughan, Ontario
LATITUDE = 43.8563
LONGITUDE = -79.5085

CANDLE_LIGHTING_MINUTES = 18
HAVDALAH_MINUTES = 42

FRIDAY = 4   # datetime.weekday()
SATURDAY = 5

IMAGE_INTERVAL_SECONDS = 60 * 60  # 1 hour
IMAGE_SKIP_HOURS = range(0, 6)    # midnight to 5:59am

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

flaskapp = flask.Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_time_offset_ms = 0  # Debug offset in milliseconds

# Weather cache
_weather_cache = {"data": None, "timestamp": 0}
WEATHER_CACHE_SECONDS = 15 * 60  # 15 minutes

# Calendar cache (keyed by date string YYYY-MM-DD)
_calendar_cache = collections.defaultdict()
_last_prefetch_date_key = None

# Image generation timestamp
_last_image_gen = 0

# Calendar state when the current image was generated, used for staleness detection.
# Keys: holiday_name, is_shabbat, is_yom_tov
_last_image_cal_state = None

# Throttled warning timestamps
_last_weather_error_log = 0.0
_last_calendar_error_log = 0.0

# Network behavior
NETWORK_TIMEOUT = (3.05, 8)  # (connect timeout, read timeout)
NETWORK_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.25

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime.datetime:
    """Current time adjusted by debug offset."""
    return datetime.datetime.now() + datetime.timedelta(milliseconds=_time_offset_ms)


def _parse_date(date_string: str) -> datetime.datetime:
    """Parse a Hebcal date string into a datetime."""
    if "T" in date_string:
        # Has time component — try parsing with timezone offset
        # Format: 2026-04-01T19:27:00-04:00
        try:
            return datetime.datetime.fromisoformat(date_string)
        except ValueError:
            pass
    # Date only — treat as midnight local
    try:
        return datetime.datetime.strptime(date_string, "%Y-%m-%d").replace(hour=0, minute=0, second=1)
    except ValueError:
        return datetime.datetime.now()


def _format_time_12h(dt: datetime.datetime) -> str:
    """Format a datetime as '7:32 PM'."""
    hour = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{minute} {ampm}"


def _format_omer_count(omer_data: dict[str, typing.Any] | None) -> dict[str, str] | None:
    """Extract Omer count strings from Hebcal API data.

    Returns a dict with 'en' and 'he' count strings, or None.
    """
    if not omer_data or not isinstance(omer_data, dict):
        return None
    count = omer_data.get("count", {})
    en = count.get("en")
    if not en:
        return None
    return {"en": en, "he": count.get("he", en)}


def _log_throttled(last_log_ts: float, message: str, interval_seconds: int = 300) -> float:
    """Log a warning at most once per interval to avoid log spam."""
    now_ts = time.time()
    if now_ts - last_log_ts >= interval_seconds:
        logging.warning(message)
        return now_ts
    return last_log_ts


def _get_json_with_retries(url: str, label: str) -> typing.Any:
    """GET JSON with basic retries for transient network errors."""
    attempts = NETWORK_RETRIES + 1
    last_exc: requests.RequestException | None = None

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=NETWORK_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < attempts:
                logging.warning("%s request failed (%d/%d): %s", label, attempt, attempts, exc)
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    if last_exc is None:
        raise RuntimeError(f"Unexpected: no exception raised for {label}")
    raise last_exc


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def fetch_weather() -> dict[str, typing.Any] | None:
    """Fetch weather from Open-Meteo API, cached for 15 minutes."""
    global _last_weather_error_log

    now_ts = time.time()
    if _weather_cache["data"] and now_ts - _weather_cache["timestamp"] < WEATHER_CACHE_SECONDS:
        return _weather_cache["data"]

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&current=temperature_2m,weather_code"
        f"&hourly=temperature_2m,weather_code"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&temperature_unit=celsius&timezone=auto"
    )

    try:
        data = _get_json_with_retries(url, "Open-Meteo")

        # Build 2-hour interval forecast for the next 8 hours
        forecast = []
        hourly_times = data.get("hourly", {}).get("time", [])
        hourly_temps = data.get("hourly", {}).get("temperature_2m", [])
        hourly_codes = data.get("hourly", {}).get("weather_code", [])
        current_time = data.get("current", {}).get("time", "")
        if hourly_times and current_time:
            # Find the index of the next hour after current time
            start_idx = 0
            for i, t in enumerate(hourly_times):
                if t > current_time:
                    start_idx = i
                    break
            # Pick every 2 hours, up to 4 entries (covers 8 hours)
            for step in range(4):
                idx = start_idx + step * 2
                if idx < len(hourly_times):
                    forecast.append({
                        "time": hourly_times[idx],
                        "temp": round(hourly_temps[idx]),
                        "code": hourly_codes[idx],
                    })

        result = {
            "temp": round(data["current"]["temperature_2m"]),
            "code": data["current"]["weather_code"],
            "high": round(data["daily"]["temperature_2m_max"][0]),
            "low": round(data["daily"]["temperature_2m_min"][0]),
            "forecast": forecast,
        }
        _weather_cache["data"] = result
        _weather_cache["timestamp"] = now_ts
        return result
    except requests.RequestException as exc:
        # Keep stale weather when available and avoid noisy tracebacks.
        if _weather_cache["data"] is not None:
            _last_weather_error_log = _log_throttled(
                _last_weather_error_log,
                f"Weather fetch failed; using stale cached weather: {exc}",
            )
            return _weather_cache["data"]

        _last_weather_error_log = _log_throttled(
            _last_weather_error_log,
            f"Weather fetch failed with no cache available: {exc}",
        )
        return None


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def _fetch_calendar_events(now: datetime.datetime) -> list[dict[str, typing.Any]]:
    """Fetch calendar events from Hebcal API, cached per effective date."""
    global _last_calendar_error_log

    date_key = now.strftime("%Y-%m-%d")
    cached_events = _calendar_cache.get(date_key)
    if cached_events is not None:
        return cached_events

    start = now.strftime("%Y-%m-%d")
    end = (now + datetime.timedelta(days=30)).strftime("%Y-%m-%d")

    url = (
        f"https://www.hebcal.com/hebcal"
        f"?v=1&cfg=json&start={start}&end={end}"
        f"&maj=on&min=on&c=on&o=on"
        f"&latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&b={CANDLE_LIGHTING_MINUTES}&m={HAVDALAH_MINUTES}&s=on"
    )

    try:
        data = _get_json_with_retries(url, "Hebcal")
        events = []
        for item in data.get("items", []):
            parsed = _parse_date(item.get("date", ""))
            events.append({
                "title": item.get("title", ""),
                "date": item.get("date", ""),
                "category": item.get("category", ""),
                "yomtov": item.get("yomtov", False),
                "parsed_date": parsed,
                "is_holiday": item.get("category") == "holiday",
                "is_shabbat": item.get("category") == "parashat",
                "is_yom_tov": item.get("yomtov") is True,
                "is_candle_lighting": item.get("category") == "candles",
                "is_havdalah": item.get("category") == "havdalah",
                "is_omer": item.get("category") == "omer",
                "omer_day": item.get("omer"),
            })
        _calendar_cache[date_key] = events

        # Keep cache bounded to a few recent day-keys.
        if len(_calendar_cache) > 4:
            for old_key in sorted(_calendar_cache.keys())[:-4]:
                del _calendar_cache[old_key]

        logging.info("Fetched %d calendar events from Hebcal for %s", len(events), date_key)
        return events
    except requests.RequestException as exc:
        _last_calendar_error_log = _log_throttled(
            _last_calendar_error_log,
            f"Calendar fetch failed; using cached events: {exc}",
        )
        return _calendar_cache.get(date_key, [])


def _prefetch_tomorrow_events_if_needed(now: datetime.datetime) -> None:
    """
    Prefetch tomorrow's Hebcal events shortly before midnight.

    This keeps the date rollover smooth while avoiding repeated API calls.
    """
    global _last_prefetch_date_key

    if now.hour != 23 or now.minute < 50:
        return

    tomorrow = now + datetime.timedelta(days=1)
    tomorrow_key = tomorrow.strftime("%Y-%m-%d")

    if _last_prefetch_date_key == tomorrow_key:
        return
    if tomorrow_key in _calendar_cache:
        _last_prefetch_date_key = tomorrow_key
        return

    _fetch_calendar_events(tomorrow)
    _last_prefetch_date_key = tomorrow_key
    logging.info("Prefetched Hebcal events for %s", tomorrow_key)


def _get_events_for_date(now: datetime.datetime, target_date: datetime.datetime) -> list[dict[str, typing.Any]]:
    """Filter cached events to those matching target_date."""
    all_events = _fetch_calendar_events(now)
    return [
        e for e in all_events
        if (e["parsed_date"].year == target_date.year
            and e["parsed_date"].month == target_date.month
            and e["parsed_date"].day == target_date.day)
    ]


def _is_shabbat(now: datetime.datetime, candle_events: list[dict[str, typing.Any]], havdalah_events: list[dict[str, typing.Any]]) -> bool:
    """Check if it's currently Shabbat based on day-of-week and event times."""
    weekday = now.weekday()  # Monday=0 ... Sunday=6
    naive_now = now.replace(tzinfo=None) if now.tzinfo else now

    if weekday == SATURDAY:
        if havdalah_events:
            havdalah_time = havdalah_events[0]["parsed_date"]
            if havdalah_time.tzinfo:
                havdalah_time = havdalah_time.replace(tzinfo=None)
            if naive_now >= havdalah_time:
                return False
        return True
    elif weekday == FRIDAY:
        if candle_events:
            candle_time = candle_events[0]["parsed_date"]
            if candle_time.tzinfo:
                candle_time = candle_time.replace(tzinfo=None)
            if naive_now >= candle_time:
                return True
        return False

    return False


def get_calendar_state(now: datetime.datetime) -> dict[str, typing.Any]:
    """
    Compute the full calendar display state for the given time.

    Returns a dict with all the information the frontend needs.
    """
    events = _get_events_for_date(now, now)
    candle_events = [e for e in events if e["is_candle_lighting"]]
    havdalah_events = [e for e in events if e["is_havdalah"]]

    # Determine Shabbat BEFORE possibly swapping to tomorrow
    currently_shabbat = _is_shabbat(now, candle_events, havdalah_events)

    # If past candle lighting, swap to tomorrow's events for display
    naive_now = now.replace(tzinfo=None) if now.tzinfo else now
    if candle_events:
        candle_time = candle_events[0]["parsed_date"]
        if candle_time.tzinfo:
            candle_time = candle_time.replace(tzinfo=None)
        if naive_now >= candle_time:
            tomorrow = now + datetime.timedelta(days=1)
            events = _get_events_for_date(now, tomorrow)
            candle_events = [e for e in events if e["is_candle_lighting"]]
            havdalah_events = [e for e in events if e["is_havdalah"]]
    elif havdalah_events:
        havdalah_time = havdalah_events[0]["parsed_date"]
        if havdalah_time.tzinfo:
            havdalah_time = havdalah_time.replace(tzinfo=None)
        if naive_now >= havdalah_time:
            tomorrow = now + datetime.timedelta(days=1)
            events = _get_events_for_date(now, tomorrow)
            candle_events = [e for e in events if e["is_candle_lighting"]]
            havdalah_events = [e for e in events if e["is_havdalah"]]

    # Candle lighting / Havdalah display
    candle_lighting_text = None
    havdalah_text = None
    next_event_epoch = None
    if candle_events:
        candle_lighting_text = _format_time_12h(candle_events[0]["parsed_date"])
        _dt = candle_events[0]["parsed_date"]
        next_event_epoch = int(_dt.replace(tzinfo=None).timestamp()) if _dt.tzinfo else int(_dt.timestamp())
    elif havdalah_events:
        havdalah_text = _format_time_12h(havdalah_events[0]["parsed_date"])
        _dt = havdalah_events[0]["parsed_date"]
        next_event_epoch = int(_dt.replace(tzinfo=None).timestamp()) if _dt.tzinfo else int(_dt.timestamp())

    holiday_events = [e for e in events if e["is_holiday"]]
    yom_tov_events = [e for e in events if e["is_yom_tov"]]
    shabbat_events = [e for e in events if e["is_shabbat"]]
    omer_events = [e for e in events if e.get("is_omer")]

    # Display priority: Yom Tov > Shabbat > holiday > regular
    show_shabbat_bg = False
    holiday_name = None
    display_class = "date"

    if yom_tov_events:
        show_shabbat_bg = True
        holiday_name = yom_tov_events[0]["title"]
        display_class = "shabbat"
    elif currently_shabbat or shabbat_events:
        show_shabbat_bg = True
        event = shabbat_events[0] if shabbat_events else (holiday_events[0] if holiday_events else None)
        if event:
            holiday_name = event["title"]
        display_class = "shabbat"
    elif holiday_events:
        holiday_name = holiday_events[0]["title"]
        display_class = "shabbat"

    # Omer count
    omer_count = None
    if omer_events:
        omer_count = _format_omer_count(omer_events[0]["omer_day"])

    # Background image
    bg_image = None
    if image_gen.has_current_image():
        bg_image = f"/images/current.png?t={int(os.path.getmtime(image_gen.CURRENT_IMAGE))}"

    return {
        "candle_lighting": candle_lighting_text,
        "havdalah": havdalah_text,
        "next_event_epoch": next_event_epoch,
        "holiday_name": holiday_name,
        "show_shabbat_background": show_shabbat_bg,
        "display_class": display_class,
        "background_image": bg_image,
        "is_shabbat": currently_shabbat,
        "is_yom_tov": bool(yom_tov_events),
        "events": events,
        "omer_count": omer_count,
    }


# ---------------------------------------------------------------------------
# Image scheduler
# ---------------------------------------------------------------------------

def _cal_state_key(cal_state: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Extract the fields used to detect whether the image is stale."""
    return {
        "holiday_name": cal_state.get("holiday_name"),
        "is_shabbat": cal_state.get("is_shabbat", False),
        "is_yom_tov": cal_state.get("is_yom_tov", False),
    }


def _image_is_stale(cal_state: dict[str, typing.Any]) -> bool:
    """True if the current image was generated for a different calendar state."""
    if _last_image_cal_state is None:
        return True
    return _cal_state_key(cal_state) != _last_image_cal_state


def _image_generation_loop() -> None:
    """Background thread: generate a new image every hour (6am-midnight)."""
    global _last_image_gen, _last_image_cal_state

    # Wait a few seconds for app to start
    time.sleep(5)

    while True:
        try:
            now = _now()
            if now.hour not in IMAGE_SKIP_HOURS:
                weather = fetch_weather()
                cal_state = get_calendar_state(now)
                stale = _image_is_stale(cal_state)
                use_batch = not stale
                if stale:
                    logging.info(
                        "Image is stale (state changed) — using sync API for immediate refresh"
                    )
                result = image_gen.generate_image(GEMINI_API_KEY, weather, cal_state, now, use_batch=use_batch)
                if result:
                    _last_image_gen = time.time()
                    _last_image_cal_state = _cal_state_key(cal_state)
            else:
                logging.info("Skipping image generation (hour=%d)", now.hour)
        except Exception:
            logging.exception("Error in image generation loop")

        time.sleep(IMAGE_INTERVAL_SECONDS)


WATER_METER_POLL_SECONDS = 5

def _water_meter_loop() -> None:
    """Background thread: poll the water meter every few seconds."""
    time.sleep(2)
    while True:
        try:
            water_meter.fetch_reading()
        except Exception:
            logging.exception("Error in water meter loop")
        time.sleep(WATER_METER_POLL_SECONDS)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@flaskapp.route("/")
def index() -> flask.Response:
    return flask.send_from_directory("templates", "index.html")


@flaskapp.route("/api/state")
def api_state() -> flask.Response:
    now = _now()
    _prefetch_tomorrow_events_if_needed(now)
    weather = fetch_weather()
    cal_state = get_calendar_state(now)

    stock_data = stocks.fetch_quotes()

    return flask.jsonify({
        "weather": weather,
        "candle_lighting": cal_state["candle_lighting"],
        "havdalah": cal_state["havdalah"],
        "holiday_name": cal_state["holiday_name"],
        "show_shabbat_background": cal_state["show_shabbat_background"],
        "display_class": cal_state["display_class"],
        "background_image": cal_state["background_image"],
        "is_shabbat": cal_state["is_shabbat"],
        "is_yom_tov": cal_state["is_yom_tov"],
        "omer_count": cal_state["omer_count"],
        "next_event_epoch": cal_state["next_event_epoch"],
        "stocks": stock_data,
    })


@flaskapp.route("/api/offset", methods=["POST"])
def api_offset() -> flask.Response:
    global _time_offset_ms
    data = flask.request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "reset":
        _time_offset_ms = 0
    elif "offset_ms" in data:
        _time_offset_ms += int(data["offset_ms"])

    return flask.jsonify({"offset_ms": _time_offset_ms})


@flaskapp.route("/api/test-announcement", methods=["POST"])
def api_test_announcement() -> flask.Response | tuple[flask.Response, int]:
    try:
        data = flask.request.get_json(silent=True) or {}
        host = data.get("host")  # optional: cast to a specific IP
        ok = announcements.send_test(_PORT.value, host=host)
        return flask.jsonify({"ok": ok})
    except Exception as exc:
        logging.exception("Test announcement failed")
        return flask.jsonify({"ok": False, "error": str(exc)}), 500


@flaskapp.route("/api/chromecast-devices")
def api_chromecast_devices() -> flask.Response | tuple[flask.Response, int]:
    try:
        devices = announcements.discover_devices()
        return flask.jsonify({"devices": devices})
    except Exception as exc:
        logging.exception("Chromecast discovery failed")
        return flask.jsonify({"devices": [], "error": str(exc)}), 500


@flaskapp.route("/images/<path:filename>")
def serve_image(filename: str) -> flask.Response:
    return flask.send_from_directory("images", filename)


# ---------------------------------------------------------------------------
# Water meter routes
# ---------------------------------------------------------------------------

@flaskapp.route("/api/water")
def api_water() -> flask.Response:
    reading = water_meter.get_current_reading()
    return flask.jsonify({"cubic_metres": reading})


@flaskapp.route("/api/water/history")
def api_water_history() -> flask.Response:
    return flask.jsonify(water_meter.get_history())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> None:
    del argv

    # Setup Google Cloud logging
    client = google.cloud.logging.Client()
    client.setup_logging(log_level=py_logging.INFO)
    logging.info('Front Door Display server starting...')

    # Silence per-request access logs from Flask's dev server to prevent log spam.
    py_logging.getLogger("werkzeug").setLevel(py_logging.ERROR)

    # Generate an initial image on startup if none exists and it's daytime.
    # Uses the sync API so the kiosk doesn't wait several minutes for a batch job.
    global _last_image_cal_state
    now = _now()
    if not image_gen.has_current_image() and now.hour not in IMAGE_SKIP_HOURS and GEMINI_API_KEY:
        logging.info("No current image — generating on startup (sync)")
        try:
            weather = fetch_weather()
            cal_state = get_calendar_state(now)
            result = image_gen.generate_image(GEMINI_API_KEY, weather, cal_state, now, use_batch=False)
            if result:
                _last_image_cal_state = _cal_state_key(cal_state)
        except Exception:
            logging.exception("Failed to generate startup image")

    # Start background image generation thread
    gen_thread = threading.Thread(target=_image_generation_loop, daemon=True)
    gen_thread.start()

    # Start background water meter polling thread
    water_thread = threading.Thread(target=_water_meter_loop, daemon=True)
    water_thread.start()

    # Start Shabbat announcement loop
    announcements.start_announcement_loop(_now, _get_events_for_date, _PORT.value)

    flaskapp.run(host="0.0.0.0", port=_PORT.value, debug=False)


if __name__ == "__main__":
    app.run(main)
