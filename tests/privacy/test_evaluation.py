"""Spec 011 §2.6: how a redaction run is measured, and when it counts as meeting the bar."""

import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from lumen.privacy.evaluation import (
    DIRECT,
    Entry,
    Identifier,
    Metrics,
    Outcome,
    RunAbortedError,
    agreement,
    collect,
    load_entries,
    measure,
    meets_bar,
    read_owner_sheet,
    record_if_met,
)
from lumen.privacy.redaction import Pseudonymized, Redactor
from lumen.privacy.rules import IdentifierType as T

EVALS = Path(__file__).parents[2] / "evals" / "redaction"


def entry(
    text: str,
    *identifiers: tuple[str, T],
    decoys: tuple[str, ...] = (),
    language: str = "en",
    category: str = "names",
) -> Entry:
    return Entry(
        id="e1",
        split="test",
        language=language,
        category=category,
        text=text,
        identifiers=tuple(Identifier(t, k) for t, k in identifiers),
        decoys=decoys,
    )


def outcome(
    e: Entry, text: str | None, seconds: float = 1.0, *, loads_model: bool = False, **mapping: str
) -> Outcome:
    result = None if text is None else Pseudonymized(text, MappingProxyType(mapping))
    return Outcome(e, result, seconds, loads_model=loads_model)


def metrics(**changes: float) -> Metrics:
    """Every figure exactly at its bar."""
    passing = Metrics(
        direct=20,
        direct_recall=0.95,
        contextual=20,
        contextual_recall=0.85,
        decoys=10,
        decoys_kept=0.90,
        entries=10,
        leak_free=0.5,
        right_type=0.5,
        p95_seconds=9.99,
        failures=0,
        distress_failures=0,
    )
    return replace(passing, **changes)


def test_an_identifier_is_caught_only_when_no_word_of_it_survives() -> None:
    e = entry(
        "Ana Silva saw Joy at Hospital de Santa Maria; joy came back de manhã.",
        ("Ana Silva", T.PERSON),
        ("Joy", T.PERSON),
        ("Hospital de Santa Maria", T.ORG),
    )
    output = "[PERSON_1] Silva saw [PERSON_2] at [ORG_1]; joy came back de manhã."

    result = measure([outcome(e, output)])

    # "Silva" survived. The lowercase "joy" is the feeling, and "de" is also outside identifiers.
    assert (result.direct, result.direct_recall) == (3, pytest.approx(2 / 3))
    assert result.leak_free == 0.0


def test_replacing_the_feeling_instead_of_the_name_is_a_miss_and_a_lost_decoy() -> None:
    e = entry("Joy felt joy.", ("Joy", T.PERSON), decoys=("joy",))

    result = measure([outcome(e, "Joy felt [PERSON_1].")])

    assert (result.direct_recall, result.decoys_kept) == (0.0, 0.0)


def test_a_word_shared_with_the_rest_of_the_entry_still_counts_when_it_survives_twice() -> None:
    e = entry("Rua de Cima 3, de novo.", ("Rua de Cima 3", T.ADDRESS))

    assert measure([outcome(e, "Rua de [ADDRESS_1], de novo.")]).direct_recall == 0.0


def test_direct_and_contextual_identifiers_and_decoys_are_measured_apart() -> None:
    e = entry(
        "My sister met Rex in Porto on 3 May, my birthday.",
        ("Rex", T.NAME),
        ("Porto", T.PLACE),
        ("3 May", T.DATE),
        decoys=("My sister", "birthday"),
    )
    output = "My [ID_1] met [NAME_1] in [PLACE_1] on 3 May, my birthday."

    result = measure([outcome(e, output, **{"[NAME_1]": "Rex", "[PLACE_1]": "Porto"})])

    assert (result.direct, result.contextual) == (0, 3)
    assert result.contextual_recall == pytest.approx(2 / 3)
    assert (result.decoys, result.decoys_kept) == (2, 0.5)
    assert result.right_type == 1.0


def test_a_caught_identifier_with_the_wrong_placeholder_type_is_counted_as_a_wrong_type() -> None:
    e = entry("Ana works at Deloitte.", ("Ana", T.PERSON), ("Deloitte", T.ORG))
    output = "[PERSON_1] works at [PLACE_1]."

    result = measure([outcome(e, output, **{"[PERSON_1]": "Ana", "[PLACE_1]": "Deloitte"})])

    assert (result.direct_recall, result.right_type, result.leak_free) == (1.0, 0.5, 1.0)


def test_a_failed_entry_misses_all_its_identifiers_and_loses_its_decoys() -> None:
    e = entry("Ana is my sister.", ("Ana", T.PERSON), decoys=("my sister",), category="distressing")

    result = measure([outcome(e, None)])

    assert (result.direct_recall, result.decoys_kept, result.leak_free) == (0.0, 0.0, 0.0)
    assert (result.failures, result.distress_failures) == (1, 1)


def test_the_slowest_time_leaves_out_only_the_call_that_loaded_the_model() -> None:
    e = entry("Ana.", ("Ana", T.PERSON))
    loading = outcome(e, "[PERSON_1].", 30.0, loads_model=True)
    others = [outcome(e, "[PERSON_1].", s) for s in [*([1.0] * 19), 4.0]]

    result = measure([loading, *others])

    assert result.p95_seconds == 1.0
    assert measure([loading, *others[:-2], *[outcome(e, "[PERSON_1].", 4.0)] * 2]) == (
        replace(result, p95_seconds=4.0)
    )
    # Another language's first call didn't load the model, so it counts.
    unmarked = [outcome(e, "[PERSON_1].", s) for s in (30.0, 1.0, 1.0)]
    assert measure(unmarked).p95_seconds == 30.0


def test_the_bar_is_met_exactly_at_each_limit() -> None:
    assert meets_bar(metrics())


@pytest.mark.parametrize(
    "changes",
    [
        {"direct_recall": 0.9499},
        {"contextual_recall": 0.8499},
        {"decoys_kept": 0.8999},
        {"p95_seconds": 10.0},
        {"distress_failures": 1},
        {"direct": 0},
        {"contextual": 0},
        {"decoys": 0},
    ],
)
def test_the_bar_fails_past_each_limit_or_with_nothing_to_measure(
    changes: dict[str, float],
) -> None:
    assert not meets_bar(metrics(**changes))


def test_a_held_out_run_that_meets_the_bar_in_every_language_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "measured.json"

    recorded = record_if_met(
        path,
        prompt="redaction_v1",
        sha256="abc",
        model="some-model",
        split="test",
        by_language={"en": metrics(), "pt": metrics(), "mixed": metrics()},
    )

    assert recorded is True
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "prompt": "redaction_v1",
        "sha256": "abc",
        "model": "some-model",
        "split": "test",
    }


@pytest.mark.parametrize(
    ("split", "by_language"),
    [
        ("dev", {"en": metrics(), "pt": metrics(), "mixed": metrics()}),
        ("test", {"en": metrics(), "pt": metrics(), "mixed": metrics(direct_recall=0.94)}),
        ("test", {"en": metrics(), "pt": metrics()}),
    ],
    ids=["tuning-split", "one-language-below", "a-language-missing"],
)
def test_anything_else_leaves_the_record_as_it_was(
    tmp_path: Path, split: str, by_language: dict[str, Metrics]
) -> None:
    path = tmp_path / "measured.json"
    path.write_text("the earlier record", encoding="utf-8")

    recorded = record_if_met(
        path, prompt="v", sha256="abc", model="m", split=split, by_language=by_language
    )

    assert recorded is False
    assert path.read_text(encoding="utf-8") == "the earlier record"


class Scripted:
    """A detector that finds the names it's given, or fails."""

    def __init__(self, names: dict[str, str | None]) -> None:
        self.names = names

    def detect(self, text: str) -> str:
        name = self.names[text]
        if name is None:
            raise TimeoutError
        return json.dumps({"findings": [{"text": name, "type": "PERSON"}]})


def test_collect_redacts_each_entry_as_the_app_would_and_times_it() -> None:
    first = replace(entry("Ana called.", ("Ana", T.PERSON)), id="a")
    second = replace(entry("Rui called.", ("Rui", T.PERSON)), id="b")
    ticks = iter([0.0, 2.0, 10.0, 13.5])

    outcomes = collect(
        Redactor(Scripted({"Ana called.": "Ana", "Rui called.": None})),
        [first, second],
        clock=lambda: next(ticks),
    )

    assert [(o.entry.id, o.seconds, o.loads_model) for o in outcomes] == [
        ("a", 2.0, True),
        ("b", 3.5, False),
    ]
    assert outcomes[0].result is not None and outcomes[0].result.text == "[PERSON_1] called."
    assert outcomes[1].result is None


def test_a_run_stops_after_three_failed_calls_in_a_row_rather_than_reporting_them() -> None:
    entries = [replace(entry(f"Note {i}."), id=str(i)) for i in range(4)]

    with pytest.raises(RunAbortedError):
        collect(Redactor(Scripted(dict.fromkeys((e.text for e in entries), None))), entries)


def test_agreement_counts_each_distinct_form_once(tmp_path: Path) -> None:
    sheet = tmp_path / "owner.csv"
    sheet.write_text(
        "id,text,identifiers\n"
        'e1,"Ana and ana met Rui.","Ana;Ana; Rui ;Lisbon"\n'
        "e2,Nothing here.,\n",
        encoding="utf-8",
    )
    entries = [
        entry("Ana and ana met Rui.", ("Ana", T.PERSON), ("ana", T.PERSON), ("Rui", T.PERSON)),
        replace(entry("Nothing here."), id="e2"),
    ]

    owner = read_owner_sheet(sheet)
    result = agreement(entries, owner)

    assert owner == {"e1": frozenset({"Ana", "Rui", "Lisbon"}), "e2": frozenset()}
    assert (result.labelled, result.marked, result.both) == (3, 3, 2)


def test_loading_refuses_a_label_the_measurement_couldn_t_use(tmp_path: Path) -> None:
    good = {
        "id": "x",
        "split": "test",
        "language": "en",
        "category": "names",
        "text": "Ana called.",
        "identifiers": [{"text": "Ana", "type": "PERSON"}],
        "decoys": [],
    }
    path = tmp_path / "entries.jsonl"
    decomposed = "Ine\u0301s"  # the output is NFC, so this form would never be found in it
    for bad, problem in (
        ({"split": "train"}, "an unknown split or language"),
        ({"language": "fr"}, "an unknown split or language"),
        ({"identifiers": [{"text": "Ana", "type": "PERSONS"}]}, "an unknown type"),
        ({"identifiers": [{"text": "Rui", "type": "PERSON"}]}, "an identifier that isn't in"),
        ({"decoys": ["sister"]}, "a decoy that isn't in"),
        (
            {
                "text": f"{decomposed} called.",
                "identifiers": [{"text": decomposed, "type": "PERSON"}],
            },
            "text that isn't NFC",
        ),
    ):
        path.write_text(json.dumps(good | bad) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match=f"Entry x has {problem}"):
            load_entries(path)


def test_the_evaluation_set_is_what_the_spec_says() -> None:
    entries = load_entries(EVALS / "entries.jsonl")

    held_out = [e for e in entries if e.split == "test"]
    assert (len(entries), len(held_out)) == (510, 225)
    for language in ("en", "pt", "mixed"):
        own = [e for e in held_out if e.language == language]
        direct = [i for e in own for i in e.identifiers if i.type in DIRECT]
        assert len(own) == 75
        assert len(direct) >= 210  # spec 011 §10: about ±3 points at 95%
