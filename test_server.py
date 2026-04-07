"""
Tests for the front-door-display Flask backend.

Ports the key test cases from ui.test.js — Shabbat detection boundaries,
calendar event filtering, holiday classification, and prompt building.
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Cached API responses (ported from ui.test.js)
# ---------------------------------------------------------------------------

PASSOVER_API_RESPONSE = {
    "items": [
        {"title": "Erev Pesach", "date": "2026-04-01", "category": "holiday", "subcat": "major"},
        {"title": "Candle lighting: 7:27pm", "date": "2026-04-01T19:27:00-04:00", "category": "candles"},
        {"title": "Pesach I", "date": "2026-04-02", "category": "holiday", "subcat": "major", "yomtov": True},
        {"title": "Candle lighting: 8:28pm", "date": "2026-04-02T20:28:00-04:00", "category": "candles"},
        {"title": "Pesach II", "date": "2026-04-03", "category": "holiday", "subcat": "major", "yomtov": True},
        {"title": "Candle lighting: 7:29pm", "date": "2026-04-03T19:29:00-04:00", "category": "candles"},
        {"title": "Pesach III (CH''M)", "date": "2026-04-04", "category": "holiday", "subcat": "major"},
        {"title": "Havdalah (42 min): 8:31pm", "date": "2026-04-04T20:31:00-04:00", "category": "havdalah"},
        {"title": "Pesach IV (CH''M)", "date": "2026-04-05", "category": "holiday", "subcat": "major"},
        {"title": "Pesach V (CH''M)", "date": "2026-04-06", "category": "holiday", "subcat": "major"},
    ]
}

REGULAR_SHABBAT_API_RESPONSE = {
    "items": [
        {"title": "Candle lighting: 7:37pm", "date": "2026-04-10T19:37:00-04:00", "category": "candles"},
        {"title": "Parashat Shmini", "date": "2026-04-11", "category": "parashat"},
        {"title": "Havdalah (42 min): 8:39pm", "date": "2026-04-11T20:39:00-04:00", "category": "havdalah"},
    ]
}

OMER_API_RESPONSE = {
    "items": [
        {"title": "Pesach IV (CH''M)", "date": "2026-04-05", "category": "holiday", "subcat": "major"},
        {"title": "3rd day of the Omer", "date": "2026-04-05", "category": "omer", "omer": 3},
    ]
}

OMER_WEEK_API_RESPONSE = {
    "items": [
        {"title": "14th day of the Omer", "date": "2026-04-16", "category": "omer", "omer": 14},
    ]
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_caches():
    """Reset server caches before each test."""
    import server
    server._calendar_cache["events_by_date"] = {}
    server._last_prefetch_date_key = None
    server._weather_cache["data"] = None
    server._weather_cache["timestamp"] = 0
    server._time_offset_ms = 0
    yield


def _mock_hebcal(api_response):
    """Create a mock for requests.get that returns the given Hebcal API response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = api_response
    return mock_resp


# ---------------------------------------------------------------------------
# Calendar event filtering tests
# ---------------------------------------------------------------------------

class TestCalendarEvents:
    def test_returns_only_events_matching_date(self):
        """Should return only events matching the given date."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            friday = datetime(2026, 4, 3, 12, 0, 0)
            events = server._get_events_for_date(friday, friday)

        assert len(events) == 2
        titles = [e["title"] for e in events]
        assert "Pesach II" in titles
        assert any(e["is_candle_lighting"] for e in events)

    def test_saturday_chol_hamoed_events(self):
        """Saturday Chol HaMoed: Pesach III + Havdalah, no parashat, not Yom Tov."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            saturday = datetime(2026, 4, 4, 12, 0, 0)
            events = server._get_events_for_date(saturday, saturday)

        assert len(events) == 2
        assert any("Pesach III" in e["title"] for e in events)
        assert any(e["is_havdalah"] for e in events)
        assert not any(e["is_shabbat"] for e in events)
        assert not any(e["is_yom_tov"] for e in events)

    def test_regular_shabbat_has_parashat(self):
        """Regular Shabbat should have a parashat event."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(REGULAR_SHABBAT_API_RESPONSE)):
            saturday = datetime(2026, 4, 11, 12, 0, 0)
            events = server._get_events_for_date(saturday, saturday)

        assert any(e["is_shabbat"] for e in events)
        assert any(e["title"] == "Parashat Shmini" for e in events)

    def test_uses_same_day_cache_without_refetch(self):
        """Repeated same-day reads should only fetch Hebcal once."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)) as mocked_get:
            d1 = datetime(2026, 4, 3, 9, 0, 0)
            d2 = datetime(2026, 4, 3, 18, 0, 0)
            server._get_events_for_date(d1, d1)
            server._get_events_for_date(d2, d2)

        assert mocked_get.call_count == 1

    def test_refetches_when_date_changes(self):
        """A new date should trigger a new Hebcal fetch."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)) as mocked_get:
            d1 = datetime(2026, 4, 3, 23, 59, 0)
            d2 = datetime(2026, 4, 4, 0, 1, 0)
            server._get_events_for_date(d1, d1)
            server._get_events_for_date(d2, d2)

        assert mocked_get.call_count == 2

    def test_prefetches_tomorrow_once_near_midnight(self):
        """Near midnight, tomorrow should be prefetched once and then reused."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)) as mocked_get:
            now = datetime(2026, 4, 3, 23, 55, 0)

            # First call fetches today.
            server._get_events_for_date(now, now)
            assert mocked_get.call_count == 1

            # Prefetch should fetch tomorrow once.
            server._prefetch_tomorrow_events_if_needed(now)
            assert mocked_get.call_count == 2

            # Repeated prefetch attempts should be no-op.
            server._prefetch_tomorrow_events_if_needed(now)
            assert mocked_get.call_count == 2


# ---------------------------------------------------------------------------
# Shabbat detection tests
# ---------------------------------------------------------------------------

class TestShabbatDetection:
    def test_friday_night_after_candle_lighting(self):
        """Friday night after candle lighting = Shabbat."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(REGULAR_SHABBAT_API_RESPONSE)):
            friday_night = datetime(2026, 4, 10, 22, 0, 0)
            state = server.get_calendar_state(friday_night)

        assert state["is_shabbat"] is True
        assert state["show_shabbat_background"] is True
        assert state["holiday_name"] == "Parashat Shmini"

    def test_friday_before_candle_lighting(self):
        """Friday before candle lighting = not Shabbat."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(REGULAR_SHABBAT_API_RESPONSE)):
            friday_afternoon = datetime(2026, 4, 10, 15, 0, 0)
            state = server.get_calendar_state(friday_afternoon)

        assert state["is_shabbat"] is False

    def test_saturday_before_havdalah(self):
        """Saturday noon = Shabbat."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(REGULAR_SHABBAT_API_RESPONSE)):
            saturday_noon = datetime(2026, 4, 11, 12, 0, 0)
            state = server.get_calendar_state(saturday_noon)

        assert state["is_shabbat"] is True
        assert state["show_shabbat_background"] is True

    def test_saturday_after_havdalah(self):
        """Saturday after Havdalah = not Shabbat."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            saturday_after = datetime(2026, 4, 4, 21, 0, 0)
            state = server.get_calendar_state(saturday_after)

        assert state["is_shabbat"] is False
        assert state["show_shabbat_background"] is False

    def test_regular_wednesday(self):
        """Regular Wednesday = not Shabbat."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            wednesday = datetime(2026, 4, 1, 12, 0, 0)
            state = server.get_calendar_state(wednesday)

        assert state["is_shabbat"] is False
        assert state["show_shabbat_background"] is False

    def test_friday_night_passover_chol_hamoed(self):
        """Friday night during Passover after candle lighting = Shabbat."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            friday_night = datetime(2026, 4, 3, 22, 0, 0)
            state = server.get_calendar_state(friday_night)

        assert state["is_shabbat"] is True
        assert state["show_shabbat_background"] is True

    def test_saturday_chol_hamoed_is_shabbat(self):
        """Saturday during Chol HaMoed = Shabbat."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            saturday_noon = datetime(2026, 4, 4, 12, 0, 0)
            state = server.get_calendar_state(saturday_noon)

        assert state["is_shabbat"] is True
        assert state["show_shabbat_background"] is True


# ---------------------------------------------------------------------------
# Yom Tov detection tests
# ---------------------------------------------------------------------------

class TestYomTovDetection:
    def test_pesach_ii_is_yom_tov(self):
        """Pesach II is Yom Tov."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            friday_afternoon = datetime(2026, 4, 3, 15, 0, 0)
            state = server.get_calendar_state(friday_afternoon)

        assert state["is_yom_tov"] is True
        assert state["show_shabbat_background"] is True
        assert state["holiday_name"] == "Pesach II"

    def test_chol_hamoed_is_not_yom_tov(self):
        """Chol HaMoed is not Yom Tov."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            sunday = datetime(2026, 4, 5, 12, 0, 0)
            state = server.get_calendar_state(sunday)

        assert state["is_yom_tov"] is False


# ---------------------------------------------------------------------------
# Havdalah display tests
# ---------------------------------------------------------------------------

class TestHavdalahDisplay:
    def test_havdalah_shown_on_shabbat_chol_hamoed(self):
        """Saturday Chol HaMoed should show Havdalah time."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(PASSOVER_API_RESPONSE)):
            saturday_noon = datetime(2026, 4, 4, 12, 0, 0)
            state = server.get_calendar_state(saturday_noon)

        assert state["havdalah"] is not None
        assert "8:31" in state["havdalah"]


# ---------------------------------------------------------------------------
# Omer counting tests
# ---------------------------------------------------------------------------

class TestOmerCounting:
    def test_format_omer_day_only(self):
        """Days without full weeks should show just the day."""
        import server
        assert server._format_omer_count(3) == "Day 3 of the Omer"

    def test_format_omer_exact_weeks(self):
        """Exact week multiples should show weeks."""
        import server
        assert server._format_omer_count(7) == "Day 7 of the Omer · 1 week"
        assert server._format_omer_count(14) == "Day 14 of the Omer · 2 weeks"
        assert server._format_omer_count(49) == "Day 49 of the Omer · 7 weeks"

    def test_format_omer_weeks_and_days(self):
        """Mixed weeks and days should show both."""
        import server
        assert server._format_omer_count(8) == "Day 8 of the Omer · 1 week, 1 day"
        assert server._format_omer_count(18) == "Day 18 of the Omer · 2 weeks, 4 days"

    def test_format_omer_invalid(self):
        """Out-of-range or missing values should return None."""
        import server
        assert server._format_omer_count(0) is None
        assert server._format_omer_count(50) is None
        assert server._format_omer_count(None) is None

    def test_omer_in_calendar_state(self):
        """Calendar state should include omer_count during the Omer."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(OMER_API_RESPONSE)):
            sunday = datetime(2026, 4, 5, 12, 0, 0)
            state = server.get_calendar_state(sunday)

        assert state["omer_count"] == "Day 3 of the Omer"

    def test_no_omer_outside_period(self):
        """Calendar state should have no omer_count outside the Omer period."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(REGULAR_SHABBAT_API_RESPONSE)):
            saturday = datetime(2026, 4, 11, 12, 0, 0)
            state = server.get_calendar_state(saturday)

        assert state["omer_count"] is None

    def test_omer_exact_week_in_calendar_state(self):
        """Calendar state should format exact weeks correctly."""
        import server
        with patch("server.requests.get", return_value=_mock_hebcal(OMER_WEEK_API_RESPONSE)):
            thursday = datetime(2026, 4, 16, 12, 0, 0)
            state = server.get_calendar_state(thursday)

        assert state["omer_count"] == "Day 14 of the Omer · 2 weeks"


# ---------------------------------------------------------------------------
# Prompt builder tests
# ---------------------------------------------------------------------------

class TestPromptBuilder:
    def test_weather_affects_prompt(self):
        """Prompt should include weather description."""
        from image_gen import build_image_prompt
        weather = {"temp": 5, "code": 63, "high": 8, "low": 2}
        cal_state = {"holiday_name": None, "is_shabbat": False, "is_yom_tov": False, "events": []}
        now = datetime(2026, 4, 6, 14, 0, 0)
        prompt = build_image_prompt(weather, cal_state, now)
        assert "moderate rain" in prompt
        assert "5°C" in prompt

    def test_holiday_affects_prompt(self):
        """Prompt should include holiday imagery for Pesach."""
        from image_gen import build_image_prompt
        weather = {"temp": 15, "code": 0, "high": 18, "low": 10}
        events = [{"title": "Pesach II"}, {"title": "Candle lighting: 7:29pm"}]
        cal_state = {"holiday_name": "Pesach II", "is_shabbat": False, "is_yom_tov": True, "events": events}
        now = datetime(2026, 4, 3, 15, 0, 0)
        prompt = build_image_prompt(weather, cal_state, now)
        assert "matzah" in prompt.lower() or "seder" in prompt.lower()

    def test_shabbat_prompt_has_challah(self):
        """Default Shabbat prompt should mention challah."""
        from image_gen import build_image_prompt
        weather = {"temp": 20, "code": 0, "high": 22, "low": 15}
        cal_state = {"holiday_name": "Parashat Shmini", "is_shabbat": True, "is_yom_tov": False, "events": [{"title": "Parashat Shmini"}]}
        now = datetime(2026, 4, 11, 12, 0, 0)
        prompt = build_image_prompt(weather, cal_state, now)
        assert "challah" in prompt.lower()

    def test_time_of_day_affects_prompt(self):
        """Morning vs evening should produce different prompts."""
        from image_gen import build_image_prompt
        weather = {"temp": 15, "code": 0, "high": 18, "low": 10}
        cal_state = {"holiday_name": None, "is_shabbat": False, "is_yom_tov": False, "events": []}

        morning = datetime(2026, 4, 6, 7, 0, 0)
        evening = datetime(2026, 4, 6, 19, 0, 0)

        morning_prompt = build_image_prompt(weather, cal_state, morning)
        evening_prompt = build_image_prompt(weather, cal_state, evening)

        assert "dawn" in morning_prompt.lower()
        assert "sunset" in evening_prompt.lower() or "golden" in evening_prompt.lower()

    def test_prompt_always_ends_with_watercolor(self):
        """All prompts should include watercolor style."""
        from image_gen import build_image_prompt
        weather = {"temp": -10, "code": 75, "high": -5, "low": -15}
        cal_state = {"holiday_name": None, "is_shabbat": False, "is_yom_tov": False, "events": []}
        now = datetime(2026, 1, 15, 12, 0, 0)
        prompt = build_image_prompt(weather, cal_state, now)
        assert "watercolor" in prompt.lower()

    def test_chanukah_prompt(self):
        """Chanukah events should produce menorah imagery."""
        from image_gen import build_image_prompt
        weather = {"temp": -2, "code": 71, "high": 0, "low": -5}
        events = [{"title": "Chanukah: 3 Candles"}]
        cal_state = {"holiday_name": "Chanukah: 3 Candles", "is_shabbat": False, "is_yom_tov": False, "events": events}
        now = datetime(2025, 12, 16, 18, 0, 0)
        prompt = build_image_prompt(weather, cal_state, now)
        assert "menorah" in prompt.lower()


# ---------------------------------------------------------------------------
# Flask API tests
# ---------------------------------------------------------------------------

class TestFlaskAPI:
    @pytest.fixture
    def client(self):
        import server
        server.app.config["TESTING"] = True
        with server.app.test_client() as c:
            yield c

    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Digital Clock" in resp.data

    def test_api_state_returns_json(self, client):
        mock_weather = MagicMock()
        mock_weather.status_code = 200
        mock_weather.raise_for_status = MagicMock()
        mock_weather.json.return_value = {
            "current": {"temperature_2m": 15.0, "weather_code": 1},
            "daily": {"temperature_2m_max": [18.0], "temperature_2m_min": [10.0]},
        }

        mock_hebcal = _mock_hebcal(REGULAR_SHABBAT_API_RESPONSE)

        def route_request(url, **kwargs):
            if "open-meteo" in url:
                return mock_weather
            return mock_hebcal

        with patch("server.requests.get", side_effect=route_request):
            resp = client.get("/api/state")

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "weather" in data
        assert "is_shabbat" in data
        assert data["weather"]["temp"] == 15

    def test_api_offset_reset(self, client):
        import server
        server._time_offset_ms = 3600000
        resp = client.post("/api/offset", json={"action": "reset"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["offset_ms"] == 0

    def test_api_offset_increment(self, client):
        import server
        server._time_offset_ms = 0
        resp = client.post("/api/offset", json={"offset_ms": 3600000})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["offset_ms"] == 3600000
