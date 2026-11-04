"""Useful operator diagnostics without rendering arbitrary exception payloads."""


def operator_error_summary(error: Exception) -> str:
    """Driver messages/details may contain credentials, URIs or media records."""
    summary = type(error).__name__
    code = getattr(error, 'code', None)
    if type(code) is int:
        summary += f', MongoDB code {code}'
    return summary
