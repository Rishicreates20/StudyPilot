"""A deterministic stand-in for an embedding model: for tests and explicit local development ONLY.

It turns a text into a vector by *feature hashing*: every meaningful word is hashed to one of the
1536 positions with a sign, the counts are damped and the whole vector is scaled to length 1. Two
texts that share words therefore have a high cosine similarity and unrelated texts have a similarity
near zero, which is what retrieval needs, so the whole pipeline (chunk, embed, store, search, cite)
can be exercised and tested without a model. It is *not* semantic: it cannot tell that "car" and
"automobile" mean the same thing. Everything it produces is marked ``synthetic``.
"""

import hashlib
import math
import re
from collections import Counter

from app.ai.provider import EMBEDDING_DIMENSIONS

_WORD = re.compile(r"\w+", re.UNICODE)

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "so",
        "than",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
        "about",
        "can",
        "do",
        "does",
        "not",
        "no",
    }
)


def words(text: str) -> list[str]:
    """The meaningful, lightly normalised words of ``text`` (lower case, plurals folded)."""
    found: list[str] = []
    for word in _WORD.findall(text.casefold()):
        if len(word) < 2 or word in _STOP_WORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        found.append(word)
    return found


def hashed_vector(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """A unit vector of ``dimensions`` numbers built from the words of ``text``."""
    vector = [0.0] * dimensions
    for word, count in Counter(words(text)).items():
        digest = hashlib.blake2b(word.encode("utf-8"), digest_size=8).digest()
        position = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[position] += sign * (1.0 + math.log(count))
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0.0:
        # No meaningful word at all: still a valid unit vector, the same for every such text.
        vector[0] = 1.0
        return vector
    return [value / length for value in vector]


def normalised(values: list[float]) -> list[float]:
    """``values`` scaled to length 1 (an all-zero vector is returned unchanged)."""
    length = math.sqrt(sum(value * value for value in values))
    return values if length == 0.0 else [value / length for value in values]
