// Vaughan, Ontario
const LATITUDE = 43.8563;
const LONGITUDE = -79.5085;

let fetchCalendarEventsCache = {
  timestamp: 0,
  events: [],
}
let getCalendarEventsCache = {
  timestamp: 0,
  events: [],
}

function parseDate(dateString) {
  const hasTime = dateString.includes('T') || dateString.includes(':');
  if (!hasTime) {
    dateString = dateString + "T00:00:01";
  }
  return new Date(dateString);
}

async function fetchCalendarEvents(now) {
  if (Date.now() - fetchCalendarEventsCache.timestamp < 5 * 60 * 1000) {
    console.log("Using cached calendar events from", new Date(fetchCalendarEventsCache.timestamp));
    return fetchCalendarEventsCache.events;
  }

  const start = new Date(now);
  const end = new Date(now);
  end.setMonth(end.getMonth() + 1);

  const hebcalUrl = new URL("https://www.hebcal.com/hebcal");
  hebcalUrl.searchParams.set("v", "1"); // API version
  hebcalUrl.searchParams.set("cfg", "json"); // JSON format
  hebcalUrl.searchParams.set("start", start.toISOString().split('T')[0]);
  hebcalUrl.searchParams.set("end", end.toISOString().split('T')[0]);
  hebcalUrl.searchParams.set("maj", "on"); // Major holidays
  hebcalUrl.searchParams.set("min", "on"); // Minor holidays
  hebcalUrl.searchParams.set("c", "on"); // Candle lighting
  hebcalUrl.searchParams.set("latitude", LATITUDE);
  hebcalUrl.searchParams.set("longitude", LONGITUDE);
  hebcalUrl.searchParams.set("b", "18"); // Candle lighting minutes
  hebcalUrl.searchParams.set("m", "42"); // Havdalah minutes
  hebcalUrl.searchParams.set("s", "off"); // Sedra

  console.log("Calling the HebCal API:", hebcalUrl.toString());
  const response = await fetch(hebcalUrl).then((response) => response.json());
  fetchCalendarEventsCache.timestamp = Date.now();
  fetchCalendarEventsCache.events = response.items.map(event => {
    return {
      ...event,
      isHoliday: event.category === "holiday",
      isShabbat: event.category === "shabbat",
      isYomTov: event.yomtov === true,
      isCandleLighting: event.category === "candles",
      parsedDate: parseDate(event.date),
    }
  });

  console.log("Retrieved", fetchCalendarEventsCache.events.length, "event(s):");
  fetchCalendarEventsCache.events.forEach(element => {
    console.log(element);
  });

  return fetchCalendarEventsCache.events;
}

/**
 * @returns {Promise<any>}
 */
export async function getCalendarEvents(now) {
  // if (Date.now() - getCalendarEventsCache.timestamp < 0 * 1000) {
  //   console.log("Using cached calendar events from", new Date(getCalendarEventsCache.timestamp));
  //   return getCalendarEventsCache.events;
  // }

  console.log("Getting calendar events...");
  const allEvents = await fetchCalendarEvents(now);

  getCalendarEventsCache.timestamp = Date.now();
  getCalendarEventsCache.events = allEvents.filter(event => {
    return event.parsedDate.getFullYear() === now.getFullYear() &&
           event.parsedDate.getMonth() === now.getMonth() &&
           event.parsedDate.getDate() === now.getDate();
  });

  console.log("Found", getCalendarEventsCache.events.length, "event(s) today:");
  getCalendarEventsCache.events.forEach(element => {
    console.log(element);
  });

  return getCalendarEventsCache.events;
}
