from django.db.backends.signals import connection_created

def set_sqlite_pragmas(sender, connection, **kwargs):
    """Enable WAL journaling and a 20s busy timeout on every new SQLite connection."""
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=20000;")


connection_created.connect(set_sqlite_pragmas)
