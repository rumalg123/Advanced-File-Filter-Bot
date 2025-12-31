# core/utils/helpers.py
"""Common utility functions used across the application"""
import re
from datetime import datetime
from typing import Dict, Any


def format_file_size(size: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for better search"""
    filename = re.sub(r"([_\-.+])", " ", str(filename))
    return filename.strip()


def normalize_query(query: str) -> str:
    """Normalize search query"""
    query = re.sub(r"[_\-.+]", " ", query)
    query = re.sub(r"\s+", " ", query).strip().lower()
    return query


def parse_datetime_fields(data: Dict[str, Any], *fields: str) -> None:
    """
    Parse datetime fields from ISO format strings in-place.

    This is a reusable utility to eliminate duplicate datetime parsing code
    across repositories.

    Args:
        data: Dictionary containing the data
        *fields: Field names to parse as datetime

    Example:
        parse_datetime_fields(data, 'created_at', 'updated_at', 'expires_at')
    """
    for field in fields:
        if data.get(field) and isinstance(data[field], str):
            data[field] = datetime.fromisoformat(data[field])