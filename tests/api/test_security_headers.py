"""Acceptance criteria of spec 003 (docs/specs/003-security-headers.md)."""

from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from lumen.api.app import create_app
from lumen.config import Settings

HEADERS = {
    "content-security-policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), geolocation=(), microphone=()",
}


def _settings(web_dist: Path | None) -> Settings:
    return Settings(_env_file=None, secret_key=SecretStr("x" * 32), web_dist=web_dist)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<title>Lumen</title>")
    (tmp_path / "app.js").write_text("console.log('lumen')")
    return TestClient(create_app(_settings(tmp_path)), base_url="https://testserver")


def _assert_security_headers(response: httpx2.Response) -> None:
    assert {name: response.headers.get(name) for name in HEADERS} == HEADERS


def test_ac1_ac2_pages_and_assets_have_the_headers_and_may_be_cached(client: TestClient) -> None:
    for path in ("/", "/app.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        _assert_security_headers(response)
        assert "cache-control" not in response.headers, path


def test_ac1_ac2_api_responses_have_the_headers_and_are_never_stored(client: TestClient) -> None:
    for path, status in (("/api/auth/me", 401), ("/api/does-not-exist", 404)):
        response = client.get(path)
        assert response.status_code == status, path
        _assert_security_headers(response)
        assert response.headers["cache-control"] == "no-store", path


def test_ac1_a_request_refused_by_the_origin_check_has_the_headers(client: TestClient) -> None:
    response = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    _assert_security_headers(response)
    assert response.headers["cache-control"] == "no-store"


def test_ac3_the_api_docs_are_not_served() -> None:
    client = TestClient(create_app(_settings(None)), base_url="https://testserver")

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path
