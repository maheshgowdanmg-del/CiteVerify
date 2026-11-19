"""SQLite storage: API cache, saved runs and the human-review audit trail."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from .config import DB_PATH


def _conn():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, ts TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, filename TEXT, created TEXT, payload TEXT)")
    con.execute(
        "CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, "
        "result_id TEXT, action TEXT, new_status TEXT, comment TEXT, ts TEXT)"
    )
    return con


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cache_get(key):
    with closing(_conn()) as con:
        row = con.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_set(key, value):
    with closing(_conn()) as con:
        con.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, json.dumps(value), now()))
        con.commit()


def save_run(run):
    with closing(_conn()) as con:
        con.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?)",
            (run["run_id"], run["filename"], run["created"], json.dumps(run)),
        )
        con.commit()


def list_runs():
    with closing(_conn()) as con:
        return con.execute("SELECT run_id, filename, created FROM runs ORDER BY created DESC").fetchall()


def load_run(run_id):
    with closing(_conn()) as con:
        row = con.execute("SELECT payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return json.loads(row[0]) if row else None


def add_review(run_id, result_id, action, new_status="", comment=""):
    with closing(_conn()) as con:
        con.execute(
            "INSERT INTO reviews (run_id, result_id, action, new_status, comment, ts) VALUES (?,?,?,?,?,?)",
            (run_id, result_id, action, new_status, comment, now()),
        )
        con.commit()


def get_reviews(run_id):
    with closing(_conn()) as con:
        rows = con.execute(
            "SELECT result_id, action, new_status, comment, ts FROM reviews WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
    return [dict(result_id=r[0], action=r[1], new_status=r[2], comment=r[3], ts=r[4]) for r in rows]
