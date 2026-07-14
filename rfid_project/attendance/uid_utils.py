import re


def preprocess_uid(raw_uid: str) -> int:
    """Convert a raw RFID UID string (as streamed by the ESP8266) into an int.

    Mirrors the original ESP8266 C++ logic:
      1. strip '-' formatting chars
      2. keep rightmost 16 hex chars if longer
      3. reject anything that is not 1-16 hex chars
      4. pad odd length with a leading '0'
      5. parse as base-16
      6. cap at 999999999999
    """
    clean = raw_uid.replace('-', '')
    if len(clean) > 16:
        clean = clean[len(clean) - 16:]
    if not re.fullmatch(r'[0-9A-Fa-f]{1,16}', clean):
        raise ValueError('invalid uid')
    if len(clean) % 2 != 0:
        clean = '0' + clean
    value = int(clean, 16)
    return min(value, 999999999999)
