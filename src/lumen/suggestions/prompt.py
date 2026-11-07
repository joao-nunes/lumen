"""Renders the prompt for suggesting check-in scores (spec 006).

The wording lives in `prompts/`, and each version is a new file: the accuracy bar was met by one
exact prompt, and `evals/extraction/measured_prompt.json` records which one.
"""

import hashlib
import json
from collections.abc import Collection
from importlib.resources import files
from string import Template

from lumen.domain.dimensions import (
    DIMENSIONS,
    SCALE_MAX,
    SCALE_MIN,
    Dimension,
    Polarity,
)
from lumen.suggestions.model import STARTER_TAGS

PROMPT_NAME = "checkin_extraction_v1"

# Read at import, so that a missing file stops the app from starting rather than failing later.
_TEMPLATE = Template(
    files("lumen.suggestions").joinpath("prompts", f"{PROMPT_NAME}.txt").read_text(encoding="utf-8")
)


def _describe(dimension: Dimension) -> str:
    spec = DIMENSIONS[dimension]
    direction = (
        "Higher means MORE of it, which is worse."
        if spec.polarity is Polarity.HIGHER_IS_WORSE
        else "Higher is better."
    )
    anchors = "\n".join(
        f"  {SCALE_MIN + i} = {anchor.label}: {anchor.description}"
        for i, anchor in enumerate(spec.anchors)
    )
    return f"{dimension.value} ({spec.display_name}). {direction}\n{anchors}"


def checkin_extraction_prompt(dimensions: Collection[Dimension], tags: Collection[str]) -> str:
    shape = {
        "dimensions": {
            d.value: {"quote": "... or null", "score": "1-5 or null"} for d in dimensions
        },
        "tags": ["..."],
    }
    return _TEMPLATE.substitute(
        scale_min=SCALE_MIN,
        scale_max=SCALE_MAX,
        described="\n\n".join(_describe(d) for d in dimensions),
        offered=", ".join(tags) if tags else "(none)",
        shape=json.dumps(shape),
    )


def prompt_fingerprint() -> str:
    """The hash of the prompt as the evaluation sends it, so anchors and starter tags count too."""
    rendered = checkin_extraction_prompt(tuple(Dimension), STARTER_TAGS)
    return hashlib.sha256(rendered.encode()).hexdigest()
