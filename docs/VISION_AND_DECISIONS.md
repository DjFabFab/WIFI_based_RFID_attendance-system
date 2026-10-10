# Vision & Decisions

## C1. Higher goal and vision

The higher goal is one Raspberry Pi at the fire station serving two missions at once, not a single-purpose attendance box. RFID attendance is the project's origin: the reader identifies members and records their presence. The Divera alarm-kiosk is the growth path built on top of the same hardware: the same Pi also drives a kiosk screen that shows the fire station's active alarms. Both missions are named and weighted equally, and this equal weighting is a locked user decision, not an evidence-derived conclusion README.md:1-14; rfid_project/divera_kiosk.py:1-22.

The repository name and the historical README still describe only the attendance mission, so the vision recorded here is deliberately broader than the code's original scope: attendance is mission one, the alarm dashboard is mission two, and one Pi is shared between them. The lightweight product name is Presency README.md:9-13. Everything downstream - the serial protocol, the schema, the kiosk switcher, and the deployment units - exists to support those two co-equal missions on a single device.

## C2. Attendance concept and end-to-end flow

The attendance concept is a fully local, one-way RFID pipeline: a card tap becomes a stored presence record, with no Wi-Fi or HTTP on the reader itself README.md:3-7.

End-to-end flow, from device to screen:

1. Reader. An ESP8266/ESP32 running ESPHome drives a PN532 NFC reader over I2C. On each tag the firmware writes the raw, hyphen-separated UID (for example 74-10-37-94) followed by a newline to the UART RFID_NodeMCU/RFID_NodeMCU.yaml:1-4; RFID_NodeMCU/RFID_NodeMCU.yaml:43-57.
2. Transport. The UID leaves the board only on UART0-TX (GPIO1) at 115200 baud; logging is moved to UART1 so the ticker stays clear of the UID line, and the NeoPixel keeps the otherwise-conflicting RX/GPIO3 pin RFID_NodeMCU/RFID_NodeMCU.yaml:1-4; RFID_NodeMCU/RFID_NodeMCU.yaml:28-37. The device uses no Wi-Fi, HTTP, or API components RFID_NodeMCU/RFID_NodeMCU.yaml:1-4.
3. Host port. A udev rule maps the USB-serial adapter to the stable symlink /dev/ttyRFID (see C5). The host bridge auto-detects the port, preferring /dev/ttyUSB0, then /dev/ttyACM0, then /dev/ttyRFID rfid_project/rfid_serial_bridge.py:59-104.
4. Bridge. rfid_project/rfid_serial_bridge.py reads the port line by line, strips whitespace, skips any line that is not a hex-or-hyphen string (bootloader serial noise), and forwards each valid line as GET /process/?uid=... to Django, retrying transient HTTP failures with exponential backoff and dropping a line after five attempts rfid_project/rfid_serial_bridge.py:21-29; rfid_project/rfid_serial_bridge.py:32-56.
5. Django handler. attendance.views.process reads uid, runs preprocess_uid, and returns HTTP 400 on an invalid UID. preprocess_uid strips hyphens, keeps the rightmost 16 hex chars, enforces a 1-to-16 hex-char pattern, pads an odd length with a leading zero, parses base-16, and caps the result at 999999999999 rfid_project/attendance/views.py:982-987; rfid_project/attendance/uid_utils.py:4-23.
6. Attendance update. For a known Student, attend() closes the open Log (setting time_out, returning logout) or opens a new Log (returning auth). For an unknown card, process() creates a new Student and returns registered successfully rfid_project/attendance/views.py:1008-1019; rfid_project/attendance/views.py:1022-1033.
7. Storage and UI. Records land in SQLite, and the server-rendered Bootstrap 4 frontend lists presence and drives AJAX refreshes (see C4 and C5) README.md:3-7.

Schema summary rfid_project/attendance/models.py:5-30:

- Student: card_id (BigIntegerField) plus blank/nullable profile fields name, dob, sex, email, and address; __str__ shows the name, or the card id when the name is empty.
- Log: one row per scan with ida (the Student id), card_id, name, date (DateField, indexed), time_in (TimeField), a nullable time_out (TimeField), and status (Text). A null time_out marks a person as still present.

## C3. Divera alarm-kiosk mission

The same single Pi that captures attendance also drives the kiosk display, where a second mission runs: an alarm dashboard for the fire station. An optional switcher daemon `rfid_project/divera_kiosk.py` polls the Divera247 API and controls which Chromium tab is visible through the Chrome DevTools Protocol (CDP). The module docstring states the full state machine and the upstream API contract `rfid_project/divera_kiosk.py:1-22`.

- **Local alarm page at `GET /alarm/`.** Django renders the alarm dashboard itself instead of embedding the external Divera site. The route is registered at `rfid_project/attendance/urls.py:32-33` and served by the `alarm` view `rfid_project/attendance/views.py:1145`. The endpoint is deliberately unauthenticated (no login cookie) and is API-key-driven: the view reads the Divera key from the environment, falling back to a Django setting `rfid_project/attendance/views.py:1147-1149`. When the key is missing or the upstream call fails it still returns HTTP 200 and renders an idle/error state instead of erroring out `rfid_project/attendance/views.py:1150-1157`.
- **Local URL is the default, external is the override.** The switcher's `DEFAULTS` point `divera_page_url` at the local dashboard `http://127.0.0.1:8000/alarm/` `rfid_project/divera_kiosk.py:35-43`. The `DIVERA_PAGE_URL` environment value overrides it, for example back to the external Divera site `rfid_project/divera_kiosk.py:63-64`. The env template records both the local default and the external override, and holds placeholder keys only `rfid_project/deployment/divera_kiosk.env.template:7-16`.
- **Timing: 15 s poll, 1200 s visible window.** The daemon polls every 15 seconds and keeps the alarm tab visible for 1200 seconds (20 minutes) after the first alarm; a newer alarm id extends the window `rfid_project/divera_kiosk.py:41-42; rfid_project/divera_kiosk.py:230-284`. Both values are configurable via `POLL_SECONDS` and `ALARM_VISIBLE_SECONDS` `rfid_project/deployment/divera_kiosk.env.template:19-20`.
- **Tab switching over CDP on port 9222.** Chromium starts with `--remote-debugging-port=9222` `rfid_project/deployment/kiosk-browser.sh:12`, and the switcher reaches it at `http://127.0.0.1:9222` `rfid_project/divera_kiosk.py:39`. While an alarm is active it opens or activates the dashboard tab; once the window expires it closes that tab and brings the attendance tab back to the front `rfid_project/divera_kiosk.py:241-284`.
- **Idle wording.** With no active alarm the dashboard shows an idle screen; its wording is "Kein aktiver Alarm". The `get_alarm_display` helper builds the idle and active display context `rfid_project/attendance/views.py:238-316`.

## C4. Decision inventory

| decision | where | stated-or-inferred | rationale/consequence |
| --- | --- | --- | --- |
| UID wire format: raw hyphenated hex streamed over USB-serial; host preprocess_uid mirrors the legacy firmware (regex ^[0-9A-Fa-f]{1,16}$, rightmost-16 truncation, cap 999999999999) | RFID_NodeMCU/RFID_NodeMCU.yaml:1-4; rfid_project/attendance/uid_utils.py:4-23 | stated | One canonical hex-to-decimal path on the host keeps DB records identical to the pre-migration firmware output |
| TX-only UART0-TX (GPIO1) at 115200 with logger moved to UART1; NeoPixel stays on RX/GPIO3 | RFID_NodeMCU/RFID_NodeMCU.yaml:28-37; RFID_NodeMCU/RFID_NodeMCU.yaml:70-79 | stated | One-way ESP-to-Pi stream avoids the physical RX/GPIO3 pin conflict with the WS2812 LED; the UART1 logger keeps the UID stream clean |
| Bridge skips non-hex serial noise, retries HTTP with exponential backoff, drops after 5 attempts; Django returns 400 on invalid uid | rfid_project/rfid_serial_bridge.py:21-29; rfid_project/rfid_serial_bridge.py:32-56; rfid_project/attendance/views.py:982-987 | stated | Bootloader garbage never reaches the API; bounded retry covers a brief server restart without wedging the bridge; invalid input is a client error, never a 500 |
| Student.card_id is BigIntegerField with blank/nullable profile fields | rfid_project/attendance/models.py:5-11 | stated | Card IDs exceed 32-bit range after hex-to-decimal conversion; blank profiles let a card register before profile data exists |
| Log stores one row per scan with time_in and nullable time_out | rfid_project/attendance/models.py:20-27; rfid_project/attendance/views.py:1022-1033 | stated | Per-scan records give the attendance list its present/absent state; a null time_out means the person is still present |
| Function-based views with module globals stat/selected | rfid_project/attendance/views.py:931-1055; AGENTS.md:46-48 | stated | Original Django 2.2 style kept for consistency; AGENTS.md documents the globals convention (note: current views.py no longer defines stat; selected survives as a local in the alarm helper) |
| Obfuscated admin-ish URL paths kept stable | rfid_project/attendance/urls.py:23-25; AGENTS.md:52-56 | stated | Unpredictable paths hide admin-like pages; changing them would break templates and the device flow |
| Django built-in LoginView/LogoutView with LOGIN_REDIRECT_URL=/ | rfid_project/rfid_project/settings.py:79-80; AGENTS.md:58-60 | stated | Standard auth keeps the kiosk login-free while protecting management pages; redirect settings live in settings.py (note: current rfid_project/urls.py no longer wires LoginView/LogoutView) |
| Server-rendered Bootstrap 4 templates with AJAX polling | rfid_project/attendance/templates/attendance/basic.html:8-11; rfid_project/attendance/templates/attendance/basic.html:43-45; rfid_project/attendance/templates/attendance/index.html:75-79; rfid_project/attendance/templates/attendance/alarm.html:279-298 | stated | SSR keeps the kiosk simple; AJAX refreshes the present list and alarm state without full page reloads |
| ESPHome PN532 NFC reader over I2C; no Wi-Fi or HTTP on the device | RFID_NodeMCU/RFID_NodeMCU.yaml:1-4; RFID_NodeMCU/RFID_NodeMCU.yaml:39-57; README.md:3-7 | stated | All data flows over the local USB-serial link; the device never joins a network |
| SQLite database with DEBUG=True | rfid_project/rfid_project/settings.py:26; rfid_project/rfid_project/settings.py:85-91; AGENTS.md:71-72 | stated | Single-file DB fits a one-Pi deployment; DEBUG stays on for local operation |
| systemd trio (rfid-server, rfid-serial-bridge, divera-kiosk) plus udev /dev/ttyRFID symlink | install-rpi.sh:28-45; install-rpi.sh:56-61; install-rpi.sh:143-147; rfid_project/deployment/rfid-serial-bridge.service:3-5; rfid_project/deployment/99-rfid.rules:6-7 | stated | Services auto-start in order; the stable symlink survives USB re-enumeration |
| GET /alarm/ is unauthenticated and API-key-driven | rfid_project/attendance/views.py:1145-1161; rfid_project/attendance/urls.py:33 | stated | The kiosk has no login cookie; the Divera access key from the environment gates the upstream API call |
| Kiosk defaults to the local alarm URL with an external override | rfid_project/divera_kiosk.py:35-43; rfid_project/divera_kiosk.py:58-72; README.md:68-71 | stated | The local dashboard is the default; the page URL can be overridden to point at the external Divera site instead |
| Kiosk state machine polls every 15s and keeps the alarm tab visible for 1200s | rfid_project/divera_kiosk.py:41-42; rfid_project/divera_kiosk.py:230-284 | stated | A 15s poll catches new alarms quickly; the 1200s window keeps the alarm readable before returning home |

## C5. Ops and deployment reality

This section records how the project is run and deployed. It names configuration template paths only; live values (the Divera access key, VPN or external addresses) are deliberately left out.

**Runtime and dependencies.**
- A virtualenv lives inside `rfid_project/`: create it with `python3 -m venv .` and activate `bin/activate` `install-rpi.sh:17-19`.
- Dependencies install from `rfid_project/requirements.txt` `install-rpi.sh:20`.
- Migrations run with `python3 manage.py makemigrations` then `python3 manage.py migrate` `install-rpi.sh:21-22`.
- The server runs with `python3 manage.py runserver`, and the test suite runs with `python3 manage.py test` `install-rpi.sh:23`.

**The systemd trio.** Three units run the system on the Pi:
1. `rfid-server.service` runs the Django server; its unit is written by the install script `install-rpi.sh:28-43`.
2. `rfid-serial-bridge.service` reads `/dev/ttyRFID` and forwards UIDs to Django. It is declared `After=rfid-server.service` and `Restart=always`, so it recovers from crashes `rfid_project/deployment/rfid-serial-bridge.service:1-16`.
3. `divera-kiosk.service` runs the alarm switcher and loads its configuration through a systemd `EnvironmentFile=` `rfid_project/deployment/divera-kiosk.service:1-16`. The file it points at is created from the template and is not committed.

**Stable device name (udev).** A udev rule maps the USB-serial adapter to the stable symlink `/dev/ttyRFID`, covering CH340/CH341 (`1a86:7523`) and CP210x (`10c4:ea60`) chips `rfid_project/deployment/99-rfid.rules:1-7; install-rpi.sh:47-61`.

**Kiosk browser.** Chromium runs in kiosk mode under Wayland with `--kiosk` and `--remote-debugging-port=9222`, pointed at the local attendance app `rfid_project/deployment/kiosk-browser.sh:12`. The switcher from C3 then drives this browser over CDP. The install script wires the browser into the labwc autostart `install-rpi.sh:63-79; install-rpi.sh:109-147`.

**Pi deploy flow, in words.** On a fresh Raspberry Pi OS Lite: clone the repository into the `pi` home, create the virtualenv inside `rfid_project/`, install `requirements.txt`, run the migrations, and start the server. Copy the systemd units into `/etc/systemd/system/` and the udev rule into `/etc/udev/rules.d/`, then reload udev and systemd and enable the services. Create the live environment file from `rfid_project/deployment/divera_kiosk.env.template` and put the real Divera key there, where it stays out of version control. Finally start the kiosk browser so Chromium exposes the debugging port, and enable the alarm switcher. The reference sequence is `install-rpi.sh:1-147`, and the bridge setup steps are also summarized in `README.md:51-67`.

## C6. Maintenance and update rule

`docs/VISION_AND_DECISIONS.md` is the single canonical home for this project's higher goal, concept, and decisions. Keep it that way; never spawn additional decision documents.

Update-in-place rule: whenever a decision changes, edit this file directly. Re-tag the affected inventory rows above as `stated` or `inferred`, and keep the README link back to this document current. One file, one source of truth.

Prior art lives under `.omo/drafts/` (design drafts such as `.omo/drafts/rfid-serial-migration.md`, `.omo/drafts/divera-local-dashboard.md`, and `.omo/drafts/project-vision-decisions-doc.md`) and `.omo/plans/` (`.omo/plans/project-vision-decisions-doc.md`). Read them for context; this file is the authoritative snapshot.

## Kurzfassung (DE)

Presency-Kurzfassung: ein Pi, zwei Aufgaben, Anwesenheit per RFID und ein Alarm-Dashboard für die Feuerwehr.

1. Anwesenheit per RFID: Karten werden mit einem ESP8266/ESP32 (PN532 per I2C, ESPHome) gelesen.
   Die UID läuft über USB-Serial (`/dev/ttyRFID`) zur Serial-Bridge und als HTTP GET
   `/process/?uid=...` an Django, das die Anwesenheiten in SQLite speichert.
2. Alarm-Dashboard: Das lokale Kiosk-Dashboard unter `GET /alarm/` zeigt aktive Einsätze; der
   Kiosk wechselt per CDP zu dieser Ansicht, sobald ein Alarm ansteht.

Beide Aufgaben sind gleichgewichtet. Dieses Dokument enthält keine Zugangsdaten und wird bei
jeder Änderung direkt aktualisiert. Weitere Details stehen im englischen Teil oben.