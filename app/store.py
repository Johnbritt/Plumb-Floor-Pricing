"""SQLite storage. One file, no server to run."""
import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get("PLUMB_DB", os.path.join(os.path.dirname(__file__), "..", "var", "plumb.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
  cell_id TEXT NOT NULL, date TEXT NOT NULL, requests REAL NOT NULL, floor REAL NOT NULL, rpm REAL NOT NULL,
  PRIMARY KEY (cell_id, date));
CREATE TABLE IF NOT EXISTS notes (
  cell_id TEXT NOT NULL, date TEXT NOT NULL, text TEXT NOT NULL, UNIQUE (cell_id, date, text));
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cell_id TEXT NOT NULL, as_of TEXT NOT NULL, ts TEXT NOT NULL,
  actor TEXT NOT NULL, action TEXT NOT NULL, current_floor REAL NOT NULL, rec_floor REAL, refused INTEGER NOT NULL,
  reason TEXT, final_floor REAL NOT NULL, comment TEXT, snapshot TEXT);
CREATE INDEX IF NOT EXISTS ix_dec ON decisions (as_of, cell_id, id);
CREATE TABLE IF NOT EXISTS plans (
  cell_id TEXT NOT NULL, as_of TEXT NOT NULL, key TEXT NOT NULL, plan TEXT NOT NULL, PRIMARY KEY (cell_id, as_of, key));
"""


def connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


@contextmanager
def db():
    with _lock:
        c = connect()
        try:
            c.executescript(SCHEMA)
            yield c
            c.commit()
        finally:
            c.close()
