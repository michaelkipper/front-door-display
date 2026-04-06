# Front Door Display

A full-screen kiosk-style webapp for a Raspberry Pi 5 with a Raspberry Touch Display 2 (1280×720 landscape), mounted at the front door. It displays the current time, date, weather, and Jewish calendar information for Vaughan, Ontario.

## What it shows

- **Clock** — Large 12-hour time with AM/PM indicator, updated every second.
- **Date** — Full weekday and date (e.g. "Sunday, April 5, 2026").
- **Weather** — Current temperature, daily high/low, and a weather condition icon. Data from the [Open-Meteo API](https://open-meteo.com/), cached for 15 minutes.
- **Jewish calendar** — Powered by the [Hebcal API](https://www.hebcal.com/). Shows:
  - **Candle lighting & Havdalah times** in the top-right corner.
  - **Holiday and Shabbat status** — when it's Shabbat or Yom Tov, the background switches to a generated image with a dark overlay and displays the parashat hashavua or holiday name.
  - Automatically transitions between candle lighting and Havdalah display as the day progresses.
- **Dynamic backgrounds** — Context-aware images generated hourly (6am–midnight) via Gemini 2.5 Flash. The prompt incorporates current weather, holiday context, time of day, and season.

## Architecture

Python Flask backend with a thin vanilla JavaScript frontend (clock tick + periodic state fetch).

| File | Purpose |
|---|---|
| `server.py` | Flask app — calendar, weather, state API, image scheduler |
| `image_gen.py` | Gemini image generation + context-aware prompt builder |
| `config.py` | Gemini API key (gitignored) |
| `templates/index.html` | Single-page UI with clock, date, holiday, weather containers + thin JS |
| `static/style.css` | Dark theme, responsive `vw`-based sizing, Shabbat background styling |
| `static/challah.png` | Fallback background image when no Gemini key is configured |
| `test_server.py` | pytest tests for calendar logic, Shabbat detection, prompt builder |

### API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Serves the main HTML page |
| `/api/state` | GET | Returns JSON with weather, holiday, candle lighting, background image |
| `/api/offset` | POST | Debug time offset (body: `{"action": "reset"}` or `{"offset_ms": 3600000}`) |

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in your Gemini API key
cp config.example.py config.py
# Edit config.py with your key

# Run the server
python server.py
```

The server starts at `http://localhost:8080`. Images are generated hourly and saved to `images/current.png`.

## Image generation

Background images are generated hourly (6am–midnight) using **Gemini 2.5 Flash** (`$0.0195/image`, ~`$10.53/month`). The prompt combines:

- **Weather**: temperature, conditions (rain → moody, sun → bright, snow → cozy)
- **Holiday**: Pesach → seder plate, Chanukah → menorah, Shabbat → challah & candles
- **Time of day**: dawn light, bright midday, golden hour sunset, cool evening
- **Season**: inferred from month and temperature

If no API key is configured, `challah.png` is used as a fallback.

## Debug offset controls

A hidden 100×100px hit target in the top-left corner opens time-offset buttons (`-1d`, `-6h`, `-3h`, now, `+3h`, `+6h`, `+1d`). This lets you scrub through time to test Shabbat/holiday transitions. The offset is applied server-side so all state (calendar, weather, image scheduling) reflects the adjusted time.

## Configuration

Location is hardcoded to **Vaughan, Ontario** (`43.8563, -79.5085`) in `server.py`. Candle lighting is set to 18 minutes before sunset and Havdalah to 42 minutes after.

## Running tests

```bash
pip install pytest
pytest test_server.py -v
```
