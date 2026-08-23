#!/usr/bin/env python3
"""Run the API locally on http://127.0.0.1:8080.

Reads .env.local if it exists, then starts Flask. With no DATABASE_URL set it
uses a SQLite file (local.db) and seeds it from data/puzzles.json, so this works
with nothing else installed.

    python scripts/serve_local.py
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

env_file = REPO_ROOT / ".env.local"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

from crossword import db  # noqa: E402
from api.index import app  # noqa: E402

if __name__ == "__main__":
    db.ensure_schema()
    print(f"API on http://127.0.0.1:8080  (storage: {'postgres' if db.is_postgres() else db.sqlite_path()})")
    print("Now run 'npm run dev' in another terminal and open http://localhost:5173")
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8080)), debug=True)
