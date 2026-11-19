"""Spec 011 §2.6: the rules on the evaluation set, without the model.

Rule-shaped identifiers must all be caught (a miss is a bug in the rules), and the rules must
never touch a decoy. Malformed labels would make the measurement meaningless, so they fail here.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from lumen.privacy.redaction import Redactor
from lumen.privacy.rules import IdentifierType

ENTRIES = [
    json.loads(line)
    for line in (Path(__file__).parents[2] / "evals/redaction/entries.jsonl")
    .read_text()
    .splitlines()
]


class FindsNothing:
    def detect(self, text: str) -> str:
        return '{"findings": []}'


def present(needle: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text) is not None


def test_the_labels_are_well_formed() -> None:
    assert len({e["id"] for e in ENTRIES}) == len(ENTRIES)
    for entry in ENTRIES:
        assert entry["split"] in {"dev", "test"}
        assert entry["language"] in {"en", "pt", "mixed"}
        for identifier in entry["identifiers"]:
            assert identifier["type"] in set(IdentifierType), entry["id"]
            assert present(identifier["text"], entry["text"]), entry["id"]
        for decoy in entry["decoys"]:
            assert present(decoy, entry["text"]), entry["id"]


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["id"] for e in ENTRIES])
def test_rules_alone_catch_every_rule_shaped_identifier_and_keep_every_decoy(
    entry: dict[str, Any],
) -> None:
    output = Redactor(FindsNothing()).pseudonymize(entry["text"], owner="eval", context="").text

    left = [i["text"] for i in entry["identifiers"] if i.get("rule") and present(i["text"], output)]
    lost = [d for d in entry["decoys"] if not present(d, output)]
    assert (left, lost) == ([], [])
