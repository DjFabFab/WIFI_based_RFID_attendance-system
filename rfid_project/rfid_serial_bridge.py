import argparse
import logging
import re
import sys
import time
import serial
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_backoff_delay(attempt):
    """Calculate exponential backoff delay."""
    return min(2 ** (attempt - 1), 30)

def main():
    parser = argparse.ArgumentParser(description="TX-only serial to HTTP bridge")
    parser.add_argument("--port", default="/dev/ttyRFID", help="Serial port")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--api", default="http://127.0.0.1:8000/process/", help="Django API endpoint")
    args = parser.parse_args()

    serial_attempt = 0
    
    while True:
        try:
            logger.info(f"Attempting to connect to {args.port} at {args.baud} baud...")
            ser = serial.Serial(args.port, args.baud, timeout=1)
            serial_attempt = 0
            logger.info(f"Connected to {args.port}")
            
            while True:
                try:
                    raw = ser.readline()
                    if not raw:
                        continue
                    
                    line = raw.decode('utf-8', errors='ignore').strip()
                    if not line:
                        continue
                    
                    if not re.fullmatch(r'[0-9A-Fa-f-]+', line):
                        logger.info(f"Skipping non-hex noise: {line}")
                        continue
                    # The ESP8266 streams dashed UIDs (e.g. "12-34-56-78"); strip dashes
                    # before forwarding so the URL carries clean hex. Django's
                    # preprocess_uid also tolerates dashes, but clean hex is safer.
                    line = line.replace('-', '')
                    
                    # Forward to API
                    http_attempt = 0
                    while True:
                        try:
                            response = requests.get(f"{args.api}?uid={line}", timeout=5)
                            response.raise_for_status()
                            logger.info(f"Successfully forwarded UID: {line}")
                            break
                        except requests.exceptions.RequestException as e:
                            http_attempt += 1
                            delay = get_backoff_delay(http_attempt)
                            logger.error(f"HTTP request failed: {e}. Retrying in {delay}s...")
                            time.sleep(delay)
                            
                except serial.SerialException as e:
                    logger.error(f"Serial read error: {e}")
                    break # Break inner loop to reconnect
                    
        except serial.SerialException as e:
            serial_attempt += 1
            delay = get_backoff_delay(serial_attempt)
            logger.error(f"Failed to connect to serial port: {e}. Retrying in {delay}s...")
            time.sleep(delay)

if __name__ == '__main__':
    main()
