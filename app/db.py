# SQLite storage. Raw API responses are kept per day so metrics can be re-extracted later without new calls.
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw (
  source TEXT NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL,
  fetched_at TEXT NOT NULL, json TEXT NOT NULL,
  PRIMARY KEY (source, kind, day)
);
CREATE TABLE IF NOT EXISTS metrics (
  day TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY (day, metric)
);
CREATE TABLE IF NOT EXISTS activities (
  id TEXT PRIMARY KEY, day TEXT NOT NULL, start_time TEXT, type TEXT, name TEXT,
  duration_s REAL, distance_m REAL, avg_hr REAL, max_hr REAL, kcal REAL,
  training_load REAL, aerobic_te REAL, anaerobic_te REAL, json TEXT
);
CREATE INDEX IF NOT EXISTS activities_day ON activities(day);
CREATE TABLE IF NOT EXISTS sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, exercise TEXT NOT NULL,
  set_no INTEGER NOT NULL, weight_kg REAL, reps INTEGER, source_file TEXT,
  UNIQUE (day, exercise, set_no)
);
CREATE TABLE IF NOT EXISTS imports (
  sha TEXT PRIMARY KEY, file TEXT NOT NULL, kind TEXT, rows INTEGER, imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, started TEXT NOT NULL,
  finished TEXT, status TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workouts (
  id TEXT PRIMARY KEY, day TEXT NOT NULL, start_ts INTEGER, end_ts INTEGER, duration_s REAL,
  volume_kg REAL, exercises INTEGER, source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS workouts_day ON workouts(day);
"""

# Columns added after the first version: (table, column, type).
COLUMNS = [
    ('sets', 'eid', 'TEXT'), ('sets', 'session', 'TEXT'), ('sets', 'log_ts', 'INTEGER'), ('sets', 'source', 'TEXT'),
]

_lock = threading.Lock()


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con


def init():
    with connect() as con:
        con.executescript(SCHEMA)
        for table, col, typ in COLUMNS:
            if col not in {r['name'] for r in con.execute(f'PRAGMA table_info({table})')}:
                con.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')


@contextmanager
def tx():
    # One writer at a time: sync jobs and imports run in background threads.
    with _lock:
        con = connect()
        try:
            yield con
            con.commit()
        finally:
            con.close()


def now():
    return datetime.now().isoformat(timespec='seconds')


def put_raw(con, source, kind, day, data):
    con.execute('INSERT OR REPLACE INTO raw VALUES (?,?,?,?,?)', (source, kind, day, now(), json.dumps(data)))


def has_raw(con, source, kind, day):
    return con.execute('SELECT 1 FROM raw WHERE source=? AND kind=? AND day=?', (source, kind, day)).fetchone() is not None


def put_metric(con, day, metric, value, source):
    if value is None:
        return
    try:
        value = float(value)
    except (TypeError, ValueError):
        return
    con.execute('INSERT OR REPLACE INTO metrics VALUES (?,?,?,?)', (day, metric, value, source))


def kv_get(key, default=None):
    with connect() as con:
        row = con.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    return json.loads(row['value']) if row else default


def kv_set(key, value):
    with tx() as con:
        con.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', (key, json.dumps(value)))


def log_start(source):
    with tx() as con:
        cur = con.execute('INSERT INTO sync_log (source, started, status) VALUES (?,?,?)', (source, now(), 'running'))
        return cur.lastrowid


def log_end(log_id, status, message=''):
    with tx() as con:
        con.execute('UPDATE sync_log SET finished=?, status=?, message=? WHERE id=?', (now(), status, message[:2000], log_id))
