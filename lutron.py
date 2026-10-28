"""Lutron Caséta module — connects to a Smart Bridge via LEAP/TLS.

Maintains a persistent background asyncio connection to the bridge,
subscribes to real-time zone and scene state updates, and exposes
thread-safe helper functions for Flask endpoints and announcement triggers.
"""

from __future__ import annotations

import asyncio
import os
from pylutron_caseta.smartbridge import Smartbridge
from pylutron_caseta.pairing import async_pair
import threading
import time
import typing

from absl import app
from absl import flags
from absl import logging

try:
    import config  # pyright: ignore[reportMissingImports]
except ImportError:
    import importlib.util

    _example_config_path = os.path.join(os.path.dirname(__file__), "config.example.py")
    if os.path.isfile(_example_config_path):
        _spec = importlib.util.spec_from_file_location("config", _example_config_path)
        if _spec and _spec.loader:
            config = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(config)
        else:
            raise
    else:
        raise

LUTRON_BRIDGE_IP: str = getattr(config, "LUTRON_BRIDGE_IP", "")
LUTRON_KEY_PATH: str = getattr(config, "LUTRON_KEY_PATH", "certs/caseta.key")
LUTRON_CERT_PATH: str = getattr(config, "LUTRON_CERT_PATH", "certs/caseta.crt")
LUTRON_CA_PATH: str = getattr(config, "LUTRON_CA_PATH", "certs/caseta-bridge.crt")
LUTRON_DINNER_BELL_ZONES: list[str] = getattr(config, "LUTRON_DINNER_BELL_ZONES", [])
LUTRON_SHABBAT_REMINDER_ZONES: list[str] = getattr(config, "LUTRON_SHABBAT_REMINDER_ZONES", [])

# CLI flags for pairing tool
_PAIR_IP = flags.DEFINE_string("pair_ip", None, "IP address of Lutron Smart Bridge to pair with")
_CERTS_DIR = flags.DEFINE_string("certs_dir", "certs", "Output directory for TLS certificates")

# ---------------------------------------------------------------------------
# Module State
# ---------------------------------------------------------------------------

_bridge: typing.Any | None = None
_loop: asyncio.AbstractEventLoop | None = None
_worker_thread: threading.Thread | None = None
_is_connected: bool = False
_connection_lock = threading.Lock()

# Cached state for fast synchronous reads
_cached_state: dict[str, typing.Any] = {
    "devices": [],
    "scenes": [],
    "timestamp": 0.0,
}

_last_error_log: float = 0.0
ERROR_LOG_INTERVAL_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_throttled(message: str, *args: typing.Any) -> None:
    """Log a warning throttled to at most once per interval."""
    global _last_error_log
    now = time.time()
    if now - _last_error_log >= ERROR_LOG_INTERVAL_SECONDS:
        logging.warning(message, *args)
        _last_error_log = now


def _clean_device_name(raw_name: str) -> str:
    """Convert Lutron internal device names into readable names.

    E.g., 'Living_Room_Ceiling_Light' -> 'Living Room Ceiling Light'.
    """
    if not raw_name:
        return "Unknown Light"
    name = raw_name.replace("_", " ").strip()
    return name


def _format_device(device_id: str, raw_device: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Format raw Lutron device dictionary into a clean UI-ready dictionary."""
    dev_type = str(raw_device.get("type", "Unknown"))
    is_dimmer = "Dimmer" in dev_type or "dimmer" in dev_type.lower()
    current_state = raw_device.get("current_state", -1)
    level = current_state if current_state >= 0 else 0
    is_on = level > 0

    return {
        "id": str(device_id),
        "name": _clean_device_name(str(raw_device.get("name", ""))),
        "type": dev_type,
        "is_on": is_on,
        "level": level,
        "is_dimmable": is_dimmer,
        "zone": raw_device.get("zone"),
    }


def _format_scene(scene_id: str, raw_scene: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Format raw Lutron scene dictionary into a clean UI-ready dictionary."""
    return {
        "id": str(scene_id),
        "name": _clean_device_name(str(raw_scene.get("name", ""))),
    }


def is_configured() -> bool:
    """Return True if Lutron bridge IP and certificate paths are configured on disk."""
    if not LUTRON_BRIDGE_IP:
        return False
    return (
        os.path.isfile(LUTRON_KEY_PATH)
        and os.path.isfile(LUTRON_CERT_PATH)
        and os.path.isfile(LUTRON_CA_PATH)
    )


def is_connected() -> bool:
    """Return True if the bridge client is currently connected and authenticated."""
    return _is_connected and _bridge is not None


# ---------------------------------------------------------------------------
# Background Asyncio Event Loop & Connection
# ---------------------------------------------------------------------------

def _refresh_cache_from_bridge() -> None:
    """Rebuild the cached device and scene list from the current bridge object."""
    global _cached_state
    if not _bridge:
        return

    try:
        raw_devices = _bridge.get_devices()
        controllable_devices: list[dict[str, typing.Any]] = []

        # Filter for lights and switches (WallDimmer, WallSwitch, PlugInDimmer, etc.)
        for dev_id, dev in raw_devices.items():
            dev_type = str(dev.get("type", ""))
            if "Dimmer" in dev_type or "Switch" in dev_type or "Light" in dev_type:
                controllable_devices.append(_format_device(dev_id, dev))

        # Sort alphabetically by name
        controllable_devices.sort(key=lambda d: d["name"])

        raw_scenes = _bridge.get_scenes()
        scenes: list[dict[str, typing.Any]] = [
            _format_scene(s_id, s) for s_id, s in raw_scenes.items()
        ]
        scenes.sort(key=lambda s: s["name"])

        _cached_state = {
            "devices": controllable_devices,
            "scenes": scenes,
            "timestamp": time.time(),
        }
    except Exception:
        logging.exception("Failed to refresh Lutron device cache")


def _on_device_updated() -> None:
    """Callback fired by Smartbridge when any device state changes."""
    _refresh_cache_from_bridge()


def _on_bridge_connected() -> None:
    """Callback fired by Smartbridge upon successful connection."""
    global _is_connected
    _is_connected = True
    logging.info("Connected to Lutron Smart Bridge at %s", LUTRON_BRIDGE_IP)
    _refresh_cache_from_bridge()


def _on_bridge_disconnected() -> None:
    """Callback fired by Smartbridge if disconnected."""
    global _is_connected
    _is_connected = False
    logging.warning("Disconnected from Lutron Smart Bridge at %s", LUTRON_BRIDGE_IP)


async def _bridge_lifecycle_task() -> None:
    """Asynchronous task managing the Smartbridge connection."""
    global _bridge, _is_connected

    if not is_configured():
        _log_throttled(
            "Lutron Caséta is not configured. Missing LUTRON_BRIDGE_IP or cert files (%s, %s, %s)",
            LUTRON_KEY_PATH,
            LUTRON_CERT_PATH,
            LUTRON_CA_PATH,
        )
        return

    logging.info("Initializing connection to Lutron Smart Bridge at %s...", LUTRON_BRIDGE_IP)

    try:
        bridge_cls = typing.cast(typing.Any, Smartbridge)
        bridge_instance = bridge_cls.create_tls(
            hostname=LUTRON_BRIDGE_IP,
            keyfile=LUTRON_KEY_PATH,
            certfile=LUTRON_CERT_PATH,
            ca_certs=LUTRON_CA_PATH,
            on_connect_callback=_on_bridge_connected,
            on_disconnect_callback=_on_bridge_disconnected,
        )
        _bridge = bridge_instance

        await bridge_instance.connect()
        _is_connected = True
        logging.info("Lutron Smart Bridge connected and logged in")

        # Subscribe to all devices for push updates
        raw_devices = bridge_instance.get_devices()
        for dev_id in raw_devices:
            bridge_instance.add_subscriber(dev_id, _on_device_updated)

        _refresh_cache_from_bridge()

    except Exception:
        _is_connected = False
        _log_throttled("Failed to connect to Lutron Smart Bridge at %s", LUTRON_BRIDGE_IP)


def _run_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Entry point for the background worker thread."""
    asyncio.set_event_loop(loop)
    loop.create_task(_bridge_lifecycle_task())
    try:
        loop.run_forever()
    finally:
        loop.close()


def start_lutron() -> None:
    """Start the background Lutron worker thread if not already running."""
    global _loop, _worker_thread

    with _connection_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return

        _loop = asyncio.new_event_loop()
        _worker_thread = threading.Thread(
            target=_run_event_loop,
            args=(_loop,),
            name="LutronWorkerThread",
            daemon=True,
        )
        _worker_thread.start()
        logging.info("Lutron background worker thread started")


def stop_lutron() -> None:
    """Stop the background Lutron worker thread."""
    global _loop, _worker_thread, _is_connected, _bridge

    with _connection_lock:
        if _loop is not None and _loop.is_running():
            if _bridge:
                try:
                    asyncio.run_coroutine_threadsafe(_bridge.close(), _loop).result(timeout=2.0)
                except Exception:
                    pass
            _loop.call_soon_threadsafe(_loop.stop)

        _is_connected = False
        _bridge = None
        _worker_thread = None
        _loop = None


# ---------------------------------------------------------------------------
# Device Control Coroutines
# ---------------------------------------------------------------------------

async def _async_set_device_level(device_id: str, level: int) -> bool:
    """Async implementation: set a device's brightness level (0-100)."""
    if not _bridge:
        return False
    clamped_level = max(0, min(100, level))
    if clamped_level == 0:
        await _bridge.turn_off(device_id)
    else:
        await _bridge.set_value(device_id, clamped_level)
    _refresh_cache_from_bridge()
    return True


async def _async_turn_all_off() -> bool:
    """Async implementation: turn off all controllable devices."""
    if not _bridge:
        return False
    devices = _bridge.get_devices()
    tasks = []
    for dev_id, dev in devices.items():
        dev_type = str(dev.get("type", ""))
        if ("Dimmer" in dev_type or "Switch" in dev_type or "Light" in dev_type) and dev.get("current_state", 0) > 0:
            tasks.append(_bridge.turn_off(dev_id))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _refresh_cache_from_bridge()
    return True


async def _async_activate_scene(scene_id: str) -> bool:
    """Async implementation: activate a Lutron scene."""
    if not _bridge:
        return False
    await _bridge.activate_scene(scene_id)
    _refresh_cache_from_bridge()
    return True


async def _async_flash_lights(device_ids: list[str], count: int = 3, delay_seconds: float = 0.5) -> None:
    """Async implementation: pulse specified lights, then restore original levels."""
    if not _bridge or not device_ids:
        return

    # Snapshot current levels
    raw_devices = _bridge.get_devices()
    original_levels: dict[str, int] = {}
    valid_ids: list[str] = []

    for dev_id in device_ids:
        if dev_id in raw_devices:
            st = raw_devices[dev_id].get("current_state", 0)
            original_levels[dev_id] = max(0, st)
            valid_ids.append(dev_id)

    if not valid_ids:
        return

    logging.info("Flashing %d Lutron lights for reminder/alert", len(valid_ids))

    try:
        for _ in range(count):
            # Turn ON (100%)
            await asyncio.gather(*[_bridge.set_value(did, 100) for did in valid_ids], return_exceptions=True)
            await asyncio.sleep(delay_seconds)
            # Turn OFF
            await asyncio.gather(*[_bridge.turn_off(did) for did in valid_ids], return_exceptions=True)
            await asyncio.sleep(delay_seconds)

        # Restore original levels
        restore_tasks = []
        for did in valid_ids:
            orig = original_levels.get(did, 0)
            if orig > 0:
                restore_tasks.append(_bridge.set_value(did, orig))
            else:
                restore_tasks.append(_bridge.turn_off(did))
        await asyncio.gather(*restore_tasks, return_exceptions=True)
        _refresh_cache_from_bridge()
    except Exception:
        logging.exception("Error during light flashing sequence")


# ---------------------------------------------------------------------------
# Public Thread-Safe API
# ---------------------------------------------------------------------------

def get_devices() -> list[dict[str, typing.Any]]:
    """Return the cached list of controllable devices."""
    return list(_cached_state["devices"])


def get_scenes() -> list[dict[str, typing.Any]]:
    """Return the cached list of scenes."""
    return list(_cached_state["scenes"])


def set_device_level(device_id: str, level: int, timeout: float = 5.0) -> bool:
    """Set the brightness level of a device (0-100). Level 0 turns off."""
    if not _loop or not _loop.is_running() or not _is_connected:
        return False
    try:
        future = asyncio.run_coroutine_threadsafe(_async_set_device_level(device_id, level), _loop)
        return future.result(timeout=timeout)
    except Exception:
        logging.exception("Failed to set Lutron device %s level to %d", device_id, level)
        return False


def turn_all_off(timeout: float = 5.0) -> bool:
    """Turn off all lights in the house."""
    if not _loop or not _loop.is_running() or not _is_connected:
        return False
    try:
        future = asyncio.run_coroutine_threadsafe(_async_turn_all_off(), _loop)
        return future.result(timeout=timeout)
    except Exception:
        logging.exception("Failed to turn all Lutron lights off")
        return False


def activate_scene(scene_id: str, timeout: float = 5.0) -> bool:
    """Activate a Lutron scene by ID."""
    if not _loop or not _loop.is_running() or not _is_connected:
        return False
    try:
        future = asyncio.run_coroutine_threadsafe(_async_activate_scene(scene_id), _loop)
        return future.result(timeout=timeout)
    except Exception:
        logging.exception("Failed to activate Lutron scene %s", scene_id)
        return False


def flash_lights(device_ids: list[str], count: int = 3, delay_seconds: float = 0.5) -> None:
    """Flash designated lights asynchronously in the background."""
    if not _loop or not _loop.is_running() or not _is_connected or not device_ids:
        return
    asyncio.run_coroutine_threadsafe(_async_flash_lights(device_ids, count, delay_seconds), _loop)


def flash_lights_for_dinner_bell() -> None:
    """Flash configured dinner bell alert lights."""
    if LUTRON_DINNER_BELL_ZONES:
        flash_lights(LUTRON_DINNER_BELL_ZONES, count=3, delay_seconds=0.4)


def flash_lights_for_shabbat_reminder() -> None:
    """Flash configured 5-minute pre-Shabbat candle lighting lights."""
    if LUTRON_SHABBAT_REMINDER_ZONES:
        flash_lights(LUTRON_SHABBAT_REMINDER_ZONES, count=3, delay_seconds=0.6)


# ---------------------------------------------------------------------------
# Pairing Tool (CLI)
# ---------------------------------------------------------------------------

async def async_pair_bridge(
    host: str,
    output_dir: str = "certs",
    on_ready: typing.Callable[[], None] | None = None,
) -> dict[str, str]:
    """Pair with a Lutron Smart Bridge and write generated certificates to output_dir."""
    def _default_ready_prompt() -> None:
        logging.info(">>> PRESS THE SMALL BLACK BUTTON ON THE BACK OF THE LUTRON BRIDGE NOW <<<")

    ready_fn = on_ready or _default_ready_prompt
    logging.info("Initiating pairing with Lutron Smart Bridge at %s...", host)
    data = await async_pair(host, ready_fn)

    os.makedirs(output_dir, exist_ok=True)
    key_path = os.path.join(output_dir, "caseta.key")
    cert_path = os.path.join(output_dir, "caseta.crt")
    ca_path = os.path.join(output_dir, "caseta-bridge.crt")

    with open(key_path, "w", encoding="utf-8") as f:
        f.write(data["key"])
    with open(cert_path, "w", encoding="utf-8") as f:
        f.write(data["cert"])
    with open(ca_path, "w", encoding="utf-8") as f:
        f.write(data["ca"])

    logging.info("Successfully paired! Certificates saved to %s", output_dir)
    return {
        "key": key_path,
        "cert": cert_path,
        "ca": ca_path,
        "version": str(data.get("version", "")),
    }


def pair_bridge(host: str, output_dir: str = "certs") -> dict[str, str]:
    """Synchronous entry point for pairing with a Lutron Smart Bridge."""
    return asyncio.run(async_pair_bridge(host, output_dir))


def main(argv: list[str]) -> None:
    """CLI entry point for running the pairing utility."""
    if _PAIR_IP.value:
        bridge_ip = _PAIR_IP.value
    elif len(argv) > 1 and argv[1] != "pair":
        bridge_ip = argv[1]
    elif len(argv) > 2 and argv[1] == "pair":
        bridge_ip = argv[2]
    else:
        logging.error("Usage: python lutron.py --pair_ip=<BRIDGE_IP> (or 'python lutron.py pair <BRIDGE_IP>')")
        return

    out_dir = _CERTS_DIR.value
    try:
        pair_bridge(bridge_ip, out_dir)
        logging.info("Add these lines to config.py:")
        logging.info("LUTRON_BRIDGE_IP = '%s'", bridge_ip)
        logging.info("LUTRON_KEY_PATH = '%s/caseta.key'", out_dir)
        logging.info("LUTRON_CERT_PATH = '%s/caseta.crt'", out_dir)
        logging.info("LUTRON_CA_PATH = '%s/caseta-bridge.crt'", out_dir)
    except Exception as exc:
        logging.exception("Pairing failed: %s", exc)


if __name__ == "__main__":
    app.run(main)
