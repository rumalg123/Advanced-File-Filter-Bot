"""PH-021: explicit UTC calendar-day policy for bot quotas.

Persisted day keys remain YYYY-MM-DD strings. The reservation amount carries
the original day so refunds cannot decrement another UTC day's allowance.
"""
from datetime import UTC, date, datetime


def quota_day_utc(at: datetime | None = None) -> date:
    """One explicit day boundary shared across all bot hosts and replicas."""
    at = datetime.now(UTC) if at is None else at
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Quota timestamps must be timezone-aware")
    return at.astimezone(UTC).date()


class QuotaReservation(int):
    """Integer-compatible reserved amount tagged with the original UTC day.

    Existing consumers may unpack and compare reservations as ints. Subtracting
    a delivered count retains the day for partial refunds in bulk handlers.
    No new MongoDB fields, return tuple members, or callback formats.
    """

    def __new__(cls, amount: int, quota_day: date | str):
        if type(amount) is not int or amount < 0:
            raise ValueError("Reserved quota amount must be a nonnegative integer")
        day = date.fromisoformat(quota_day) if isinstance(quota_day, str) else quota_day
        if not isinstance(day, date) or isinstance(day, datetime):
            raise ValueError("Quota reservation requires a calendar date")
        value = int.__new__(cls, amount)
        value.quota_day = day.isoformat()
        return value

    def __sub__(self, other):
        result = int.__sub__(self, other)
        if result is NotImplemented:
            return NotImplemented
        return QuotaReservation(int(result), self.quota_day) if result >= 0 else result
