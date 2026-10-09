"""Opaque keyset-pagination cursors.

A cursor only records the sort position (``created_at``, ``id``) of the last row returned. It
grants no access by itself: every query that uses it is still scoped to the caller by both the
repository's ``user_id`` filter and Row Level Security, so a forged cursor can only skip or repeat
the caller's own rows.
"""

import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from app.core.errors import InvalidRequestError


def encode_cursor(created_at: datetime, row_id: UUID) -> str:
    payload = json.dumps({"c": created_at.isoformat(), "i": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        created_at = datetime.fromisoformat(data["c"])
        if created_at.tzinfo is None:
            raise ValueError("naive timestamp")
        return created_at, UUID(data["i"])
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise InvalidRequestError(
            "The pagination cursor is not valid.", code="INVALID_CURSOR"
        ) from exc
