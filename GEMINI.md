# Front Door Display

## Instructions

You are a web developer, building an app for my house's front door. You are a full-stack web developer, writing high quality code. You prefer to write small, well-documented functions rather than having functions grow too large and become unreadable.

## Details

The front door display is a Raspberry Pi 5, running a Raspberry Pi Touch Display 2 at 720x1280.

Its primary purpose is to display the time, but it can display much more information, like:

* Shabbat candle lighting time
* Shabbat havdallah time
* Weather information
* Public holiday information

## Project overview

A full-screen kiosk webapp (Flask backend, vanilla JS frontend) showing the time,
date, weather (Open-Meteo), Jewish calendar data (Hebcal), stock quotes (yfinance),
water meter readings (ESP32-CAM Prometheus endpoint), and AI-generated background
images (Gemini). It also broadcasts voice announcements (gTTS + PyChromecast) to
Google Home speakers before candle lighting/havdalah, plus a "dinner bell".

Location is hardcoded to Vaughan, Ontario (43.8563, -79.5085) in `server.py`.
Candle lighting is 18 minutes before sunset; havdalah is 42 minutes after.

## Project structure

| File | Purpose |
|---|---|
| `server.py` | Flask app — routes, weather, Hebcal calendar state, background threads (image gen, water meter, announcements) |
| `image_gen.py` | Gemini image generation (batch + sync fallback) and context-aware prompt builder |
| `announcements.py` | Voice broadcasts to Chromecast speakers via gTTS (Shabbat reminders, dinner bell) |
| `stocks.py` | Stock quotes via yfinance (QQQ, SPY, GOOG), 5-minute cache |
| `water_meter.py` | Polls ESP32-CAM Prometheus endpoint, keeps 30-minute rolling history |
| `config.py` | Secrets (gitignored) — see `config.example.py` |
| `templates/index.html` | Single-page kiosk UI + thin JS (clock tick, periodic `/api/state` fetch) |
| `static/` | CSS/JS for clock, water meter, hourglass; fallback `challah.png` background |
| `server_test.py` | Tests for calendar logic, Shabbat/Yom Tov detection, image staleness, prompt builder |
| `announcements_test.py` | Tests for the announcements module |
| `autostart.sh` | Deployed to `~/.config/labwc/autostart` on the Pi — starts the server + kiosk Chromium |

## Commands

```bash
pip install -r requirements.txt        # runtime deps
pip install -r requirements-dev.txt    # pyright + pytest
cp config.example.py config.py         # then add your Gemini API key

python server.py                       # run on port 8080 (absl flag: --port)
pytest                                 # run all tests (files are named *_test.py)
pyright                                # type check (standard mode)
```

## API endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Main kiosk page |
| `/api/state` | GET | Weather, holiday, candle lighting, background image, stocks |
| `/api/offset` | POST | Debug time offset (`{"offset_ms": ...}` or `{"action": "reset"}`) |
| `/api/test-announcement` | POST | Trigger a test voice broadcast |
| `/api/dinner-bell` | POST | Play the dinner bell announcement |
| `/api/chromecast-devices` | GET | List discovered Chromecast devices |
| `/api/water`, `/api/water/history` | GET | Current water reading / 30-min history |
| `/images/<file>`, `/api/images/history` | GET | Generated background images |

A hidden 100×100px hit target in the top-left corner of the UI opens time-offset
controls (`-1d` … `+1d`) for testing Shabbat/holiday transitions. The offset is
applied server-side via `_now()`, so all modules see the adjusted time.

## Coding conventions

* Every Python file starts with `from __future__ import annotations`; target Python 3.10.
* Use `absl-py` for logging (`from absl import logging`) and CLI flags — not `print` or `argparse`.
* Small, single-purpose functions with docstrings; separate sections with
  `# ---------------------------------------------------------------------------` dividers.
* Type hints throughout; pyright runs in standard mode (see `pyrightconfig.json`).
* Module-level cached state follows the `{"data": None, "timestamp": 0}` pattern,
  with throttled error logging (`_log_throttled` / `_last_error_log`) to avoid log spam.
* Network calls use `NETWORK_TIMEOUT = (3.05, 8)` with retry/backoff (`_get_json_with_retries`).
* Tests live in `*_test.py` files (pytest pattern configured in `pyproject.toml`),
  use pytest fixtures to reset module state, and mock external APIs (Hebcal, Chromecast).
* Never commit `config.py` or generated `images/`.

## Deployment

Runs as a kiosk on the Pi: `autostart.sh` (labwc autostart) launches the server
with the venv python, logs to `server.log`, then opens Chromium in kiosk mode
pointing at `http://localhost:8080`. Images are generated hourly between 6am and
midnight, saved to `images/current.png` with history in `images/history/`; if no
Gemini key is configured, `static/challah.png` is the fallback background.
