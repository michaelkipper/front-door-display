import { describe, it, expect, vi, beforeEach } from 'vitest';

// Cached API response for April 1-6, 2026 (Passover period)
// Fetched from: https://www.hebcal.com/hebcal?v=1&cfg=json&start=2026-04-01&end=2026-04-06&maj=on&min=on&c=on&latitude=43.8563&longitude=-79.5085&b=18&m=42&s=on
const PASSOVER_API_RESPONSE = {
  items: [
    { title: "Erev Pesach", date: "2026-04-01", category: "holiday", subcat: "major" },
    { title: "Candle lighting: 7:27pm", date: "2026-04-01T19:27:00-04:00", category: "candles", title_orig: "Candle lighting" },
    { title: "Pesach I", date: "2026-04-02", category: "holiday", subcat: "major", yomtov: true },
    { title: "Candle lighting: 8:28pm", date: "2026-04-02T20:28:00-04:00", category: "candles", title_orig: "Candle lighting" },
    { title: "Pesach II", date: "2026-04-03", category: "holiday", subcat: "major", yomtov: true },
    { title: "Candle lighting: 7:29pm", date: "2026-04-03T19:29:00-04:00", category: "candles", title_orig: "Candle lighting" },
    { title: "Pesach III (CH''M)", date: "2026-04-04", category: "holiday", subcat: "major" },
    { title: "Havdalah (42 min): 8:31pm", date: "2026-04-04T20:31:00-04:00", category: "havdalah", title_orig: "Havdalah" },
    { title: "Pesach IV (CH''M)", date: "2026-04-05", category: "holiday", subcat: "major" },
    { title: "Pesach V (CH''M)", date: "2026-04-06", category: "holiday", subcat: "major" },
  ],
};

// Cached API response for April 10-12, 2026 (regular Shabbat after Passover)
// Fetched from: https://www.hebcal.com/hebcal?v=1&cfg=json&start=2026-04-10&end=2026-04-12&maj=on&min=on&c=on&latitude=43.8563&longitude=-79.5085&b=18&m=42&s=on
const REGULAR_SHABBAT_API_RESPONSE = {
  items: [
    { title: "Candle lighting: 7:37pm", date: "2026-04-10T19:37:00-04:00", category: "candles", title_orig: "Candle lighting" },
    { title: "Parashat Shmini", date: "2026-04-11", category: "parashat", link: "https://hebcal.com/s/5786/26" },
    { title: "Havdalah (42 min): 8:39pm", date: "2026-04-11T20:39:00-04:00", category: "havdalah", title_orig: "Havdalah" },
  ],
};

function setupDOM() {
  document.body.innerHTML = `
    <div id="offset-trigger"></div>
    <div id="offset-controls"></div>
    <div class="clock-container">
      <div id="time" class="time">
        <span id="time-string">12:34:56</span>
        <div class="ampm-stack">
          <span id="am-indicator" class="inactive">AM</span>
          <span id="pm-indicator" class="active">PM</span>
        </div>
      </div>
      <div id="date-display" class="date">Monday, 1 January</div>
      <div id="holiday-info" class="date" style="display:none">Holiday Info</div>
    </div>
    <div id="shabbat-time-info"></div>
    <div id="weather-info"></div>
  `;
}

function mockFetch(apiResponse) {
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve(apiResponse),
    })
  ));
}

describe('calendar.js', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    setupDOM();
  });

  describe('getCalendarEvents', () => {
    it('should return only events matching the given date', async () => {
      mockFetch(PASSOVER_API_RESPONSE);
      const { getCalendarEvents } = await import('./calendar.js');

      const friday = new Date('2026-04-03T12:00:00-04:00');
      const events = await getCalendarEvents(friday);

      // Should find Pesach II and candle lighting for April 3
      expect(events.length).toBe(2);
      expect(events.some(e => e.title === 'Pesach II')).toBe(true);
      expect(events.some(e => e.isCandleLighting)).toBe(true);
    });

    it('should return Saturday Chol HaMoed events for April 4', async () => {
      mockFetch(PASSOVER_API_RESPONSE);
      const { getCalendarEvents } = await import('./calendar.js');

      const saturday = new Date('2026-04-04T12:00:00-04:00');
      const events = await getCalendarEvents(saturday);

      // Should find Pesach III (CH''M) and Havdalah
      expect(events.length).toBe(2);
      expect(events.some(e => e.title.includes("Pesach III"))).toBe(true);
      expect(events.some(e => e.isHavdalah)).toBe(true);

      // Critically: NO parashat event on Shabbat Chol HaMoed
      expect(events.some(e => e.isShabbat)).toBe(false);
      // And Chol HaMoed is NOT yomtov
      expect(events.some(e => e.isYomTov)).toBe(false);
    });

    it('should return parashat event for regular Shabbat', async () => {
      mockFetch(REGULAR_SHABBAT_API_RESPONSE);
      const { getCalendarEvents } = await import('./calendar.js');

      const saturday = new Date('2026-04-11T12:00:00-04:00');
      const events = await getCalendarEvents(saturday);

      expect(events.some(e => e.isShabbat)).toBe(true);
      expect(events.some(e => e.title === 'Parashat Shmini')).toBe(true);
    });
  });
});

describe('ui.js — Shabbat display', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    setupDOM();
  });

  it('should show Shabbat on a regular Friday night after candle lighting', async () => {
    mockFetch(REGULAR_SHABBAT_API_RESPONSE);
    const { updateClockUI } = await import('./ui.js');

    // Friday April 10, 2026 at 10pm (after candle lighting at 7:37pm)
    const fridayNight = new Date('2026-04-10T22:00:00-04:00');
    await updateClockUI(fridayNight);

    expect(document.body.classList.contains('shabbat-background')).toBe(true);
    const holidayInfo = document.getElementById('holiday-info');
    expect(holidayInfo.textContent).toBe('Parashat Shmini');
  });

  it('BUG: should show Shabbat on Friday night during Passover (Chol HaMoed transition)', async () => {
    mockFetch(PASSOVER_API_RESPONSE);
    const { updateClockUI } = await import('./ui.js');

    // Friday April 3, 2026 at 10pm EDT
    // Pesach II (Yom Tov) has ended, Shabbat has begun (candle lighting was 7:29pm)
    // Saturday is Pesach III (Chol HaMoed) with no parashat event
    const fridayNight = new Date('2026-04-03T22:00:00-04:00');
    await updateClockUI(fridayNight);

    // The display should show Shabbat background because it IS Shabbat
    // (Friday night after candle lighting), even though Saturday's events
    // have no parashat event (Chol HaMoed replaces the weekly portion)
    expect(document.body.classList.contains('shabbat-background')).toBe(true);
  });

  it('should show Shabbat on Saturday during Chol HaMoed Pesach', async () => {
    mockFetch(PASSOVER_API_RESPONSE);
    const { updateClockUI } = await import('./ui.js');

    // Saturday April 4, 2026 at noon — Shabbat Chol HaMoed Pesach
    const saturdayNoon = new Date('2026-04-04T12:00:00-04:00');
    await updateClockUI(saturdayNoon);

    // It IS Shabbat (Saturday before havdalah), should show Shabbat background
    expect(document.body.classList.contains('shabbat-background')).toBe(true);
  });

  it('should NOT show Shabbat on Saturday after havdalah', async () => {
    mockFetch(PASSOVER_API_RESPONSE);
    const { updateClockUI } = await import('./ui.js');

    // Saturday April 4, 2026 at 9pm — after havdalah at 8:31pm
    const saturdayAfterHavdalah = new Date('2026-04-04T21:00:00-04:00');
    await updateClockUI(saturdayAfterHavdalah);

    expect(document.body.classList.contains('shabbat-background')).toBe(false);
  });

  it('should show Yom Tov on Friday afternoon during Pesach II (before candle lighting)', async () => {
    mockFetch(PASSOVER_API_RESPONSE);
    const { updateClockUI } = await import('./ui.js');

    // Friday April 3, 2026 at 3pm — still Pesach II (Yom Tov), before candle lighting
    const fridayAfternoon = new Date('2026-04-03T15:00:00-04:00');
    await updateClockUI(fridayAfternoon);

    expect(document.body.classList.contains('shabbat-background')).toBe(true);
    const holidayInfo = document.getElementById('holiday-info');
    expect(holidayInfo.textContent).toBe('Pesach II');
  });

  it('should NOT show Shabbat on a regular Wednesday', async () => {
    mockFetch(PASSOVER_API_RESPONSE);
    const { updateClockUI } = await import('./ui.js');

    // Wednesday April 1, 2026 at noon — Erev Pesach, before candle lighting
    const wednesday = new Date('2026-04-01T12:00:00-04:00');
    await updateClockUI(wednesday);

    expect(document.body.classList.contains('shabbat-background')).toBe(false);
  });

  it('should show Havdalah time on Saturday during Chol HaMoed', async () => {
    mockFetch(PASSOVER_API_RESPONSE);
    const { updateClockUI } = await import('./ui.js');

    // Saturday April 4, 2026 at noon
    const saturdayNoon = new Date('2026-04-04T12:00:00-04:00');
    await updateClockUI(saturdayNoon);

    const shabbatInfo = document.getElementById('shabbat-time-info');
    expect(shabbatInfo.textContent).toContain('Havdalah');
    expect(shabbatInfo.style.display).toBe('block');
  });
});
