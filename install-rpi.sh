# based on rpios lite
sed -i 's/bookworm/trixie/g' /etc/apt/sources.list
sed -i 's/bookworm/trixie/g' /etc/apt/sources.list.d/raspi.list

apt-get purge -y avahi-daemon man-db modemmanager pigpio bluez --autoremove
echo "deb [signed-by=/usr/share/keyrings/azlux-archive-keyring.gpg] http://packages.azlux.fr/debian/ trixie main" | sudo tee /etc/apt/sources.list.d/azlux.list
sudo wget -O /usr/share/keyrings/azlux-archive-keyring.gpg  https://azlux.fr/repo.gpg
sudo apt update
sudo apt install -y log2ram vim
vim /etc/log2ram.conf

apt install -y chromium rpd-wayland-core

sudo -i -u pi
git clone https://github.com/DjFabFab/WIFI_based_RFID_attendance-system.git
cd WIFI_based_RFID_attendance-system/rfid_project
apt install -y python3-venv
python3 -m venv .
source bin/activate
pip3 install -r requirements.txt
python3 manage.py makemigrations
python3 manage.py migrate
# python3 manage.py runserver 0.0.0.0:8000
# python3 manage.py changepassword root


# Create new systemd service file
cat << EOF | sudo tee /etc/systemd/system/rfid-server.service
[Unit]
Description=Run RFID Server
After=network.target

[Service]
Type=simple
ExecStart=/home/pi/WIFI_based_RFID_attendance-system/rfid_project/bin/python3 manage.py runserver 0.0.0.0:8000
WorkingDirectory=/home/pi/WIFI_based_RFID_attendance-system/rfid_project
User=pi
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now rfid-server.service

# RFID Serial Bridge (ESP8266/ESP32 USB-serial adapter -> Django /process/)
# Installs the systemd unit that reads /dev/ttyRFID and the udev rule that
# creates the stable /dev/ttyRFID symlink for the device's USB-serial chip
# (CH340/CH341 = 1a86:7523, CP210x = 10c4:ea60). If your adapter uses a
# different chip, edit the VID/PID in rfid_project/deployment/99-rfid.rules first.
RFID_DIR=/home/pi/WIFI_based_RFID_attendance-system/rfid_project
sudo cp "$RFID_DIR/deployment/rfid-serial-bridge.service" /etc/systemd/system/
sudo cp "$RFID_DIR/deployment/99-rfid.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo systemctl daemon-reload
sudo systemctl enable --now rfid-serial-bridge.service

# Control Display
# export XDG_RUNTIME_DIR=/run/user/1000
# export XDG_VTNR=1
# export XDG_SEAT=seat0
# export XDG_SESSION_TYPE=tty
# export XDG_SESSION_CLASS=user
# cage -- /usr/bin/chromium

labwc

# WAYLAND_DISPLAY=/run/user/1000/wayland-0 wlr-randr
# WAYLAND_DISPLAY=/run/user/1000/wayland-0 wlr-randr --output DSI-1 --transform 180
# WAYLAND_DISPLAY=/run/user/1000/wayland-0 wlopm --off DSI-1

cat << EOF | sudo tee /etc/udev/rules.d/95-rpi-ft5406.rules
KERNEL=="event[0-9]", SUBSYSTEM=="input", ENV{WL_OUTPUT}="DSI-1"
EOF

# ---------------------------------------------------------------------------
# Divera Kiosk Switcher (Presency) - alarm-aware kiosk tab switching
# ---------------------------------------------------------------------------
# The kiosk Chromium (launched by /usr/local/bin/kiosk-browser.sh with
# --remote-debugging-port=9222) normally shows the local Django attendance
# app. divera-kiosk.service runs rfid_project/divera_kiosk.py, which polls
# the Divera247 alarm API and switches the visible tab to the Divera
# dashboard (https://www.divera247.com/) while an alarm is active, keeps it
# visible for ALARM_VISIBLE_SECONDS (default 1200s = 20 min) after the
# initial alarm, then switches back to the Django app.
#
# 1. Put the real Divera247 access key into the env file (gitignored):
#    sudo cp "$RFID_DIR/deployment/divera_kiosk.env.template" "$RFID_DIR/deployment/divera_kiosk.env"
#    sudo nano "$RFID_DIR/deployment/divera_kiosk.env"   # set DIVERA_ACCESS_KEY=<your real key>
#
# 2. Start the kiosk browser. Add this line to ~/.config/labwc/autostart
#    (as the pi user) so Chromium starts with remote debugging enabled:
#      exec /usr/local/bin/kiosk-browser.sh &
#    Log into https://www.divera247.com/ once in that kiosk profile
#    (~/.config/presency-kiosk) so the dashboard shows member statuses.
#
# 3. Install the switcher launcher and service, then enable/start it:
RFID_DIR=/home/pi/WIFI_based_RFID_attendance-system/rfid_project
sudo cp "$RFID_DIR/deployment/divera-kiosk.service" /etc/systemd/system/
sudo cp "$RFID_DIR/deployment/kiosk-browser.sh" /usr/local/bin/
sudo chmod +x /usr/local/bin/kiosk-browser.sh
sudo systemctl daemon-reload
sudo systemctl enable --now divera-kiosk.service