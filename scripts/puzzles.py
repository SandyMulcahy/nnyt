#!/usr/bin/env python3
"""Manage the puzzle bank.

    python scripts/puzzles.py add          # add a puzzle to data/puzzles.json
    python scripts/puzzles.py list         # show what's in data/puzzles.json
    python scripts/puzzles.py seed         # load data/puzzles.json into the database
    python scripts/puzzles.py push URL     # POST data/puzzles.json to a deployed site

"seed" talks to the database directly (needs DATABASE_URL, or it uses the local
SQLite file). "push" needs ADMIN_TOKEN set to the same value as on the server,
and is the easy way to add puzzles to a live deployment.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PUZZLE_FILE = REPO_ROOT / "data" / "puzzles.json"

sys.path.insert(0, str(REPO_ROOT))


def load() -> list[dict]:
    if not PUZZLE_FILE.exists():
        return []
    with open(PUZZLE_FILE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save(puzzles: list[dict]) -> None:
    puzzles.sort(key=lambda p: p["date"])
    PUZZLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PUZZLE_FILE, "w", encoding="utf-8") as handle:
        json.dump(puzzles, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def next_free_date(puzzles: list[dict]) -> str:
    used = {p["date"] for p in puzzles}
    candidate = date.today()
    while candidate.isoformat() in used:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def cmd_list() -> int:
    puzzles = load()
    if not puzzles:
        print("No puzzles yet.")
        return 0

    today = date.today().isoformat()
    for puzzle in puzzles:
        marker = "  <- today" if puzzle["date"] == today else ""
        print(f"{puzzle['date']}  {' '.join(puzzle['rows'])}{marker}")

    upcoming = [p for p in puzzles if p["date"] >= today]
    print(f"\n{len(puzzles)} puzzles, {len(upcoming)} from today onwards.")
    return 0


def cmd_add() -> int:
    puzzles = load()

    default_date = next_free_date(puzzles)
    puzzle_date = input(f"Date [{default_date}]: ").strip() or default_date
    if any(p["date"] == puzzle_date for p in puzzles):
        print(f"There is already a puzzle for {puzzle_date}.")
        return 1

    print("\nEnter the five rows, top to bottom (5 letters each):")
    rows = []
    while len(rows) < 5:
        word = input(f"  row {len(rows) + 1}: ").strip().lower()
        if len(word) == 5 and word.isalpha():
            rows.append(word)
        else:
            print("  needs to be exactly 5 letters")

    columns = ["".join(rows[r][c] for r in range(5)) for c in range(5)]
    print("\nThat gives these columns (down answers):")
    for i, column in enumerate(columns, start=1):
        print(f"  {i}: {column}")

    print("\nClues for the across answers:")
    across = [input(f"  {i + 1} ({rows[i]}): ").strip() for i in range(5)]

    print("\nClues for the down answers:")
    down = [input(f"  {i + 1} ({columns[i]}): ").strip() for i in range(5)]

    if not all(across) or not all(down):
        print("Every answer needs a clue. Nothing was saved.")
        return 1

    puzzles.append({"date": puzzle_date, "rows": rows, "across": across, "down": down})
    save(puzzles)
    print(f"\nSaved {puzzle_date} to {PUZZLE_FILE.relative_to(REPO_ROOT)}.")
    print("Run 'python scripts/puzzles.py push <your-url>' to publish it, or")
    print("commit and push to git if you would rather redeploy.")
    return 0


def cmd_seed() -> int:
    from crossword import db

    puzzles = load()
    if not puzzles:
        print("No puzzles to seed.")
        return 1

    db.ensure_schema()
    with db.connection() as conn:
        for puzzle in puzzles:
            db.upsert_puzzle(conn, puzzle)

    print(f"Seeded {len(puzzles)} puzzles into the database.")
    return 0


def cmd_push(base_url: str) -> int:
    token = os.environ.get("ADMIN_TOKEN", "").strip()
    if not token:
        print("Set ADMIN_TOKEN first, e.g. ADMIN_TOKEN=... python scripts/puzzles.py push URL")
        return 1

    puzzles = load()
    if not puzzles:
        print("No puzzles to push.")
        return 1

    url = base_url.rstrip("/") + "/api/admin/puzzles"
    request = urllib.request.Request(
        url,
        data=json.dumps({"puzzles": puzzles}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Admin-Token": token},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"Failed ({exc.code}): {exc.read().decode('utf-8', 'replace')}")
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach {url}: {exc.reason}")
        return 1

    return 0


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "list"

    if command == "list":
        return cmd_list()
    if command == "add":
        return cmd_add()
    if command == "seed":
        return cmd_seed()
    if command == "push":
        if len(argv) < 3:
            print("Usage: python scripts/puzzles.py push https://your-site.vercel.app")
            return 1
        return cmd_push(argv[2])

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
