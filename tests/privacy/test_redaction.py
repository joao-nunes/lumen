"""Spec 011, first PR: redaction and re-hydration, with a fake detector (AC-1 to AC-10).

The detector is the only slow, non-deterministic part, so it's the only thing faked. The fake
returns raw replies, as the protocol does, so parsing and the schema checks are exercised too.
"""

import json
import unicodedata
from collections import Counter

import pytest

from lumen.privacy.redaction import (
    Pseudonymized,
    RedactionUnavailableError,
    Redactor,
    rehydrate,
)

NOTHING = '{"findings": []}'


def reply(*findings: tuple[str, str]) -> str:
    return json.dumps({"findings": [{"text": text, "type": kind} for text, kind in findings]})


class FakeDetector:
    """Answers with a fixed raw reply per input text, and counts what it was asked."""

    def __init__(self, replies: dict[str, str] | None = None, *, fail_on: str | None = None):
        self.replies = replies or {}
        self.fail_on = fail_on
        self.calls: Counter[str] = Counter()

    def detect(self, text: str) -> str:
        self.calls[text] += 1
        if text == self.fail_on:
            raise RuntimeError(f"model choked on {text}")
        return self.replies.get(text, NOTHING)


def pseudonymize(text: str, found: str = NOTHING, context: str = "") -> Pseudonymized:
    # The detector is asked about the text in NFC, whatever form it arrived in.
    detector = FakeDetector({unicodedata.normalize("NFC", text): found})
    return Redactor(detector).pseudonymize(text, owner="u1", context=context)


AC1_TEXT = (
    "Ana criticised my report at Deloitte again, and I couldn't sleep before my session "
    "with Dr. Costa on Tuesday."
)
AC1_FOUND = reply(("Ana", "PERSON"), ("Costa", "PERSON"), ("Deloitte", "ORG"))


def test_ac1_findings_become_numbered_placeholders() -> None:
    result = pseudonymize(AC1_TEXT, AC1_FOUND)

    assert result.text == (
        "[PERSON_1] criticised my report at [ORG_1] again, and I couldn't sleep before my "
        "session with Dr. [PERSON_2] on Tuesday."
    )
    assert dict(result.mapping) == {
        "[PERSON_1]": "Ana",
        "[ORG_1]": "Deloitte",
        "[PERSON_2]": "Costa",
    }


def test_ac2_every_whole_word_occurrence_ignoring_case_longest_span_wins() -> None:
    text = "Ana Silva called. Ana was upset. Bananas for lunch. ana's day was hard."

    result = pseudonymize(text, reply(("Ana Silva", "PERSON"), ("Ana", "PERSON")))

    assert result.text == (
        "[PERSON_1] called. [PERSON_2] was upset. Bananas for lunch. [PERSON_2]'s day was hard."
    )
    assert dict(result.mapping) == {"[PERSON_1]": "Ana Silva", "[PERSON_2]": "Ana"}


def test_findings_match_across_unicode_forms_and_surrounding_spaces() -> None:
    """Added during implementation: both made a name the model pointed at leak."""
    in_text, in_finding = unicodedata.normalize("NFD", "Inês"), unicodedata.normalize("NFD", "João")
    found = reply(("Inês", "PERSON"), (" Rui ", "PERSON"), (in_finding, "PERSON"))

    result = pseudonymize(f"{in_text} and Rui talked with João. Ines didn't.", found)

    assert result.text == "[PERSON_1] and [PERSON_2] talked with [PERSON_3]. Ines didn't."
    assert dict(result.mapping) == {"[PERSON_1]": "Inês", "[PERSON_2]": "Rui", "[PERSON_3]": "João"}


def test_ac3_a_finding_not_in_the_text_is_ignored_and_the_rest_used() -> None:
    found = reply(("Ana", "PERSON"), ("Zé", "PERSON"), ("", "PERSON"), ("  ", "ORG"))

    result = pseudonymize("Ana called.", found)

    assert result.text == "[PERSON_1] called."
    assert dict(result.mapping) == {"[PERSON_1]": "Ana"}


@pytest.mark.parametrize(
    ("text", "found", "expected"),
    [
        ("Call 912 345 678.", reply(("912 345", "ID")), "Call [CONTACT_1]."),
        ("My NIF is 234567899.", NOTHING, "My NIF is [ID_1]."),
        ("My NIF is 234567890.", NOTHING, "My NIF is [CONTACT_1]."),
    ],
    ids=["model-finding-inside-phone", "valid-nif", "wrong-check-digit-is-phone"],
)
def test_ac3b_overlapping_spans_merge_and_take_the_highest_precedence(
    text: str, found: str, expected: str
) -> None:
    assert pseudonymize(text, found).text == expected


RULE_SHAPED = [
    ("ana@example.com", "CONTACT"),
    ("https://example.com/ana", "CONTACT"),
    ("@ana.s", "CONTACT"),
    ("+351 912 345 678", "CONTACT"),
    ("+351913572468", "CONTACT"),  # starts with the valid NIF 351913572, not a whole token
    ("912 345 678", "CONTACT"),
    ("PT50 0002 0123 1234 5678 9015 4", "ID"),  # a valid Portuguese IBAN
    ("234567899", "ID"),  # a valid NIF
    ("4111119111111111", "ID"),  # a card number holding the phone-shaped 911111111
    ("1100-053", "ADDRESS"),
    ("192.168.1.10", "CONTACT"),
    ("2001:db8::1", "CONTACT"),
    ("12345678 9 ZZ1", "ID"),  # Cartão de Cidadão
    ("12345678", "ID"),
    ("1 500 000", "ID"),
    ("1234-5678", "ID"),
    ("2024-13-45", "ID"),
    ("2024-02-30", "ID"),
    ("45-13-2024", "ID"),
    ("2021-2019", "ID"),
    ("1850-1890", "ID"),
]
SENTENCES = ["Reach me at {} tomorrow.", "Contacta-me em {} amanhã."]


@pytest.mark.parametrize("sentence", SENTENCES, ids=["en", "pt"])
@pytest.mark.parametrize(("identifier", "kind"), RULE_SHAPED, ids=[i for i, _ in RULE_SHAPED])
def test_ac4_rules_replace_fixed_shape_identifiers_without_the_model(
    sentence: str, identifier: str, kind: str
) -> None:
    result = pseudonymize(sentence.format(identifier))

    assert result.text == sentence.format(f"[{kind}_1]")
    assert dict(result.mapping) == {f"[{kind}_1]": identifier}


def test_ac5_rules_keep_numbers_dates_and_words_that_only_look_like_identifiers() -> None:
    text = (
        "My sister, 34, works as a nurse in Portugal. Slept 6 hours, walked 10000 steps on "
        "Tuesday, took 50 mg of sertraline. From 2019-2021 I lived abroad; on 2024-05-03 8 hours "
        "of sleep weren't enough, and again on 03-05-2025."
    )

    result = pseudonymize(text)

    assert result.text == text
    assert dict(result.mapping) == {}


CONTEXT = "My friends Ana and Rosa, my dog Rex. I work at Deloitte and live in Porto."
CONTEXT_FOUND = reply(
    ("Ana", "PERSON"),
    ("Rosa", "PERSON"),
    ("Rex", "NAME"),
    ("Deloitte", "ORG"),
    ("Porto", "PLACE"),
)


def test_ac6_names_from_the_personal_context_are_replaced_when_the_model_misses_them() -> None:
    text = "Ana again. Rosa called; the rosa dress. Walked Rex. Back in Porto, Deloitte phoned."
    detector = FakeDetector({CONTEXT: CONTEXT_FOUND, text: NOTHING})

    result = Redactor(detector).pseudonymize(text, owner="u1", context=CONTEXT)

    assert result.text == (
        "[PERSON_1] again. [PERSON_2] called; the rosa dress. Walked [NAME_1]. "
        "Back in [PLACE_1], [ORG_1] phoned."
    )


def test_ac6b_known_names_are_cached_per_owner_until_the_context_changes() -> None:
    detector = FakeDetector({CONTEXT: CONTEXT_FOUND})
    redactor = Redactor(detector)
    changed = CONTEXT + " Ana moved away."

    redactor.pseudonymize("one", owner="u1", context=CONTEXT)
    redactor.pseudonymize("two", owner="u1", context=CONTEXT)
    assert detector.calls[CONTEXT] == 1

    redactor.pseudonymize("three", owner="u1", context=changed)
    assert detector.calls[changed] == 1

    redactor.pseudonymize("four", owner="u2", context=CONTEXT)
    assert detector.calls[CONTEXT] == 2


def test_ac6b_dates_and_roles_in_the_context_dont_become_known_names() -> None:
    context = "Ana's birthday is 3 May. She is the only paediatric surgeon in town."
    found = reply(("Ana", "PERSON"), ("3 May", "DATE"), ("paediatric surgeon", "ROLE"))
    text = "On 3 May I met a paediatric surgeon."

    result = Redactor(FakeDetector({context: found})).pseudonymize(
        text, owner="u1", context=context
    )

    assert result.text == text


def test_ac7_rehydration_maps_back_only_the_placeholders_lumen_issued() -> None:
    result = pseudonymize(AC1_TEXT, AC1_FOUND)

    answer = "Feedback from [PERSON_1] at [ORG_1] weighs on you; [PERSON_9] isn't mentioned."

    assert rehydrate(answer, result) == (
        "Feedback from Ana at Deloitte weighs on you; [PERSON_9] isn't mentioned."
    )


def test_ac8_placeholders_already_in_the_text_are_skipped_and_stay_literal() -> None:
    result = pseudonymize("I wrote [PERSON_1] in my notes. Ana called.", reply(("Ana", "PERSON")))

    assert result.text == "I wrote [PERSON_1] in my notes. [PERSON_2] called."
    assert rehydrate("[PERSON_1] and [PERSON_2]", result) == "[PERSON_1] and Ana"


MARKER = "marker_private_text"
TEXT = f"{MARKER} Ana called."


class TimingOut(FakeDetector):
    def detect(self, text: str) -> str:
        raise TimeoutError(f"no answer for {text}")


@pytest.mark.parametrize(
    "detector",
    [
        FakeDetector(fail_on=TEXT),
        TimingOut(),
        FakeDetector(fail_on=f"{MARKER} context"),
        *(
            FakeDetector({TEXT: malformed})
            for malformed in [
                f"not json {MARKER}",
                '{"findings": [{"text": "Ana", "ty',
                "[]",
                '{"findings": "Ana"}',
                '{"findings": [{"text": "Ana"}]}',
                '{"findings": [{"text": 5, "type": "PERSON"}]}',
                '{"findings": [{"text": "Ana", "type": "PERSONS"}]}',
                '{"findings": [], "note": "extra"}',
            ]
        ),
    ],
    ids=[
        "raises",
        "times-out",
        "fails-on-context",
        "not-json",
        "cut-off",
        "not-an-object",
        "findings-not-a-list",
        "no-type",
        "text-not-a-string",
        "unknown-type",
        "unexpected-key",
    ],
)
def test_ac9_any_detector_failure_fails_closed_without_quoting_the_text(
    detector: FakeDetector,
) -> None:
    with pytest.raises(RedactionUnavailableError) as raised:
        Redactor(detector).pseudonymize(TEXT, owner="u1", context=f"{MARKER} context")

    error = raised.value
    assert MARKER not in str(error)
    assert MARKER not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_ac10_repr_and_str_hide_the_original_and_the_map() -> None:
    result = pseudonymize(f"{MARKER} Ana called.", reply(("Ana", "PERSON")))

    for shown in (repr(result), str(result)):
        assert MARKER not in shown
        assert "Ana" not in shown
