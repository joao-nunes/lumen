import pytest
from argon2 import PasswordHasher

from lumen.auth.passwords import (
    MAX_LENGTH,
    MIN_LENGTH,
    PasswordPolicyError,
    Passwords,
    check_policy,
)

GOOD = "correct horse battery staple"


# --- policy ---------------------------------------------------------------------


def test_long_simple_passphrase_is_accepted() -> None:
    # No composition rules: lowercase words are fine if long enough.
    check_policy(GOOD)


@pytest.mark.parametrize("password", ["a" * (MIN_LENGTH - 1), "Sh0rt!Pass#1"])
def test_short_passwords_are_rejected_even_if_complex(password: str) -> None:
    with pytest.raises(PasswordPolicyError, match="at least"):
        check_policy(password)


def test_overlong_passwords_are_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="at most"):
        check_policy("a" * (MAX_LENGTH + 1))


def test_length_counts_characters_not_bytes() -> None:
    # 15 characters, but 45 bytes in UTF-8.
    check_policy("çãõ" * 5)


@pytest.mark.parametrize("password", ["my lumen diary password", "MY LUMEN DIARY PASSWORD"])
def test_app_name_is_rejected(password: str) -> None:
    with pytest.raises(PasswordPolicyError, match="app name"):
        check_policy(password)


def test_email_local_part_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="email"):
        check_policy("joaonunes horse battery", email="JoaoNunes@example.com")


def test_very_short_local_part_is_not_treated_as_context() -> None:
    # Rejecting every password containing "jo" would be absurd.
    check_policy("joyful horse battery staple", email="jo@example.com")


# --- hashing --------------------------------------------------------------------


def test_hash_is_argon2id_and_salted(passwords: Passwords) -> None:
    first, second = passwords.hash(GOOD), passwords.hash(GOOD)
    assert first.startswith("$argon2id$")
    assert first != second  # random salt per hash


def test_verify_accepts_correct_and_rejects_wrong_password(passwords: Passwords) -> None:
    stored = passwords.hash(GOOD)
    assert passwords.verify(stored, GOOD).valid
    assert not passwords.verify(stored, GOOD + "!").valid


def test_unicode_normalization_makes_equivalent_input_match(passwords: Passwords) -> None:
    # "é" as one code point vs "e" + combining accent: same visible password.
    composed = "café horse battery staple"
    decomposed = "café horse battery staple"
    assert passwords.verify(passwords.hash(composed), decomposed).valid


def test_hash_with_outdated_parameters_needs_rehash(passwords: Passwords) -> None:
    old = Passwords(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, hash_len=16))
    result = passwords.verify(old.hash(GOOD), GOOD)
    assert result.valid
    assert result.needs_rehash


def test_current_hash_does_not_need_rehash(passwords: Passwords) -> None:
    assert not passwords.verify(passwords.hash(GOOD), GOOD).needs_rehash


def test_verify_dummy_never_raises(passwords: Passwords) -> None:
    passwords.verify_dummy(GOOD)


def test_production_parameters_are_rfc_9106_low_memory() -> None:
    stored = Passwords().hash(GOOD)
    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
