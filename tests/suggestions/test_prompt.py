"""The accuracy bar was met by one exact prompt, so a changed prompt must be measured again."""

import json
from pathlib import Path

from lumen.suggestions.prompt import PROMPT_NAME, prompt_fingerprint

MEASURED = Path(__file__).parents[2] / "evals" / "extraction" / "measured_prompt.json"


def test_the_prompt_in_use_is_the_one_measured_on_the_held_out_split() -> None:
    record = json.loads(MEASURED.read_text(encoding="utf-8"))

    assert (record["prompt"], record["split"]) == (PROMPT_NAME, "test")
    assert record["sha256"] == prompt_fingerprint(), (
        "The prompt changed since it was measured: add a new version, and measure it on new "
        "held-out notes (developer guide, 'Change a prompt')."
    )
