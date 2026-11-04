"""`make run` (spec 002 §2.4): FastAPI serves the built frontend without shadowing the API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from lumen.api.app import create_app
from lumen.config import Settings
from tests.api.client import error_code


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<title>Lumen</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('lumen')")
    settings = Settings(_env_file=None, secret_key=SecretStr("x" * 32), web_dist=tmp_path)
    return TestClient(create_app(settings), base_url="https://testserver")


def test_the_app_and_its_assets_are_served(client: TestClient) -> None:
    for path in ("/", "/login"):  # /login: a reload on a browser route must still load the app
        response = client.get(path)
        assert (response.status_code, response.text) == (200, "<title>Lumen</title>"), path
        assert response.headers["content-type"].startswith("text/html")
    assert client.get("/assets/app.js").text == "console.log('lumen')"


def test_the_api_is_not_shadowed_by_the_app(client: TestClient) -> None:
    # A real route still answers, and an unknown one must not get a 200 with HTML:
    # the frontend would try to read it as JSON.
    assert error_code(client.get("/api/auth/me")) == (401, "not_authenticated")
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_refuses_to_serve_a_directory_that_is_not_a_built_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An empty WEB_DIST= in .env means the current directory: serving that would
    # publish the whole repository, including .env.
    (tmp_path / ".env").write_text("SECRET_KEY=do-not-serve-me")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WEB_DIST", "")

    with pytest.raises(ValueError, match=r"index\.html"):
        create_app(Settings(_env_file=None, secret_key=SecretStr("x" * 32)))
