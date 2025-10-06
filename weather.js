const weatherInfoElement = document.getElementById("weather-info");

// --- Location & API Settings ---
const LATITUDE = 43.8563; // Vaughan, Ontario
const LONGITUDE = -79.5085; // Vaughan, Ontario

/**
 * Gets a weather icon SVG based on the WMO weather code.
 * @param {number} code The WMO code.
 * @returns {string} An SVG string for the corresponding weather icon.
 */
function getWeatherIcon(code) {
  // Simplified mapping of WMO codes to icons
  if (code === 0)
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`; // Sun
  if (code >= 1 && code <= 3)
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path></svg>`; // Cloud
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82))
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25"></path><line x1="8" y1="19" x2="8" y2="21"></line><line x1="12" y1="19" x2="12" y2="21"></line><line x1="16" y1="19" x2="16" y2="21"></line></svg>`; // Rain
  if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86))
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 17.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25"></path><line x1="8" y1="19" x2="8" y2="21"></line><line x1="12" y1="19" x2="12" y2="21"></line><line x1="16" y1="19" x2="16" y2="21"></line><line x1="10" y1="15" x2="14" y2="15"></line><line x1="9" y1="12" x2="11" y2="12"></line><line x1="13" y1="12" x2="15" y2="12"></line></svg>`; // Snow
  if (code >= 95 && code <= 99)
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16.5c0-1.68-1.34-3-3-3h-1.26a8 8 0 1 0-11.48 0H4c-1.66 0-3 1.32-3 3s1.34 3 3 3h14c1.66 0 3-1.32 3-3z"></path><polyline points="13 11 9 17 15 17 11 23"></polyline></svg>`; // Thunderstorm
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"></path></svg>`; // Default to Cloud
}

/**
 * Fetches weather data and updates the UI.
 */
export async function fetchWeather() {
  const url = `https://api.open-meteo.com/v1/forecast?latitude=${LATITUDE}&longitude=${LONGITUDE}&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min&temperature_unit=celsius&timezone=auto`;
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Weather data not available");
    const data = await response.json();

    const temperature = Math.round(data.current.temperature_2m);
    const weatherCode = data.current.weather_code;
    const highTemp = Math.round(data.daily.temperature_2m_max[0]);
    const lowTemp = Math.round(data.daily.temperature_2m_min[0]);

    weatherInfoElement.innerHTML = `
              ${getWeatherIcon(weatherCode)}
              <div class="weather-details">
                  <span class="current-temp">${temperature}°C</span>
                  <div class="high-low-temp">
                      <span>H: ${highTemp}°</span>
                      <span>L: ${lowTemp}°</span>
                  </div>
              </div>
          `;
  } catch (error) {
    console.error("Failed to fetch weather:", error);
    weatherInfoElement.innerHTML = `<span>--°C</span>`;
  }
}
