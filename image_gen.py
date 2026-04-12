"""
Image generation using Gemini 2.5 Flash.

Generates context-aware background images based on weather, holiday,
time of day, and season. Supports both synchronous (standard) and batch
API modes. Batch is 50% cheaper but takes several minutes; sync is used
when an image is needed immediately (e.g. cold start or stale state).
Images are saved to the images/ directory.
"""

from __future__ import annotations

import datetime
import typing

from absl import logging
import os
import time

import google.genai
import google.genai.errors

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
CURRENT_IMAGE = os.path.join(IMAGES_DIR, "current.png")
HISTORY_DIR = os.path.join(IMAGES_DIR, "history")

# Ordered model candidates for image generation.
# The first available model in this list will be used.
MODEL_CANDIDATES = [
    "gemini-2.5-flash-image",
    "gemini-2.5-flash-image-preview",
]

# How often to poll for batch job completion.
BATCH_POLL_INTERVAL_SECONDS = 5

# WMO weather code descriptions for prompt building
WMO_DESCRIPTIONS = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def _get_season(month: int, temp: float) -> str:
    """Infer season from month and temperature."""
    if month in (12, 1, 2) or temp < 0:
        return "Winter"
    elif month in (3, 4, 5):
        return "Spring"
    elif month in (6, 7, 8):
        return "Summer"
    else:
        return "Autumn"


def _get_time_of_day(hour: int) -> str:
    """Get time-of-day description for prompt."""
    if 6 <= hour < 9:
        return "early morning with soft dawn light"
    elif 9 <= hour < 12:
        return "bright morning"
    elif 12 <= hour < 15:
        return "bright midday"
    elif 15 <= hour < 18:
        return "warm afternoon"
    elif 18 <= hour < 21:
        return "golden hour sunset"
    else:
        return "evening with cool blue tones and warm interior lighting"


def _get_holiday_context(holiday_name: str | None, events: list[dict[str, typing.Any]]) -> str | None:
    """Get holiday-specific imagery description from event titles."""
    if not events:
        return None

    all_text = " ".join(e.get("title", "").lower() for e in events)

    if "pesach" in all_text or "passover" in all_text:
        return "matzah on a Passover seder plate, spring flowers"
    if "shavuot" in all_text:
        return "rolling green hills with wildflowers, a Torah scroll, dairy foods like cheesecake"
    if "sukkot" in all_text:
        return "a decorated sukkah with hanging fruits, palm branches, and warm string lights"
    if "rosh hashana" in all_text:
        return "apples and honey jar with a shofar, pomegranates"
    if "yom kippur" in all_text:
        return "white prayer shawls and lit memorial candles, serene and solemn atmosphere"
    if "chanukah" in all_text or "hanukkah" in all_text:
        return "a menorah with glowing candles, dreidels and golden gelt"
    if "purim" in all_text:
        return "hamantaschen pastries, a colorful Purim mask, and a megillah scroll, joyful festive atmosphere"
    if "simchat torah" in all_text:
        return "joyful dancing with Torah scrolls, colorful celebration, festive lights"
    if "shmini atzeret" in all_text:
        return "Torah scrolls and golden autumn leaves, warm harvest light"

    return None


def build_image_prompt(weather: dict[str, typing.Any] | None, calendar_state: dict[str, typing.Any], now: datetime.datetime) -> str:
    """
    Build a context-aware image prompt from current weather, calendar, and time.

    Args:
        weather: dict with keys temp, code, high, low (or None)
        calendar_state: dict with keys holiday_name, is_shabbat, is_yom_tov, events
        now: datetime object
    Returns:
        str: descriptive prompt for image generation
    """
    parts = []

    # Time of day
    time_desc = _get_time_of_day(now.hour)
    parts.append(f"Scene set during {time_desc}")

    # Weather
    if weather:
        temp = weather.get("temp")
        code = weather.get("code", 0)
        weather_desc = WMO_DESCRIPTIONS.get(code, "clear sky")
        season = _get_season(now.month, temp if temp is not None else 15)
        parts.append(f"{season} weather with {weather_desc}, {temp}°C")
    else:
        season = _get_season(now.month, 15)
        parts.append(f"{season} atmosphere")

    # Holiday / Shabbat context
    events = calendar_state.get("events", [])
    holiday_name = calendar_state.get("holiday_name")
    is_shabbat = calendar_state.get("is_shabbat", False)
    is_yom_tov = calendar_state.get("is_yom_tov", False)

    holiday_imagery = _get_holiday_context(holiday_name, events)

    if holiday_imagery:
        parts.append(f"Featuring {holiday_imagery}")
    elif is_shabbat:
        parts.append(
            "Featuring two braided challah breads, Shabbat candles, "
            "and a kiddush cup of wine on a table"
        )

    if is_shabbat and not holiday_imagery:
        parts.append("Warm golden Shabbat lighting")
    elif is_yom_tov:
        parts.append("Festive holiday lighting")

    # Style directive
    parts.append("Beautiful Pixar-like cartoon style, with vibrant colors")

    prompt = "Generate an image: " + ". ".join(parts) + "."
    return prompt


def generate_image(api_key: str, weather: dict[str, typing.Any] | None, calendar_state: dict[str, typing.Any], now: datetime.datetime, use_batch: bool = True) -> str | None:
    """
    Generate an image using Gemini and save it.

    When use_batch=True (default), submits a batch job for 50% cost savings
    but takes several minutes. When use_batch=False, uses the standard
    synchronous API for an immediate result.

    Args:
        api_key: Gemini API key string
        weather: dict with weather data (or None)
        calendar_state: dict with calendar state
        now: datetime object
        use_batch: if True use Batch API (cheaper), if False use sync API (faster)
    Returns:
        str: path to saved image, or None on failure
    """
    if not api_key:
        logging.warning("No Gemini API key configured — skipping image generation")
        return None

    prompt = build_image_prompt(weather, calendar_state, now)
    logging.info("Image prompt: %s", prompt)
    mode = "batch" if use_batch else "sync"

    try:
        client = google.genai.Client(api_key=api_key)

        image_data = None
        used_model = None

        for model_name in MODEL_CANDIDATES:
            try:
                if use_batch:
                    image_data = _generate_via_batch(client, model_name, prompt)
                else:
                    image_data = _generate_via_sync(client, model_name, prompt)
                used_model = model_name
                break
            except google.genai.errors.ClientError as exc:
                if exc.status_code == 404:  # type: ignore[attr-defined]
                    logging.warning("Gemini model unavailable: %s", model_name)
                    continue
                raise

        if used_model is None:
            logging.error(
                "No supported Gemini image model found. Tried: %s",
                ", ".join(MODEL_CANDIDATES),
            )
            return None

        if image_data is None:
            return None

        _archive_current_image()

        os.makedirs(IMAGES_DIR, exist_ok=True)
        with open(CURRENT_IMAGE, "wb") as f:
            f.write(image_data)

        logging.info("Generated and saved new image to %s using %s (%s)", CURRENT_IMAGE, used_model, mode)
        return CURRENT_IMAGE

    except Exception:
        logging.exception("Failed to generate image via Gemini (%s)", mode)
        return None


def _generate_via_sync(client: typing.Any, model_name: str, prompt: str, max_retries: int = 2) -> bytes | None:
    """Generate an image using the standard synchronous API."""
    for attempt in range(1, max_retries + 1):
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={"response_modalities": ["IMAGE"]},
        )

        if not response.candidates:
            logging.error("No candidates in sync response for %s (attempt %d/%d)",
                          model_name, attempt, max_retries)
            return None

        content = response.candidates[0].content
        finish_reason = getattr(response.candidates[0], 'finish_reason', None)
        if not content or not content.parts:
            logging.warning("No content/parts in sync response for %s (finish_reason=%s, attempt %d/%d)",
                            model_name, finish_reason, attempt, max_retries)
            if attempt < max_retries:
                time.sleep(1)
                continue
            return None

        for part in content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                return part.inline_data.data

        logging.warning("No image data found in parts for %s (attempt %d/%d)", model_name, attempt, max_retries)
        if attempt < max_retries:
            time.sleep(1)
            continue

    logging.error("No image data in sync response for %s after %d attempts", model_name, max_retries)
    return None


def _generate_via_batch(client: typing.Any, model_name: str, prompt: str) -> bytes | None:
    """Generate an image using the Batch API (50% cheaper, minutes latency)."""
    batch_job = client.batches.create(
        model=model_name,
        src=[{
            "contents": [{
                "parts": [{"text": prompt}],
                "role": "user",
            }],
            "config": {
                "response_modalities": ["IMAGE"],
            },
        }],
        config={"display_name": "front-door-image"},
    )

    logging.info("Submitted batch job %s using %s", batch_job.name, model_name)

    # Poll until the job finishes
    completed_states = {
        "JOB_STATE_SUCCEEDED",
        "JOB_STATE_FAILED",
        "JOB_STATE_CANCELLED",
        "JOB_STATE_EXPIRED",
        "JOB_STATE_PARTIALLY_SUCCEEDED",
    }

    while batch_job.state.name not in completed_states:
        time.sleep(BATCH_POLL_INTERVAL_SECONDS)
        batch_job = client.batches.get(name=batch_job.name)
        logging.info("Batch job %s state: %s", batch_job.name, batch_job.state.name)

    if batch_job.state.name != "JOB_STATE_SUCCEEDED":
        logging.error(
            "Batch job %s finished with state %s: %s",
            batch_job.name, batch_job.state.name, batch_job.error,
        )
        return None

    return _extract_image_from_batch(batch_job)


def _extract_image_from_batch(batch_job: typing.Any) -> bytes | None:
    """Extract image bytes from a completed batch job's inline responses."""
    if not batch_job.dest or not batch_job.dest.inlined_responses:
        logging.error("No inline responses in batch job %s", batch_job.name)
        return None

    for inlined in batch_job.dest.inlined_responses:
        if inlined.error:
            logging.error("Batch response error: %s", inlined.error)
            continue
        if not inlined.response or not inlined.response.candidates:
            continue
        for part in inlined.response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                return part.inline_data.data

    logging.error("No image data found in batch job %s responses", batch_job.name)
    return None


def _archive_current_image() -> None:
    """Move current.png to history/ with a timestamp, keeping the last 24."""
    if not os.path.exists(CURRENT_IMAGE):
        return

    os.makedirs(HISTORY_DIR, exist_ok=True)
    timestamp = int(time.time())
    archive_path = os.path.join(HISTORY_DIR, f"{timestamp}.png")

    try:
        os.rename(CURRENT_IMAGE, archive_path)
    except OSError:
        logging.warning("Failed to archive current image")

    # Clean up old history, keeping only the last 24
    try:
        files = sorted(
            (f for f in os.listdir(HISTORY_DIR) if f.endswith(".png")),
            reverse=True,
        )
        for old_file in files[24:]:
            os.remove(os.path.join(HISTORY_DIR, old_file))
    except OSError:
        logging.warning("Failed to clean up image history")


def has_current_image() -> bool:
    """Check if a current generated image exists."""
    return os.path.exists(CURRENT_IMAGE)
