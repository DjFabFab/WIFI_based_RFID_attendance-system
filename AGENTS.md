<!--
Concise, project-specific guidance for AI coding assistants working on
WIFI_based_RFID_attendance-system_using_NodeMcu_and_Django.
Keep suggestions concrete and reference files below.
-->

# Copilot / AI-assistant instructions (short)

This repository is a small Django-backed RFID attendance system with an
ESPHome firmware (YAML) for the hardware reader. Use these notes to be
productive quickly.

- Big picture
  - Backend: Django app located in `rfid_project/` with the core app
    `attendance/` (models: `Student`, `Log`; views in
    `attendance/views.py`; templates in `attendance/templates/attendance/`).
  - Frontend: server-rendered Django templates + Bootstrap 4 and a few
    AJAX endpoints (see `attendance/process/` path handled by
    `attendance.views.process`).
  - Device: ESP8266/ESP32 firmware is configured via ESPHome YAML at
    `RFID_NodeMCU/RFID_NodeMCU.yaml` (PN532 NFC reader over I2C). The device
    streams the raw, hyphenated RFID UID over its USB-serial adapter
    (local `ttyUSB0` → udev symlink `/dev/ttyRFID`). The host-side
    `rfid_project/rfid_serial_bridge.py` reads that port and forwards each UID
    to the Django `/process/?uid=...` endpoint. No Wi‑Fi/HTTP on the device.
  - Deployment: The repo includes `install-rpi.sh` that shows the
    intended Raspberry Pi setup and creates a systemd service
    (`/etc/systemd/system/rfid-server.service`) that runs
    `manage.py runserver` from the virtualenv at
    `/home/pi/.../rfid_project/bin/python3`.

- Developer workflows & commands
  - Create/activate venv (project uses a venv in `rfid_project/`):
    - python3 -m venv rfid_project
    - source rfid_project/bin/activate
    - pip install -r rfid_project/requirements.txt
  - Database migrations and local server (from `rfid_project/`):
    - python3 manage.py makemigrations
    - python3 manage.py migrate
    - python3 manage.py runserver 0.0.0.0:8000
  - The install script `install-rpi.sh` shows how the systemd service is
    defined and the display configuration for a Raspberry Pi Wayland
    kiosk environment. Use it as a reference, not as a blind installer.

- Project-specific patterns & conventions
  - Views: Many views are function-based and use global module state
    (see `attendance/views.py` — globals: `stat`, `selected`). Be careful
    when refactoring concurrency or request-scope logic.
  - Models: `Student` uses `card_id` (IntegerField) and may have blank
    profiles; `Log` stores per-scan records. `attendance/functions.py`
    contains helper `add_user()` that assumes a contiguous max `card_id`.
  - URLs: There are both readable paths and intentionally obfuscated
    endpoints used by templates (see `attendance/urls.py` where some
    admin-like pages live under unpredictable paths). Prefer editing
    URLs carefully — changing them affects the NodeMCU/device and
    templates.
  - Templates: Look in `attendance/templates/attendance/` for the UI.
    Authentication uses Django's built‑in LoginView/LogoutView in
    `rfid_project/urls.py` and redirect settings are set in
    `rfid_project/settings.py` (`LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL`).

- Integration & external dependencies
  - The NodeMCU posts card IDs to `/process/` (see `attendance.process`).
  - The repo includes `requirements.txt` inside `rfid_project/` — install
    from that file for a reproducible dev environment.
  - `install-rpi.sh` documents additional OS-level dependencies (Wayland
    utilities, gamescope) and demonstrates how the server is run as a
    systemd service on a Pi user `pi` — use it for packaging hints.

- Safety checks & quick debugging tips
  - The project runs with DEBUG=True and SQLite; keep that in mind when
    debugging auth/template issues locally.
  - Many view functions iterate over QuerySets in Python (not filtered)
    — watch for O(n) loops when the dataset grows. Prefer `filter()` or
    indexed lookups by `card_id`/`id` when adding features.
  - Tests: there are skeleton `tests.py` files. Run `python manage.py test`
    from `rfid_project/` to run tests; add focused unit tests around
    `attendance.functions` and `attendance.views.process` when changing
    device-protocol behaviour.

- Examples to reference while coding
  - Device -> server: the ESPHome firmware (`RFID_NodeMCU/RFID_NodeMCU.yaml`)
    streams the raw UID over USB serial; `rfid_project/rfid_serial_bridge.py`
    forwards it as `GET /process/?uid=<hex>`; server handler:
    `attendance/views.process` -> `preprocess_uid` -> `attend()`.
  - DB schema: `attendance/models.py` (`Student`, `Log`).
  - Deployment hint: `install-rpi.sh` (systemd unit and venv path).

- Device protocol example (concrete)
  - The ESPHome firmware streams the raw UID (hyphen-separated hex, e.g.
    `74-10-37-94` for a 4-byte MIFARE tag) over USB serial. The
    `rfid_serial_bridge` strips the hyphens and forwards it as
    `GET /process/?uid=74103794`. The Django handler `attendance.views.process`
    reads `uid` (raw) and runs `preprocess_uid`.
  - Example request (URL-encoded GET):

    GET /process/?uid=74103794 HTTP/1.1

  - Server-side handler: `attendance/views.process` reads `uid` (raw) and runs `preprocess_uid`; a legacy `card_id` parameter is also accepted.
    It will:
    - If `card_id` matches an existing `Student.card_id` -> call `attend(user)` and return one of:
      - `auth` — new Log entry created (time_in)
      - `logout` — time_out updated on existing Log
      - `time out already saved` or `profile saved` depending on state
    - If `card_id` is unknown -> create a new `Student(card_id=...)` and return `registered successfully`.

  - When you modify protocol behavior, update `RFID_NodeMCU/RFID_NodeMCU.yaml`
    (device side) and `rfid_project/rfid_serial_bridge.py` /
    `attendance/uid_utils.py` (host side) accordingly.

If anything above is unclear or you want more details (for example a
short diagram of request flows or tests to add), tell me which part and
I'll expand this file.
