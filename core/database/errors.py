"""Public-safe search failure contract. Never expose MongoDB connection details."""


SEARCH_RETRY_MESSAGE = "Search temporarily unavailable. Please try again shortly."


class SearchBackendUnavailableError(RuntimeError):
    """Search did not complete because a database query failed.

    Distinct from a valid, successful search returning zero results.
    The original exception is preserved through exception chaining for logs.
    """
