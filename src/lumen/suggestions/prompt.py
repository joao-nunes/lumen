"""Renders the prompt for suggesting check-in scores (spec 006).

The wording lives in `prompts/`, and each version is a new file: the accuracy bar was met by one
exact prompt, and `evals/extraction/measured_prompt.json` records which one.

The app sends a day's dimensions and a person's own tags, so that's what gets measured (spec 007).
"""

import hashlib
import json
from collections.abc import Collection
from datetime import date, timedelta
from importlib.resources import files
from string import Template

from lumen.domain.dimensions import (
    DIMENSIONS,
    SCALE_MAX,
    SCALE_MIN,
    Dimension,
    Polarity,
    dimensions_for,
)
from lumen.suggestions.model import offered_tags

PROMPT_NAME = "checkin_extraction_v2"

# Stand in for a person's own tags, which can't go in a public repository. No note mentions these
# and no label uses them, so choosing one always counts against precision.
INVENTED_TAGS = (
    "piano_practice",
    "dog_walk",
    "board_games",
    "volunteering",
    "pottery",
    "language_class",
    "knitting",
    "birdwatching",
    "chess",
    "baking",
    "museum_visit",
    "choir",
)

_SCHEDULE_START = date(2026, 1, 1)
_SCHEDULE_DAYS = 14  # A test checks that this sees every day type the schedule can produce.

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


def _outline(dimension: Dimension) -> str:
    spec = DIMENSIONS[dimension]
    lowest, highest = spec.anchors[0].description, spec.anchors[-1].description
    return f'- {dimension.value} ({spec.display_name}): from "{lowest}" to "{highest}"'


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
        # v2: naming what isn't asked stops the model moving it onto what is (spec 007).
        not_asked="\n".join(_outline(d) for d in Dimension if d not in dimensions) or "(none)",
        offered=", ".join(tags) if tags else "(none)",
        shape=json.dumps(shape),
    )


def day_types() -> tuple[tuple[Dimension, ...], ...]:
    """The different sets of dimensions the schedule asks about, read from the schedule itself."""
    days = (_SCHEDULE_START + timedelta(days=i) for i in range(_SCHEDULE_DAYS))
    return tuple(dict.fromkeys(dimensions_for(day) for day in days))


def measured_requests() -> tuple[tuple[tuple[Dimension, ...], tuple[str, ...]], ...]:
    """What the evaluation asks the model for, once per note."""
    tags = offered_tags(INVENTED_TAGS)
    return tuple((asked, tags) for asked in day_types())


def prompt_fingerprint() -> str:
    """The hash of every prompt the evaluation sends, so anchors and tags count too."""
    rendered = "\n".join(checkin_extraction_prompt(*request) for request in measured_requests())
    return hashlib.sha256(rendered.encode()).hexdigest()
