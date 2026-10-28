"""Guardrails and progress types for operator-approved keyword deletions."""
from dataclasses import dataclass

MAX_BULK_DELETE_FILES = 1000
BULK_DELETE_BATCH_SIZE = 100
PREVIEW_SAMPLE_SIZE = 5


class BulkDeleteRejected(ValueError):
    """Unsafe request: empty match, too many matches, or changed preview."""


class BulkDeleteInterrupted(RuntimeError):
    """The operation stopped after zero or more acknowledged deletions."""

    def __init__(self, message: str, deleted_count: int = 0):
        super().__init__(message)
        self.deleted_count = deleted_count


@dataclass(frozen=True)
class BulkDeletePreview:
    keyword: str
    count: int
    sample: tuple[str, ...]
    max_allowed: int = MAX_BULK_DELETE_FILES
