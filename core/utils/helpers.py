# core/utils/helpers.py
"""Common utility functions used across the application"""
import re


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