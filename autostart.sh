#!/bin/bash
#
# This script is intended to be run at startup, and will launch a kiosk-mode
# Chromium browser instance that points to the local web server hosting the
# front-door-display application.
#
# It should be located at ~/.config/labwc/autostart and be executable.
#

cd /home/mkipper/src/michaelkipper/front-door-display
python3 server.py > ~/http.log 2>&1 &

sleep 2

exec chromium-browser \
        --remote-debugging-port=9222 \
        --noerrdialogs \
        --disable-infobars \
        --kiosk \
        --incognito \
        http://localhost:8080
