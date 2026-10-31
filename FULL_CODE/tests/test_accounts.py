"""Password hashing, sign-in, sessions and the lockout after repeated wrong passwords."""

import pytest

from voice_of_store.accounts import (
    AccountError,
    LoginThrottle,
    authenticate,
    end_session,
    hash_password,
    save_user,
    session_user,
    start_session,
    verify_password,
)
from voice_of_store.database import apply_schema, session


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "app.db"
    apply_schema(path)
    with session(path) as connection:
        save_user(connection, "head-office", "Head office", "correct-horse", "admin")
        save_user(connection, "kothrud", "Kothrud manager", "store-pass-1", "store", "ST-AAAAA")
    return path


def test_password_hash_is_salted_and_checks_only_the_right_password():
    first, second = hash_password("correct-horse"), hash_password("correct-horse")
    assert first != second and "correct-horse" not in first
    assert verify_password("correct-horse", first)
    assert not verify_password("wrong-horse", first)
    assert not verify_password("correct-horse", "not-a-hash")


def test_sign_in_needs_the_right_username_and_password(db):
    with session(db) as connection:
        user = authenticate(connection, "kothrud", "store-pass-1")
        assert user.store_id == "ST-AAAAA" and not user.is_admin
        assert authenticate(connection, "kothrud", "store-pass-2") is None
        assert authenticate(connection, "nobody", "store-pass-1") is None


def test_short_passwords_and_store_rules_are_refused(db):
    with session(db) as connection, pytest.raises(AccountError, match="at least 8"):
        save_user(connection, "short", "Short", "1234", "admin")


def test_session_finds_the_user_until_it_ends_or_expires(db):
    with session(db) as connection:
        user = authenticate(connection, "head-office", "correct-horse")
        token = start_session(connection, user, hours=12)
        assert session_user(connection, token).username == "head-office"
        assert session_user(connection, token + "x") is None
        end_session(connection, token)
        assert session_user(connection, token) is None
        expired = start_session(connection, user, hours=0)
        assert session_user(connection, expired) is None


def test_throttle_locks_after_too_many_wrong_passwords_and_resets_on_success():
    throttle = LoginThrottle(max_failures=3, lockout_minutes=15)
    for _ in range(2):
        throttle.failed("kothrud")
    assert throttle.seconds_locked("kothrud") == 0
    throttle.failed("kothrud")
    assert 0 < throttle.seconds_locked("kothrud") <= 15 * 60 + 1
    assert throttle.seconds_locked("someone-else") == 0
    throttle.succeeded("kothrud")
    assert throttle.seconds_locked("kothrud") == 0
