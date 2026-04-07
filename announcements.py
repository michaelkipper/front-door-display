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
SPEAKER_GROUP_NAME = "All Speakers"
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


def _cast_to_speakers(audio_url):
    """Cast an audio URL to the All Speakers group."""
    chromecasts, browser = pychromecast.get_listed_chromecasts(
        friendly_names=[SPEAKER_GROUP_NAME]
    )
    try:
        if not chromecasts:
            logging.error("Speaker group '%s' not found on network", SPEAKER_GROUP_NAME)
            return False

        cast = chromecasts[0]
        cast.wait()
        mc = cast.media_controller
        mc.play_media(audio_url, "audio/mp3")
        mc.block_until_active()
        logging.info("Announcement cast to '%s'", SPEAKER_GROUP_NAME)
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


def send_test(server_port, text="This is a test announcement from the front door display."):
    """Send a one-off test announcement to the speakers."""
    return _broadcast(text, server_port)


def start_announcement_loop(get_now_fn, get_events_fn, server_port):
    """Launch the announcement background thread."""
    thread = threading.Thread(
        target=_announcement_loop,
        args=(get_now_fn, get_events_fn, server_port),
        daemon=True,
    )
    thread.start()
    logging.info("Announcement loop started (checking every %ds)", CHECK_INTERVAL_SECONDS)
