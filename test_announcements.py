"""Tests for the announcements module."""

from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

import announcements


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_announced():
    """Clear the announced-events set before each test."""
    announcements._announced_events.clear()
    yield
    announcements._announced_events.clear()


def _make_event(category, date_str, parsed_date):
    """Build a minimal event dict matching the shape from server.py."""
    return {
        "title": f"Test {category}",
        "date": date_str,
        "category": category,
        "parsed_date": parsed_date,
        "is_candle_lighting": category == "candles",
        "is_havdalah": category == "havdalah",
        "is_holiday": category == "holiday",
        "is_shabbat": category == "parashat",
        "is_yom_tov": False,
        "is_omer": False,
        "omer_day": None,
    }


def _mock_cast():
    """Build a mock Chromecast object matching pychromecast 14.x API."""
    cast = MagicMock()
    cast.name = "Kitchen display"
    cast.model_name = "Google Nest Hub Max"
    cast.uuid = "fake-uuid"
    cast.socket_client.host = "192.168.2.24"
    cast.socket_client.port = 8009
    cast.status.app_id = None
    cast.status.display_name = "Backdrop"
    cast.status.volume_level = 0.5
    cast.status.volume_muted = False
    mc = MagicMock()
    mc.status.player_state = "PLAYING"
    mc.status.content_id = "http://192.168.2.10:8080/static/announcement.mp3"
    cast.media_controller = mc
    return cast


# ---------------------------------------------------------------------------
# _format_time_for_speech
# ---------------------------------------------------------------------------

class TestFormatTimeForSpeech:
    def test_evening_pm(self):
        assert announcements._format_time_for_speech(datetime(2026, 4, 10, 19, 37)) == "7:37 PM"

    def test_morning_am(self):
        assert announcements._format_time_for_speech(datetime(2026, 4, 10, 9, 5)) == "9:05 AM"

    def test_noon(self):
        assert announcements._format_time_for_speech(datetime(2026, 4, 10, 12, 0)) == "12:00 PM"

    def test_midnight(self):
        assert announcements._format_time_for_speech(datetime(2026, 4, 10, 0, 0)) == "12:00 AM"


# ---------------------------------------------------------------------------
# _get_local_ip
# ---------------------------------------------------------------------------

class TestGetLocalIp:
    def test_returns_ip_string(self):
        ip = announcements._get_local_ip()
        parts = ip.split(".")
        assert len(parts) == 4

    def test_fallback_on_error(self):
        with patch("announcements.socket.socket") as mock_sock:
            mock_sock.return_value.connect.side_effect = OSError("no network")
            assert announcements._get_local_ip() == "127.0.0.1"


# ---------------------------------------------------------------------------
# _generate_tts
# ---------------------------------------------------------------------------

class TestGenerateTts:
    def test_calls_gtts_save(self):
        with patch("announcements.gTTS") as MockGTTS:
            mock_tts = MagicMock()
            MockGTTS.return_value = mock_tts
            announcements._generate_tts("Hello world")
            MockGTTS.assert_called_once_with(text="Hello world", lang="en")
            mock_tts.save.assert_called_once_with(announcements.ANNOUNCEMENT_FILE)


# ---------------------------------------------------------------------------
# _play_on_device
# ---------------------------------------------------------------------------

class TestPlayOnDevice:
    def test_plays_media_and_blocks(self):
        cast = _mock_cast()
        announcements._play_on_device(cast, "http://host:8080/static/announcement.mp3")
        cast.wait.assert_called_once()
        cast.media_controller.play_media.assert_called_once_with(
            "http://host:8080/static/announcement.mp3", "audio/mp3"
        )
        cast.media_controller.block_until_active.assert_called_once()


# ---------------------------------------------------------------------------
# _cast_to_speakers
# ---------------------------------------------------------------------------

class TestCastToSpeakers:
    def test_success(self):
        cast = _mock_cast()
        browser = MagicMock()
        with patch("announcements.pychromecast.get_listed_chromecasts",
                    return_value=([cast], browser)):
            result = announcements._cast_to_speakers("http://host:8080/audio.mp3")
        assert result is True
        cast.wait.assert_called_once()
        cast.media_controller.play_media.assert_called_once()
        browser.stop_discovery.assert_called_once()

    def test_no_device_found(self):
        browser = MagicMock()
        with patch("announcements.pychromecast.get_listed_chromecasts",
                    return_value=([], browser)):
            result = announcements._cast_to_speakers("http://host:8080/audio.mp3")
        assert result is False
        browser.stop_discovery.assert_called_once()

    def test_browser_stopped_on_exception(self):
        cast = _mock_cast()
        cast.wait.side_effect = RuntimeError("connection lost")
        browser = MagicMock()
        with patch("announcements.pychromecast.get_listed_chromecasts",
                    return_value=([cast], browser)):
            with pytest.raises(RuntimeError):
                announcements._cast_to_speakers("http://host:8080/audio.mp3")
        browser.stop_discovery.assert_called_once()


# ---------------------------------------------------------------------------
# _cast_to_host
# ---------------------------------------------------------------------------

class TestCastToHost:
    def test_success(self):
        cast = _mock_cast()
        browser = MagicMock()
        with patch("announcements.pychromecast.get_listed_chromecasts",
                    return_value=([cast], browser)):
            result = announcements._cast_to_host("192.168.2.24", "http://host:8080/audio.mp3")
        assert result is True
        cast.media_controller.play_media.assert_called_once()
        browser.stop_discovery.assert_called_once()

    def test_no_device_at_host(self):
        browser = MagicMock()
        with patch("announcements.pychromecast.get_listed_chromecasts",
                    return_value=([], browser)):
            result = announcements._cast_to_host("192.168.2.99", "http://host:8080/audio.mp3")
        assert result is False
        browser.stop_discovery.assert_called_once()


# ---------------------------------------------------------------------------
# _broadcast
# ---------------------------------------------------------------------------

class TestBroadcast:
    def test_generates_tts_and_casts(self):
        with patch("announcements._generate_tts") as mock_tts, \
             patch("announcements._get_local_ip", return_value="192.168.2.10"), \
             patch("announcements._cast_to_speakers", return_value=True) as mock_cast:
            result = announcements._broadcast("Hello", 8080)
        assert result is True
        mock_tts.assert_called_once_with("Hello")
        mock_cast.assert_called_once_with("http://192.168.2.10:8080/static/announcement.mp3")


# ---------------------------------------------------------------------------
# send_test
# ---------------------------------------------------------------------------

class TestSendTest:
    def test_default_uses_speakers(self):
        with patch("announcements._generate_tts"), \
             patch("announcements._get_local_ip", return_value="192.168.2.10"), \
             patch("announcements._cast_to_speakers", return_value=True) as mock_cast:
            result = announcements.send_test(8080)
        assert result is True
        mock_cast.assert_called_once()

    def test_host_override(self):
        with patch("announcements._generate_tts"), \
             patch("announcements._get_local_ip", return_value="192.168.2.10"), \
             patch("announcements._cast_to_host", return_value=True) as mock_host:
            result = announcements.send_test(8080, host="192.168.2.24")
        assert result is True
        mock_host.assert_called_once_with(
            "192.168.2.24", "http://192.168.2.10:8080/static/announcement.mp3"
        )

    def test_custom_text(self):
        with patch("announcements._generate_tts") as mock_tts, \
             patch("announcements._get_local_ip", return_value="10.0.0.1"), \
             patch("announcements._cast_to_speakers", return_value=True):
            announcements.send_test(8080, text="Custom message")
        mock_tts.assert_called_once_with("Custom message")


# ---------------------------------------------------------------------------
# _check_and_announce
# ---------------------------------------------------------------------------

class TestCheckAndAnnounce:
    def _run(self, now, events, broadcast_return=True):
        """Helper: run _check_and_announce with mocked deps."""
        get_now = lambda: now
        get_events = lambda n, d: events
        with patch("announcements._broadcast", return_value=broadcast_return) as mock_b:
            announcements._check_and_announce(get_now, get_events, 8080)
        return mock_b

    def test_announces_candle_lighting_in_window(self):
        candle_time = datetime(2026, 4, 10, 19, 37)
        now = datetime(2026, 4, 10, 19, 33)  # 4 min before
        event = _make_event("candles", "2026-04-10T19:37:00-04:00", candle_time)
        mock_b = self._run(now, [event])
        mock_b.assert_called_once()
        text = mock_b.call_args[0][0]
        assert "Candle Lighting" in text
        assert "7:37 PM" in text
        assert "5 minutes" in text

    def test_announces_havdalah_in_window(self):
        havdalah_time = datetime(2026, 4, 11, 20, 39)
        now = datetime(2026, 4, 11, 20, 35)  # 4 min before
        event = _make_event("havdalah", "2026-04-11T20:39:00-04:00", havdalah_time)
        mock_b = self._run(now, [event])
        mock_b.assert_called_once()
        text = mock_b.call_args[0][0]
        assert "Havdalah" in text
        assert "8:39 PM" in text

    def test_does_not_announce_too_early(self):
        candle_time = datetime(2026, 4, 10, 19, 37)
        now = datetime(2026, 4, 10, 19, 0)  # 37 min before — outside window
        event = _make_event("candles", "2026-04-10T19:37:00-04:00", candle_time)
        mock_b = self._run(now, [event])
        mock_b.assert_not_called()

    def test_does_not_announce_past_events(self):
        candle_time = datetime(2026, 4, 10, 19, 37)
        now = datetime(2026, 4, 10, 19, 38)  # 1 min after
        event = _make_event("candles", "2026-04-10T19:37:00-04:00", candle_time)
        mock_b = self._run(now, [event])
        mock_b.assert_not_called()

    def test_does_not_repeat_announcement(self):
        candle_time = datetime(2026, 4, 10, 19, 37)
        now = datetime(2026, 4, 10, 19, 33)
        event = _make_event("candles", "2026-04-10T19:37:00-04:00", candle_time)

        # First call announces
        mock_b = self._run(now, [event])
        mock_b.assert_called_once()

        # Second call does not re-announce
        mock_b = self._run(now, [event])
        mock_b.assert_not_called()

    def test_skips_non_candle_havdalah_events(self):
        now = datetime(2026, 4, 5, 12, 0)
        holiday = _make_event("holiday", "2026-04-05", datetime(2026, 4, 5, 0, 0, 1))
        mock_b = self._run(now, [holiday])
        mock_b.assert_not_called()

    def test_does_not_record_if_broadcast_fails(self):
        candle_time = datetime(2026, 4, 10, 19, 37)
        now = datetime(2026, 4, 10, 19, 33)
        event = _make_event("candles", "2026-04-10T19:37:00-04:00", candle_time)
        self._run(now, [event], broadcast_return=False)
        # Event should NOT be marked as announced
        assert "2026-04-10T19:37:00-04:00" not in announcements._announced_events

    def test_announced_set_bounded(self):
        """The announced set should be cleared when it exceeds 50 entries."""
        announcements._announced_events.update(set(str(i) for i in range(51)))
        now = datetime(2026, 4, 10, 12, 0)
        self._run(now, [])
        assert len(announcements._announced_events) == 0


# ---------------------------------------------------------------------------
# discover_devices
# ---------------------------------------------------------------------------

class TestDiscoverDevices:
    def test_returns_device_list(self):
        mock_service = MagicMock()
        mock_service.friendly_name = "Kitchen display"
        mock_service.model_name = "Google Nest Hub Max"
        mock_service.host = "192.168.2.24"
        mock_service.port = 8009
        mock_service.cast_type = "cast"

        mock_browser = MagicMock()
        mock_browser.devices = {"fake-uuid": mock_service}

        with patch("announcements.pychromecast.CastBrowser", return_value=mock_browser), \
             patch("announcements.pychromecast.SimpleCastListener"), \
             patch("announcements.pychromecast.zeroconf.Zeroconf"), \
             patch("announcements.time.sleep"):
            devices = announcements.discover_devices(timeout=1)

        assert len(devices) == 1
        assert devices[0]["name"] == "Kitchen display"
        assert devices[0]["host"] == "192.168.2.24"
        assert devices[0]["model"] == "Google Nest Hub Max"
        mock_browser.start_discovery.assert_called_once()
        mock_browser.stop_discovery.assert_called_once()

    def test_empty_network(self):
        mock_browser = MagicMock()
        mock_browser.devices = {}

        with patch("announcements.pychromecast.CastBrowser", return_value=mock_browser), \
             patch("announcements.pychromecast.SimpleCastListener"), \
             patch("announcements.pychromecast.zeroconf.Zeroconf"), \
             patch("announcements.time.sleep"):
            devices = announcements.discover_devices(timeout=1)

        assert devices == []
