#!/bin/sh
#
# This script is intended to be run at startup, and will launch a kiosk-mode
# Chromium browser instance that points to the local web server hosting the
# front-door-display application.
#
# It should be located at ~/.config/labwc/autostart and be executable.
#

PROJECT_DIR="/home/mkipper/src/michaelkipper/front-door-display"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG="$PROJECT_DIR/server.log"

cd "$PROJECT_DIR" || exit 1

{
        echo "Starting up..."
        date
} > "$LOG"

# Do not use "source" here: labwc autostart runs under /bin/sh.
if [ -x "$VENV_PYTHON" ]; then
        "$VENV_PYTHON" server.py >> "$LOG" 2>&1 &
else
        echo "WARN: venv python not found at $VENV_PYTHON; falling back to system python3" >> "$LOG"
        python3 server.py >> "$LOG" 2>&1 &
fi

sleep 2

exec chromium-browser \
        --remote-debugging-port=9222 \
        --noerrdialogs \
        --disable-infobars \
        --kiosk \
        --incognito \
        http://localhost:8080
