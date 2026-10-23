from dataclasses import dataclass
from datetime import date

from lumen.domain.dimensions import Dimension


@dataclass(frozen=True, slots=True)
class Observation:
    """A single score for one dimension on the user's local day."""

    day: date
    dimension: Dimension
    value: int
