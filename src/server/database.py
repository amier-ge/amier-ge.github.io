from contextlib import closing
import sqlite3


class Database:
    def __init__(self, path):
        self.path = path
        with closing(self.connect()) as conn, conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS totals (
                    key INTEGER PRIMARY KEY CHECK (key = 1), count INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO totals VALUES (1, 968);
                CREATE TABLE IF NOT EXISTS visits (tab TEXT PRIMARY KEY, day TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (
                    kind TEXT NOT NULL, number INTEGER NOT NULL, lang TEXT NOT NULL,
                    draft TEXT, published TEXT, revision INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (kind, number, lang)
                );
                CREATE TABLE IF NOT EXISTS post_visibility (
                    number INTEGER PRIMARY KEY,
                    hidden INTEGER NOT NULL CHECK (hidden IN (0, 1)),
                    revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, expires INTEGER NOT NULL);
            """)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
