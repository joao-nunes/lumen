"""AC-1 of spec 006, and spec 007. A bug in these sums could report a bar as met when it isn't."""

import json
from collections.abc import Collection
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from lumen.domain.dimensions import Dimension, dimensions_for
from lumen.suggestions.evaluation import (
    Agreement,
    Entry,
    Metrics,
    Outcome,
    agreement,
    blind_sheet_entries,
    collect,
    labelled_by_owner,
    load_entries,
    measure,
    meets_bar,
    read_blind_sheet,
    record_if_met,
    write_blind_sheet,
)
from lumen.suggestions.model import (
    STARTER_TAGS,
    Suggestion,
    SuggestionsUnavailableError,
    offered_tags,
)
from lumen.suggestions.prompt import INVENTED_TAGS, day_types

MOOD, ENERGY, STRESS = Dimension.MOOD, Dimension.ENERGY, Dimension.STRESS
ENTRIES = Path(__file__).parents[2] / "evals" / "extraction" / "entries.jsonl"
SCORED = ENTRIES.with_name("owner_scores.csv")


def entry(
    scores: dict[Dimension, int],
    tags: tuple[str, ...] = (),
    either: tuple[Dimension, ...] = (),
    category: str = "terse",
) -> Entry:
    return Entry(
        id="x",
        split="dev",
        language="en",
        category=category,
        text="x",
        scores=scores,
        tags=frozenset(tags),
        either=frozenset(either),
    )


def outcome(
    labelled: Entry, scores: dict[Dimension, int] | None, tags: tuple[str, ...] = ()
) -> Outcome:
    return Outcome(
        labelled, None if scores is None else Suggestion(scores=scores, tags=frozenset(tags))
    )


ALL_SEVEN = len(Dimension)


def test_a_blank_lowers_coverage_rather_than_counting_as_a_wrong_suggestion() -> None:
    metrics = measure([outcome(entry({MOOD: 3, ENERGY: 3}), {MOOD: 3})])

    assert metrics.addressed == 2
    assert metrics.coverage == 0.5
    assert metrics.within_one == 1.0  # of the one score it suggested
    assert metrics.exact == 0.5
    assert metrics.off_by_three == 0


def test_score_distance_is_measured_both_ways() -> None:
    metrics = measure(
        [
            outcome(entry({MOOD: 3}), {MOOD: 3}),  # exact
            outcome(entry({MOOD: 3}), {MOOD: 4}),  # within one, above
            outcome(entry({MOOD: 3}), {MOOD: 2}),  # within one, below
            outcome(entry({MOOD: 3}), {MOOD: 5}),  # two away
            outcome(entry({MOOD: 5}), {MOOD: 1}),  # four away
            outcome(entry({MOOD: 1}), {MOOD: 4}),  # three away, above
            outcome(entry({MOOD: 4}), {MOOD: 1}),  # three away, below
            outcome(entry({MOOD: 3}), {}),  # blank
        ]
    )

    assert metrics.addressed == 8
    assert metrics.coverage == 7 / 8
    assert metrics.within_one == 3 / 7  # of the 7 it suggested
    assert metrics.exact == 1 / 8  # of the 8 addressed
    assert metrics.off_by_three == 3 / 8  # of the 8 addressed, as the owner approved


def test_scores_on_unaddressed_dimensions_dont_count_towards_within_one() -> None:
    metrics = measure([outcome(entry({MOOD: 3}), {MOOD: 3, ENERGY: 1})])
    assert (metrics.within_one, metrics.coverage) == (1.0, 1.0)


def test_an_invented_score_on_an_unaddressed_dimension_counts_against_blanks() -> None:
    metrics = measure([outcome(entry({MOOD: 3}), {MOOD: 3, ENERGY: 2})])

    assert metrics.unaddressed == ALL_SEVEN - 1
    assert metrics.left_blank == (ALL_SEVEN - 2) / (ALL_SEVEN - 1)


def test_a_dimension_marked_either_way_counts_in_neither_measure() -> None:
    labelled = entry({MOOD: 3}, either=(ENERGY,))

    filled = measure([outcome(labelled, {MOOD: 3, ENERGY: 1})])
    blank = measure([outcome(labelled, {MOOD: 3})])

    assert filled.addressed == blank.addressed == 1
    assert filled.within_one == blank.within_one == 1
    assert filled.coverage == blank.coverage == 1
    assert filled.unaddressed == blank.unaddressed == ALL_SEVEN - 2
    assert filled.left_blank == blank.left_blank == 1


def test_a_failed_call_counts_as_wrong_everywhere() -> None:
    metrics = measure(
        [
            outcome(entry({MOOD: 3}), None),
            outcome(entry({MOOD: 3}, category="distress"), None),
        ]
    )

    assert metrics.within_one == 0
    assert metrics.coverage == 0
    assert metrics.left_blank == 0  # a failure must not look like correctly leaving things blank
    assert metrics.addressed == 2
    assert metrics.unaddressed == 2 * (ALL_SEVEN - 1)
    assert metrics.off_by_three == 0
    assert (metrics.failures, metrics.distress_failures) == (2, 1)


def test_tag_precision_and_recall() -> None:
    metrics = measure(
        [
            outcome(entry({MOOD: 3}, tags=("a", "b")), {MOOD: 3}, tags=("a", "c", "d")),
            outcome(entry({MOOD: 3}, tags=("e",)), None),  # a failure misses its tags
        ]
    )

    assert metrics.tag_precision == 1 / 3
    assert metrics.tag_recall == 1 / 3


def test_nothing_suggested_has_defined_tag_measures() -> None:
    metrics = measure([outcome(entry({MOOD: 3}), {MOOD: 3})])
    assert (metrics.tag_precision, metrics.tag_recall) == (1.0, 1.0)


def test_slowest_time_excludes_the_first_call_which_loads_the_model() -> None:
    labelled = entry({MOOD: 3})
    times = [100.0, *[1.0] * 18, 5.0, 2.0]
    metrics = measure([Outcome(labelled, Suggestion(scores={MOOD: 3}), t) for t in times])

    assert metrics.p95_seconds == 2.0


GOOD = Metrics(
    addressed=300,
    within_one=0.95,
    coverage=0.75,
    exact=0.5,
    off_by_three=0.01,
    unaddressed=300,
    left_blank=0.90,
    tag_precision=0.5,
    tag_recall=0.5,
    p95_seconds=9.99,
    failures=0,
    distress_failures=0,
)


def with_(**changes: float) -> Metrics:
    return Metrics(**{**{f: getattr(GOOD, f) for f in GOOD.__slots__}, **changes})


def test_the_bar_is_met_exactly_at_each_limit() -> None:
    assert meets_bar(GOOD)


@pytest.mark.parametrize(
    "changes",
    [
        {"within_one": 0.949},
        {"coverage": 0.749},
        {"left_blank": 0.899},
        {"off_by_three": 0.0101},
        {"p95_seconds": 10.0},
        {"distress_failures": 1},
        {"addressed": 0},
        {"unaddressed": 0},
    ],
)
def test_the_bar_fails_past_each_limit(changes: dict[str, float]) -> None:
    assert not meets_bar(with_(**changes))


def test_only_the_dimensions_asked_are_measured() -> None:
    asked = (MOOD, ENERGY, STRESS, Dimension.CONCENTRATION, Dimension.SOCIAL_CONNECTION)
    labelled = entry({MOOD: 4, Dimension.SLEEP_QUALITY: 2})

    metrics = measure([Outcome(labelled, Suggestion(scores={MOOD: 4}), asked=asked)])

    assert (metrics.addressed, metrics.coverage, metrics.within_one) == (1, 1.0, 1.0)
    assert (metrics.unaddressed, metrics.left_blank) == (4, 1.0)


class RecordingModel:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Dimension, ...], tuple[str, ...]]] = []

    def suggest(
        self, text: str, dimensions: Collection[Dimension], tags: Collection[str]
    ) -> Suggestion:
        self.calls.append((text, tuple(dimensions), tuple(tags)))
        if text == "fails":
            raise SuggestionsUnavailableError
        return Suggestion(scores={MOOD: 3})


def test_every_note_is_asked_under_every_day_type_with_the_app_s_tags() -> None:
    first, second = day_types()
    model = RecordingModel()
    notes = [replace(entry({MOOD: 3}), text="fine"), replace(entry({MOOD: 3}), text="fails")]
    ticks = iter(range(100))

    outcomes = collect(model, notes, clock=lambda: float(next(ticks)))

    tags = (*INVENTED_TAGS, *STARTER_TAGS)
    assert model.calls == [
        ("fine", first, tags),
        ("fine", second, tags),
        ("fails", first, tags),
        ("fails", second, tags),
    ]
    assert [(o.entry.text, o.asked, o.seconds) for o in outcomes] == [
        ("fine", first, 1.0),
        ("fine", second, 1.0),
        ("fails", first, 1.0),
        ("fails", second, 1.0),
    ]
    assert [o.suggestion is None for o in outcomes] == [False, False, True, True]


def test_the_day_types_cover_every_day_of_the_schedule_and_every_dimension() -> None:
    types = day_types()
    start = date(2026, 1, 1)

    assert {dimensions_for(start + timedelta(days=i)) for i in range(731)} == set(types)
    assert {d for asked in types for d in asked} == set(Dimension)


def test_a_person_s_own_tags_are_offered_first_and_each_tag_once() -> None:
    others = tuple(t for t in STARTER_TAGS if t != "exercise")

    assert offered_tags(["reading", "exercise"]) == ("reading", "exercise", *others)


def test_invented_tags_can_only_count_against_precision() -> None:
    entries = load_entries(ENTRIES)
    labelled = {tag for e in entries for tag in e.tags}

    assert len(INVENTED_TAGS) == len(set(INVENTED_TAGS)) == 12
    assert not set(INVENTED_TAGS) & (labelled | set(STARTER_TAGS))


def test_a_held_out_run_that_meets_the_bar_in_both_languages_is_recorded(tmp_path: Path) -> None:
    path = tmp_path / "measured.json"

    recorded = record_if_met(
        path,
        prompt="some_prompt_v2",
        sha256="abc",
        model="some-model",
        split="test",
        english=with_(),
        portuguese=with_(),
    )

    assert recorded is True
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "prompt": "some_prompt_v2",
        "sha256": "abc",
        "model": "some-model",
        "split": "test",
    }


@pytest.mark.parametrize(
    ("split", "english", "portuguese"),
    [
        ("dev", with_(), with_()),  # the tuning split is no measurement
        ("test", with_(coverage=0.74), with_()),
        ("test", with_(), with_(coverage=0.74)),
    ],
)
def test_anything_else_leaves_the_record_as_it_was(
    tmp_path: Path, split: str, english: Metrics, portuguese: Metrics
) -> None:
    path = tmp_path / "measured.json"
    path.write_text("the earlier record", encoding="utf-8")

    recorded = record_if_met(
        path,
        prompt="some_prompt_v2",
        sha256="abc",
        model="some-model",
        split=split,
        english=english,
        portuguese=portuguese,
    )

    assert recorded is False
    assert path.read_text(encoding="utf-8") == "the earlier record"


def test_the_evaluation_set_is_what_the_spec_says() -> None:
    entries = load_entries(ENTRIES)

    assert len(entries) == 350
    assert len({e.id for e in entries}) == 350
    assert len({e.text for e in entries}) == 350
    for language in ("en", "pt"):
        for split, count in (("dev", 25), ("test", 50), ("test_v1", 50), ("test_v2", 50)):
            assert len([e for e in entries if (e.language, e.split) == (language, split)]) == count
        # Enough of each awkward kind in both splits, or a weakness could go unmeasured.
        for split in ("dev", "test"):
            subset = [e for e in entries if (e.language, e.split) == (language, split)]
            assert {e.category for e in subset} >= {
                "terse",
                "long",
                "mixed",
                "negation",
                "stress",
                "irrelevant",
                "distress",
            }
    assert len([e for e in entries if e.category == "distress"]) >= 10
    for e in entries:
        assert not set(e.scores) & set(e.either), e.id
    irrelevant = [e for e in entries if e.category == "irrelevant"]
    assert irrelevant and all(not e.scores for e in irrelevant)
    # About 100 per language, which is good to roughly 4 points either way (spec 006 §7, 007, 008).
    for language in ("en", "pt"):
        held_out = [e for e in entries if (e.language, e.split) == (language, "test")]
        assert sum(len(e.scores) for e in held_out) >= 100


def test_loading_refuses_a_bad_entry(tmp_path: Path) -> None:
    good = (
        '{"id":"a","split":"dev","language":"en","category":"terse","text":"x",'
        '"scores":{"mood":3},"tags":[]}'
    )
    for bad in (
        good.replace('"mood":3', '"mood":6'),
        good.replace('"mood":3', '"moood":3'),
        good.replace('"split":"dev"', '"split":"other"'),
        good.replace('"language":"en"', '"language":"fr"'),
    ):
        path = tmp_path / "bad.jsonl"
        path.write_text(bad + "\n")
        with pytest.raises(ValueError):
            load_entries(path)

    path = tmp_path / "good.jsonl"
    path.write_text(good + "\n")
    assert load_entries(path)[0].scores == {MOOD: 3}


def test_the_blind_sheet_never_shows_the_labels_and_leaves_out_distress(tmp_path: Path) -> None:
    entries = load_entries(ENTRIES)
    chosen = blind_sheet_entries(entries)

    assert len(chosen) == 30
    assert len([e for e in chosen if e.language == "en"]) == 15
    assert len([e for e in chosen if e.language == "pt"]) == 15
    assert {e.split for e in chosen} == {"test_v1"}
    assert {e.id for e in chosen} == set(read_blind_sheet(SCORED))  # the notes the owner scored
    assert "distress" not in {e.category for e in chosen}
    assert {e.category for e in chosen} >= {"terse", "long", "mixed", "negation", "stress"}
    assert chosen == blind_sheet_entries(entries)  # the same sheet every time

    path = tmp_path / "sheet.csv"
    write_blind_sheet(chosen, path)
    written = path.read_text(encoding="utf-8")
    assert read_blind_sheet(path) == {e.id: {} for e in chosen}  # every score blank
    assert chosen[0].text in written
    assert written.splitlines()[0].split(",") == ["id", "text", *[d.value for d in Dimension]]


def test_reading_scores_back_refuses_a_score_off_the_scale(tmp_path: Path) -> None:
    path = tmp_path / "sheet.csv"
    labelled = entry({MOOD: 3})
    write_blind_sheet([labelled], path)
    path.write_text(path.read_text().replace(",x,,", ",x,7,"))

    with pytest.raises(ValueError, match="1 to 5"):
        read_blind_sheet(path)


def test_agreement_compares_only_what_both_people_scored() -> None:
    first = Entry("a", "test", "en", "terse", "x", {MOOD: 3, ENERGY: 2, STRESS: 5})
    second = Entry("b", "test", "pt", "terse", "x", {MOOD: 1}, either=frozenset({ENERGY}))
    owner = {
        "a": {MOOD: 3, ENERGY: 3, Dimension.SLEEP_QUALITY: 2},  # no stress; added sleep
        "b": {MOOD: 4, ENERGY: 1},  # energy was marked either way, so it isn't compared
    }

    assert agreement([first, second], owner) == Agreement(
        both_scored=3,
        exact=1 / 3,
        within_one=2 / 3,
        only_owner_scored=1,
        only_labels_scored=1,
    )


def test_the_owner_s_scores_replace_the_labels_completely() -> None:
    labelled = Entry(
        "a", "test", "en", "terse", "x", {MOOD: 3}, frozenset({"tag"}), frozenset({ENERGY})
    )

    [theirs] = labelled_by_owner([labelled], {"a": {STRESS: 4}})

    assert theirs.scores == {STRESS: 4}
    assert theirs.either == frozenset()  # the hint was a judgement in the labels, not the owner's
    assert (theirs.id, theirs.text, theirs.language) == ("a", "x", "en")
