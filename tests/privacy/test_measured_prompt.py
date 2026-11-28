"""Spec 011 AC-12: the bar was met by one exact prompt, so a change must be measured again."""

import json
from pathlib import Path

from lumen.privacy.evaluation import SPLITS
from lumen.privacy.ollama import PROMPT_NAME, prompt_fingerprint

MEASURED = Path(__file__).parents[2] / "evals" / "redaction" / "measured_prompt.json"


def test_ac12_the_prompt_in_use_is_the_one_measured_on_the_held_out_split() -> None:
    record = json.loads(MEASURED.read_text(encoding="utf-8"))

    # Spec 011 §8.5: the record names its split as it's called now, so a retired one (test_vN).
    assert record["prompt"] == PROMPT_NAME
    assert record["split"] in SPLITS - {"dev"}
    assert record["sha256"] == prompt_fingerprint(), (
        "The redaction prompt changed since it was measured: add a new version, "
        "and measure it on new held-out entries (developer guide, 'Change a prompt')."
    )
