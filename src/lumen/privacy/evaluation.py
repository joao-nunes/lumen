"""Measures redaction against the evaluation set (spec 011 §2.6). Only `collect` calls a model.

An identifier is caught only when no word of it survives, whatever type it was given: each of its
words may appear in the output no more often than in the entry outside identifiers. A failed entry
fails closed, so nothing leaks, but the text is unusable: it misses all its identifiers and loses
its decoys.
"""

import csv
import json
import math
import re
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from lumen.privacy.redaction import Pseudonymized, RedactionUnavailableError, Redactor
from lumen.privacy.rules import IdentifierType

# "test" is the held-out split for the current measurement. "test_v1" held redaction_v1's, and has
# been read, so it's never tuned on or measured against again (spec 011 §10).
SPLITS = frozenset({"dev", "test", "test_v1"})
LANGUAGES = ("en", "pt", "mixed")
DIRECT = frozenset(
    {
        IdentifierType.PERSON,
        IdentifierType.ORG,
        IdentifierType.ADDRESS,
        IdentifierType.CONTACT,
        IdentifierType.ID,
    }
)
DISTRESSING = "distressing"

DIRECT_BAR = 0.95
CONTEXTUAL_BAR = 0.85
DECOYS_BAR = 0.90
P95_SECONDS_BAR = 10.0
MAX_FAILURES_IN_A_ROW = 3

_PLACEHOLDER_TYPE = re.compile(r"\[([A-Z]+)_\d+\]")


@dataclass(frozen=True, slots=True)
class Identifier:
    text: str
    type: IdentifierType
    rule: bool = False  # fixed-shape: the rules alone must catch it


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    split: str
    language: str
    category: str
    text: str
    identifiers: tuple[Identifier, ...]
    decoys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Outcome:
    entry: Entry
    result: Pseudonymized | None  # None: redaction failed closed
    seconds: float = 0.0
    loads_model: bool = False  # the run's first call, which loads the model into memory


@dataclass(frozen=True, slots=True)
class Metrics:
    direct: int
    direct_recall: float
    contextual: int
    contextual_recall: float
    decoys: int
    decoys_kept: float
    entries: int
    leak_free: float  # entries that missed no identifier
    right_type: float  # of caught identifiers
    p95_seconds: float
    failures: int
    distress_failures: int


def _count(phrase: str, text: str) -> int:
    """Whole-word occurrences, case-sensitive: "Joy" must go while "joy" the feeling stays."""
    return len(re.findall(rf"(?<!\w){re.escape(phrase)}(?!\w)", text))


def load_entries(path: Path) -> list[Entry]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        problem = None
        written = [raw["text"], *(i["text"] for i in raw["identifiers"]), *raw["decoys"]]
        if any(unicodedata.normalize("NFC", s) != s for s in written):
            # The redactor's output is NFC, so another form would never be found in it.
            problem = "text that isn't NFC"
        elif raw["split"] not in SPLITS or raw["language"] not in LANGUAGES:
            problem = "an unknown split or language"
        elif any(i["type"] not in set(IdentifierType) for i in raw["identifiers"]):
            problem = "an unknown type"
        elif any(not _count(p, raw["text"]) for p in [i["text"] for i in raw["identifiers"]]):
            problem = "an identifier that isn't in its text"
        elif any(not _count(decoy, raw["text"]) for decoy in raw["decoys"]):
            problem = "a decoy that isn't in its text"
        if problem:
            raise ValueError(f"Entry {raw['id']} has {problem}")
        entries.append(
            Entry(
                id=raw["id"],
                split=raw["split"],
                language=raw["language"],
                category=raw["category"],
                text=raw["text"],
                identifiers=tuple(
                    Identifier(i["text"], IdentifierType(i["type"]), i.get("rule", False))
                    for i in raw["identifiers"]
                ),
                decoys=tuple(raw["decoys"]),
            )
        )
    return entries


class RunAbortedError(Exception):
    """The run stopped rather than report results that only measure an outage."""


def collect(
    redactor: Redactor,
    entries: Iterable[Entry],
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> list[Outcome]:
    """Redacts each entry as the app would. No entry has a personal context."""
    outcomes: list[Outcome] = []
    failures_in_a_row = 0
    for entry in entries:
        started = clock()
        try:
            result: Pseudonymized | None = redactor.pseudonymize(
                entry.text, owner="evaluation", context=""
            )
        except RedactionUnavailableError:
            result = None
        outcomes.append(Outcome(entry, result, clock() - started, loads_model=not outcomes))
        failures_in_a_row = failures_in_a_row + 1 if result is None else 0
        if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
            raise RunAbortedError(f"{MAX_FAILURES_IN_A_ROW} failed calls in a row")
    return outcomes


def _outside_identifiers(entry: Entry) -> str:
    text = entry.text
    for identifier in sorted(entry.identifiers, key=lambda i: -len(i.text)):
        text = re.sub(rf"(?<!\w){re.escape(identifier.text)}(?!\w)", " ", text)
    return text


def caught(identifier: Identifier, entry: Entry, output: str) -> bool:
    """No word of it survives, beyond those the entry also has outside identifiers (§2.6)."""
    rest = _outside_identifiers(entry)
    return all(
        _count(word, output) <= _count(word, rest) for word in re.findall(r"\w+", identifier.text)
    )


def decoy_kept(decoy: str, entry: Entry, output: str) -> bool:
    """Every occurrence of the decoy is still there."""
    return _count(decoy, output) >= _count(decoy, entry.text)


def _typed_right(identifier: Identifier, result: Pseudonymized) -> bool:
    """Some placeholder standing for text that holds the identifier has the identifier's type."""
    return any(
        _count(identifier.text.casefold(), original.casefold())
        and (kind := _PLACEHOLDER_TYPE.fullmatch(placeholder)) is not None
        and kind[1] == identifier.type.value
        for placeholder, original in result.mapping.items()
    )


def _ratio(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def measure(outcomes: list[Outcome]) -> Metrics:
    direct = direct_caught = contextual = contextual_caught = 0
    decoys = decoys_kept = leak_free = caught_total = right = 0
    for outcome in outcomes:
        entry, result = outcome.entry, outcome.result
        missed = False
        for identifier in entry.identifiers:
            hit = result is not None and caught(identifier, entry, result.text)
            missed = missed or not hit
            if identifier.type in DIRECT:
                direct, direct_caught = direct + 1, direct_caught + hit
            else:
                contextual, contextual_caught = contextual + 1, contextual_caught + hit
            if hit and result is not None:
                caught_total += 1
                right += _typed_right(identifier, result)
        for decoy in entry.decoys:
            decoys += 1
            decoys_kept += result is not None and decoy_kept(decoy, entry, result.text)
        leak_free += result is not None and not missed

    failed = [o for o in outcomes if o.result is None]
    # Loading the model into memory is a wait a person only meets once.
    times = sorted(o.seconds for o in outcomes if not o.loads_model)
    return Metrics(
        direct=direct,
        direct_recall=_ratio(direct_caught, direct),
        contextual=contextual,
        contextual_recall=_ratio(contextual_caught, contextual),
        decoys=decoys,
        decoys_kept=_ratio(decoys_kept, decoys),
        entries=len(outcomes),
        leak_free=_ratio(leak_free, len(outcomes)),
        right_type=_ratio(right, caught_total),
        p95_seconds=times[math.ceil(0.95 * len(times)) - 1] if times else 0.0,
        failures=len(failed),
        distress_failures=len([o for o in failed if o.entry.category == DISTRESSING]),
    )


def meets_bar(metrics: Metrics) -> bool:
    """Spec 011 §2.6, for one language. An empty measure can't pass."""
    return (
        metrics.direct > 0
        and metrics.contextual > 0
        and metrics.decoys > 0
        and metrics.direct_recall >= DIRECT_BAR
        and metrics.contextual_recall >= CONTEXTUAL_BAR
        and metrics.decoys_kept >= DECOYS_BAR
        and metrics.p95_seconds < P95_SECONDS_BAR
        and metrics.distress_failures == 0
    )


def record_if_met(
    path: Path,
    *,
    prompt: str,
    sha256: str,
    model: str,
    split: str,
    by_language: Mapping[str, Metrics],
) -> bool:
    """Records the prompt only for a held-out run that meets the bar in every language."""
    if split != "test" or set(by_language) != set(LANGUAGES):
        return False
    if not all(meets_bar(metrics) for metrics in by_language.values()):
        return False
    record = {"prompt": prompt, "sha256": sha256, "model": model, "split": split}
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return True


@dataclass(frozen=True, slots=True)
class Agreement:
    labelled: int  # distinct forms in the labels
    marked: int  # distinct forms the owner marked
    both: int


def read_owner_sheet(path: Path) -> dict[str, frozenset[str]]:
    """The owner's blind marks, each distinct form once."""
    with path.open(encoding="utf-8", newline="") as file:
        return {
            row["id"]: frozenset(f.strip() for f in row["identifiers"].split(";") if f.strip())
            for row in csv.DictReader(file)
        }


def agreement(entries: Iterable[Entry], owner: Mapping[str, frozenset[str]]) -> Agreement:
    """The labels against the owner's marks, on the entries the owner marked."""
    labelled = marked = both = 0
    for entry in entries:
        if entry.id not in owner:
            continue
        labels = {i.text for i in entry.identifiers}
        labelled, marked = labelled + len(labels), marked + len(owner[entry.id])
        both += len(labels & owner[entry.id])
    return Agreement(labelled, marked, both)
