"""
Image generation using Gemini 2.5 Flash.

Generates context-aware background images based on weather, holiday,
time of day, and season. Images are saved to the images/ directory.
"""

from absl import logging
import os
import time

from google import genai
from google.genai import errors as genai_errors

IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
CURRENT_IMAGE = os.path.join(IMAGES_DIR, "current.png")
HISTORY_DIR = os.path.join(IMAGES_DIR, "history")

# Ordered model candidates for image generation.
# The first available model in this list will be used.
MODEL_CANDIDATES = [
    "gemini-2.5-flash-image",
    "gemini-2.5-flash-image-preview",
    "gemini-2.0-flash-preview-image-generation",
]

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


def _get_season(month, temp):
    """Infer season from month and temperature."""
    if month in (12, 1, 2) or temp < 0:
        return "Winter"
    elif month in (3, 4, 5):
        return "Spring"
    elif month in (6, 7, 8):
        return "Summer"
    else:
        return "Autumn"


def _get_time_of_day(hour):
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


def _get_holiday_context(holiday_name, events):
    """Get holiday-specific imagery description from event titles."""
    if not events:
        return None

    all_text = " ".join(e.get("title", "").lower() for e in events)

    if "pesach" in all_text or "passover" in all_text:
        return "matzah bread on a Passover seder plate, spring flowers"
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


def build_image_prompt(weather, calendar_state, now):
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

    prompt = ". ".join(parts) + "."
    return prompt


def generate_image(api_key, weather, calendar_state, now):
    """
    Generate an image using Gemini 2.5 Flash and save it.

    Args:
        api_key: Gemini API key string
        weather: dict with weather data (or None)
        calendar_state: dict with calendar state
        now: datetime object
    Returns:
        str: path to saved image, or None on failure
    """
    if not api_key:
        logging.warning("No Gemini API key configured — skipping image generation")
        return None

    prompt = build_image_prompt(weather, calendar_state, now)
    logging.info("Image prompt: %s", prompt)

    try:
        client = genai.Client(api_key=api_key)

        response = None
        used_model = None
        for model_name in MODEL_CANDIDATES:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                    ),
                )
                used_model = model_name
                break
            except genai_errors.ClientError as exc:
                # Model not found / unsupported: try next candidate.
                if exc.status_code == 404:
                    logging.warning("Gemini model unavailable: %s", model_name)
                    continue
                raise

        if response is None:
            logging.error(
                "No supported Gemini image model found. Tried: %s",
                ", ".join(MODEL_CANDIDATES),
            )
            return None

        # Extract image data from response
        if not response.candidates:
            logging.error("No candidates in Gemini response")
            return None

        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                image_data = part.inline_data.data
                break
        else:
            logging.error("No image data found in Gemini response")
            return None

        # Archive current image before overwriting
        _archive_current_image()

        os.makedirs(IMAGES_DIR, exist_ok=True)
        with open(CURRENT_IMAGE, "wb") as f:
            f.write(image_data)

        logging.info("Generated and saved new image to %s using %s", CURRENT_IMAGE, used_model)
        return CURRENT_IMAGE

    except Exception:
        logging.exception("Failed to generate image via Gemini")
        return None


def _archive_current_image():
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


def has_current_image():
    """Check if a current generated image exists."""
    return os.path.exists(CURRENT_IMAGE)
