import { formatTime, padZero } from "./utils.js";

// Select the DOM elements
const timeStringElement = document.getElementById("time-string");
const dateDisplayElement = document.getElementById("date-display");
const amIndicator = document.getElementById("am-indicator");
const pmIndicator = document.getElementById("pm-indicator");
const shabbatInfoElement = document.getElementById("shabbat-time-info");
const offsetControlsElement = document.getElementById("offset-controls");
const offsetTriggerElement = document.getElementById("offset-trigger");

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

export function updateClockUI(now, isShabbat, shabbatStartTime, shabbatEndTime) {
  // --- Time Formatting ---
  let hours = now.getHours();
  const minutes = padZero(now.getMinutes());
  const seconds = padZero(now.getSeconds());
  const isAm = hours < 12;
  hours = hours % 12;
  hours = hours ? hours : 12;
  timeStringElement.textContent = `${hours}:${minutes}:${seconds}`;
  setAmPmIndicator(now);

  // --- UI Update Logic ---
  if (isShabbat) {
    document.body.classList.add("shabbat-background");
    shabbatInfoElement.textContent = `Shabbat Ends: ${formatTime(
      shabbatEndTime
    )}`;
    shabbatInfoElement.style.display = "block";
  } else {
    document.body.classList.remove("shabbat-background");
    if (now.getDay() === 5) {
      shabbatInfoElement.textContent = `Shabbat Starts: ${formatTime(
        shabbatStartTime
      )}`;
      shabbatInfoElement.style.display = "block";
    } else {
      shabbatInfoElement.style.display = "none";
    }
  }

  if (isShabbat) {
    dateDisplayElement.textContent = "Shabbat Shalom";
    dateDisplayElement.className = "shabbat";
  } else {
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
}
