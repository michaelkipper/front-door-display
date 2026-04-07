"""
Front Door Display — Flask backend.

Serves the kiosk UI and provides /api/state with weather, calendar,
and background image data. Generates new images hourly via Gemini.
"""

from absl import app
from absl import flags
from absl import logging
from collections import defaultdict
from datetime import datetime, timedelta
import logging as py_logging
import os
import requests
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

from image_gen import CURRENT_IMAGE, generate_image, has_current_image
from water_meter import fetch_reading as fetch_water_reading, get_current_reading as get_water_reading, get_history as get_water_history

_PORT = flags.DEFINE_integer("port", 8080, "Port to listen on")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

try:
    from config import GEMINI_API_KEY
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

flaskapp = Flask(
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
_calendar_cache = defaultdict()
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

def _now():
    """Current time adjusted by debug offset."""
    return datetime.now() + timedelta(milliseconds=_time_offset_ms)


def _parse_date(date_string):
    """Parse a Hebcal date string into a datetime."""
    if "T" in date_string:
        # Has time component — try parsing with timezone offset
        # Format: 2026-04-01T19:27:00-04:00
        try:
            return datetime.fromisoformat(date_string)
        except ValueError:
            pass
    # Date only — treat as midnight local
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").replace(hour=0, minute=0, second=1)
    except ValueError:
        return datetime.now()


def _format_time_12h(dt):
    """Format a datetime as '7:32 PM'."""
    hour = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{minute} {ampm}"


def _format_omer_count(omer_data):
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


def _log_throttled(last_log_ts, message, interval_seconds=300):
    """Log a warning at most once per interval to avoid log spam."""
    now_ts = time.time()
    if now_ts - last_log_ts >= interval_seconds:
        logging.warning(message)
        return now_ts
    return last_log_ts


def _get_json_with_retries(url, label):
    """GET JSON with basic retries for transient network errors."""
    attempts = NETWORK_RETRIES + 1
    last_exc = None

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

    raise last_exc


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def fetch_weather():
    """Fetch weather from Open-Meteo API, cached for 15 minutes."""
    global _last_weather_error_log

    now_ts = time.time()
    if _weather_cache["data"] and now_ts - _weather_cache["timestamp"] < WEATHER_CACHE_SECONDS:
        return _weather_cache["data"]

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&current=temperature_2m,weather_code"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&temperature_unit=celsius&timezone=auto"
    )

    try:
        data = _get_json_with_retries(url, "Open-Meteo")
        result = {
            "temp": round(data["current"]["temperature_2m"]),
            "code": data["current"]["weather_code"],
            "high": round(data["daily"]["temperature_2m_max"][0]),
            "low": round(data["daily"]["temperature_2m_min"][0]),
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

def _fetch_calendar_events(now):
    """Fetch calendar events from Hebcal API, cached per effective date."""
    global _last_calendar_error_log

    date_key = now.strftime("%Y-%m-%d")
    cached_events = _calendar_cache.get(date_key)
    if cached_events is not None:
        return cached_events

    start = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=30)).strftime("%Y-%m-%d")

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


def _prefetch_tomorrow_events_if_needed(now):
    """
    Prefetch tomorrow's Hebcal events shortly before midnight.

    This keeps the date rollover smooth while avoiding repeated API calls.
    """
    global _last_prefetch_date_key

    if now.hour != 23 or now.minute < 50:
        return

    tomorrow = now + timedelta(days=1)
    tomorrow_key = tomorrow.strftime("%Y-%m-%d")

    if _last_prefetch_date_key == tomorrow_key:
        return
    if tomorrow_key in _calendar_cache:
        _last_prefetch_date_key = tomorrow_key
        return

    _fetch_calendar_events(tomorrow)
    _last_prefetch_date_key = tomorrow_key
    logging.info("Prefetched Hebcal events for %s", tomorrow_key)


def _get_events_for_date(now, target_date):
    """Filter cached events to those matching target_date."""
    all_events = _fetch_calendar_events(now)
    return [
        e for e in all_events
        if (e["parsed_date"].year == target_date.year
            and e["parsed_date"].month == target_date.month
            and e["parsed_date"].day == target_date.day)
    ]


def _is_shabbat(now, candle_events, havdalah_events):
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


def get_calendar_state(now):
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
            tomorrow = now + timedelta(days=1)
            events = _get_events_for_date(now, tomorrow)
            candle_events = [e for e in events if e["is_candle_lighting"]]
            havdalah_events = [e for e in events if e["is_havdalah"]]
    elif havdalah_events:
        havdalah_time = havdalah_events[0]["parsed_date"]
        if havdalah_time.tzinfo:
            havdalah_time = havdalah_time.replace(tzinfo=None)
        if naive_now >= havdalah_time:
            tomorrow = now + timedelta(days=1)
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
    if has_current_image():
        bg_image = f"/images/current.png?t={int(os.path.getmtime(CURRENT_IMAGE))}"

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

def _cal_state_key(cal_state):
    """Extract the fields used to detect whether the image is stale."""
    return {
        "holiday_name": cal_state.get("holiday_name"),
        "is_shabbat": cal_state.get("is_shabbat", False),
        "is_yom_tov": cal_state.get("is_yom_tov", False),
    }


def _image_is_stale(cal_state):
    """True if the current image was generated for a different calendar state."""
    if _last_image_cal_state is None:
        return True
    return _cal_state_key(cal_state) != _last_image_cal_state


def _image_generation_loop():
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
                result = generate_image(GEMINI_API_KEY, weather, cal_state, now, use_batch=use_batch)
                if result:
                    _last_image_gen = time.time()
                    _last_image_cal_state = _cal_state_key(cal_state)
            else:
                logging.info("Skipping image generation (hour=%d)", now.hour)
        except Exception:
            logging.exception("Error in image generation loop")

        time.sleep(IMAGE_INTERVAL_SECONDS)


WATER_METER_POLL_SECONDS = 5

def _water_meter_loop():
    """Background thread: poll the water meter every few seconds."""
    time.sleep(2)
    while True:
        try:
            fetch_water_reading()
        except Exception:
            logging.exception("Error in water meter loop")
        time.sleep(WATER_METER_POLL_SECONDS)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@flaskapp.route("/")
def index():
    return send_from_directory("templates", "index.html")


@flaskapp.route("/api/state")
def api_state():
    now = _now()
    _prefetch_tomorrow_events_if_needed(now)
    weather = fetch_weather()
    cal_state = get_calendar_state(now)

    return jsonify({
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
    })


@flaskapp.route("/api/offset", methods=["POST"])
def api_offset():
    global _time_offset_ms
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "reset":
        _time_offset_ms = 0
    elif "offset_ms" in data:
        _time_offset_ms += int(data["offset_ms"])

    return jsonify({"offset_ms": _time_offset_ms})


@flaskapp.route("/images/<path:filename>")
def serve_image(filename):
    return send_from_directory("images", filename)


# ---------------------------------------------------------------------------
# Water meter routes
# ---------------------------------------------------------------------------

@flaskapp.route("/api/water")
def api_water():
    reading = get_water_reading()
    return jsonify({"cubic_metres": reading})


@flaskapp.route("/api/water/history")
def api_water_history():
    return jsonify(get_water_history())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv):
    del argv

    # Silence per-request access logs from Flask's dev server to prevent log spam.
    py_logging.getLogger("werkzeug").setLevel(py_logging.ERROR)

    # Generate an initial image on startup if none exists and it's daytime.
    # Uses the sync API so the kiosk doesn't wait several minutes for a batch job.
    global _last_image_cal_state
    now = _now()
    if not has_current_image() and now.hour not in IMAGE_SKIP_HOURS and GEMINI_API_KEY:
        logging.info("No current image — generating on startup (sync)")
        try:
            weather = fetch_weather()
            cal_state = get_calendar_state(now)
            result = generate_image(GEMINI_API_KEY, weather, cal_state, now, use_batch=False)
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

    flaskapp.run(host="0.0.0.0", port=_PORT.value, debug=False)


if __name__ == "__main__":
    app.run(main)
