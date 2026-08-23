"""Daily 5x5 crossword API.

Deployed on Vercel as a single Python function mounted at /api/*, alongside the
static React build. Everything the browser needs is under /api, so one rewrite
rule covers the whole API.

Design notes:
  * The solution never leaves the server. The browser posts a filled grid and
    is told only whether it matches.
  * Solve times are measured server-side, between /api/puzzle/start and
    /api/puzzle/submit, so a doctored clock in the browser doesn't help.
  * Sessions are stateless signed tokens; there is no user id in any URL.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

# The shared code lives in crossword/ rather than in this directory, because
# every .py file under api/ would otherwise be deployed as its own function.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crossword import db  # noqa: E402
from crossword.auth import (  # noqa: E402
    hash_password,
    make_token,
    normalise_username,
    read_token,
    validate_credentials,
    verify_password,
)

MAX_ELAPSED_SECONDS = 60 * 60 * 6
LEADERBOARD_SIZE = 10

app = Flask(__name__)


def puzzle_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("PUZZLE_TZ", "Europe/London"))
    except Exception:  # pragma: no cover - bad env value shouldn't take the site down
        return ZoneInfo("UTC")


def today() -> str:
    return datetime.now(puzzle_timezone()).date().isoformat()


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def with_user(view):
    """Resolve the signed token into a user row, or 401."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        user_id = read_token(bearer_token())
        if user_id is None:
            return error("Not signed in", 401)

        db.ensure_schema()
        with db.connection() as conn:
            user = db.user_by_id(conn, user_id)
            if user is None:
                return error("Not signed in", 401)
            return view(conn, user, *args, **kwargs)

    return wrapper


def normalise_grid(raw) -> str | None:
    if isinstance(raw, list):
        raw = "".join("".join(row) if isinstance(row, list) else str(row) for row in raw)
    if not isinstance(raw, str):
        return None
    letters = "".join(ch for ch in raw.lower() if ch.isalpha())
    return letters if len(letters) == 25 else None


def elapsed_since(started_at: int) -> int:
    return max(0, db.now_ts() - int(started_at))


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #


@app.post("/api/auth/signup")
def signup():
    body = request.get_json(silent=True) or {}
    username = normalise_username(body.get("username", ""))
    password = body.get("password", "")

    problem = validate_credentials(username, password)
    if problem:
        return error(problem)

    db.ensure_schema()
    with db.connection() as conn:
        if db.user_by_name(conn, username):
            return error("That username is already taken", 409)
        try:
            user_id = db.create_user(conn, username, hash_password(password))
        except db.IntegrityError:
            return error("That username is already taken", 409)

    return jsonify({"token": make_token(user_id), "username": username}), 201


@app.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    username = normalise_username(body.get("username", ""))
    password = body.get("password", "")

    db.ensure_schema()
    with db.connection() as conn:
        user = db.user_by_name(conn, username)

    # Deliberately vague: don't reveal which half was wrong.
    if user is None or not verify_password(user["password_hash"], password):
        return error("Incorrect username or password", 401)

    return jsonify({"token": make_token(user["id"]), "username": user["username"]})


@app.get("/api/me")
@with_user
def me(conn, user):
    return jsonify({"username": user["username"]})


# --------------------------------------------------------------------------- #
# puzzle
# --------------------------------------------------------------------------- #


@app.get("/api/puzzle")
@with_user
def get_puzzle(conn, user):
    """Today's clues plus this user's progress. Never includes the solution."""
    puzzle = db.puzzle_for(conn, today())
    if puzzle is None:
        return error("No puzzle available yet", 404)

    attempt = db.attempt_for(conn, user["id"], puzzle["id"])
    solved = bool(attempt and attempt["solved_at"])

    payload = {
        "date": puzzle["puzzle_date"],
        "size": 5,
        "across": puzzle["clues_across"],
        "down": puzzle["clues_down"],
        "solved": solved,
        "in_progress": bool(attempt) and not solved,
        "elapsed_seconds": None,
    }

    if solved:
        payload["elapsed_seconds"] = attempt["elapsed_seconds"]
    elif attempt:
        # Resume the server's clock, so refreshing the page can't reset it.
        payload["elapsed_seconds"] = elapsed_since(attempt["started_at"])

    return jsonify(payload)


@app.post("/api/puzzle/start")
@with_user
def start_puzzle(conn, user):
    """Start, or resume, the server-side clock for today's puzzle."""
    puzzle = db.puzzle_for(conn, today())
    if puzzle is None:
        return error("No puzzle available yet", 404)

    attempt = db.start_attempt(conn, user["id"], puzzle["id"])
    if attempt is None:  # pragma: no cover - only on a hard database failure
        return error("Could not start the puzzle", 500)

    if attempt["solved_at"]:
        return jsonify({"solved": True, "elapsed_seconds": attempt["elapsed_seconds"]})

    return jsonify({"solved": False, "elapsed_seconds": elapsed_since(attempt["started_at"])})


@app.post("/api/puzzle/submit")
@with_user
def submit_puzzle(conn, user):
    """Check a filled grid against the solution, which stays on the server."""
    body = request.get_json(silent=True) or {}
    grid = normalise_grid(body.get("grid"))
    if grid is None:
        return error("Grid must contain 25 letters")

    puzzle = db.puzzle_for(conn, today())
    if puzzle is None:
        return error("No puzzle available yet", 404)

    if grid != puzzle["solution"]:
        return jsonify({"correct": False})

    attempt = db.start_attempt(conn, user["id"], puzzle["id"])
    if attempt["solved_at"]:
        return jsonify(
            {
                "correct": True,
                "elapsed_seconds": attempt["elapsed_seconds"],
                "already_solved": True,
            }
        )

    elapsed = max(1, min(elapsed_since(attempt["started_at"]), MAX_ELAPSED_SECONDS))
    db.finish_attempt(conn, attempt["id"], elapsed)

    return jsonify({"correct": True, "elapsed_seconds": elapsed, "already_solved": False})


# --------------------------------------------------------------------------- #
# leaderboard
# --------------------------------------------------------------------------- #


@app.get("/api/leaderboard")
def leaderboard():
    db.ensure_schema()
    with db.connection() as conn:
        puzzle = db.puzzle_for(conn, today())
        if puzzle is None:
            return jsonify({"date": today(), "entries": []})

        rows = db.leaderboard_for(conn, puzzle["id"], LEADERBOARD_SIZE)

    return jsonify(
        {
            "date": puzzle["puzzle_date"],
            "entries": [
                {"rank": i + 1, "username": row["username"], "seconds": row["seconds"]}
                for i, row in enumerate(rows)
            ],
        }
    )


# --------------------------------------------------------------------------- #
# admin + health
# --------------------------------------------------------------------------- #


@app.post("/api/admin/puzzles")
def add_puzzles():
    """Add or replace puzzles. Guarded by the ADMIN_TOKEN environment variable."""
    expected = os.environ.get("ADMIN_TOKEN", "").strip()
    if not expected:
        return error("Admin API is disabled (ADMIN_TOKEN is not set)", 403)
    if request.headers.get("X-Admin-Token", "") != expected:
        return error("Bad admin token", 403)

    body = request.get_json(silent=True) or {}
    entries = body if isinstance(body, list) else body.get("puzzles", [])
    if not isinstance(entries, list) or not entries:
        return error("Expected a list of puzzles")

    db.ensure_schema()
    try:
        with db.connection() as conn:
            for entry in entries:
                db.upsert_puzzle(conn, entry)
            dates = db.all_puzzle_dates(conn)
    except (KeyError, TypeError, ValueError) as exc:
        return error(f"Invalid puzzle: {exc}")

    return jsonify({"saved": len(entries), "dates": sorted(dates)})


@app.get("/api/health")
def health():
    db.ensure_schema()
    with db.connection() as conn:
        puzzle = db.puzzle_for(conn, today())

    return jsonify(
        {
            "ok": True,
            "today": today(),
            "puzzle_date": puzzle["puzzle_date"] if puzzle else None,
            "backend": "postgres" if db.is_postgres() else "sqlite",
        }
    )


def _add_unprefixed_aliases(flask_app: Flask) -> None:
    """Also answer on paths without the /api prefix.

    Depending on how the platform rewrites /api/* onto this function, Flask may
    see either "/api/auth/login" or "/auth/login". Registering both keeps the
    deployment working either way.
    """
    for rule in list(flask_app.url_map.iter_rules()):
        if not rule.rule.startswith("/api/"):
            continue
        flask_app.add_url_rule(
            rule.rule[len("/api") :],
            endpoint=f"{rule.endpoint}__alias",
            view_func=flask_app.view_functions[rule.endpoint],
            methods=sorted(rule.methods - {"HEAD", "OPTIONS"}),
        )


_add_unprefixed_aliases(app)


if __name__ == "__main__":
    db.ensure_schema()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8080)), debug=True)
