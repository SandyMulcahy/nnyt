"""Password hashing and signed session tokens.

Passwords are hashed on the server with werkzeug's scrypt implementation and
never stored or transmitted in plain text beyond the HTTPS request body.
Sessions are stateless: a signed, expiring token carrying the user id.
"""

from __future__ import annotations

import os
import re

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{2,20}$")

_DEV_SECRET = "dev-secret-do-not-use-in-production"


def secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    if os.environ.get("VERCEL_ENV") in {"production", "preview"}:
        raise RuntimeError("SECRET_KEY must be set in the deployed environment")
    return _DEV_SECRET


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key(), salt="nnyt-auth")


def make_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_token(token: str) -> int | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None


def normalise_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_credentials(username: str, password: str) -> str | None:
    """Return an error message, or None if the credentials are acceptable."""
    if not USERNAME_RE.match(username):
        return "Username must be 2-20 characters: letters, numbers, . _ -"
    if not password or len(password) < 6:
        return "Password must be at least 6 characters"
    if len(password) > 200:
        return "Password is too long"
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)
