# WIFI_based_RFID_attendance-system_using_NodeMcu_and_Django

-> This attendance system is based on RFID technology for identification. The reader is an ESP8266/ESP32 running ESPHome (PN532 NFC reader over I2C) that streams the raw card UID over its local USB-serial port.

-> A host-side Python bridge (`rfid_project/rfid_serial_bridge.py`) reads that serial port (udev symlink `/dev/ttyRFID`) and forwards each UID to the Django backend. The server-side code is written using Django and the frontend is made using Bootstrap 4.

-> No Wi-Fi or HTTP is used on the device — all attendance data flows over the local USB connection to the Django server, which stores it in SQLite.

# Presency

Presency ist ein leichtgewichtiges Anwesenheitssystem, das RFID-Karten mit einem ESP8266/ESP32 (PN532 per I2C, geflasht via ESPHome) liest und die UID über die lokale USB-Seriell-Verbindung an einen Django-Server weiterleitet.

Kurz: ESP8266/ESP32 (ESPHome) -> USB-Serial (/dev/ttyRFID) -> `rfid_serial_bridge.py` -> HTTP GET /process/?uid=... -> Django speichert Anwesenheiten in SQLite.

# Technology Stack
SOFTWARE:
1) Django Framework
2) Bootstrap
3) Javascript-AJAX
4) HTML und CSS

HARDWARE:
1) ESP8266/ESP32 (mit ESPHome geflasht)
2) PN532 NFC-Reader (I2C)
3) LEDs und Buzzer

# SCREENSHOTS
1) Password Authentication :

![Screenshot (35)](https://user-images.githubusercontent.com/37211676/65944711-f413d300-e44f-11e9-896b-63ac29feae6a.png)

2) Attendance Homescreen :

![Screenshot (17)](https://user-images.githubusercontent.com/37211676/65944778-1b6aa000-e450-11e9-8bd7-ca5db54e3ac9.png)

3) Registered User Details :

![Screenshot (18)](https://user-images.githubusercontent.com/37211676/65944793-1efe2700-e450-11e9-8f7e-e8935ac15258.png)

4) All Users Management Screen :

![Screenshot (19)](https://user-images.githubusercontent.com/37211676/65944802-24f40800-e450-11e9-9bce-0ba0cbc9dd73.png)

5) Hardware Prototype

![WhatsApp Image 2019-08-11 at 9 41 42 PM (1)](https://user-images.githubusercontent.com/37211676/65944846-3b9a5f00-e450-11e9-8449-4b11fbc246ba.jpeg)

6) Final Hardware with PCB

![WhatsApp Image 2019-08-11 at 9 41 41 PM (3)](https://user-images.githubusercontent.com/37211676/65944862-4228d680-e450-11e9-849c-fb3f0b062e3f.jpeg)
## Serial Bridge (ESP8266 → Raspberry Pi)

To set up the serial bridge service:

1. Copy the service file:
   `sudo cp rfid_project/deployment/rfid-serial-bridge.service /etc/systemd/system/`
2. Enable and start the service:
   `sudo systemctl daemon-reload && sudo systemctl enable --now rfid-serial-bridge.service`

To set up the udev symlink:

1. Copy the udev rules:
   `sudo cp rfid_project/deployment/99-rfid.rules /etc/udev/rules.d/`
2. Reload rules and trigger:
   `sudo udevadm control --reload-rules && sudo udevadm trigger`

The service depends on `rfid-server.service` and will automatically restart on failure.

## Local Alarm Dashboard (Divera kiosk)

The optional Divera kiosk switcher (`rfid_project/divera_kiosk.py`, deployed via `rfid_project/deployment/divera-kiosk.service`) shows a local alarm dashboard instead of the external Divera site. Local alarm dashboard at `GET /alarm/` (API-key-driven, no login) — kiosk switches via CDP to `http://127.0.0.1:8000/alarm/` when active. The `DIVERA_PAGE_URL` in `rfid_project/deployment/divera_kiosk.env.template` defaults to `http://127.0.0.1:8000/alarm/`; override it to `https://www.divera247.com/` if you prefer the external Divera site. The optional `kiosk-browser.sh` handles the kiosk login note.
