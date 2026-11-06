"""Measures a model against the evaluation set (spec 006 §3). Deterministic, with no model calls."""

import csv
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lumen.domain.dimensions import SCALE_MAX, SCALE_MIN, Dimension
from lumen.suggestions.model import Suggestion

SPLITS = frozenset({"dev", "test"})
LANGUAGES = frozenset({"en", "pt"})

WITHIN_ONE_BAR = 0.95
LEFT_BLANK_BAR = 0.95
OFF_BY_THREE_BAR = 0.01
P95_SECONDS_BAR = 10.0
BLIND_PER_LANGUAGE = 15


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    split: str
    language: str
    category: str
    text: str
    scores: dict[Dimension, int]  # dimensions the text addresses, with the right score
    tags: frozenset[str] = frozenset()
    # Dimensions the text only hints at: a score or a blank are both fair, so neither is measured.
    either: frozenset[Dimension] = frozenset()


@dataclass(frozen=True, slots=True)
class Outcome:
    entry: Entry
    suggestion: Suggestion | None  # None: the call failed
    seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class Metrics:
    addressed: int
    within_one: float
    exact: float
    off_by_three: float
    unaddressed: int
    left_blank: float
    tag_precision: float
    tag_recall: float
    p95_seconds: float
    failures: int
    distress_failures: int


def load_entries(path: Path) -> list[Entry]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = json.loads(line)
        if raw["split"] not in SPLITS or raw["language"] not in LANGUAGES:
            raise ValueError(f"Unknown split or language in entry {raw['id']}")
        scores = {Dimension(key): value for key, value in raw["scores"].items()}
        if not all(SCALE_MIN <= value <= SCALE_MAX for value in scores.values()):
            raise ValueError(f"Score out of range in entry {raw['id']}")
        entries.append(
            Entry(
                id=raw["id"],
                split=raw["split"],
                language=raw["language"],
                category=raw["category"],
                text=raw["text"],
                scores=scores,
                tags=frozenset(raw["tags"]),
                either=frozenset(Dimension(key) for key in raw.get("either", [])),
            )
        )
    return entries


def _ratio(part: int, whole: int, *, empty: float = 0.0) -> float:
    return part / whole if whole else empty


def measure(outcomes: list[Outcome]) -> Metrics:
    addressed = exact = within_one = off_by_three = 0
    unaddressed = left_blank = 0
    suggested_tags = correct_tags = labelled_tags = 0

    for outcome in outcomes:
        entry, suggestion = outcome.entry, outcome.suggestion
        for dimension in Dimension:
            if dimension in entry.either:
                continue
            guess = None if suggestion is None else suggestion.scores.get(dimension)
            if dimension in entry.scores:
                addressed += 1
                if (
                    guess is not None
                ):  # a blank here is a miss, so leaving everything blank can't win
                    distance = abs(guess - entry.scores[dimension])
                    exact += distance == 0
                    within_one += distance <= 1
                    off_by_three += distance >= 3
            else:
                unaddressed += 1
                left_blank += suggestion is not None and guess is None
        labelled_tags += len(entry.tags)
        if suggestion is not None:
            suggested_tags += len(suggestion.tags)
            correct_tags += len(suggestion.tags & entry.tags)

    failed = [o for o in outcomes if o.suggestion is None]
    # The first call loads the model into memory, which a person only meets once.
    times = sorted(o.seconds for o in outcomes[1:])
    return Metrics(
        addressed=addressed,
        within_one=_ratio(within_one, addressed),
        exact=_ratio(exact, addressed),
        off_by_three=_ratio(off_by_three, addressed),
        unaddressed=unaddressed,
        left_blank=_ratio(left_blank, unaddressed),
        tag_precision=_ratio(correct_tags, suggested_tags, empty=1.0),
        tag_recall=_ratio(correct_tags, labelled_tags, empty=1.0),
        p95_seconds=times[math.ceil(0.95 * len(times)) - 1] if times else 0.0,
        failures=len(failed),
        distress_failures=len([o for o in failed if o.entry.category == "distress"]),
    )


def meets_bar(metrics: Metrics) -> bool:
    """Spec 006 §3. An empty measure can't pass, and distressing text must never fail."""
    return (
        metrics.addressed > 0
        and metrics.unaddressed > 0
        and metrics.within_one >= WITHIN_ONE_BAR
        and metrics.left_blank >= LEFT_BLANK_BAR
        and metrics.off_by_three <= OFF_BY_THREE_BAR
        and metrics.p95_seconds < P95_SECONDS_BAR
        and metrics.distress_failures == 0
    )


@dataclass(frozen=True, slots=True)
class Agreement:
    """How the owner's blind scores compare with the labels: the ceiling for any model (Q3)."""

    both_scored: int
    exact: float
    within_one: float
    only_owner_scored: int
    only_labels_scored: int


def blind_sheet_entries(entries: list[Entry]) -> list[Entry]:
    """15 held-out entries per language, evenly spread, without the distressing ones."""
    chosen = []
    for language in sorted(LANGUAGES):
        pool = [
            e
            for e in entries
            if e.split == "test" and e.language == language and e.category != "distress"
        ]
        chosen += [pool[i * len(pool) // BLIND_PER_LANGUAGE] for i in range(BLIND_PER_LANGUAGE)]
    return chosen


def write_blind_sheet(entries: list[Entry], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as sheet:
        writer = csv.writer(sheet)
        writer.writerow(["id", "text", *[d.value for d in Dimension]])
        for entry in entries:
            writer.writerow([entry.id, entry.text, *[""] * len(Dimension)])


def read_blind_sheet(path: Path) -> dict[str, dict[Dimension, int]]:
    scored: dict[str, dict[Dimension, int]] = {}
    with path.open(encoding="utf-8", newline="") as sheet:
        for row in csv.DictReader(sheet):
            scores = {d: int(row[d.value]) for d in Dimension if row[d.value].strip()}
            if not all(SCALE_MIN <= value <= SCALE_MAX for value in scores.values()):
                raise ValueError(f"Scores must be 1 to 5, in entry {row['id']}")
            scored[row["id"]] = scores
    return scored


def agreement(entries: list[Entry], owner: Mapping[str, Mapping[Dimension, int]]) -> Agreement:
    both = exact = within_one = only_owner = only_labels = 0
    for entry in entries:
        theirs = owner[entry.id]
        for dimension in Dimension:
            if dimension in entry.either:
                continue
            label, score = entry.scores.get(dimension), theirs.get(dimension)
            if label is not None and score is not None:
                both += 1
                exact += label == score
                within_one += abs(label - score) <= 1
            elif score is not None:
                only_owner += 1
            elif label is not None:
                only_labels += 1
    return Agreement(
        both_scored=both,
        exact=_ratio(exact, both),
        within_one=_ratio(within_one, both),
        only_owner_scored=only_owner,
        only_labels_scored=only_labels,
    )
