import pytest

from lumen.auth.models import SESSION_TOKEN_HASH_BYTES
from lumen.auth.tokens import hash_token, is_well_formed, new_token


def test_tokens_are_unique_and_well_formed() -> None:
    tokens = {new_token() for _ in range(1000)}
    assert len(tokens) == 1000
    assert all(is_well_formed(t) for t in tokens)


def test_hash_is_deterministic_and_matches_schema_length() -> None:
    token = new_token()
    assert hash_token(token) == hash_token(token)
    assert len(hash_token(token)) == SESSION_TOKEN_HASH_BYTES


def test_different_tokens_have_different_hashes() -> None:
    assert hash_token(new_token()) != hash_token(new_token())


@pytest.mark.parametrize(
    "value",
    [
        "",
        "short",
        "a" * 42,
        "a" * 44,
        "a" * 42 + "=",  # padding is not part of token_urlsafe output
        "a" * 42 + "é",
        "' OR 1=1 --" + "a" * 32,
    ],
)
def test_malformed_tokens_are_rejected(value: str) -> None:
    assert not is_well_formed(value)
