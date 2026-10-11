"""Helpers every prompt uses to keep untrusted text inert.

Everything a learner typed (and anything derived from it) is untrusted. It is JSON-encoded and
fenced inside a tag such as ``<learner_data>`` with ``<`` and ``>`` escaped, so the text cannot
close the fence or open another tag; the system prompt then says the fenced block is data, not
instructions.
"""

import json
from typing import Any


def escape_tags(text: str) -> str:
    """Make ``<`` and ``>`` inert inside JSON text so it cannot close or open a tag."""
    return text.replace("<", "\\u003c").replace(">", "\\u003e")


def data_block(value: Any) -> str:
    """JSON that cannot close or open an XML-style tag, whatever the text inside says."""
    return escape_tags(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
