import argparse
import logging
import re
import sys
import time
import urllib.parse
import serial
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_backoff_delay(attempt):
    """Calculate exponential backoff delay."""
    return min(2 ** (attempt - 1), 30)


# A raw UID is 1-16 hex chars, optionally hyphen-separated (e.g. "74-10-37-94").
# Anything else on the serial line is bootloader/serial noise that must be
# skipped instead of forwarded (it would otherwise get a permanent 400).
UID_LINE_RE = re.compile(r"^[0-9A-Fa-f-]+$")

# Max HTTP attempts per line before it is dropped. Backoff (1+2+4+8+16s = 31s)
# covers a brief server restart; after that the line is discarded so the
# bridge never wedges on a persistently failing endpoint.
MAX_HTTP_ATTEMPTS = 5


def forward_uid(api_url, line, timeout=5, max_attempts=MAX_HTTP_ATTEMPTS):
    """Forward one UID line. True = API accepted it (2xx), False = dropped (4xx or retries exhausted)."""
    for attempt in range(1, max_attempts + 1):
        try:
            encoded = urllib.parse.quote(line)
            response = requests.get(f"{api_url}?uid={encoded}", timeout=timeout)
            if response.status_code < 400:
                logger.info(f"Successfully forwarded UID: {line}")
                return True
            if response.status_code < 500:
                logger.error(f"API rejected UID {line} with {response.status_code}; dropping line")
                return False
            reason = f"API error {response.status_code} for UID {line}"
        except requests.exceptions.RequestException as e:
            reason = f"HTTP request failed: {e}"
        if attempt < max_attempts:
            delay = get_backoff_delay(attempt)
            logger.error(f"{reason}. Retrying in {delay}s...")
            time.sleep(delay)
        else:
            logger.error(f"{reason}; dropping line after {max_attempts} attempts")
    return False


def auto_detect_port(port_arg):
    """
    Auto-detect the serial port.

    Priority order:
      1. Explicit --port argument (if provided)
      2. /dev/ttyUSB0
      3. /dev/ttyACM0
      4. /dev/ttyRFID (existing udev symlink)
      5. serial.tools.list_ports.comports() scan

    Returns the first matching port string, or the first port from the
    list-compass scan if none of the above matched.
    """
    if port_arg:
        return port_arg

    # Explicitly preferred defaults
    candidates = ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyRFID"]
    for candidate in candidates:
        try:
            import serial.tools.list_ports
            for port in serial.tools.list_ports.comports():
                if port.device == candidate:
                    return candidate
        except Exception:
            pass

    # Fallback: try the explicit candidates again (they may not exist yet)
    for candidate in candidates:
        try:
            ser = serial.Serial(candidate, 115200, timeout=1)
            ser.close()
            return candidate
        except serial.SerialException:
            pass

    # Final fallback: scan all ports
    try:
        import serial.tools.list_ports
        for port in serial.tools.list_ports.comports():
            return port.device
    except Exception:
        pass

    return None


def main():
    parser = argparse.ArgumentParser(description="Serial-to-HTTP bridge (raw pass-through)")
    parser.add_argument("--port", default=None, help="Serial port (auto-detect if not given)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--api", default="http://127.0.0.1:8000/process/", help="Django API endpoint")
    args = parser.parse_args()

    # Auto-detect the serial port if not explicitly provided
    port = args.port or auto_detect_port(None)
    if not port:
        logger.error("Could not detect a serial port. Please specify --port explicitly.")
        sys.exit(1)

    serial_attempt = 0

    while True:
        try:
            logger.info(f"Attempting to connect to {port} at {args.baud} baud...")
            ser = serial.Serial(port, args.baud, timeout=1)
            serial_attempt = 0
            logger.info(f"Connected to {port}")

            while True:
                try:
                    raw = ser.readline()
                    if not raw:
                        continue

                    line = raw.decode('utf-8', errors='ignore').strip()
                    if not line:
                        continue

                    # Skip serial noise that cannot be a UID (bootloader
                    # garbage etc.) -- forwarding it would only get a
                    # permanent 400 from Django.
                    if not UID_LINE_RE.match(line):
                        logger.debug("Skipping non-UID serial line: %r", line)
                        continue

                    forward_uid(args.api, line)

                except serial.SerialException as e:
                    logger.error(f"Serial read error: {e}")
                    break  # Break inner loop to reconnect

        except serial.SerialException as e:
            serial_attempt += 1
            delay = get_backoff_delay(serial_attempt)
            logger.error(f"Failed to connect to serial port: {e}. Retrying in {delay}s...")
            time.sleep(delay)


if __name__ == '__main__':
    main()
