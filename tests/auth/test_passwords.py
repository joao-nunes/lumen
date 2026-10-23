import pytest
from argon2 import PasswordHasher

from lumen.auth.passwords import MAX_LENGTH, PasswordPolicyError, Passwords, check_policy

GOOD = "correct horse battery staple"


# --- policy (NIST SP 800-63B rev. 4) ----------------------------------------------


def test_long_simple_passphrase_is_accepted() -> None:
    check_policy(GOOD)  # no composition rules


def test_short_password_is_rejected_even_if_complex() -> None:
    with pytest.raises(PasswordPolicyError, match="at least"):
        check_policy("Sh0rt!Pass#1")


def test_overlong_password_is_rejected() -> None:
    with pytest.raises(PasswordPolicyError, match="at most"):
        check_policy("a" * (MAX_LENGTH + 1))


def test_length_counts_characters_not_bytes() -> None:
    check_policy("çãõ" * 5)  # 15 characters, 45 bytes


def test_context_words_are_rejected_case_insensitively() -> None:
    for password, email in [
        ("MY LUMEN DIARY PASSWORD", None),
        ("joaonunes horse battery", "JoaoNunes@example.com"),
    ]:
        with pytest.raises(PasswordPolicyError, match="email or the app name"):
            check_policy(password, email=email)
    # A very short local part is not treated as a context word.
    check_policy("joyful horse battery staple", email="jo@example.com")


# --- hashing ----------------------------------------------------------------------


def test_hash_is_salted_argon2id_that_verifies_only_the_right_password(
    passwords: Passwords,
) -> None:
    first, second = passwords.hash(GOOD), passwords.hash(GOOD)
    assert first.startswith("$argon2id$")
    assert first != second
    assert passwords.verify(first, GOOD).valid
    assert not passwords.verify(first, GOOD + "!").valid


def test_equivalent_unicode_input_verifies(passwords: Passwords) -> None:
    composed = "café horse battery staple"  # é as one code point
    decomposed = "café horse battery staple"  # e + combining accent
    assert passwords.verify(passwords.hash(composed), decomposed).valid


def test_only_hashes_with_outdated_parameters_need_rehash(passwords: Passwords) -> None:
    old = Passwords(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, hash_len=16))
    assert passwords.verify(old.hash(GOOD), GOOD).needs_rehash
    assert not passwords.verify(passwords.hash(GOOD), GOOD).needs_rehash


def test_production_parameters_are_rfc_9106_low_memory() -> None:
    assert Passwords().hash(GOOD).startswith("$argon2id$v=19$m=65536,t=3,p=4$")
