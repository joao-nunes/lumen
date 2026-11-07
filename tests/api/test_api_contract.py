"""The API's error contract: every failure has one shape, and the OpenAPI document says so."""

from typing import Any

from fastapi import FastAPI

from tests.api.client import NewClient, csrf, register


def test_unknown_paths_and_wrong_methods_have_the_documented_shape(new_client: NewClient) -> None:
    client = new_client()

    missing = client.get("/api/does-not-exist")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "Not Found"}}

    wrong_method = client.delete("/api/auth/me")
    assert wrong_method.status_code == 405
    assert wrong_method.json() == {
        "error": {"code": "method_not_allowed", "message": "Method Not Allowed"}
    }
    assert wrong_method.headers["Allow"] == "GET"


def test_invalid_paths_queries_and_bodies_get_a_message_that_fits_all_of_them(
    new_client: NewClient,
) -> None:
    client = new_client()
    assert register(client).status_code == 201
    invalid = {"error": {"code": "invalid_request", "message": "The request is invalid"}}

    responses = (
        client.get("/api/checkins/notadate"),
        client.get("/api/overview"),
        client.put("/api/checkins/2026-10-23", json={"scores": "no"}, headers=csrf(client)),
    )
    for response in responses:
        assert (response.status_code, response.json()) == (422, invalid), response.url


# Statuses each operation can return from the app itself. 404 and 405 can come from any path, so
# they aren't repeated per operation.
EXPECTED_ERRORS = {
    ("post", "/api/auth/register"): {403, 409, 415, 422},
    ("post", "/api/auth/login"): {401, 403, 415, 422, 429},
    ("post", "/api/auth/logout"): {403, 415},
    ("post", "/api/auth/password"): {401, 403, 415, 422, 429},
    ("get", "/api/auth/me"): {401},
    ("get", "/api/dimensions"): {401},
    ("get", "/api/checkins/{local_date}"): {401, 422},
    ("put", "/api/checkins/{local_date}"): {401, 403, 415, 422},
    ("post", "/api/checkins/{local_date}/suggestion"): {401, 403, 415, 422, 503},
    ("get", "/api/tags"): {401},
    ("get", "/api/overview"): {401, 422},
}


def _response_schema(response: dict[str, Any]) -> str:
    return str(response["content"]["application/json"]["schema"]["$ref"])


def test_the_openapi_document_describes_every_error(app: FastAPI) -> None:
    document = app.openapi()
    documented = {
        (method, path): {
            int(status): _response_schema(response)
            for status, response in operation["responses"].items()
            if int(status) >= 400
        }
        for path, operations in document["paths"].items()
        for method, operation in operations.items()
    }
    expected = {
        operation: dict.fromkeys(statuses, "#/components/schemas/ErrorBody")
        for operation, statuses in EXPECTED_ERRORS.items()
    }
    assert documented == expected
    assert "HTTPValidationError" not in document["components"]["schemas"]
