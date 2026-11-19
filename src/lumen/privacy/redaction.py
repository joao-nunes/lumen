"""Pseudonymization of Tier 0 text into Tier 1, and re-hydration of replies (spec 011).

Rules and the local model find identifiers; this code replaces them. The model only points: it
returns findings, never rewritten text. Every failure of the model fails closed, raising
`RedactionUnavailableError` and returning no text, never falling back to the rules alone.

The pseudonym map lives in a `Pseudonymized`, in memory, for one exchange (§3). Nothing here
saves it.
"""

import hashlib
import json
import re
import threading
from collections.abc import Hashable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from lumen.privacy.rules import IdentifierType, Rank, Span, rule_spans

type Finding = tuple[str, IdentifierType]

_TYPE_NAMES = frozenset(IdentifierType)
_TYPE_ORDER = {kind: i for i, kind in enumerate(IdentifierType)}
# Proper names that recur and mean the same thing wherever they appear (§2.2).
_KNOWN_NAME_TYPES = frozenset(
    {IdentifierType.PERSON, IdentifierType.ORG, IdentifierType.PLACE, IdentifierType.NAME}
)
_PLACEHOLDER = re.compile(r"\[(" + "|".join(IdentifierType) + r")_(\d+)\]")


class RedactionUnavailableError(Exception):
    """The local model couldn't redact the text, so no Tier 1 text exists for it.

    It never carries the text: exceptions end up in logs and tracebacks.
    """

    def __init__(self) -> None:
        super().__init__("Redaction is unavailable: the local model failed")


class IdentifierDetector(Protocol):
    def detect(self, text: str) -> str:
        """The model's raw reply: JSON with a list of findings, each a `text` and a `type`."""
        ...


@dataclass(frozen=True, repr=False)
class Pseudonymized:
    """Tier 1 text and its pseudonym map, which is Tier 0 and never leaves memory."""

    text: str
    mapping: Mapping[str, str]

    def __repr__(self) -> str:
        return f"Pseudonymized(<{len(self.text)} characters, {len(self.mapping)} placeholders>)"


def _parsed(reply: object) -> list[Finding] | None:
    """The findings in a reply, or None if it doesn't match the schema exactly (§2.2)."""
    if not isinstance(reply, str):
        return None
    try:
        data = json.loads(reply)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.keys() != {"findings"}:
        return None
    items = data["findings"]
    if not isinstance(items, list):
        return None
    findings: list[Finding] = []
    for item in items:
        if not isinstance(item, dict) or item.keys() != {"text", "type"}:
            return None
        text, kind = item["text"], item["type"]
        if not isinstance(text, str) or kind not in _TYPE_NAMES:
            return None
        findings.append((text, IdentifierType(kind)))
    return findings


def _occurrences(needle: str, text: str, *, ignore_case: bool) -> Iterator[tuple[int, int]]:
    """Whole-word occurrences, so "Ana" never matches inside "Banana"."""
    if not needle.strip():
        return
    flags = re.IGNORECASE if ignore_case else 0
    for match in re.finditer(rf"(?<!\w){re.escape(needle)}(?!\w)", text, flags):
        yield match.span()


def _merged(spans: list[Span]) -> list[Span]:
    """Overlapping spans become one, with the type of the part that ranks first."""
    merged: list[Span] = []
    for span in sorted(spans, key=lambda s: (s.start, -s.end)):
        if merged and span.start < merged[-1].end:
            last = merged[-1]
            first = min(last, span, key=lambda s: (s.rank, _TYPE_ORDER[s.type]))
            merged[-1] = Span(last.start, max(last.end, span.end), first.type, first.rank)
        else:
            merged.append(span)
    return merged


def _replaced(text: str, spans: list[Span]) -> Pseudonymized:
    taken = {(m[1], int(m[2])) for m in _PLACEHOLDER.finditer(text)}
    last_number: dict[IdentifierType, int] = {}
    by_text: dict[str, str] = {}
    mapping: dict[str, str] = {}
    pieces: list[str] = []
    cursor = 0
    for span in spans:
        original = text[span.start : span.end]
        placeholder = by_text.get(original.casefold())
        if placeholder is None:
            number = last_number.get(span.type, 0) + 1
            while (span.type.value, number) in taken:
                number += 1
            last_number[span.type] = number
            placeholder = f"[{span.type}_{number}]"
            by_text[original.casefold()] = placeholder
            mapping[placeholder] = original
        pieces += [text[cursor : span.start], placeholder]
        cursor = span.end
    pieces.append(text[cursor:])
    return Pseudonymized("".join(pieces), MappingProxyType(mapping))


class Redactor:
    """The one entry point. Holds each owner's known names, in memory only."""

    def __init__(self, detector: IdentifierDetector) -> None:
        self._detector = detector
        self._known: dict[Hashable, tuple[str, tuple[Finding, ...]]] = {}
        self._lock = threading.Lock()

    def pseudonymize(self, text: str, *, owner: Hashable, context: str) -> Pseudonymized:
        """Tier 1 text and its map. `owner` is an opaque key for the known-name cache."""
        known = self._known_names(owner, context)
        findings = self._findings(text)
        # Raised here, outside any except block, so the error chains nothing that could quote
        # the text.
        if known is None or findings is None:
            raise RedactionUnavailableError

        spans = rule_spans(text)
        for name, kind in known:
            spans += [
                Span(*o, kind, Rank.KNOWN_NAME) for o in _occurrences(name, text, ignore_case=False)
            ]
        for found, kind in findings:
            spans += [
                Span(*o, kind, Rank.MODEL) for o in _occurrences(found, text, ignore_case=True)
            ]
        result = _replaced(text, _merged(spans))

        # Defence in depth (§2.2): nothing a rule or a known name matches may be left.
        left = rule_spans(result.text) or any(
            any(_occurrences(name, result.text, ignore_case=False)) for name, _ in known
        )
        if left:
            raise RedactionUnavailableError
        return result

    def _findings(self, text: str) -> list[Finding] | None:
        try:
            reply = self._detector.detect(text)
        except Exception:  # any failure of the model fails closed (§2.3)
            return None
        return _parsed(reply)

    def _known_names(self, owner: Hashable, context: str) -> tuple[Finding, ...] | None:
        """Proper names in the personal context, as it writes them; None if the model failed."""
        if not context.strip():
            return ()
        digest = hashlib.sha256(context.encode()).hexdigest()
        with self._lock:
            cached = self._known.get(owner)
        if cached is not None and cached[0] == digest:
            return cached[1]

        findings = self._findings(context)
        if findings is None:
            return None
        names: set[Finding] = set()
        for found, kind in findings:
            if kind in _KNOWN_NAME_TYPES:
                names.update(
                    (context[start:end], kind)
                    for start, end in _occurrences(found, context, ignore_case=True)
                )
        known = tuple(sorted(names))
        with self._lock:
            self._known[owner] = (digest, known)
        return known


def rehydrate(reply: str, pseudonymized: Pseudonymized) -> str:
    """Maps back exactly the placeholders Lumen issued; any other is left as it is."""
    return _PLACEHOLDER.sub(lambda m: pseudonymized.mapping.get(m[0], m[0]), reply)
