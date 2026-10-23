from lumen.auth.models import SESSION_TOKEN_HASH_BYTES
from lumen.auth.tokens import hash_token, is_well_formed, new_token


def test_tokens_are_unique_and_well_formed() -> None:
    tokens = {new_token() for _ in range(1000)}
    assert len(tokens) == 1000
    assert all(is_well_formed(t) for t in tokens)


def test_token_hash_is_deterministic_and_fits_the_schema() -> None:
    token = new_token()
    assert hash_token(token) == hash_token(token)
    assert len(hash_token(token)) == SESSION_TOKEN_HASH_BYTES


def test_malformed_cookie_values_are_rejected() -> None:
    for value in ("", "a" * 42, "a" * 42 + "=", "' OR 1=1 --" + "a" * 32):
        assert not is_well_formed(value)
