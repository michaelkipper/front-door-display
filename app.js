import { getShabbatDetails } from "./shabbat.js";
import { fetchWeather } from "./weather.js";
import { initializeOffsetControls, updateClockUI } from "./ui.js";

// --- State and Cache Variables ---
let timeOffset = 0;
let lastWeatherUpdate = null;
const WEATHER_CACHE_DURATION_MS = 15 * 60 * 1000; // 15 minutes

/**
 * Main function to update the entire clock display.
 */
function updateClock() {
  const now = new Date(Date.now() + timeOffset);
  const nowMs = now.getTime();

  // --- Update Weather if cache is stale ---
  if (
    !lastWeatherUpdate ||
    nowMs - lastWeatherUpdate > WEATHER_CACHE_DURATION_MS
  ) {
    fetchWeather();
    lastWeatherUpdate = nowMs;
  }

  // --- Shabbat Calculation Logic ---
  const { isShabbat, shabbatStartTime, shabbatEndTime } = getShabbatDetails(now);

  // --- UI Update Logic ---
  updateClockUI(now, isShabbat, shabbatStartTime, shabbatEndTime);
}

function setTimeOffset(offset) {
  timeOffset = offset;
}

// --- Main Execution ---
initializeOffsetControls(() => timeOffset, setTimeOffset, updateClock);
updateClock(); // Initial call
setInterval(updateClock, 1000);
