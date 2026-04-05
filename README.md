# front-door-display

A full-screen kiosk-style webapp for a Raspberry Pi 5 with a Raspberry Touch Display 2, mounted at the front door. It displays the current time, date, weather, and Jewish calendar information for Vaughan, Ontario.

## What it shows

- **Clock** — Large 12-hour time with AM/PM indicator, updated every second.
- **Date** — Full weekday and date (e.g. "Sunday, April 5, 2026").
- **Weather** — Current temperature, daily high/low, and a weather condition icon. Data from the [Open-Meteo API](https://open-meteo.com/), cached for 15 minutes.
- **Jewish calendar** — Powered by the [Hebcal API](https://www.hebcal.com/). Shows:
  - **Candle lighting & Havdalah times** in the top-right corner.
  - **Holiday and Shabbat status** — when it's Shabbat or Yom Tov, the background switches to a challah image with a gold overlay and displays the parashat hashavua or holiday name.
  - Automatically transitions between candle lighting and Havdalah display as the day progresses.

## Architecture

Pure vanilla JavaScript with ES modules — no framework, no build step.

| File | Purpose |
|---|---|
| `index.html` | Single-page structure with clock, date, holiday, Shabbat, and weather containers |
| `app.js` | Entry point — runs the 1-second update loop and triggers weather fetches |
| `ui.js` | All DOM manipulation — clock formatting, Shabbat/holiday display logic, offset controls |
| `calendar.js` | Hebcal API client — fetches and caches Jewish calendar events, exposes helpers for candle lighting, Havdalah, and Yom Tov |
| `weather.js` | Open-Meteo API client — fetches current weather and renders it with inline SVG icons |
| `utils.js` | Small helpers (`padZero`, `formatTime`) |
| `style.css` | Dark theme, responsive `vw`-based sizing, Shabbat background styling, hidden cursor for kiosk use |

## Debug offset controls

A hidden 100×100px hit target in the top-left corner opens time-offset buttons (`-1d`, `-6h`, `-3h`, now, `+3h`, `+6h`, `+1d`). This lets you scrub through time to test Shabbat/holiday transitions without waiting for them to happen naturally.

## Configuration

Location is hardcoded to **Vaughan, Ontario** (`43.8563, -79.5085`) in both `calendar.js` and `weather.js`. Candle lighting is set to 18 minutes before sunset and Havdalah to 42 minutes after.
