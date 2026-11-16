"""Авторизация владельца, сессии, CSRF, ограничение частоты запросов."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .db import Database

SESSION_COOKIE = "nexus_session"
CSRF_HEADER = "x-csrf-token"


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Пароль должен быть не короче 12 символов")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b, dk_b = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b)
        expected = base64.b64decode(dk_b)
    except ValueError:
        return False
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(dk, expected)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self, db: Database, ttl_hours: int = 72):
        self.db = db
        self.ttl = ttl_hours

    def owner_exists(self) -> bool:
        return self.db.one("SELECT 1 AS x FROM owner WHERE id=1") is not None

    def set_owner(self, username: str, password: str) -> None:
        h = hash_password(password)
        self.db.execute(
            "INSERT INTO owner(id, username, password_hash) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET username=excluded.username, password_hash=excluded.password_hash",
            (username, h),
        )
        self.db.execute("DELETE FROM sessions")

    def check_credentials(self, username: str, password: str) -> bool:
        row = self.db.one("SELECT username, password_hash FROM owner WHERE id=1")
        if not row:
            # одинаковое время ответа
            hashlib.scrypt(b"x", salt=b"0" * 16, n=2**14, r=8, p=1, dklen=32)
            return False
        ok = verify_password(password, row["password_hash"])
        return ok and hmac.compare_digest(username, row["username"])

    def create_session(self, ip: str = "", ua: str = "") -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO sessions(token_hash, csrf_token, expires_at, ip, user_agent) VALUES (?,?,?,?,?)",
            (token_hash(token), csrf, _fmt(_now() + timedelta(hours=self.ttl)), ip, ua[:200]),
        )
        self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (_fmt(_now()),))
        return token, csrf

    def get_session(self, token: str | None) -> dict | None:
        if not token:
            return None
        row = self.db.one("SELECT * FROM sessions WHERE token_hash=?", (token_hash(token),))
        if not row or row["expires_at"] < _fmt(_now()):
            return None
        return row

    def destroy(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))

    @staticmethod
    def csrf_ok(session: dict, header_value: str | None) -> bool:
        return bool(header_value) and hmac.compare_digest(session["csrf_token"], header_value or "")


class RateLimiter:
    """Простое скользящее окно в памяти процесса."""

    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window = window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str) -> deque:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.limit

    def hit(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def allow(self, key: str) -> bool:
        if self.blocked(key):
            return False
        self.hit(key)
        return True
