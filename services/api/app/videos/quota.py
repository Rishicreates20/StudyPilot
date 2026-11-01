"""The day the YouTube quota belongs to. YouTube resets its daily quota at midnight Pacific Time."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

_PACIFIC = ZoneInfo("America/Los_Angeles")


def quota_day(moment: datetime | None = None) -> date:
    """The Pacific date of ``moment`` (now if omitted): the key of the quota ledger."""
    return (moment or datetime.now(UTC)).astimezone(_PACIFIC).date()
