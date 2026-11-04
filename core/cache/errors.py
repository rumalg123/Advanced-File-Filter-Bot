"""Operational Redis failures must not create apparently valid dead buttons."""


STATE_RETRY_MESSAGE = "Search session temporarily unavailable. Please try again shortly."


class OperationalStateUnavailableError(RuntimeError):
    """An operation requiring durable, non-evicting Redis state could not finish."""
