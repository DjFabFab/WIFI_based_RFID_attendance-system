#!/usr/bin/env python3
"""Automated end-to-end integration test for the RFID serial bridge.

Spawns Django runserver + rfid_serial_bridge against a virtual serial port
(pty), simulates an ESP8266 writing a raw UID, and asserts the corresponding
Student/Log row is created in the database. No physical hardware required.

Uses a throwaway SQLite database (mock_serial_settings) so the tracked
rfid_project/db.sqlite3 is never touched.
"""
import os
import shutil
import sys
import tempfile
import time
import socket
import subprocess
import pty

# Point Django at a temporary DB before anything imports the real settings.
TMP_DB_DIR = tempfile.mkdtemp(prefix="rfid-mock-db-")
TMP_DB = os.path.join(TMP_DB_DIR, "db.sqlite3")
os.environ["MOCK_SERIAL_DB"] = TMP_DB
os.environ["DJANGO_SETTINGS_MODULE"] = "mock_serial_settings"

import django  # noqa: E402
django.setup()

from attendance.models import Student, Log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
VENV_PYTHON = os.path.join(PROJECT_ROOT, "rfid_project", "bin", "python3")
TEST_PORT = 8731
API_URL = "http://127.0.0.1:%d/process/" % TEST_PORT
CARD_ID = 305419896  # preprocess_uid("12-34-56-78")
RAW_UID = b"12-34-56-78\n"

procs = []


def cleanup():
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    shutil.rmtree(TMP_DB_DIR, ignore_errors=True)


def wait_for_port(host, port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def migrate():
    """Create the schema in the throwaway DB."""
    subprocess.run(
        [VENV_PYTHON, "manage.py", "migrate", "--noinput"],
        cwd=os.path.join(PROJECT_ROOT, "rfid_project"),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=True,
    )


def main():
    passed = True
    master_fd = None
    slave_fd = None
    try:
        migrate()

        master_fd, slave_fd = pty.openpty()
        slave_name = os.ttyname(slave_fd)

        runserver = subprocess.Popen(
            [VENV_PYTHON, "manage.py", "runserver", "127.0.0.1:%d" % TEST_PORT, "--noreload"],
            cwd=os.path.join(PROJECT_ROOT, "rfid_project"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(runserver)
        if not wait_for_port("127.0.0.1", TEST_PORT, timeout=30):
            print("FAIL: runserver did not start")
            passed = False
            return

        bridge = subprocess.Popen(
            [VENV_PYTHON, os.path.join(PROJECT_ROOT, "rfid_project", "rfid_serial_bridge.py"),
             "--api", API_URL, "--port", slave_name],
            cwd=os.path.join(PROJECT_ROOT, "rfid_project"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(bridge)
        time.sleep(2)

        os.write(master_fd, RAW_UID)
        time.sleep(2)

        if not Student.objects.filter(card_id=CARD_ID).exists():
            print("FAIL: Student not created from simulated UID")
            passed = False
        else:
            print("PASS: Student created from simulated UID")

        Student.objects.filter(card_id=CARD_ID).update(name="Sim User")
        os.write(master_fd, RAW_UID)
        time.sleep(2)
        if not Log.objects.filter(card_id=CARD_ID).exists():
            print("FAIL: Log not created from simulated UID")
            passed = False
        else:
            print("PASS: Log created from simulated UID")

    finally:
        cleanup()
        for fd in (master_fd, slave_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass

    if passed:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
