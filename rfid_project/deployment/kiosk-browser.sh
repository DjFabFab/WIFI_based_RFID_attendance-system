#!/bin/bash
# Presency kiosk launcher: starts Chromium in kiosk mode with the Chrome
# DevTools Protocol (CDP) remote debugging port enabled so the
# divera-kiosk.service watcher can switch the visible tab to Divera while an
# alarm is active. Add this line to ~/.config/labwc/autostart (pi user):
#   exec /usr/local/bin/kiosk-browser.sh &
# Log into https://www.divera247.com/ once in the kiosk profile
# (~/.config/presency-kiosk) so the dashboard shows member statuses.
exec chromium --kiosk --remote-debugging-port=9222 --noerrdialogs --disable-infobars --disable-session-crashed-bubble --user-data-dir=/home/pi/.config/presency-kiosk "${KIOSK_HOME_URL:-http://127.0.0.1:8000/}"
