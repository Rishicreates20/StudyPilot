"""A rule a model's answer broke, worded so it can be handed back for one repair attempt."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
