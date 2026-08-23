"""Database layer.

Two backends, one set of SQL: Postgres in production (Neon, via DATABASE_URL)
and a plain SQLite file when DATABASE_URL is unset, so local development needs
no database server at all.

Everything is stored in types both engines agree on -- dates as YYYY-MM-DD
strings, timestamps as Unix seconds, clue lists as JSON text -- which keeps the
queries identical apart from the placeholder style.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from threading import Lock

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = REPO_ROOT / "data" / "puzzles.json"


def database_url() -> str:
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or ""
    ).strip()


def is_postgres() -> bool:
    return database_url().startswith(("postgres://", "postgresql://"))


def sqlite_path() -> str:
    return os.environ.get("SQLITE_PATH") or str(REPO_ROOT / "local.db")


class IntegrityError(Exception):
    """Raised for unique-constraint violations, whichever backend is in use."""


_lock = Lock()
_pg_connection = None


def _connect_postgres():
    import psycopg  # imported lazily so local dev doesn't need the driver

    global _pg_connection
    if _pg_connection is not None and not _pg_connection.closed:
        try:
            _pg_connection.execute("SELECT 1")
            return _pg_connection
        except Exception:
            try:
                _pg_connection.close()
            except Exception:
                pass
            _pg_connection = None

    _pg_connection = psycopg.connect(database_url(), autocommit=False)
    return _pg_connection


@contextmanager
def connection():
    """Yield a DB-API connection, committing on success and rolling back on error.

    Postgres connections are reused across invocations of the same warm
    serverless instance; SQLite opens a fresh handle each time.
    """
    if is_postgres():
        import psycopg

        with _lock:
            conn = _connect_postgres()
            try:
                yield conn
                conn.commit()
            except psycopg.IntegrityError as exc:
                conn.rollback()
                raise IntegrityError(str(exc)) from exc
            except Exception:
                conn.rollback()
                raise
    else:
        conn = sqlite3.connect(sqlite_path(), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise IntegrityError(str(exc)) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def sql(statement: str) -> str:
    """Translate the `?` placeholders used throughout this module."""
    return statement.replace("?", "%s") if is_postgres() else statement


def query(conn, statement: str, params: tuple = ()) -> list[dict]:
    cur = conn.execute(sql(statement), params)
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def query_one(conn, statement: str, params: tuple = ()) -> dict | None:
    rows = query(conn, statement, params)
    return rows[0] if rows else None


def execute(conn, statement: str, params: tuple = ()) -> None:
    conn.execute(sql(statement), params)


def insert(conn, statement: str, params: tuple = ()) -> int:
    """Run an INSERT and return the new row's id."""
    if is_postgres():
        cur = conn.execute(sql(statement) + " RETURNING id", params)
        return cur.fetchone()[0]
    cur = conn.execute(statement, params)
    return int(cur.lastrowid)


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #

SCHEMA_SQLITE = [
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS puzzles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        puzzle_date TEXT NOT NULL UNIQUE,
        solution TEXT NOT NULL,
        clues_across TEXT NOT NULL,
        clues_down TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        puzzle_id INTEGER NOT NULL REFERENCES puzzles(id),
        started_at INTEGER NOT NULL,
        solved_at INTEGER,
        elapsed_seconds INTEGER,
        UNIQUE (user_id, puzzle_id)
    )""",
]

SCHEMA_POSTGRES = [
    """CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS puzzles (
        id SERIAL PRIMARY KEY,
        puzzle_date TEXT NOT NULL UNIQUE,
        solution TEXT NOT NULL,
        clues_across TEXT NOT NULL,
        clues_down TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS attempts (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        puzzle_id INTEGER NOT NULL REFERENCES puzzles(id),
        started_at BIGINT NOT NULL,
        solved_at BIGINT,
        elapsed_seconds INTEGER,
        UNIQUE (user_id, puzzle_id)
    )""",
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_attempts_puzzle ON attempts (puzzle_id, elapsed_seconds)",
]

_schema_ready = False


def ensure_schema() -> None:
    """Create tables on first use, seeding puzzles if the table is empty.

    Runs at most once per process, so a warm instance pays nothing.
    """
    global _schema_ready
    if _schema_ready:
        return

    statements = SCHEMA_POSTGRES if is_postgres() else SCHEMA_SQLITE
    with connection() as conn:
        for statement in statements + INDEXES:
            conn.execute(statement)

    with connection() as conn:
        row = query_one(conn, "SELECT COUNT(*) AS n FROM puzzles")
        if (row or {}).get("n", 0) == 0:
            seed_from_file(conn)

    _schema_ready = True


def reset_schema_cache() -> None:
    """Used by the tests to rebuild between cases."""
    global _schema_ready
    _schema_ready = False


def seed_from_file(conn) -> int:
    if not SEED_FILE.exists():
        return 0

    with open(SEED_FILE, "r", encoding="utf-8") as handle:
        puzzles = json.load(handle)

    for entry in puzzles:
        upsert_puzzle(conn, entry)
    return len(puzzles)


# --------------------------------------------------------------------------- #
# puzzles
# --------------------------------------------------------------------------- #


def normalise_solution(rows) -> str:
    """Accept either five 5-letter rows or one 25-letter string."""
    text = rows if isinstance(rows, str) else "".join(rows)
    letters = "".join(ch for ch in text.lower() if ch.isalpha())
    if len(letters) != 25:
        raise ValueError(f"solution must be 25 letters, got {len(letters)}")
    return letters


def upsert_puzzle(conn, entry: dict) -> None:
    """Insert or replace the puzzle for a given date."""
    puzzle_date = entry["date"]
    if isinstance(puzzle_date, date):
        puzzle_date = puzzle_date.isoformat()
    date.fromisoformat(puzzle_date)  # validation

    solution = normalise_solution(entry.get("rows") or entry["solution"])
    across = list(entry["across"])
    down = list(entry["down"])
    if len(across) != 5 or len(down) != 5:
        raise ValueError("each puzzle needs exactly 5 across and 5 down clues")

    existing = query_one(
        conn, "SELECT id FROM puzzles WHERE puzzle_date = ?", (puzzle_date,)
    )
    if existing:
        execute(
            conn,
            "UPDATE puzzles SET solution = ?, clues_across = ?, clues_down = ? WHERE id = ?",
            (solution, json.dumps(across), json.dumps(down), existing["id"]),
        )
    else:
        insert(
            conn,
            "INSERT INTO puzzles (puzzle_date, solution, clues_across, clues_down)"
            " VALUES (?, ?, ?, ?)",
            (puzzle_date, solution, json.dumps(across), json.dumps(down)),
        )


def puzzle_for(conn, on_date: str) -> dict | None:
    """The puzzle for a date, or the most recent earlier one if there isn't one."""
    row = query_one(conn, "SELECT * FROM puzzles WHERE puzzle_date = ?", (on_date,))
    if row is None:
        row = query_one(
            conn,
            "SELECT * FROM puzzles WHERE puzzle_date <= ?"
            " ORDER BY puzzle_date DESC LIMIT 1",
            (on_date,),
        )
    if row is None:
        return None

    row["clues_across"] = json.loads(row["clues_across"])
    row["clues_down"] = json.loads(row["clues_down"])
    return row


def all_puzzle_dates(conn) -> list[str]:
    return [r["puzzle_date"] for r in query(conn, "SELECT puzzle_date FROM puzzles")]


# --------------------------------------------------------------------------- #
# users and attempts
# --------------------------------------------------------------------------- #


def now_ts() -> int:
    return int(time.time())


def create_user(conn, username: str, password_hash: str) -> int:
    return insert(
        conn,
        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, password_hash, now_ts()),
    )


def user_by_name(conn, username: str) -> dict | None:
    return query_one(conn, "SELECT * FROM users WHERE username = ?", (username,))


def user_by_id(conn, user_id: int) -> dict | None:
    return query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))


def attempt_for(conn, user_id: int, puzzle_id: int) -> dict | None:
    return query_one(
        conn,
        "SELECT * FROM attempts WHERE user_id = ? AND puzzle_id = ?",
        (user_id, puzzle_id),
    )


def start_attempt(conn, user_id: int, puzzle_id: int) -> dict:
    """Create the attempt if it's the first look at this puzzle."""
    attempt = attempt_for(conn, user_id, puzzle_id)
    if attempt is not None:
        return attempt

    try:
        insert(
            conn,
            "INSERT INTO attempts (user_id, puzzle_id, started_at) VALUES (?, ?, ?)",
            (user_id, puzzle_id, now_ts()),
        )
    except IntegrityError:
        pass  # another tab got there first

    return attempt_for(conn, user_id, puzzle_id)


def finish_attempt(conn, attempt_id: int, elapsed_seconds: int) -> None:
    execute(
        conn,
        "UPDATE attempts SET solved_at = ?, elapsed_seconds = ? WHERE id = ?",
        (now_ts(), elapsed_seconds, attempt_id),
    )


def leaderboard_for(conn, puzzle_id: int, limit: int = 10) -> list[dict]:
    return query(
        conn,
        "SELECT users.username AS username, attempts.elapsed_seconds AS seconds"
        " FROM attempts JOIN users ON users.id = attempts.user_id"
        " WHERE attempts.puzzle_id = ? AND attempts.solved_at IS NOT NULL"
        " ORDER BY attempts.elapsed_seconds ASC, attempts.solved_at ASC"
        f" LIMIT {int(limit)}",
        (puzzle_id,),
    )
