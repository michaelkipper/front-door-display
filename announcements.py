"""Shabbat announcement broadcaster.

Broadcasts a voice reminder to Google Home speakers 5 minutes before
candle lighting or havdalah using pychromecast and gTTS.
"""

import os
import socket
import threading
import time

from absl import logging
from gtts import gTTS
import pychromecast

REMINDER_MINUTES = 5
SPEAKER_NAME = "Kitchen display"
ANNOUNCEMENT_FILE = os.path.join("static", "announcement.mp3")
CHECK_INTERVAL_SECONDS = 30

# Track announced events to avoid repeats.
_announced_events = set()


def _get_local_ip():
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _format_time_for_speech(dt):
    """Format a datetime for spoken English, e.g. '7:34 PM'."""
    hour = dt.hour % 12 or 12
    minute = f"{dt.minute:02d}"
    ampm = "PM" if dt.hour >= 12 else "AM"
    return f"{hour}:{minute} {ampm}"


def _generate_tts(text):
    """Generate announcement audio and save to static file."""
    tts = gTTS(text=text, lang="en")
    tts.save(ANNOUNCEMENT_FILE)
    logging.info("Generated TTS audio: %s", ANNOUNCEMENT_FILE)


def discover_devices(timeout: int = 30) -> list[dict]:
    """Scan the network for all Chromecast devices and return info about each."""
    logging.info("Scanning for all Chromecast devices (timeout=%ds)...", timeout)
    browser = pychromecast.CastBrowser(
        pychromecast.SimpleCastListener(lambda uuid, name: None),
        pychromecast.zeroconf.Zeroconf(),
    )
    browser.start_discovery()
    time.sleep(timeout)
    devices = []
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
            logging.info(
                "  Device: name='%s', model='%s', host=%s:%s, uuid=%s, type=%s",
                info["name"], info["model"], info["host"], info["port"],
                info["uuid"], info["cast_type"],
            )
        logging.info("Found %d device(s) on network", len(devices))
    finally:
        browser.stop_discovery()
    return devices


def _play_on_device(cast, audio_url):
    """Play audio on an already-discovered Chromecast device."""
    logging.info(
        "Casting to device: name='%s', model='%s', host=%s:%s, uuid=%s",
        cast.name, cast.model_name, cast.host, cast.port, cast.uuid,
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


def _cast_to_speakers(audio_url):
    """Cast an audio URL to the default speaker."""
    logging.info("Discovering Chromecast devices matching '%s'...", SPEAKER_NAME)
    chromecasts, browser = pychromecast.get_listed_chromecasts(
        friendly_names=[SPEAKER_NAME]
    )
    try:
        if not chromecasts:
            logging.error("Device '%s' not found on network", SPEAKER_NAME)
            return False

        _play_on_device(chromecasts[0], audio_url)
        logging.info("Announcement cast to '%s'", SPEAKER_NAME)
        return True
    finally:
        browser.stop_discovery()


def _cast_to_host(host, audio_url):
    """Cast an audio URL to a specific Chromecast by IP address."""
    logging.info("Connecting to Chromecast at %s...", host)
    chromecasts, browser = pychromecast.get_listed_chromecasts(
        friendly_names=None, known_hosts=[host]
    )
    try:
        if not chromecasts:
            logging.error("No Chromecast found at %s", host)
            return False

        _play_on_device(chromecasts[0], audio_url)
        logging.info("Announcement cast to %s", host)
        return True
    finally:
        browser.stop_discovery()


def _broadcast(text, server_port):
    """Generate TTS audio and cast it to the speaker group."""
    _generate_tts(text)
    local_ip = _get_local_ip()
    audio_url = f"http://{local_ip}:{server_port}/static/announcement.mp3"
    return _cast_to_speakers(audio_url)


def _check_and_announce(get_now_fn, get_events_fn, server_port):
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
            text = f"{label} is in {REMINDER_MINUTES} minutes, at {time_str}."
            logging.info("Broadcasting: %s", text)
            if _broadcast(text, server_port):
                _announced_events.add(event_key)

    # Prevent unbounded growth.
    if len(_announced_events) > 50:
        _announced_events.clear()


def _announcement_loop(get_now_fn, get_events_fn, server_port):
    """Background loop: periodically check for upcoming events."""
    time.sleep(10)
    while True:
        try:
            _check_and_announce(get_now_fn, get_events_fn, server_port)
        except Exception:
            logging.exception("Error in announcement loop")
        time.sleep(CHECK_INTERVAL_SECONDS)


def send_test(server_port, text="This is a test announcement from the front door display.", host=None):
    """Send a one-off test announcement.

    If *host* is given, cast directly to that IP instead of the speaker group.
    """
    _generate_tts(text)
    local_ip = _get_local_ip()
    audio_url = f"http://{local_ip}:{server_port}/static/announcement.mp3"
    if host:
        return _cast_to_host(host, audio_url)
    return _cast_to_speakers(audio_url)


def start_announcement_loop(get_now_fn, get_events_fn, server_port):
    """Launch the announcement background thread."""
    thread = threading.Thread(
        target=_announcement_loop,
        args=(get_now_fn, get_events_fn, server_port),
        daemon=True,
    )
    thread.start()
    logging.info("Announcement loop started (checking every %ds)", CHECK_INTERVAL_SECONDS)
