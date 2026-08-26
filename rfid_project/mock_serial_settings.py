"""Throwaway Django settings for mock_serial_simulator.py.

Overrides the SQLite database path to a temporary file (from the
MOCK_SERIAL_DB environment variable) so the E2E simulator never touches
the real rfid_project/db.sqlite3.
"""
import os

from rfid_project.settings import *  # noqa: F401,F403

DATABASES["default"]["NAME"] = os.environ["MOCK_SERIAL_DB"]
