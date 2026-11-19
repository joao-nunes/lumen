from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Protocol


class RedactionUnavailableError(Exception):
    pass


class IdentifierDetector(Protocol):
    def detect(self, text: str) -> str: ...


@dataclass(frozen=True)
class Pseudonymized:
    text: str
    mapping: Mapping[str, str]


class Redactor:
    def __init__(self, detector: IdentifierDetector) -> None:
        self._detector = detector

    def pseudonymize(self, text: str, *, owner: Hashable, context: str) -> Pseudonymized:
        return Pseudonymized(text, {})


def rehydrate(reply: str, pseudonymized: Pseudonymized) -> str:
    return reply
