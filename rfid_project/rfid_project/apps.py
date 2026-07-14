from django.apps import AppConfig


class RfidProjectConfig(AppConfig):
    name = 'rfid_project'
    verbose_name = 'RFID Project'

    def ready(self):
        # Connect the SQLite WAL / busy_timeout signal handler.
        from . import db_signals  # noqa: F401
