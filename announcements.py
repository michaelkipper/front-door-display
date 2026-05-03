"""Shabbat announcement broadcaster.

Broadcasts a voice reminder to Google Home speakers 5 minutes before
candle lighting or havdalah using pychromecast and gTTS.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import collections.abc
import datetime
import typing

from absl import logging
import gtts
import pychromecast

REMINDER_MINUTES = 5
SPEAKER_NAME = "Kitchen display"
ANNOUNCEMENT_FILE = os.path.join("static", "announcement.mp3")
CHECK_INTERVAL_SECONDS = 30
DISCOVERY_CACHE_SECONDS = 5 * 60  # 5 minutes
CONNECT_PROBE_TIMEOUT_SECONDS = 1.5
CONNECT_PROBE_ATTEMPTS = 3
CONNECT_PROBE_BACKOFF_SECONDS = 0.5
DINNER_BELL_TEXT = "Attention Kipper Family! Dinner is served in the kitchen."
PREFERRED_SPEAKER_GROUP_NAME = "All Speakers"

# Track announced events to avoid repeats.
_announced_events = set()

# Cached discovery results: {"devices": [...], "cast_infos": {name: CastInfo}, "timestamp": float}
_discovery_cache = {"devices": None, "cast_infos": {}, "timestamp": 0}


def _get_local_ip() -> str:
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _format_time_for_speech(dt: datetime.datetime) -> str:
    """Format a datetime for spoken English, e.g. '7:34 PM'."""
    hour = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    ampm = "PM" if dt.hour >= 12 else "AM"
    return f"{hour}:{minute} {ampm}"


def _generate_tts(text: str) -> str:
    """Generate announcement audio and save to static file."""
    tts = gtts.gTTS(text=text, lang="en")
    tts.save(ANNOUNCEMENT_FILE)
    logging.info("Generated TTS audio: %s", ANNOUNCEMENT_FILE)

    return ANNOUNCEMENT_FILE


def discover_devices(timeout: int = 10) -> list[dict]:
    """Scan the network for all Chromecast devices and return info about each.

    Results are cached for DISCOVERY_CACHE_SECONDS to avoid repeated network scans.
    Also caches the real CastInfo objects so we can connect without re-discovery.
    """
    now_ts = time.time()
    if _discovery_cache["devices"] is not None and now_ts - _discovery_cache["timestamp"] < DISCOVERY_CACHE_SECONDS:
        logging.info("Returning cached discovery results (%d devices)", len(_discovery_cache["devices"]))
        return _discovery_cache["devices"]

    logging.info("Scanning for all Chromecast devices (timeout=%ds)...", timeout)
    browser = pychromecast.CastBrowser(  # type: ignore[attr-defined]
        pychromecast.SimpleCastListener(lambda uuid, name: None),  # type: ignore[attr-defined]
        pychromecast.zeroconf.Zeroconf(),  # type: ignore[attr-defined]
    )
    browser.start_discovery()
    time.sleep(timeout)
    devices = []
    cast_infos = {}
    try:
        for uuid, service in browser.devices.items():
            info = {
                "name": service.friendly_name,
                "model": service.model_name,
                "host": str(service.host),
                "port": service.port,
                "uuid": str(uuid),
                "cast_type": service.cast_type,
            }
            devices.append(info)
            if service.friendly_name:
                cast_infos[service.friendly_name] = service
            logging.info(
                "  Device: name='%s', model='%s', host=%s:%s, uuid=%s, type=%s",
                info["name"], info["model"], info["host"], info["port"],
                info["uuid"], info["cast_type"],
            )
        logging.info("Found %d device(s) on network", len(devices))
    finally:
        browser.stop_discovery()

    _discovery_cache["devices"] = devices
    _discovery_cache["cast_infos"] = cast_infos
    _discovery_cache["timestamp"] = now_ts
    return devices


def _resolve_speaker_cast_info() -> pychromecast.CastInfo | None:  # type: ignore[name-defined]
    """Look up the CastInfo for SPEAKER_NAME via cached discovery."""
    discover_devices()
    cast_info = _discovery_cache["cast_infos"].get(SPEAKER_NAME)
    if cast_info:
        logging.info("Resolved '%s' -> %s:%s", SPEAKER_NAME, cast_info.host, cast_info.port)
    else:
        logging.error("Device '%s' not found among %d discovered devices",
                       SPEAKER_NAME, len(_discovery_cache["devices"] or []))
    return cast_info


def _play_on_device(
    cast: typing.Any,
    audio_url: str,
    target_host: str | None = None,
    target_port: int | None = None,
) -> None:
    """Play audio on an already-discovered Chromecast device."""
    resolved_host = target_host or getattr(cast.socket_client, "host", None)
    if resolved_host in (None, "", "unknown"):
        resolved_host = "unknown"
    resolved_port = target_port or getattr(cast.socket_client, "port", None)
    logging.info(
        "Casting to device: name='%s', model='%s', host=%s:%s, uuid=%s",
        cast.name, cast.model_name,
        resolved_host, resolved_port, cast.uuid,
    )
    cast.wait()
    logging.info(
        "Device status: app_id=%s, display_name='%s', volume=%.2f, muted=%s",
        cast.status.app_id if cast.status else None,
        cast.status.display_name if cast.status else None,
        cast.status.volume_level if cast.status else -1,
        cast.status.volume_muted if cast.status else None,
    )
    mc = cast.media_controller
    logging.info("Playing media: %s", audio_url)
    mc.play_media(audio_url, "audio/mp3")
    mc.block_until_active()
    logging.info(
        "Media status: player_state=%s, content_id=%s",
        mc.status.player_state if mc.status else None,
        mc.status.content_id if mc.status else None,
    )


def _is_tcp_reachable(
    host: str,
    port: int,
    timeout: float = CONNECT_PROBE_TIMEOUT_SECONDS,
    attempts: int = CONNECT_PROBE_ATTEMPTS,
) -> bool:
    """Fast reachability probe used to avoid long pychromecast retries."""
    for attempt in range(1, attempts + 1):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError as exc:
            logging.warning(
                "TCP probe failed for %s:%s (%d/%d): %s",
                host,
                port,
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts:
                time.sleep(CONNECT_PROBE_BACKOFF_SECONDS * attempt)
    return False


def _create_chromecast(cast_info: typing.Any) -> pychromecast.Chromecast:
    """Create a Chromecast client, preferring low-retry settings when supported."""
    try:
        return pychromecast.Chromecast(cast_info, tries=1, retry_wait=1.0)
    except TypeError:
        # Backward compatibility for pychromecast versions without these kwargs.
        return pychromecast.Chromecast(cast_info)


def _connect_by_cast_info(cast_info: typing.Any) -> pychromecast.Chromecast:
    """Connect to a Chromecast using a discovered CastInfo.

    Replaces MDNSServiceInfo services with a HostServiceInfo so the socket
    client connects directly by IP instead of trying mDNS resolution.
    """
    logging.info("Connecting to Chromecast '%s' at %s:%s...",
                 cast_info.friendly_name, cast_info.host, cast_info.port)
    if not _is_tcp_reachable(str(cast_info.host), int(cast_info.port)):
        raise OSError(f"Chromecast unreachable at {cast_info.host}:{cast_info.port}")
    host_service = pychromecast.HostServiceInfo(host=cast_info.host, port=cast_info.port)  # type: ignore[attr-defined]
    direct_info = pychromecast.CastInfo(  # type: ignore[attr-defined]
        services={host_service},
        uuid=cast_info.uuid,
        model_name=cast_info.model_name,
        friendly_name=cast_info.friendly_name,
        host=cast_info.host,
        port=cast_info.port,
        cast_type=cast_info.cast_type,
        manufacturer=cast_info.manufacturer,
    )
    return _create_chromecast(direct_info)


def _connect_by_host(host: str, port: int = 8009) -> pychromecast.Chromecast:
    """Connect to a Chromecast directly by IP (fallback for /api/test-announcement?host=)."""
    logging.info("Connecting directly to Chromecast at %s:%s...", host, port)
    if not _is_tcp_reachable(host, port):
        raise OSError(f"Chromecast unreachable at {host}:{port}")
    from uuid import UUID
    service = pychromecast.HostServiceInfo(host=host, port=port)  # type: ignore[attr-defined]
    cast_info = pychromecast.CastInfo(  # type: ignore[attr-defined]
        services={service},
        uuid=UUID(int=0),
        model_name=None,
        friendly_name=None,
        host=host,
        port=port,
        cast_type="cast",
        manufacturer=None,
    )
    return _create_chromecast(cast_info)


def _cast_to_speakers(audio_url: str) -> bool:
    """Cast an audio URL to the default speaker, resolved by name."""
    cast_info = _resolve_speaker_cast_info()
    if not cast_info:
        return False
    cast = None
    try:
        cast = _connect_by_cast_info(cast_info)
        _play_on_device(cast, audio_url, str(cast_info.host), int(cast_info.port))
        logging.info("Announcement cast to '%s' (%s)", SPEAKER_NAME, cast_info.host)
        return True
    except Exception:
        logging.exception("Failed to cast to '%s' (%s)", SPEAKER_NAME, cast_info.host)
        return False
    finally:
        if cast:
            cast.disconnect()


def _cast_to_host(host: str, audio_url: str) -> bool:
    """Cast an audio URL to a specific Chromecast by IP address."""
    cast = None
    try:
        cast = _connect_by_host(host)
        _play_on_device(cast, audio_url, host, 8009)
        logging.info("Announcement cast to %s", host)
        return True
    except Exception:
        logging.exception("Failed to cast to %s", host)
        return False
    finally:
        if cast:
            cast.disconnect()


def _cast_to_all_speakers(audio_url: str) -> tuple[int, int]:
    """Cast an audio URL to a speaker group so all members play in sync."""
    discover_devices()
    group_infos = [
        cast_info
        for cast_info in _discovery_cache["cast_infos"].values()
        if str(getattr(cast_info, "cast_type", "")) == "group"
    ]

    if not group_infos:
        logging.warning("No speaker group devices were discovered")
        return (0, 0)

    chosen_group: typing.Any | None = None
    if PREFERRED_SPEAKER_GROUP_NAME:
        chosen_group = next(
            (g for g in group_infos if g.friendly_name == PREFERRED_SPEAKER_GROUP_NAME),
            None,
        )
        if not chosen_group:
            logging.warning(
                "Preferred speaker group '%s' was not found; using first discovered group",
                PREFERRED_SPEAKER_GROUP_NAME,
            )

    if not chosen_group:
        chosen_group = sorted(group_infos, key=lambda g: (g.friendly_name or ""))[0]

    cast = None
    host = str(chosen_group.host)
    port = int(chosen_group.port)
    name = chosen_group.friendly_name or host
    try:
        cast = _connect_by_cast_info(chosen_group)
        _play_on_device(cast, audio_url, host, port)
        logging.info("Dinner bell cast to speaker group '%s' (%s:%s)", name, host, port)
        return (1, 1)
    except Exception:
        logging.exception("Failed dinner bell cast to speaker group '%s' (%s:%s)", name, host, port)
        return (0, 1)
    finally:
        if cast:
            cast.disconnect()


def _broadcast(text: str, server_port: int) -> bool:
    """Generate TTS audio and cast it to the speaker group."""
    filename = _generate_tts(text)
    local_ip = _get_local_ip()
    audio_url = f"http://{local_ip}:{server_port}/static/announcement.mp3"
    return _cast_to_speakers(audio_url)


def _check_and_announce(
    get_now_fn: collections.abc.Callable[[], datetime.datetime],
    get_events_fn: collections.abc.Callable[[datetime.datetime, datetime.datetime], list[dict[str, typing.Any]]],
    server_port: int,
) -> None:
    """Check whether an event is ~5 min away and broadcast if so."""
    now = get_now_fn()
    events = get_events_fn(now, now)
    naive_now = now.replace(tzinfo=None) if now.tzinfo else now

    for event in events:
        if not (event["is_candle_lighting"] or event["is_havdalah"]):
            continue

        event_time = event["parsed_date"]
        if event_time.tzinfo:
            event_time = event_time.replace(tzinfo=None)

        delta_seconds = (event_time - naive_now).total_seconds()
        event_key = event["date"]

        # Announce when we first enter the 5-minute window.
        window = REMINDER_MINUTES * 60 + CHECK_INTERVAL_SECONDS
        if 0 < delta_seconds <= window and event_key not in _announced_events:
            label = "Candle Lighting" if event["is_candle_lighting"] else "Havdalah"
            time_str = _format_time_for_speech(event_time)
            text = (f"Attention Kipper Family! Attention Kipper Family! " +
                   f"{label} is in {REMINDER_MINUTES} minutes, at {time_str}. " +
                   f"Please prepare accordingly. " +
                   f"This is an automated announcement from the front door display. " +
                   f"Again, {label} is at {time_str}.")
            logging.info("Broadcasting: %s", text)
            if _broadcast(text, server_port):
                _announced_events.add(event_key)

    # Prevent unbounded growth.
    if len(_announced_events) > 50:
        _announced_events.clear()


def _announcement_loop(
    get_now_fn: collections.abc.Callable[[], datetime.datetime],
    get_events_fn: collections.abc.Callable[[datetime.datetime, datetime.datetime], list[dict[str, typing.Any]]],
    server_port: int,
) -> None:
    """Background loop: periodically check for upcoming events."""
    time.sleep(10)
    while True:
        try:
            _check_and_announce(get_now_fn, get_events_fn, server_port)
        except Exception:
            logging.exception("Error in announcement loop")
        time.sleep(CHECK_INTERVAL_SECONDS)


def send_test(server_port: int, text: str = "This is a test announcement from the front door display.", host: str | None = None) -> bool:
    """Send a one-off test announcement.

    If *host* is given, cast directly to that IP instead of the speaker group.
    """
    _generate_tts(text)
    local_ip = _get_local_ip()
    audio_url = f"http://{local_ip}:{server_port}/static/announcement.mp3"
    if host:
        return _cast_to_host(host, audio_url)
    return _cast_to_speakers(audio_url)


def send_dinner_bell(server_port: int, text: str = DINNER_BELL_TEXT) -> tuple[int, int]:
    """Broadcast a dinner bell announcement to a discovered speaker group."""
    filename = _generate_tts(text)
    local_ip = _get_local_ip()
    audio_url = f"http://{local_ip}:{server_port}/{filename}"
    return _cast_to_all_speakers(audio_url)


def start_announcement_loop(
    get_now_fn: collections.abc.Callable[[], datetime.datetime],
    get_events_fn: collections.abc.Callable[[datetime.datetime, datetime.datetime], list[dict[str, typing.Any]]],
    server_port: int,
) -> None:
    """Launch the announcement background thread."""
    thread = threading.Thread(
        target=_announcement_loop,
        args=(get_now_fn, get_events_fn, server_port),
        daemon=True,
    )
    thread.start()
    logging.info("Announcement loop started (checking every %ds)", CHECK_INTERVAL_SECONDS)
