"""Password policy and Argon2id hashing.

Policy follows NIST SP 800-63B (rev. 4): length over complexity, no
composition rules, Unicode allowed and normalized, context-specific words
rejected. Hashing uses Argon2id with the RFC 9106 low-memory profile.
"""

import unicodedata
from dataclasses import dataclass
from functools import cached_property

from argon2 import PasswordHasher, profiles
from argon2.exceptions import VerificationError

# NIST SP 800-63B rev. 4: at least 15 characters when the password is the only factor.
MIN_LENGTH = 15
# Bounds the work an attacker can force on the server per attempt.
MAX_LENGTH = 256
CONTEXT_WORDS = ("lumen",)


class PasswordPolicyError(ValueError):
    pass


def normalize(password: str) -> str:
    """NFKC-normalize so visually identical passwords hash identically."""
    return unicodedata.normalize("NFKC", password)


def check_policy(password: str, *, email: str | None = None) -> None:
    """Raise PasswordPolicyError if the password is unacceptable."""
    password = normalize(password)
    # Length counts Unicode code points, not bytes.
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {MAX_LENGTH} characters")

    folded = password.casefold()
    words = list(CONTEXT_WORDS)
    if email:
        local_part = email.split("@", 1)[0].casefold()
        if len(local_part) >= 3:
            words.append(local_part)
    for word in words:
        if word in folded:
            raise PasswordPolicyError("Password must not contain your email or the app name")


@dataclass(frozen=True, slots=True)
class VerifyResult:
    valid: bool
    # True when the stored hash uses outdated parameters and should be replaced.
    needs_rehash: bool = False


class Passwords:
    """Hashes and verifies passwords. Inject a cheaper hasher only in tests."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher.from_parameters(profiles.RFC_9106_LOW_MEMORY)

    def hash(self, password: str) -> str:
        return self._hasher.hash(normalize(password))

    def verify(self, password_hash: str, password: str) -> VerifyResult:
        try:
            self._hasher.verify(password_hash, normalize(password))
        except VerificationError:  # includes VerifyMismatchError (wrong password)
            return VerifyResult(valid=False)
        # InvalidHashError is deliberately not caught: the database only
        # accepts argon2id strings, so a malformed hash is a bug to surface.
        return VerifyResult(valid=True, needs_rehash=self._hasher.check_needs_rehash(password_hash))

    def verify_dummy(self, password: str) -> None:
        """Spend the same time as a real verification, for unknown accounts.

        Without this, "no such email" would return much faster than "wrong
        password", revealing which emails have accounts.
        """
        self.verify(self._dummy_hash, password)

    @cached_property
    def _dummy_hash(self) -> str:
        # Hashed with the same parameters as real hashes, so timing matches.
        return self._hasher.hash("lumen-dummy-password-for-timing")
