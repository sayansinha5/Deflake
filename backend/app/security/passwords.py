from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("deflake-dummy-password-for-timing")
_COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")


@lru_cache
def _common_passwords() -> frozenset[str]:
    lines = _COMMON_PASSWORDS_FILE.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip())


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Verify against a dummy hash when there is no user, so both paths take the same time."""
    try:
        ok = _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return ok and password_hash is not None


def password_problem(password: str, min_length: int) -> str | None:
    if len(password) < min_length:
        return f"Password must be at least {min_length} characters."
    if len(password) > 256:
        return "Password must be at most 256 characters."
    if password.lower() in _common_passwords():
        return "This password is too common. Choose a different one."
    return None
