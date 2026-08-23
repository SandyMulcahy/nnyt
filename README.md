# Daily 5 x 5

A daily 5x5 crossword: React frontend, Flask API, one deployment, no monthly bill.

```
index.html            Vite entry point
src/                  React app (Login, Home, Crossword, Leaderboard)
api/index.py          Flask API, served at /api/* (the only file in api/ --
                        every .py there becomes its own function on Vercel)
crossword/db.py       storage: Postgres in production, SQLite locally
crossword/auth.py     password hashing and signed session tokens
data/puzzles.json     the puzzle bank
scripts/puzzles.py    add / list / seed / publish puzzles
scripts/serve_local.py  run the API locally
tests/test_api.py     end-to-end API tests
legacy/               the previous version, kept for reference
```

## Running it locally

The API needs Flask. Install it into a virtual environment — macOS refuses a
plain `pip install` into its system Python, and `brew` doesn't carry Python
libraries:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Then two terminals:

```bash
source .venv/bin/activate && python scripts/serve_local.py   # API on :8080
npm install && npm run dev                                   # site on :5173
```

Open http://localhost:5173. The dev server proxies `/api` to Flask, so the
frontend code is identical in development and production.

There is no database to set up: with `DATABASE_URL` unset the API writes to a
SQLite file (`local.db`) and seeds it from `data/puzzles.json` on first run.
`requirements.txt` is the deployment manifest and also pins the Postgres
driver, which you don't need locally — that's the only difference between the
two files.

Run the tests with the virtual environment active:

```bash
python tests/test_api.py
```

## Deploying (free)

The whole site — static frontend and Python API — goes to Vercel as one
project, with the database on Neon. Both have free tiers that a game for
friends will not come close to exhausting. Vercel's free Hobby plan is for
non-commercial projects; if you ever put ads on this, you need their paid plan.

**1. Put the code on GitHub**

```bash
git init
git add .
git commit -m "Daily 5x5"
git branch -M main
git remote add origin https://github.com/YOURNAME/YOURREPO.git
git push -u origin main
```

**2. Import it into Vercel**

Sign in at vercel.com with GitHub, then *Add New → Project* and pick the repo.
It should detect Vite on its own; leave the build settings alone. Deploy.

**3. Add the database**

In the project, go to *Storage → Create Database → Neon* and connect it. Vercel
sets `DATABASE_URL` for you. (Any Postgres works — if you'd rather create the
database at neon.com directly, just paste its connection string into a
`DATABASE_URL` environment variable.)

**4. Set the environment variables**

*Settings → Environment Variables*:

| Name | Value |
| --- | --- |
| `SECRET_KEY` | a long random string — `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ADMIN_TOKEN` | another random string, if you want to publish puzzles without redeploying |
| `PUZZLE_TZ` | `Europe/London` (when the puzzle rolls over) |

`SECRET_KEY` signs the login tokens. Changing it later logs everyone out, which
is a fine way to invalidate all sessions if you ever need to.

**5. Redeploy and check**

*Deployments → ⋯ → Redeploy* so the new variables take effect, then open
`https://your-site.vercel.app/api/health`. It should report `"ok": true`, the
current date, and `"backend": "postgres"`. The tables are created and the
puzzles seeded on that first request.

## Adding puzzles

```bash
python scripts/puzzles.py add     # prompts for the five rows, shows you the
                                  # down answers, asks for ten clues
python scripts/puzzles.py list    # what's queued, and how many days are left
```

Then publish, either by committing (`git push` triggers a redeploy, and new
dates in `data/puzzles.json` are picked up) or, without a redeploy:

```bash
ADMIN_TOKEN=your-token python scripts/puzzles.py push https://your-site.vercel.app
```

If a day has no puzzle the site serves the most recent one rather than breaking,
so running out is untidy but not fatal.

`tools/` has the grid generator from the original project and its word list, for
finding new 5x5 double word squares to write clues for.

## What changed from the first version

- **Storage.** Text files were replaced by a database. Free hosts wipe the disk
  on every restart, so `users.txt` and `leaderboard.txt` would not have survived
  the first redeploy.
- **The answer used to be public.** `/getclue/10` returned the solved grid to
  anyone who asked. The solution now never leaves the server: the browser posts
  a filled grid and is told only whether it matches.
- **Passwords.** They were hashed in the browser with a 32-bit hash and sent in
  the URL, where they land in server logs. They are now sent in a POST body and
  hashed on the server with scrypt.
- **Sessions.** `/home/5` used to log you in as user 5. Login now returns a
  signed token; no user id appears in a URL.
- **Times.** The browser used to report its own solve time, and could report
  anything. The server now times the gap between "start" and a correct
  submission, and one attempt per person per puzzle is recorded.
- **A daily puzzle** keyed on the date, with the leaderboard scoped to that day.
- **Fewer requests.** The old grid fired a request on every keystroke and
  another on every cursor move. Clues now arrive once; the grid is only checked
  when all 25 squares are filled.
- **Bug fixes.** The leaderboard insert mutated the list it was iterating; the
  React grid mutated state in place; the completion timer read a stale value;
  refreshing mid-solve restarted the clock. A solve in progress now survives a
  reload, because the clock lives on the server.
- Migrated from Create React App (no longer maintained) to Vite, and dropped
  `axios` and `flask-cors` — with the frontend and API on one domain, there is
  no cross-origin request left to configure.

The old accounts are not carried over: their passwords only exist as the old
browser-side hash, which cannot be converted. Everyone signs up once more.

## If the API returns 404 after deploying

Vercel routes `/api/*` to `api/index.py` through the rewrite in `vercel.json`.
If requests 404, change that rewrite's destination from `/api/index` to `/api`
and redeploy — the Flask app answers on both prefixed and unprefixed paths, so
either routing works.
