#!/bin/bash
if pgrep -x chromium >/dev/null 2>&1; then
  echo "Chromium already running, exiting"
  exit 0
fi

for _ in $(seq 1 30); do
  curl -sf http://127.0.0.1:8000/ >/dev/null 2>&1 && break
  sleep 1
done

chromium --kiosk --ozone-platform=wayland --enable-features=WaylandWindowDecorations --remote-debugging-port=9222 --remote-allow-origins=http://127.0.0.1:9222 --noerrdialogs --disable-infobars --disable-session-crashed-bubble --incognito --no-first-run --no-default-browser-check --disable-pinch --overscroll-history-navigation=0 --disable-features=Translate --user-data-dir=/home/pi/.config/presency-kiosk http://127.0.0.1:8000/ &
CHROMIUM_PID=$!

(
  sleep 10
  JSON=$(curl -s http://127.0.0.1:9222/json/list 2>/dev/null)
  echo "$JSON" | grep -q "Presency" && exit 0
  curl -s -X PUT "http://127.0.0.1:9222/json/new?http://127.0.0.1:8000/" >/dev/null 2>&1
  sleep 2
  JSON=$(curl -s http://127.0.0.1:9222/json/list 2>/dev/null)
  IDS=$(echo "$JSON" | grep -o '"id": "[^"]*"' | cut -d'"' -f4)
  COUNT=$(echo "$IDS" | wc -l)
  if [ "$COUNT" -gt 3 ]; then
    echo "$IDS" | head -n -3 | while read id; do
      curl -s -X PUT "http://127.0.0.1:9222/json/close/$id" >/dev/null 2>&1
    done
  fi
) &

wait $CHROMIUM_PID
