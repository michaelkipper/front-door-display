"""Tests for the Lutron Caséta integration module and routes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

import lutron
import server


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_lutron_state():
    """Reset module-level Lutron state before and after each test."""
    lutron.stop_lutron()
    lutron._bridge = None
    lutron._is_connected = False
    lutron._cached_state = {
        "devices": [],
        "scenes": [],
        "timestamp": 0.0,
    }
    yield
    lutron.stop_lutron()
    lutron._bridge = None
    lutron._is_connected = False
    lutron._cached_state = {
        "devices": [],
        "scenes": [],
        "timestamp": 0.0,
    }


# ---------------------------------------------------------------------------
# Formatting & Helpers Tests
# ---------------------------------------------------------------------------

class TestLutronHelpers:
    def test_clean_device_name(self):
        assert lutron._clean_device_name("Living_Room_Ceiling") == "Living Room Ceiling"
        assert lutron._clean_device_name("Porch") == "Porch"
        assert lutron._clean_device_name("") == "Unknown Light"

    def test_format_device_dimmer(self):
        raw = {
            "name": "Front_Porch",
            "type": "WallDimmer",
            "current_state": 75,
            "zone": "12",
        }
        formatted = lutron._format_device("2", raw)
        assert formatted["id"] == "2"
        assert formatted["name"] == "Front Porch"
        assert formatted["type"] == "WallDimmer"
        assert formatted["is_on"] is True
        assert formatted["level"] == 75
        assert formatted["is_dimmable"] is True
        assert formatted["zone"] == "12"

    def test_format_device_switch_off(self):
        raw = {
            "name": "Garage_Light",
            "type": "WallSwitch",
            "current_state": 0,
        }
        formatted = lutron._format_device("3", raw)
        assert formatted["id"] == "3"
        assert formatted["name"] == "Garage Light"
        assert formatted["is_on"] is False
        assert formatted["level"] == 0
        assert formatted["is_dimmable"] is False

    def test_format_scene(self):
        raw = {"name": "Evening_Relax"}
        formatted = lutron._format_scene("101", raw)
        assert formatted["id"] == "101"
        assert formatted["name"] == "Evening Relax"


# ---------------------------------------------------------------------------
# Configuration & Connection Tests
# ---------------------------------------------------------------------------

class TestConfiguration:
    def test_is_configured_false_when_empty_ip(self):
        with patch.object(lutron, "LUTRON_BRIDGE_IP", ""):
            assert lutron.is_configured() is False

    def test_is_configured_checks_cert_files(self):
        with patch.object(lutron, "LUTRON_BRIDGE_IP", "192.168.2.50"), \
             patch("os.path.isfile", side_effect=lambda path: "caseta" in path):
            assert lutron.is_configured() is True

        with patch.object(lutron, "LUTRON_BRIDGE_IP", "192.168.2.50"), \
             patch("os.path.isfile", return_value=False):
            assert lutron.is_configured() is False

    def test_is_connected(self):
        assert lutron.is_connected() is False
        lutron._is_connected = True
        lutron._bridge = MagicMock()
        assert lutron.is_connected() is True


# ---------------------------------------------------------------------------
# Cache & Device Parsing Tests
# ---------------------------------------------------------------------------

class TestCacheRefresh:
    def test_refresh_cache_filters_controllable_devices(self):
        mock_bridge = MagicMock()
        mock_bridge.get_devices.return_value = {
            "1": {"name": "Smart_Bridge", "type": "SmartBridge", "current_state": -1},
            "2": {"name": "Hallway_Pico", "type": "Pico3ButtonRaiseLower", "current_state": -1},
            "3": {"name": "Front_Porch", "type": "WallDimmer", "current_state": 100},
            "4": {"name": "Backyard_Flood", "type": "WallSwitch", "current_state": 0},
        }
        mock_bridge.get_scenes.return_value = {
            "10": {"name": "Goodnight"},
        }
        lutron._bridge = mock_bridge
        lutron._refresh_cache_from_bridge()

        devices = lutron.get_devices()
        scenes = lutron.get_scenes()

        assert len(devices) == 2
        # Alphabetical sort: Backyard Flood before Front Porch
        assert devices[0]["name"] == "Backyard Flood"
        assert devices[0]["is_dimmable"] is False
        assert devices[1]["name"] == "Front Porch"
        assert devices[1]["is_dimmable"] is True
        assert devices[1]["level"] == 100

        assert len(scenes) == 1
        assert scenes[0]["name"] == "Goodnight"


# ---------------------------------------------------------------------------
# Device Control Coroutines & Thread-Safe Methods Tests
# ---------------------------------------------------------------------------

class TestDeviceControl:
    @pytest.mark.anyio
    async def test_async_set_device_level_turn_off(self):
        mock_bridge = MagicMock()
        mock_bridge.turn_off = AsyncMock()
        mock_bridge.set_value = AsyncMock()
        mock_bridge.get_devices.return_value = {}
        mock_bridge.get_scenes.return_value = {}
        lutron._bridge = mock_bridge

        result = await lutron._async_set_device_level("2", 0)
        assert result is True
        mock_bridge.turn_off.assert_awaited_once_with("2")

    @pytest.mark.anyio
    async def test_async_set_device_level_positive(self):
        mock_bridge = MagicMock()
        mock_bridge.turn_off = AsyncMock()
        mock_bridge.set_value = AsyncMock()
        mock_bridge.get_devices.return_value = {}
        mock_bridge.get_scenes.return_value = {}
        lutron._bridge = mock_bridge

        result = await lutron._async_set_device_level("2", 80)
        assert result is True
        mock_bridge.set_value.assert_awaited_once_with("2", 80)

    @pytest.mark.anyio
    async def test_async_turn_all_off(self):
        mock_bridge = MagicMock()
        mock_bridge.turn_off = AsyncMock()
        mock_bridge.get_devices.return_value = {
            "2": {"type": "WallDimmer", "current_state": 50},
            "3": {"type": "WallSwitch", "current_state": 0},
            "4": {"type": "WallDimmer", "current_state": 100},
        }
        mock_bridge.get_scenes.return_value = {}
        lutron._bridge = mock_bridge

        result = await lutron._async_turn_all_off()
        assert result is True
        # Only devices 2 and 4 were ON
        assert mock_bridge.turn_off.await_count == 2
        mock_bridge.turn_off.assert_any_await("2")
        mock_bridge.turn_off.assert_any_await("4")

    @pytest.mark.anyio
    async def test_async_activate_scene(self):
        mock_bridge = MagicMock()
        mock_bridge.activate_scene = AsyncMock()
        mock_bridge.get_devices.return_value = {}
        mock_bridge.get_scenes.return_value = {}
        lutron._bridge = mock_bridge

        result = await lutron._async_activate_scene("55")
        assert result is True
        mock_bridge.activate_scene.assert_awaited_once_with("55")

    @pytest.mark.anyio
    async def test_async_flash_lights_restores_state(self):
        mock_bridge = MagicMock()
        mock_bridge.set_value = AsyncMock()
        mock_bridge.turn_off = AsyncMock()
        mock_bridge.get_devices.return_value = {
            "2": {"type": "WallDimmer", "current_state": 40},
            "3": {"type": "WallDimmer", "current_state": 0},
        }
        mock_bridge.get_scenes.return_value = {}
        lutron._bridge = mock_bridge

        await lutron._async_flash_lights(["2", "3"], count=2, delay_seconds=0.01)

        # Device 2 had original level 40 -> restored with set_value("2", 40)
        # Device 3 had original level 0 -> restored with turn_off("3")
        mock_bridge.set_value.assert_any_await("2", 40)
        mock_bridge.turn_off.assert_any_await("3")


# ---------------------------------------------------------------------------
# Flask API Routes Tests
# ---------------------------------------------------------------------------

class TestLutronRoutes:
    def test_api_lutron_state(self):
        with server.flaskapp.test_client() as client:
            with patch("lutron.is_configured", return_value=True), \
                 patch("lutron.is_connected", return_value=True), \
                 patch("lutron.get_devices", return_value=[{"id": "1", "name": "Porch"}]), \
                 patch("lutron.get_scenes", return_value=[{"id": "2", "name": "Welcome"}]):
                resp = client.get("/api/lutron/state")
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["configured"] is True
                assert data["connected"] is True
                assert len(data["devices"]) == 1
                assert len(data["scenes"]) == 1

    def test_api_lutron_set_device(self):
        with server.flaskapp.test_client() as client:
            with patch("lutron.set_device_level", return_value=True) as mock_set:
                resp = client.post("/api/lutron/set", json={"device_id": "2", "level": 75})
                assert resp.status_code == 200
                assert resp.get_json()["ok"] is True
                mock_set.assert_called_once_with("2", 75)

    def test_api_lutron_set_all_off(self):
        with server.flaskapp.test_client() as client:
            with patch("lutron.turn_all_off", return_value=True) as mock_turn_off:
                resp = client.post("/api/lutron/set", json={"action": "all_off"})
                assert resp.status_code == 200
                assert resp.get_json()["ok"] is True
                mock_turn_off.assert_called_once()

    def test_api_lutron_set_missing_device_id(self):
        with server.flaskapp.test_client() as client:
            resp = client.post("/api/lutron/set", json={"level": 50})
            assert resp.status_code == 400

    def test_api_lutron_scene(self):
        with server.flaskapp.test_client() as client:
            with patch("lutron.activate_scene", return_value=True) as mock_scene:
                resp = client.post("/api/lutron/scene", json={"scene_id": "99"})
                assert resp.status_code == 200
                assert resp.get_json()["ok"] is True
                mock_scene.assert_called_once_with("99")

    def test_dinner_bell_triggers_light_flash(self):
        with server.flaskapp.test_client() as client:
            with patch("announcements.send_dinner_bell", return_value=(1, 1)), \
                 patch("lutron.flash_lights_for_dinner_bell") as mock_flash:
                resp = client.post("/api/dinner-bell")
                assert resp.status_code == 200
                mock_flash.assert_called_once()
