import { formatTime, padZero } from "./utils.js";
import { getCalendarEvents, isYomTov, getNextCandleLightingEvent, getNextHavdalahEvent, isToday } from "./calendar.js";

// Select the DOM elements
const timeStringElement = document.getElementById("time-string");
const dateDisplayElement = document.getElementById("date-display");
const amIndicator = document.getElementById("am-indicator");
const pmIndicator = document.getElementById("pm-indicator");
const shabbatInfoElement = document.getElementById("shabbat-time-info");
const offsetControlsElement = document.getElementById("offset-controls");
const offsetTriggerElement = document.getElementById("offset-trigger");
const holidayInfoElement = document.getElementById("holiday-info");

// Days of the week.
const SUNDAY = 0;
const MONDAY = 1;
const TUESDAY = 2;
const WEDNESDAY = 3;
const THURSDAY = 4;
const FRIDAY = 5;
const SATURDAY = 6;

/**
 * Initializes the offset controls and listeners.
 */
export function initializeOffsetControls(getTimeOffset, setTimeOffset, updateClock) {
  offsetTriggerElement.addEventListener("click", () =>
    offsetControlsElement.classList.add("visible")
  );
  offsetControlsElement.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.action === "close") {
      offsetControlsElement.classList.remove("visible");
      return;
    }
    const offsetAction = button.dataset.offsetMs;
    if (offsetAction === "reset") {
      setTimeOffset(0);
    } else if (offsetAction) {
      setTimeOffset(getTimeOffset() + parseInt(offsetAction, 10));
    }

    updateClock();
  });
}

function setAmPmIndicator(now) {
  const isAm = now.getHours() < 12;
  if (isAm) {
    amIndicator.classList.add("active");
    amIndicator.classList.remove("inactive");
    pmIndicator.classList.add("inactive");
    pmIndicator.classList.remove("active");
  } else {
    pmIndicator.classList.add("active");
    pmIndicator.classList.remove("inactive");
    amIndicator.classList.add("inactive");
    amIndicator.classList.remove("active");
  }
}

function isShabbat(now, candleLightingEvents, havdalahEvents) {
  // Check to see if it's Saturday.
  if (now.getDay() == SATURDAY) {
    if (havdalahEvents.length > 0 && now >= havdalahEvents[0].parsedDate) {
      return false;
    }
    return true;
  } else if (now.getDay() == FRIDAY) {
    if (candleLightingEvents.length > 0 && now >= candleLightingEvents[0].parsedDate) {
      return true;
    }
    return false;
  }

  return false;
}

export async function updateClockUI(now) {
  // --- Time Formatting ---
  let hours = now.getHours();
  const minutes = padZero(now.getMinutes());
  const seconds = padZero(now.getSeconds());
  hours = hours % 12;
  hours = hours ? hours : 12;
  timeStringElement.textContent = `${hours}:${minutes}:${seconds}`;
  setAmPmIndicator(now);

  // --- Calendar Calculation Logic ---
  let events = await getCalendarEvents(now);
  let candleLightingEvents = events.filter(event => event.isCandleLighting);
  let havdalahEvents = events.filter(event => event.isHavdalah);

  // If today was a day that we light candles, and it's past candle-lighting time,
  // then update events to be tomorrow's events.
  if (candleLightingEvents.length > 0) {
    const event = candleLightingEvents[0];
    if (now >= event.parsedDate) {
      let tomorrow = new Date(now);
      tomorrow.setDate(tomorrow.getDate() + 1);

      events = await getCalendarEvents(tomorrow);
      candleLightingEvents = events.filter(event => event.isCandleLighting);
      havdalahEvents = events.filter(event => event.isHavdalah);
    }
  } else if (havdalahEvents.length > 0) {
    const event = havdalahEvents[0];
    if (now >= event.parsedDate) {
      let tomorrow = new Date(now);
      tomorrow.setDate(tomorrow.getDate() + 1);

      events = await getCalendarEvents(tomorrow);
      candleLightingEvents = events.filter(event => event.isCandleLighting);
      havdalahEvents = events.filter(event => event.isHavdalah);
    }
  }

  if (candleLightingEvents.length > 0) {
    const event = candleLightingEvents[0];
    shabbatInfoElement.textContent = `Candle Lighting: ${formatTime(event.parsedDate)}`;
    shabbatInfoElement.style.display = "block";
    document.body.classList.remove("shabbat-background");
  } else if (havdalahEvents.length > 0) {
    const event = havdalahEvents[0];
    shabbatInfoElement.textContent = `Havdalah: ${formatTime(event.parsedDate)}`;
    shabbatInfoElement.style.display = "block";
    document.body.classList.remove("shabbat-background");
  } else {
    shabbatInfoElement.style.display = "none";
    document.body.classList.remove("shabbat-background");
  }

  const holidayEvents = events.filter(event => event.isHoliday);
  const yomTovEvents = events.filter(event => event.isYomTov);
  const shabbatEvents = events.filter(event => event.isShabbat);

  // --- UI Update Logic ---
  if (yomTovEvents.length > 0) {
    // It's chag.
    document.body.classList.add("shabbat-background");
    
    const event = yomTovEvents[0];
    console.log("It's currently a YomTov:", event);
    holidayInfoElement.textContent = event.title;
    holidayInfoElement.style.display = "block";
    dateDisplayElement.className = "shabbat";
  } else if (shabbatEvents.length > 0) {
    // It's Shabbat.
    document.body.classList.add("shabbat-background");

    const event = shabbatEvents[0];
    console.log("It's currently Shabbat:", event);
    holidayInfoElement.textContent = event.title;
    holidayInfoElement.style.display = "block";
    dateDisplayElement.className = "shabbat";
  } else if (holidayEvents.length > 0) {
    // It's a non-chag holiday.
    document.body.classList.remove("shabbat-background");

    const event = holidayEvents[0];
    console.log("It's currently a holiday:", event);
    holidayInfoElement.textContent = event.title;
    holidayInfoElement.stype = "block";
    dateDisplayElement.className = "shabbat";
  } else {
    // It's a regular weekday.
    holidayInfoElement.style.display = "none";
    document.body.classList.remove("shabbat-background");
  }

  // --- Write the current date ---
  const dateOptions = {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  };
  dateDisplayElement.textContent = new Intl.DateTimeFormat(
    "en-US",
    dateOptions
  ).format(now);
  dateDisplayElement.className = "date";
}
