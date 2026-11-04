"""Public-safe search failure contract. Never expose MongoDB connection details."""


USER_ACCESS_RETRY_MESSAGE = "User access is temporarily unavailable. Please try again."

SEARCH_RETRY_MESSAGE = "Search temporarily unavailable. Please try again shortly."
FILE_LOOKUP_RETRY_MESSAGE = "Files temporarily unavailable. Please try again shortly."


class SearchBackendUnavailableError(RuntimeError):
    """Search did not complete because a database query failed.

    Distinct from a valid, successful search returning zero results.
    The original exception is preserved through exception chaining for logs.
    """
