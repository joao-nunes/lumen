"""ASGI entry point: `uvicorn lumen.api.main:app --factory`."""

from fastapi import FastAPI

from lumen.api.app import create_app
from lumen.config import get_settings


def app() -> FastAPI:
    return create_app(get_settings())
