"""Clock helpers for operator-facing Oracle telemetry."""
from datetime import datetime
from zoneinfo import ZoneInfo

OPERATOR_TIMEZONE = ZoneInfo("Africa/Johannesburg")


def operator_now() -> datetime:
    """Return a timezone-aware timestamp in the configured operator timezone."""
    return datetime.now(OPERATOR_TIMEZONE)
