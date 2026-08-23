"""End-to-end tests for the API, run against a temporary SQLite database.

    python tests/test_api.py            (no dependencies beyond Flask)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.pop("DATABASE_URL", None)
os.environ["SQLITE_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_TOKEN"] = "test-admin"
os.environ["PUZZLE_TZ"] = "Europe/London"

from crossword import db  # noqa: E402
from api.index import app  # noqa: E402

SOLUTION = "smashpastainpenkneadyanks"


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        Path(os.environ["SQLITE_PATH"]).unlink(missing_ok=True)
        db.reset_schema_cache()
        db.ensure_schema()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    # helpers ------------------------------------------------------------- #

    def register(self, username="tester", password="hunter22"):
        response = self.client.post(
            "/api/auth/signup", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["token"]

    @staticmethod
    def auth(token):
        return {"Authorization": f"Bearer {token}"}

    def solve_as(self, username, backdate_seconds=0):
        token = self.register(username)
        self.client.post("/api/puzzle/start", headers=self.auth(token))
        if backdate_seconds:
            with db.connection() as conn:
                conn.execute(
                    "UPDATE attempts SET started_at = started_at - ?"
                    " WHERE id = (SELECT MAX(id) FROM attempts)",
                    (backdate_seconds,),
                )
        return self.client.post(
            "/api/puzzle/submit", json={"grid": SOLUTION}, headers=self.auth(token)
        ).get_json()

    # tests --------------------------------------------------------------- #

    def test_health_and_seeding(self):
        body = self.client.get("/api/health").get_json()
        self.assertTrue(body["ok"])
        self.assertIsNotNone(body["puzzle_date"])
        self.assertEqual(body["backend"], "sqlite")

    def test_signup_login_and_me(self):
        token = self.register()
        me = self.client.get("/api/me", headers=self.auth(token)).get_json()
        self.assertEqual(me["username"], "tester")

        duplicate = self.client.post(
            "/api/auth/signup", json={"username": "Tester", "password": "hunter22"}
        )
        self.assertEqual(duplicate.status_code, 409)

        good = self.client.post(
            "/api/auth/login", json={"username": "TESTER ", "password": "hunter22"}
        )
        self.assertEqual(good.status_code, 200)

        bad = self.client.post(
            "/api/auth/login", json={"username": "tester", "password": "wrong"}
        )
        self.assertEqual(bad.status_code, 401)

    def test_password_is_hashed(self):
        self.register("hasher", "correct-horse")
        with db.connection() as conn:
            user = db.user_by_name(conn, "hasher")
        self.assertNotIn("correct-horse", user["password_hash"])
        self.assertGreater(len(user["password_hash"]), 40)

    def test_weak_credentials_rejected(self):
        short_password = self.client.post(
            "/api/auth/signup", json={"username": "bob", "password": "abc"}
        )
        self.assertEqual(short_password.status_code, 400)

        bad_username = self.client.post(
            "/api/auth/signup", json={"username": "a b/c", "password": "longenough"}
        )
        self.assertEqual(bad_username.status_code, 400)

    def test_endpoints_require_auth(self):
        self.assertEqual(self.client.get("/api/puzzle").status_code, 401)
        self.assertEqual(
            self.client.post("/api/puzzle/submit", json={"grid": SOLUTION}).status_code, 401
        )
        self.assertEqual(
            self.client.get("/api/me", headers=self.auth("not-a-token")).status_code, 401
        )

    def test_puzzle_never_exposes_the_solution(self):
        token = self.register()
        response = self.client.get("/api/puzzle", headers=self.auth(token))
        body = response.get_json()
        self.assertEqual(len(body["across"]), 5)
        self.assertEqual(len(body["down"]), 5)
        self.assertNotIn("solution", body)
        self.assertNotIn(SOLUTION, response.get_data(as_text=True))

    def test_wrong_grid_rejected(self):
        token = self.register()
        self.client.post("/api/puzzle/start", headers=self.auth(token))
        response = self.client.post(
            "/api/puzzle/submit", json={"grid": "a" * 25}, headers=self.auth(token)
        )
        self.assertEqual(response.get_json(), {"correct": False})

    def test_malformed_grid_rejected(self):
        token = self.register()
        response = self.client.post(
            "/api/puzzle/submit", json={"grid": "too short"}, headers=self.auth(token)
        )
        self.assertEqual(response.status_code, 400)

    def test_solve_flow(self):
        token = self.register("solver")
        self.client.post("/api/puzzle/start", headers=self.auth(token))

        solved = self.client.post(
            "/api/puzzle/submit", json={"grid": SOLUTION}, headers=self.auth(token)
        ).get_json()
        self.assertTrue(solved["correct"])
        self.assertGreaterEqual(solved["elapsed_seconds"], 1)

        # Re-submitting keeps the original time and adds no second entry.
        again = self.client.post(
            "/api/puzzle/submit",
            json={"grid": " SMASH PASTA INPEN KNEAD YANKS "},
            headers=self.auth(token),
        ).get_json()
        self.assertTrue(again["already_solved"])
        self.assertEqual(again["elapsed_seconds"], solved["elapsed_seconds"])

        board = self.client.get("/api/leaderboard").get_json()
        self.assertEqual([e["username"] for e in board["entries"]], ["solver"])

        state = self.client.get("/api/puzzle", headers=self.auth(token)).get_json()
        self.assertTrue(state["solved"])
        self.assertFalse(state["in_progress"])

    def test_time_is_measured_server_side(self):
        result = self.solve_as("slowpoke", backdate_seconds=125)
        self.assertGreaterEqual(result["elapsed_seconds"], 125)

    def test_leaderboard_ordered_by_time(self):
        self.solve_as("slow", backdate_seconds=300)
        self.solve_as("fast", backdate_seconds=30)
        self.solve_as("middle", backdate_seconds=90)

        board = self.client.get("/api/leaderboard").get_json()
        self.assertEqual(
            [e["username"] for e in board["entries"]], ["fast", "middle", "slow"]
        )
        self.assertEqual([e["rank"] for e in board["entries"]], [1, 2, 3])

    def test_progress_resumes_after_reload(self):
        token = self.register("resumer")
        self.client.post("/api/puzzle/start", headers=self.auth(token))
        with db.connection() as conn:
            conn.execute("UPDATE attempts SET started_at = started_at - 42")

        state = self.client.get("/api/puzzle", headers=self.auth(token)).get_json()
        self.assertTrue(state["in_progress"])
        self.assertGreaterEqual(state["elapsed_seconds"], 42)

    def test_admin_requires_token(self):
        payload = {
            "puzzles": [
                {
                    "date": "2030-01-01",
                    "rows": ["abate", "legal", "llama", "octet", "there"],
                    "across": ["a", "b", "c", "d", "e"],
                    "down": ["f", "g", "h", "i", "j"],
                }
            ]
        }
        self.assertEqual(self.client.post("/api/admin/puzzles", json=payload).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/admin/puzzles", json=payload, headers={"X-Admin-Token": "nope"}
            ).status_code,
            403,
        )

        ok = self.client.post(
            "/api/admin/puzzles", json=payload, headers={"X-Admin-Token": "test-admin"}
        )
        self.assertEqual(ok.status_code, 200)
        self.assertIn("2030-01-01", ok.get_json()["dates"])

    def test_admin_rejects_bad_puzzle(self):
        bad = self.client.post(
            "/api/admin/puzzles",
            json={"puzzles": [{"date": "2030-02-02", "rows": ["short"], "across": [], "down": []}]},
            headers={"X-Admin-Token": "test-admin"},
        )
        self.assertEqual(bad.status_code, 400)

    def test_unprefixed_alias_routes(self):
        """The platform may strip /api before Flask sees the path."""
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/leaderboard").status_code, 200)

    def test_puzzle_falls_back_to_most_recent(self):
        with db.connection() as conn:
            puzzle = db.puzzle_for(conn, "2999-12-31")
        self.assertIsNotNone(puzzle)
        self.assertEqual(puzzle["puzzle_date"], max(_seed_dates()))


def _seed_dates():
    import json

    with open(REPO_ROOT / "data" / "puzzles.json", encoding="utf-8") as handle:
        return [p["date"] for p in json.load(handle)]


if __name__ == "__main__":
    unittest.main(verbosity=2)
