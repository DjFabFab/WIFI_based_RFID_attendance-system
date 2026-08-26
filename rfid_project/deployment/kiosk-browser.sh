#!/bin/bash
# Presency kiosk launcher: starts Chromium in kiosk mode with the Chrome
# DevTools Protocol (CDP) remote debugging port enabled so the
# divera-kiosk.service watcher can switch the visible tab to Divera while an
# alarm is active. Add this line to ~/.config/labwc/autostart (pi user):
#   exec /usr/local/bin/kiosk-browser.sh &
# Log into https://www.divera247.com/ once in the kiosk profile
# (~/.config/presency-kiosk) so the dashboard shows member statuses.
#
# Wayland OSK (squeekboard): Chromium must run native Wayland for the
# zwp_text_input_v3 protocol to trigger squeekboard on input focus.
# --ozone-platform=wayland is required; squeekboard must be running
# (started via labwc autostart, see install-rpi.sh). If the OSK still
# doesn't appear, check: `ps aux | grep squeekboard` and
# `WAYLAND_DISPLAY=wayland-0 squeekboard` is not blocked by kiosk layer.

# Ensure squeekboard is running (started early via autostart, but be defensive)
if ! pgrep -x squeekboard >/dev/null 2>&1; then
  nohup /usr/bin/squeekboard >/dev/null 2>&1 &
  sleep 0.5
fi

# Wait for Django to be ready before launching Chromium — otherwise the
# kiosk shows a blank <body> until a manual F5 (server takes ~5s to start
# after reboot, while labwc/Chromium starts immediately via autostart).
for _ in $(seq 1 30); do
  if curl -s -o /dev/null -w "%{http_code}" "${KIOSK_HOME_URL:-http://127.0.0.1:8000/}" 2>/dev/null | grep -q "200"; then
    break
  fi
  sleep 1
done

exec chromium --kiosk --ozone-platform=wayland --enable-features=WaylandWindowDecorations --remote-debugging-port=9222 --remote-allow-origins=* --noerrdialogs --disable-infobars --disable-session-crashed-bubble --user-data-dir=/home/pi/.config/presency-kiosk "${KIOSK_HOME_URL:-http://127.0.0.1:8000/}"
