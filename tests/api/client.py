"""Helpers shared by the HTTP tests: register, log in, and send CSRF tokens like a browser."""

from collections.abc import Callable

import httpx2
from fastapi.testclient import TestClient

SESSION, CSRF = "__Host-lumen_session", "__Host-lumen_csrf"
EMAIL = "joao@example.com"
PASSWORD = "correct horse battery staple"

NewClient = Callable[[], TestClient]


def register(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> httpx2.Response:
    return client.post("/api/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> httpx2.Response:
    return client.post("/api/auth/login", json={"email": email, "password": password})


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get(CSRF) or ""}


def error_code(response: httpx2.Response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]
