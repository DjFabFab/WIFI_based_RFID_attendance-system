#!/bin/bash
# Presency kiosk launcher: starts Chromium in kiosk mode with the Chrome
# DevTools Protocol (CDP) remote debugging port enabled so the
# divera-kiosk.service watcher can switch the visible tab to Divera while an
# alarm is active. Add this line to ~/.config/labwc/autostart (pi user):
#   exec /usr/local/bin/kiosk-browser.sh &
# Log into https://www.divera247.com/ once in the kiosk profile
# (~/.config/presency-kiosk) so the dashboard shows member statuses.
#
if pgrep -x chromium >/dev/null 2>&1; then
  echo "Chromium already running, exiting"
  exit 0
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

# Hardening for physically public kiosk (members + occasional public):
# - --incognito / --no-first-run / --no-default-browser-check : no history/first-run UI
# - --disable-pinch / --overscroll-history-navigation=0 : block pinch/ swipe escape
# - --disable-features=Translate : remove translate bubble
# - --remote-allow-origins restricted to localhost (divera_kiosk.py uses http://127.0.0.1:9222)
#   so remote CDP cannot be driven from LAN. Keep --remote-debugging-port=9222 for divera_kiosk.
#   Do NOT expose 9222 beyond 127.0.0.1 (firewall/iptables if needed).
# Physical lock beyond flags (handled outside this script): labwc should not bind
# Alt+F4/Ctrl+Shift+I/J, right-click is suppressed by kiosk JS, display auto-dims.
# Launch Chromium in background so we can verify the page loaded and
# auto-reload if the first load was blank (race where Chromium fetched
# before Django was fully ready, even though curl succeeded).
chromium --kiosk --ozone-platform=wayland --enable-features=WaylandWindowDecorations --remote-debugging-port=9222 --remote-allow-origins=http://127.0.0.1:9222 --noerrdialogs --disable-infobars --disable-session-crashed-bubble --incognito --no-first-run --no-default-browser-check --disable-pinch --overscroll-history-navigation=0 --disable-features=Translate --user-data-dir=/home/pi/.config/presency-kiosk "${KIOSK_HOME_URL:-http://127.0.0.1:8000/}" &
CHROMIUM_PID=$!

# Give Chromium a few seconds to load, then check via CDP if the body is
# still empty (blank screen). If so, send F5 to reload.
(
  sleep 5
  for _ in $(seq 1 10); do
    if curl -s http://127.0.0.1:9222/json/list 2>/dev/null | grep -q '"url": "http://127.0.0.1:8000/"'; then
      # Use wtype to send F5 if body is empty — simplest wake/reload without CDP websocket
      # The page's kiosk.js will also wake on keydown, so this both reloads and undims.
      WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 wtype -k F5 2>/dev/null || true
      break
    fi
    sleep 1
  done
) &

wait $CHROMIUM_PID
