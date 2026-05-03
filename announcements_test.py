"""Tests for the announcements module."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

import announcements


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_announced() -> Generator[None, None, None]:
    """Clear the announced-events set and discovery cache before each test."""
    announcements._announced_events.clear()
    announcements._discovery_cache["devices"] = None
    announcements._discovery_cache["cast_infos"] = {}
    announcements._discovery_cache["timestamp"] = 0
    yield
    announcements._announced_events.clear()
    announcements._discovery_cache["devices"] = None
    announcements._discovery_cache["cast_infos"] = {}
    announcements._discovery_cache["timestamp"] = 0


def _make_event(category: str, date_str: str, parsed_date: datetime) -> dict[str, Any]:
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


def _mock_cast() -> MagicMock:
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
        with patch("announcements.gtts.gTTS") as MockGTTS:
            mock_tts = MagicMock()
            MockGTTS.return_value = mock_tts
            announcements._generate_tts("Hello world")
            MockGTTS.assert_called_once_with(text="Hello world", lang="en")
            mock_tts.save.assert_called_once_with(announcements.ANNOUNCEMENT_FILE)


# ---------------------------------------------------------------------------
# _is_tcp_reachable
# ---------------------------------------------------------------------------

class TestIsTcpReachable:
    def test_returns_true_when_socket_opens(self):
        with patch("announcements.socket.create_connection") as mock_connect:
            result = announcements._is_tcp_reachable("192.168.2.24", 8009)
        assert result is True
        assert mock_connect.call_count == 1
        assert mock_connect.call_args[0][0] == ("192.168.2.24", 8009)
        assert mock_connect.call_args.kwargs["timeout"] == announcements.CONNECT_PROBE_TIMEOUT_SECONDS

    def test_returns_false_on_oserror(self):
        with patch("announcements.socket.create_connection", side_effect=OSError("unreachable")):
            result = announcements._is_tcp_reachable("192.168.2.24", 8009)
        assert result is False

    def test_retries_before_false(self):
        with patch("announcements.socket.create_connection", side_effect=OSError("unreachable")) as mock_connect, \
             patch("announcements.time.sleep") as mock_sleep:
            result = announcements._is_tcp_reachable("192.168.2.24", 8009, attempts=3)
        assert result is False
        assert mock_connect.call_count == 3
        assert mock_sleep.call_count == 2


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
        fake_cast_info = MagicMock()
        fake_cast_info.host = "192.168.2.24"
        fake_cast_info.port = 8009
        with patch("announcements._resolve_speaker_cast_info", return_value=fake_cast_info), \
             patch("announcements._connect_by_cast_info", return_value=cast):
            result = announcements._cast_to_speakers("http://host:8080/audio.mp3")
        assert result is True
        cast.wait.assert_called_once()
        cast.media_controller.play_media.assert_called_once()
        cast.disconnect.assert_called_once()

    def test_connection_failure_returns_false(self):
        cast = _mock_cast()
        cast.wait.side_effect = RuntimeError("connection lost")
        fake_cast_info = MagicMock()
        fake_cast_info.host = "192.168.2.24"
        with patch("announcements._resolve_speaker_cast_info", return_value=fake_cast_info), \
             patch("announcements._connect_by_cast_info", return_value=cast):
            result = announcements._cast_to_speakers("http://host:8080/audio.mp3")
        assert result is False
        cast.disconnect.assert_called_once()

    def test_returns_false_when_speaker_not_found(self):
        with patch("announcements._resolve_speaker_cast_info", return_value=None):
            result = announcements._cast_to_speakers("http://host:8080/audio.mp3")
        assert result is False

    def test_connect_failure_returns_false(self):
        fake_cast_info = MagicMock()
        fake_cast_info.host = "192.168.2.24"
        with patch("announcements._resolve_speaker_cast_info", return_value=fake_cast_info), \
             patch("announcements._connect_by_cast_info", side_effect=OSError("unreachable")):
            result = announcements._cast_to_speakers("http://host:8080/audio.mp3")
        assert result is False


# ---------------------------------------------------------------------------
# _cast_to_host
# ---------------------------------------------------------------------------

class TestCastToHost:
    def test_success(self):
        cast = _mock_cast()
        with patch("announcements._connect_by_host", return_value=cast):
            result = announcements._cast_to_host("192.168.2.24", "http://host:8080/audio.mp3")
        assert result is True
        cast.media_controller.play_media.assert_called_once()
        cast.disconnect.assert_called_once()

    def test_connection_failure_returns_false(self):
        cast = _mock_cast()
        cast.wait.side_effect = OSError("unreachable")
        with patch("announcements._connect_by_host", return_value=cast):
            result = announcements._cast_to_host("192.168.2.99", "http://host:8080/audio.mp3")
        assert result is False
        cast.disconnect.assert_called_once()

    def test_connect_failure_returns_false(self):
        with patch("announcements._connect_by_host", side_effect=OSError("unreachable")):
            result = announcements._cast_to_host("192.168.2.99", "http://host:8080/audio.mp3")
        assert result is False


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
# dinner bell
# ---------------------------------------------------------------------------

class TestDinnerBell:
    def test_send_dinner_bell_builds_audio_url_and_broadcasts_all(self):
        with patch("announcements._generate_tts") as mock_tts, \
             patch("announcements._get_local_ip", return_value="192.168.2.10"), \
             patch("announcements._cast_to_all_speakers", return_value=(2, 3)) as mock_cast:
            mock_tts.return_value = announcements.ANNOUNCEMENT_FILE
            result = announcements.send_dinner_bell(8080)
        assert result == (2, 3)
        mock_tts.assert_called_once_with(announcements.DINNER_BELL_TEXT)
        mock_cast.assert_called_once_with("http://192.168.2.10:8080/static/announcement.mp3")

    def test_send_dinner_bell_custom_text(self):
        with patch("announcements._generate_tts") as mock_tts, \
             patch("announcements._get_local_ip", return_value="10.0.0.1"), \
             patch("announcements._cast_to_all_speakers", return_value=(1, 1)):
            mock_tts.return_value = announcements.ANNOUNCEMENT_FILE
            announcements.send_dinner_bell(9000, text="Dinner now")
        mock_tts.assert_called_once_with("Dinner now")

    def test_cast_to_all_speakers_no_devices(self):
        announcements._discovery_cache["cast_infos"] = {}
        with patch("announcements.discover_devices"):
            result = announcements._cast_to_all_speakers("http://host/audio.mp3")
        assert result == (0, 0)

    def test_cast_to_all_speakers_uses_group_only(self):
        cast_ok = _mock_cast()
        cast_ok.status.volume_level = 0.8
        cast_ok.status.volume_muted = False
        info_group = MagicMock()
        info_group.host = "192.168.2.50"
        info_group.port = 8009
        info_group.friendly_name = "Main floor group"
        info_group.cast_type = "group"

        info_device = MagicMock()
        info_device.host = "192.168.2.24"
        info_device.port = 8009
        info_device.friendly_name = "Kitchen display"
        info_device.cast_type = "cast"

        announcements._discovery_cache["cast_infos"] = {
            "Main floor group": info_group,
            "Kitchen display": info_device,
        }

        with patch("announcements.discover_devices"), \
             patch("announcements._connect_by_cast_info", return_value=cast_ok) as mock_connect, \
             patch("announcements._play_on_device") as mock_play, \
             patch("announcements._wait_for_media_to_finish") as mock_wait:
            result = announcements._cast_to_all_speakers("http://host/audio.mp3")

        assert result == (1, 1)
        mock_connect.assert_called_once_with(info_group)
        mock_play.assert_called_once_with(cast_ok, "http://host/audio.mp3", "192.168.2.50", 8009)
        mock_wait.assert_called_once_with(cast_ok.media_controller)
        cast_ok.set_volume.assert_has_calls([
            call(announcements.DINNER_BELL_VOLUME_LEVEL),
            call(0.8),
        ])
        cast_ok.set_volume_muted.assert_called_once_with(False)
        cast_ok.disconnect.assert_called_once()

    def test_cast_to_all_speakers_restores_muted_state(self):
        cast_ok = _mock_cast()
        cast_ok.status.volume_level = 0.3
        cast_ok.status.volume_muted = True
        info_group = MagicMock()
        info_group.host = "192.168.2.50"
        info_group.port = 8009
        info_group.friendly_name = "Main floor group"
        info_group.cast_type = "group"

        announcements._discovery_cache["cast_infos"] = {
            "Main floor group": info_group,
        }

        with patch("announcements.discover_devices"), \
             patch("announcements._connect_by_cast_info", return_value=cast_ok), \
             patch("announcements._play_on_device"), \
             patch("announcements._wait_for_media_to_finish"):
            result = announcements._cast_to_all_speakers("http://host/audio.mp3")

        assert result == (1, 1)
        assert cast_ok.set_volume.call_args_list == [
            call(announcements.DINNER_BELL_VOLUME_LEVEL),
            call(0.3),
        ]
        assert cast_ok.set_volume_muted.call_args_list == [
            call(False),
            call(True),
        ]
        cast_ok.disconnect.assert_called_once()

    def test_cast_to_all_speakers_restores_volume_after_failure(self):
        cast_ok = _mock_cast()
        cast_ok.status.volume_level = 0.7
        cast_ok.status.volume_muted = False
        info_group = MagicMock()
        info_group.host = "192.168.2.50"
        info_group.port = 8009
        info_group.friendly_name = "Main floor group"
        info_group.cast_type = "group"

        announcements._discovery_cache["cast_infos"] = {
            "Main floor group": info_group,
        }

        with patch("announcements.discover_devices"), \
             patch("announcements._connect_by_cast_info", return_value=cast_ok), \
             patch("announcements._play_on_device", side_effect=RuntimeError("boom")):
            result = announcements._cast_to_all_speakers("http://host/audio.mp3")

        assert result == (0, 1)
        assert cast_ok.set_volume.call_args_list == [
            call(announcements.DINNER_BELL_VOLUME_LEVEL),
            call(0.7),
        ]
        cast_ok.set_volume_muted.assert_called_once_with(False)
        cast_ok.disconnect.assert_called_once()

    def test_cast_to_all_speakers_no_group_found(self):
        info_device = MagicMock()
        info_device.host = "192.168.2.24"
        info_device.port = 8009
        info_device.friendly_name = "Kitchen display"
        info_device.cast_type = "cast"
        announcements._discovery_cache["cast_infos"] = {"Kitchen display": info_device}
        with patch("announcements.discover_devices"):
            result = announcements._cast_to_all_speakers("http://host/audio.mp3")
        assert result == (0, 0)


# ---------------------------------------------------------------------------
# _check_and_announce
# ---------------------------------------------------------------------------

class TestCheckAndAnnounce:
    def _run(self, now: datetime, events: list[dict[str, Any]], broadcast_return: bool = True) -> MagicMock:
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
    def _mock_browser(self, devices_dict: dict[str, Any]) -> MagicMock:
        mock_browser = MagicMock()
        mock_browser.devices = devices_dict
        return mock_browser

    def _mock_service(self, name: str = "Kitchen display", host: str = "192.168.2.24", model: str = "Google Nest Hub Max", cast_type: str = "cast") -> MagicMock:
        svc = MagicMock()
        svc.friendly_name = name
        svc.model_name = model
        svc.host = host
        svc.port = 8009
        svc.cast_type = cast_type
        return svc

    def test_returns_device_list(self):
        svc = self._mock_service()
        mock_browser = self._mock_browser({"fake-uuid": svc})

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
        mock_browser = self._mock_browser({})

        with patch("announcements.pychromecast.CastBrowser", return_value=mock_browser), \
             patch("announcements.pychromecast.SimpleCastListener"), \
             patch("announcements.pychromecast.zeroconf.Zeroconf"), \
             patch("announcements.time.sleep"):
            devices = announcements.discover_devices(timeout=1)

        assert devices == []

    def test_cache_reused_within_ttl(self):
        svc = self._mock_service()
        mock_browser = self._mock_browser({"fake-uuid": svc})

        with patch("announcements.pychromecast.CastBrowser", return_value=mock_browser) as mock_cls, \
             patch("announcements.pychromecast.SimpleCastListener"), \
             patch("announcements.pychromecast.zeroconf.Zeroconf"), \
             patch("announcements.time.sleep"):
            first = announcements.discover_devices(timeout=1)
            second = announcements.discover_devices(timeout=1)

        assert first == second
        # CastBrowser should only be created once
        assert mock_cls.call_count == 1

    def test_cache_expired_triggers_rescan(self):
        svc = self._mock_service()
        mock_browser = self._mock_browser({"fake-uuid": svc})

        with patch("announcements.pychromecast.CastBrowser", return_value=mock_browser) as mock_cls, \
             patch("announcements.pychromecast.SimpleCastListener"), \
             patch("announcements.pychromecast.zeroconf.Zeroconf"), \
             patch("announcements.time.sleep"):
            announcements.discover_devices(timeout=1)
            # Expire the cache
            announcements._discovery_cache["timestamp"] = 0
            announcements.discover_devices(timeout=1)

        assert mock_cls.call_count == 2


# ---------------------------------------------------------------------------
# _resolve_speaker_host
# ---------------------------------------------------------------------------

class TestResolveSpeakerCastInfo:
    def test_finds_matching_device(self):
        fake_cast_info = MagicMock()
        fake_cast_info.host = "192.168.2.24"
        fake_cast_info.port = 8009
        fake_cast_info.friendly_name = "Kitchen display"
        devices = [{"name": "Kitchen display", "host": "192.168.2.24", "port": 8009}]
        with patch("announcements.discover_devices", return_value=devices):
            announcements._discovery_cache["cast_infos"] = {"Kitchen display": fake_cast_info}
            result = announcements._resolve_speaker_cast_info()
        assert result is fake_cast_info

    def test_returns_none_when_not_found(self):
        devices = [{"name": "Some Other Device", "host": "192.168.2.99", "port": 8009}]
        with patch("announcements.discover_devices", return_value=devices):
            announcements._discovery_cache["cast_infos"] = {"Some Other Device": MagicMock()}
            result = announcements._resolve_speaker_cast_info()
        assert result is None

    def test_returns_none_on_empty_network(self):
        with patch("announcements.discover_devices", return_value=[]):
            result = announcements._resolve_speaker_cast_info()
        assert result is None
