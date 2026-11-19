"""Identifiers with a fixed shape, found by rules (spec 011 §2.2).

Each match is a span of the original text with a type and a precedence rank: when spans overlap,
the merged span takes the type of its lowest rank. Dates and year ranges are found first and
masked, so no digit rule matches across or inside one.
"""

import datetime
import ipaddress
import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import IntEnum, StrEnum


class IdentifierType(StrEnum):
    PERSON = "PERSON"
    ORG = "ORG"
    ADDRESS = "ADDRESS"
    PLACE = "PLACE"
    CONTACT = "CONTACT"
    ID = "ID"
    DATE = "DATE"
    NAME = "NAME"
    ROLE = "ROLE"


class Rank(IntEnum):
    """Precedence when spans overlap: lower wins (§2.2 step 2)."""

    LETTERED_ID = 0  # IBAN, Cartão de Cidadão: their letters can't be confused with a phone
    NIF = 1
    CONTACT = 2
    POSTCODE = 3
    KNOWN_NAME = 4
    MODEL = 5
    DIGIT_RUN = 6


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    type: IdentifierType
    rank: Rank


# Whole tokens: no letter or digit directly before or after.
_START = r"(?<![^\W_])"
_END = r"(?![^\W_])"

_DATE_YMD = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DATE_DMY = re.compile(r"(?<!\d)(\d{2})-(\d{2})-(\d{4})(?!\d)")
_YEAR_RANGE = re.compile(r"(?<!\d)((?:19|20)\d{2}) ?- ?((?:19|20)\d{2})(?!\d)")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"']+")
_URL_TRAILING = ".,;:!?)]}"
_HANDLE = re.compile(r"(?<![\w@.])@\w(?:[\w.]*\w)?")
_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
_IPV4 = re.compile(rf"(?<![\d.])(?:{_OCTET}\.){{3}}{_OCTET}(?!\.?\d)")
_IPV6_CANDIDATE = re.compile(r"(?<![\w:])[0-9A-Fa-f]*:[0-9A-Fa-f:]*:[0-9A-Fa-f]*(?![\w:])")
_PHONE_INTERNATIONAL = re.compile(_START + r"\+\d{1,3}[ -]?(?:\d[ -]?){6,13}\d" + _END)
_NINE_DIGITS = r"\d{3}(?: ?\d{3}){2}"  # together, or three groups of three
_PHONE_PT = re.compile(_START + r"[29]\d{2}(?: ?\d{3}){2}" + _END)
_NIF = re.compile(_START + _NINE_DIGITS + _END)
_IBAN = re.compile(_START + r"[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?\d{1,3})?" + _END)
_CARTAO_CIDADAO = re.compile(_START + r"\d{8} ?\d ?[A-Z]{2}\d" + _END)
_POSTCODE = re.compile(_START + r"\d{4}-\d{3}" + _END)
_DIGIT_RUN = re.compile(r"\d(?:[ -]?\d){6,}")


def _valid_date(year: str, month: str, day: str) -> bool:
    try:
        datetime.date(int(year), int(month), int(day))
    except ValueError:
        return False
    return True


def _kept_dates(text: str) -> Iterator[tuple[int, int]]:
    """Calendar dates and year ranges, which journals often contain and Q2 keeps."""
    for m in _DATE_YMD.finditer(text):
        if _valid_date(m[1], m[2], m[3]):
            yield m.span()
    for m in _DATE_DMY.finditer(text):
        if _valid_date(m[3], m[2], m[1]):
            yield m.span()
    for m in _YEAR_RANGE.finditer(text):
        if int(m[1]) <= int(m[2]):
            yield m.span()


def _masked(text: str) -> str:
    """The text with dates and ranges blanked out, keeping every position where it was."""
    chars = list(text)
    for start, end in _kept_dates(text):
        chars[start:end] = "\0" * (end - start)
    return "".join(chars)


def _nif_check_digit_valid(digits: str) -> bool:
    values = [int(d) for d in digits]
    remainder = sum(v * (9 - i) for i, v in enumerate(values[:8])) % 11
    return values[8] == (0 if remainder < 2 else 11 - remainder)


def _is_ipv6(candidate: str) -> bool:
    try:
        ipaddress.IPv6Address(candidate)
    except ValueError:
        return False
    return True


def rule_spans(text: str) -> list[Span]:
    """Every rule match in `text`, unmerged."""
    masked = _masked(text)
    spans: list[Span] = []

    def add(pattern: re.Pattern[str], source: str, kind: IdentifierType, rank: Rank) -> None:
        spans.extend(Span(*m.span(), kind, rank) for m in pattern.finditer(source))

    add(_IBAN, text, IdentifierType.ID, Rank.LETTERED_ID)
    add(_CARTAO_CIDADAO, text, IdentifierType.ID, Rank.LETTERED_ID)
    spans.extend(
        Span(*m.span(), IdentifierType.ID, Rank.NIF)
        for m in _NIF.finditer(masked)
        if _nif_check_digit_valid(m[0].replace(" ", ""))
    )
    add(_EMAIL, text, IdentifierType.CONTACT, Rank.CONTACT)
    for m in _URL.finditer(text):
        end = m.start() + len(m[0].rstrip(_URL_TRAILING))
        spans.append(Span(m.start(), end, IdentifierType.CONTACT, Rank.CONTACT))
    add(_HANDLE, text, IdentifierType.CONTACT, Rank.CONTACT)
    add(_IPV4, text, IdentifierType.CONTACT, Rank.CONTACT)
    spans.extend(
        Span(*m.span(), IdentifierType.CONTACT, Rank.CONTACT)
        for m in _IPV6_CANDIDATE.finditer(text)
        if _is_ipv6(m[0])
    )
    add(_PHONE_INTERNATIONAL, masked, IdentifierType.CONTACT, Rank.CONTACT)
    add(_PHONE_PT, masked, IdentifierType.CONTACT, Rank.CONTACT)
    add(_POSTCODE, masked, IdentifierType.ADDRESS, Rank.POSTCODE)
    add(_DIGIT_RUN, masked, IdentifierType.ID, Rank.DIGIT_RUN)
    return spans
