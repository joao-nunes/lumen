"""Measures a model against the evaluation set (spec 006 §3, spec 007). Only `collect` calls it."""

import csv
import json
import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from lumen.domain.dimensions import SCALE_MAX, SCALE_MIN, Dimension
from lumen.suggestions.model import Suggestion, SuggestionModel, SuggestionsUnavailableError
from lumen.suggestions.prompt import request_for

# "test" is the held-out split for the current measurement. The others held earlier ones and have
# been read, so they're never tuned on or measured against again: "test_v1" (spec 006, which keeps
# the owner's blind scores), "test_v2" (spec 007) and "test_v3" (spec 008).
SPLITS = frozenset({"dev", "test", "test_v1", "test_v2", "test_v3"})
BLIND_SPLIT = "test_v1"
LANGUAGES = frozenset({"en", "pt"})

WITHIN_ONE_BAR = 0.95
COVERAGE_BAR = 0.75
LEFT_BLANK_BAR = 0.90
OFF_BY_THREE_BAR = 0.01
P95_SECONDS_BAR = 10.0
TAG_PRECISION_BAR = 0.85  # spec 010 Q4: a wrong tag distorts analysis unnoticed
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
    # An invented personal context the labels take into account (spec 010), or "" for none.
    context: str = ""


@dataclass(frozen=True, slots=True)
class Outcome:
    entry: Entry
    suggestion: Suggestion | None  # None: the call failed
    seconds: float = 0.0
    asked: tuple[Dimension, ...] = tuple(Dimension)


@dataclass(frozen=True, slots=True)
class Metrics:
    addressed: int
    within_one: float  # of the scores it suggested on addressed dimensions
    coverage: float  # of the addressed dimensions, how many it scored
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
                context=raw.get("context", ""),
            )
        )
    return entries


# More failures in a row than a model ever gave in a working run: Ollama has stopped, and the
# rest of the run would only report failures (spec 008 §7).
MAX_FAILURES_IN_A_ROW = 3


class RunAbortedError(Exception):
    """The run stopped rather than report results that only measure an outage."""


def collect(
    model: SuggestionModel,
    entries: Iterable[Entry],
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> list[Outcome]:
    """Asks about every note as the app would, under each kind of day (spec 007 §2.1)."""
    outcomes: list[Outcome] = []
    failures_in_a_row = 0
    for entry in entries:
        for asked, tags, context in (request_for(entry.context),):
            started = clock()
            try:
                suggestion: Suggestion | None = model.suggest(entry.text, asked, tags, context)
            except SuggestionsUnavailableError:
                suggestion = None
            outcomes.append(Outcome(entry, suggestion, clock() - started, asked))
            failures_in_a_row = failures_in_a_row + 1 if suggestion is None else 0
            if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
                raise RunAbortedError(f"{MAX_FAILURES_IN_A_ROW} failed calls in a row")
    return outcomes


def _ratio(part: int, whole: int, *, empty: float = 0.0) -> float:
    return part / whole if whole else empty


def measure(outcomes: list[Outcome]) -> Metrics:
    addressed = suggested = exact = within_one = off_by_three = 0
    unaddressed = left_blank = 0
    suggested_tags = correct_tags = labelled_tags = 0

    for outcome in outcomes:
        entry, suggestion = outcome.entry, outcome.suggestion
        for dimension in outcome.asked:
            if dimension in entry.either:
                continue
            guess = None if suggestion is None else suggestion.scores.get(dimension)
            if dimension in entry.scores:
                addressed += 1
                if guess is not None:
                    suggested += 1
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
        within_one=_ratio(within_one, suggested),
        coverage=_ratio(suggested, addressed),
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
        and metrics.coverage >= COVERAGE_BAR
        and metrics.left_blank >= LEFT_BLANK_BAR
        and metrics.off_by_three <= OFF_BY_THREE_BAR
        and metrics.p95_seconds < P95_SECONDS_BAR
        and metrics.distress_failures == 0
        and metrics.tag_precision >= TAG_PRECISION_BAR
    )


def record_if_met(
    path: Path,
    *,
    prompt: str,
    sha256: str,
    model: str,
    split: str,
    english: Metrics,
    portuguese: Metrics,
) -> bool:
    """Records the prompt only for a held-out run that meets the bar in both languages."""
    if split != "test" or not (meets_bar(english) and meets_bar(portuguese)):
        return False
    record = {"prompt": prompt, "sha256": sha256, "model": model, "split": split}
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return True


@dataclass(frozen=True, slots=True)
class Agreement:
    """How the owner's blind scores compare with the labels: the ceiling for any model (Q3)."""

    both_scored: int
    exact: float
    within_one: float
    only_owner_scored: int
    only_labels_scored: int


def blind_sheet_entries(entries: list[Entry]) -> list[Entry]:
    """The 15 entries per language the owner scored, evenly spread, without distressing ones."""
    chosen = []
    for language in sorted(LANGUAGES):
        pool = [
            e
            for e in entries
            if e.split == BLIND_SPLIT and e.language == language and e.category != "distress"
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


def labelled_by_owner(
    entries: list[Entry], owner: Mapping[str, Mapping[Dimension, int]]
) -> list[Entry]:
    """The same notes with the owner's scores as the truth: an independent check on the labels,
    since the model and the labels' author may read notes in the same way."""
    return [replace(e, scores=dict(owner[e.id]), either=frozenset()) for e in entries]
