"""Composition root for the HTTP API (spec 001). Walking skeleton: no routes yet."""

from fastapi import FastAPI

from lumen.api.clock import Clock, system_clock
from lumen.config import Settings


def create_app(settings: Settings, clock: Clock = system_clock) -> FastAPI:
    return FastAPI(title="Lumen")
