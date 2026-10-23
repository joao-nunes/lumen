import pytest

from lumen.auth.passwords import MAX_LENGTH, PasswordPolicyError, Passwords, check_policy

GOOD = "correct horse battery staple"


@pytest.mark.parametrize(
    ("password", "email", "rejected_because"),
    [
        ("Sh0rt!Pass#1", None, "at least"),  # complexity doesn't compensate for length
        ("a" * (MAX_LENGTH + 1), None, "at most"),
        ("MY LUMEN DIARY PASSWORD", None, "app name"),
        ("joaonunes horse battery", "JoaoNunes@example.com", "email"),
        ("joyful horse battery staple", "jo@example.com", None),  # short local part ignored
        ("çãõ" * 4 + "çã", None, "at least"),  # 14 characters, 28 bytes: count characters
    ],
)
def test_password_policy(password: str, email: str | None, rejected_because: str | None) -> None:
    if rejected_because is None:
        check_policy(password, email=email)
    else:
        with pytest.raises(PasswordPolicyError, match=rejected_because):
            check_policy(password, email=email)


def test_hash_is_salted_and_verifies_only_the_right_password(passwords: Passwords) -> None:
    first, second = passwords.hash(GOOD), passwords.hash(GOOD)
    assert first != second
    assert (passwords.verify(first, GOOD).valid, passwords.verify(first, GOOD + "!").valid) == (
        True,
        False,
    )


def test_equivalent_unicode_input_verifies(passwords: Passwords) -> None:
    # Same visible password typed on different keyboards must still log in.
    composed = "café horse battery staple"
    decomposed = "café horse battery staple"
    assert passwords.verify(passwords.hash(composed), decomposed).valid


def test_production_parameters_are_rfc_9106_low_memory() -> None:
    assert Passwords().hash(GOOD).startswith("$argon2id$v=19$m=65536,t=3,p=4$")
