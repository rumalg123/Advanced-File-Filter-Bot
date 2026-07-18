"""Parsing and grouping helpers for opt-in search features."""

import re
from collections import OrderedDict

from repositories.media import MediaFile

ADVANCED_FILTER_PATTERN = re.compile(
    r"(?<!\S)(type|year|lang|language|quality|season|episode|minsize|maxsize):"
    r"(\"[^\"]+\"|'[^']+'|\S+)",
    re.IGNORECASE
)

VALID_FILE_TYPES = {
    "video", "audio", "document", "photo", "animation", "application"
}


def _parse_size(value: str) -> int:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(b|kb|mb|gb|tb)?", value.lower())
    if not match:
        raise ValueError(f"Invalid size '{value}'. Use values such as 700MB or 2GB.")
    amount = float(match.group(1))
    unit = match.group(2) or "b"
    multipliers = {
        "b": 1,
        "kb": 1024,
        "mb": 1024 ** 2,
        "gb": 1024 ** 3,
        "tb": 1024 ** 4,
    }
    return int(amount * multipliers[unit])


def parse_advanced_search_query(query: str) -> tuple[str, dict[str, object]]:
    """Parse optional ``key:value`` filters while preserving the base query."""
    filters: dict[str, object] = {}

    for match in ADVANCED_FILTER_PATTERN.finditer(query or ""):
        key = match.group(1).lower()
        value = match.group(2).strip("\"'").strip()
        if not value:
            raise ValueError(f"Filter '{key}' requires a value.")

        if key == "type":
            normalized_type = value.lower()
            if normalized_type not in VALID_FILE_TYPES:
                raise ValueError(
                    "Invalid type. Use video, audio, document, photo, animation, or application."
                )
            filters['file_type'] = normalized_type
        elif key == "year":
            year = int(value)
            if year < 1900 or year > 2100:
                raise ValueError("Year must be between 1900 and 2100.")
            filters['year'] = year
        elif key in {"lang", "language"}:
            if not re.fullmatch(r"[A-Za-z][A-Za-z -]{1,23}", value):
                raise ValueError("Language must contain letters only.")
            filters['language'] = value.lower()
        elif key == "quality":
            normalized_quality = value.lower()
            if not re.fullmatch(r"(?:\d{3,4}p|\d{3,4}x\d{3,4})", normalized_quality):
                raise ValueError("Quality must look like 720p, 1080p, or 1920x1080.")
            filters['resolution'] = normalized_quality
        elif key in {"season", "episode"}:
            number = int(value)
            if number < 0 or number > 999:
                raise ValueError(f"{key.title()} must be between 0 and 999.")
            filters[key] = str(number).zfill(2)
        elif key == "minsize":
            filters['min_size'] = _parse_size(value)
        elif key == "maxsize":
            filters['max_size'] = _parse_size(value)

    if (
        filters.get('min_size') is not None
        and filters.get('max_size') is not None
        and int(filters['min_size']) > int(filters['max_size'])
    ):
        raise ValueError("minsize cannot be greater than maxsize.")

    cleaned_query = ADVANCED_FILTER_PATTERN.sub(" ", query or "")
    cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()
    return cleaned_query, filters


_VARIANT_NOISE = re.compile(
    r"\b(?:360p|480p|540p|720p|1080p|1440p|2160p|4k|8k|"
    r"xvid|x264|x265|h264|h265|hevc|av1|aac|ddp?\d?(?:\.\d)?|"
    r"web[- ]?dl|webrip|bluray|brrip|hdrip|dvdrip|remux|proper|repack|hdr|sdr)\b",
    re.IGNORECASE
)


def canonicalize_media_title(file_name: str) -> str:
    """Return a conservative title key that removes encode/quality noise."""
    value = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", file_name or "")
    value = re.sub(r"[._+\-]+", " ", value)
    value = _VARIANT_NOISE.sub(" ", value)
    value = re.sub(r"\b\d{3,4}x\d{3,4}\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value or (file_name or "unknown").lower()


def group_media_variants(files: list[MediaFile]) -> list[tuple[str, list[MediaFile]]]:
    """Group likely variants while preserving every file and first-seen order."""
    groups = OrderedDict()
    for file in files:
        key = canonicalize_media_title(file.file_name)
        groups.setdefault(key, []).append(file)
    return list(groups.items())
