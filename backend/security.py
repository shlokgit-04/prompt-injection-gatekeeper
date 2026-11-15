"""Auth helpers: bcrypt password hashing, signed 30-day session tokens,
rate limiting, security headers. Secrets come from host configuration only."""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque

import bcrypt
from itsdangerous import BadSignature, URLSafeTimedSerializer

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_EMAIL_MAX = 254
_PW_MIN = 8


def valid_email(email: str) -> bool:
    return bool(email) and len(email) <= _EMAIL_MAX and bool(_EMAIL_RE.fullmatch(email))


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def check_password(pw: str, pw_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), pw_hash.encode("utf-8"))
    except ValueError:
        return False


class TokenSigner:
    def __init__(self, secret: str, max_age_s: int = 30 * 24 * 3600) -> None:
        if not secret or len(secret) < 32:
            raise RuntimeError("GATEKEEPER_SECRET_KEY must be set and at least 32 characters")
        self._ser = URLSafeTimedSerializer(secret, salt="gatekeeper-session-v1")
        self._max_age = max_age_s

    def issue(self, user_id: int, token_version: int) -> str:
        return self._ser.dumps({"uid": user_id, "tv": token_version})

    def verify(self, token: str) -> dict | None:
        try:
            data = self._ser.loads(token, max_age=self._max_age)
        except BadSignature:
            return None
        return data if isinstance(data, dict) and "uid" in data else None


class RateLimiter:
    """Sliding-window limiter, per key. In-process; enough for one instance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] < now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
