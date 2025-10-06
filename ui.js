import { formatTime, padZero } from "./utils.js";
import { getCalendarEvents } from "./calendar.js";

// Select the DOM elements
const timeStringElement = document.getElementById("time-string");
const dateDisplayElement = document.getElementById("date-display");
const amIndicator = document.getElementById("am-indicator");
const pmIndicator = document.getElementById("pm-indicator");
const shabbatInfoElement = document.getElementById("shabbat-time-info");
const offsetControlsElement = document.getElementById("offset-controls");
const offsetTriggerElement = document.getElementById("offset-trigger");
const holidayInfoElement = document.getElementById("holiday-info");


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

export async function updateClockUI(now) {
  // --- Time Formatting ---
  let hours = now.getHours();
  const minutes = padZero(now.getMinutes());
  const seconds = padZero(now.getSeconds());
  hours = hours % 12;
  hours = hours ? hours : 12;
  timeStringElement.textContent = `${hours}:${minutes}:${seconds}`;
  setAmPmIndicator(now);

  let today = new Date(now);
  let tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);

  // --- Calendar Calculation Logic ---
  const todayCalendarEvents = await getCalendarEvents(today);
  const tomorrowCalendarEvents = await getCalendarEvents(tomorrow);

  const candleLightingEvents = todayCalendarEvents.filter(event => event.isCandleLighting);
  if (candleLightingEvents.length > 0) {
    const event = candleLightingEvents[0];
    if (now < candleLightingEvents[0].parsedDate) {
      // We light candles today, but it's not yet time.
      shabbatInfoElement.textContent = `Candle Lighting: ${formatTime(event.parsedDate)}`;
      shabbatInfoElement.style.display = "block";
    } else {
      const tomorrowHavdalahEvents = tomorrowCalendarEvents.filter(event => event.category === "havdalah");
      if (tomorrowHavdalahEvents.length > 0) {
        shabbatInfoElement.textContent = `Havdalah: ${formatTime(new Date(tomorrowHavdalahEvents[0].date))}`;
        shabbatInfoElement.style.display = "block";
      }
    }
  } else {
    // There is no candle lighting today.
  }

  const havdalahEvents = todayCalendarEvents.filter(event => event.category === "havdalah");
  const holidayEvents = todayCalendarEvents.filter(event => event.isHoliday);
  const shabbatEvents = todayCalendarEvents.filter(event => event.isShabbat);

  // --- UI Update Logic ---
  if (holidayEvents.length > 0) {
    const event = holidayEvents[0];
    holidayInfoElement.textContent = event.title;

    if (event.isShabbat) {
      document.body.classList.add("shabbat-background");
    } else {
      document.body.classList.remove("shabbat-background");
    }

    dateDisplayElement.className = "shabbat";
  } else {
    document.body.classList.remove("shabbat-background");
  }

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

  if (candleLightingEvents.length > 0) {
  } else if (havdalahEvents.length > 0) {
    const event = havdalahEvents[0];
    shabbatInfoElement.textContent = `Havdalah: ${formatTime(new Date(event.date))}`;
    shabbatInfoElement.style.display = "block";
  } else {
    shabbatInfoElement.style.display = "none";
  }
}
