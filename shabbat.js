// --- Location & API Settings ---
const LATITUDE = 43.8563; // Vaughan, Ontario
const LONGITUDE = -79.5085; // Vaughan, Ontario

// Start shabbat 18 minutes before sunset, and end 40 minutes after.
const shabbatStartOffsetMs = 18 * 60000;
const shabbatEndOffsetMs = 40 * 60000;

let sunCalcCache = {};
let lastSunCalcUpdate = { ms: null, date: null };
const SUN_CACHE_DURATION_MS = 5 * 60 * 1000; // 5 minutes

/**
 * Gets Shabbat details, using a cached result if available.
 */
export function getShabbatDetails(date) {
  const nowMs = date.getTime();
  const currentDate = date.getDate();

  const isCacheInvalid =
    !lastSunCalcUpdate.ms ||
    nowMs - lastSunCalcUpdate.ms > SUN_CACHE_DURATION_MS ||
    currentDate !== lastSunCalcUpdate.date;

  if (isCacheInvalid) {
    console.log(
      `[${new Date().toLocaleTimeString()}] Refreshing SunCalc cache...`
    );
    const yesterday = new Date(date);
    yesterday.setDate(date.getDate() - 1);
    const tomorrow = new Date(date);
    tomorrow.setDate(date.getDate() + 1);
    sunCalcCache = {
      yesterday: SunCalc.getTimes(yesterday, LATITUDE, LONGITUDE),
      today: SunCalc.getTimes(date, LATITUDE, LONGITUDE),
      tomorrow: SunCalc.getTimes(tomorrow, LATITUDE, LONGITUDE),
    };
    lastSunCalcUpdate = { ms: nowMs, date: currentDate };
  }

  const dayOfWeek = date.getDay();
  let shabbatStartTime,
    shabbatEndTime,
    isShabbat = false;

  if (dayOfWeek === 5) {
    // It's Friday
    shabbatStartTime = new Date(
      sunCalcCache.today.sunset.getTime() - shabbatStartOffsetMs
    );
    shabbatEndTime = new Date(
      sunCalcCache.tomorrow.sunset.getTime() + shabbatEndOffsetMs
    );
    isShabbat = date >= shabbatStartTime;
  } else if (dayOfWeek === 6) {
    // It's Saturday
    shabbatStartTime = new Date(
      sunCalcCache.yesterday.sunset.getTime() - shabbatStartOffsetMs
    );
    shabbatEndTime = new Date(
      sunCalcCache.today.sunset.getTime() + shabbatEndOffsetMs
    );
    isShabbat = date < shabbatEndTime;
  }

  return { isShabbat, shabbatStartTime, shabbatEndTime };
}
