"""Accounts, password hashing, sessions and a lockout after repeated wrong passwords."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from voice_of_store.database import now

MIN_PASSWORD_LENGTH = 8
# scrypt settings: about 50 ms per check on a laptop, which makes guessing slow but logging in quick.
SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


class AccountError(ValueError):
    """A problem with account data supplied by an operator (shown as-is)."""


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str
    store_id: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, key = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **SCRYPT)
    return hmac.compare_digest(candidate, bytes.fromhex(key))


# Checked when the username doesn't exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def _user(row: sqlite3.Row) -> User:
    return User(row["id"], row["username"], row["display_name"], row["role"], row["store_id"])


def save_user(
    connection: sqlite3.Connection,
    username: str,
    display_name: str,
    password: str,
    role: str,
    store_id: str | None = None,
) -> None:
    """Create the account, or reset its name, role, store and password if it already exists."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"The password for {username} must be at least {MIN_PASSWORD_LENGTH} characters.")
    connection.execute(
        """
        INSERT INTO users (username, display_name, role, store_id, password_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (username) DO UPDATE SET
            display_name = excluded.display_name, role = excluded.role,
            store_id = excluded.store_id, password_hash = excluded.password_hash
        """,
        (username, display_name, role, store_id, hash_password(password), now()),
    )


def has_users(connection: sqlite3.Connection) -> bool:
    return connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def authenticate(connection: sqlite3.Connection, username: str, password: str) -> User | None:
    row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        verify_password(password, _DUMMY_HASH)
        return None
    return _user(row) if verify_password(password, row["password_hash"]) else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(connection: sqlite3.Connection, user: User, hours: int) -> str:
    """Return a new random session token. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    connection.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), user.id, now(), expires),
    )
    connection.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
    return token


def session_user(connection: sqlite3.Connection, token: str) -> User | None:
    row = connection.execute(
        """
        SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
        WHERE sessions.token_hash = ? AND sessions.expires_at > ?
        """,
        (_token_hash(token), now()),
    ).fetchone()
    return _user(row) if row else None


def end_session(connection: sqlite3.Connection, token: str) -> None:
    connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


class LoginThrottle:
    """Locks a username for a while after too many wrong passwords in a row. Kept in memory: one local server."""

    def __init__(self, max_failures: int, lockout_minutes: int) -> None:
        self.max_failures = max_failures
        self.lockout_seconds = lockout_minutes * 60
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def seconds_locked(self, username: str) -> int:
        with self._lock:
            count, since = self._failures.get(username, (0, 0.0))
            if count < self.max_failures:
                return 0
            remaining = self.lockout_seconds - (time.monotonic() - since)
            if remaining <= 0:
                self._failures.pop(username, None)
                return 0
            return int(remaining) + 1

    def failed(self, username: str) -> None:
        with self._lock:
            count, _ = self._failures.get(username, (0, 0.0))
            self._failures[username] = (count + 1, time.monotonic())

    def succeeded(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)
