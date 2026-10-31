"""PH-015: explicit media dimensions and quality tags without guessing.

`quality` is an observed source label such as "540p", not a numerical
derivation from height. Pixel dimensions are trusted only when both are
provided by Telegram media attributes. Existing `resolution` documents
remain unchanged; this module also supports read-only legacy presentation.
"""
import re
from typing import Optional, Tuple

_QUALITY_TAG = re.compile(r"(?<![a-zA-Z0-9])(?P<label>\d{3,4}p)(?![a-zA-Z0-9])", re.I)
_EXACT_QUALITY_TAG = re.compile(r"\d{3,4}p", re.I)


def normalize_quality_label(value: object) -> Optional[str]:
    """Return an explicit supported quality label, never infer from dimensions."""
    if not isinstance(value, str):
        return None
    label = value.strip().lower()
    return label if _EXACT_QUALITY_TAG.fullmatch(label) else None


def extract_explicit_quality(
    filename: Optional[str], caption: Optional[str] = None
) -> Optional[str]:
    """Prefer tags in the filename; caption tags are a fallback only."""
    for source in (filename, caption):
        if not isinstance(source, str):
            continue
        match = _QUALITY_TAG.search(source)
        if match:
            return match.group("label").lower()
    return None


def extract_telegram_dimensions(media: object) -> Tuple[Optional[int], Optional[int]]:
    """Use native pixel values only; never convert a 540p label to dimensions."""
    width = getattr(media, "width", None)
    height = getattr(media, "height", None)
    # Reject bool, floats, zero and impossible or corrupt telemetry values.
    if (type(width) is int and type(height) is int
            and 0 < width <= 65535 and 0 < height <= 65535):
        return width, height
    return None, None


def effective_quality(
    quality: Optional[str],
    resolution: Optional[str],
    filename: Optional[str] = None,
    caption: Optional[str] = None,
) -> Optional[str]:
    """Read-only legacy adapter; returns an explicit tag without altering a record.

    Legacy `resolution="540p"` is a quality label. Legacy
    `resolution="960x540"` is dimensions, not proof of a "540p" tag.
    """
    return (
        normalize_quality_label(quality)
        or normalize_quality_label(resolution)
        or extract_explicit_quality(filename, caption)
    )
