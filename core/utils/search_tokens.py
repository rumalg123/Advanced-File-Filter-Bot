"""Optional indexed candidates; the legacy regex remains authoritative."""
import re

from core.utils.helpers import build_typo_tolerant_pattern

SEARCH_TOKEN_VERSION = 1
SEARCH_TOKEN_FIELD = '_search_terms_v1'
SEARCH_TOKEN_VERSION_FIELD = '_search_terms_version'
SEARCH_TOKEN_INDEX = {
    'name': 'media_search_terms_v1',
    'keys': [(SEARCH_TOKEN_VERSION_FIELD, 1), (SEARCH_TOKEN_FIELD, 1)],
    'options': {},
}
_BOUNDARY = r'(\b|[\.\+\-\s_])'
_ASCII_RUN = re.compile(r'[A-Za-z0-9]+')
# ASCII caseless matches may include these Unicode equivalents. Keep original
# runs as well: boundary semantics can differ for adjacent Unicode characters.
_ASCII_EQUIVALENTS = str.maketrans({'İ':'i', 'ı':'i', 'ſ':'s', 'K':'k'})


def media_search_tokens(file_name, caption=None) -> list[str]:
    tokens = set()
    def add(value):
        if isinstance(value, str):
            tokens.update(part.lower() for part in _ASCII_RUN.findall(value))
            tokens.update(part.lower() for part in _ASCII_RUN.findall(value.translate(_ASCII_EQUIVALENTS)))
        elif isinstance(value, list):
            for part in value:
                add(part)
    add(file_name)
    add(caption)
    return sorted(tokens)


def title_candidate_terms(title: str) -> list[str] | None:
    """Choose one necessary word, including every supported typo alternative.

    Unsupported/changed regex syntax falls back to the unfiltered legacy query.
    One selective necessary word suffices; exact matches are checked afterwards.
    """
    words = [word for word in title.split() if re.fullmatch(r'[A-Za-z0-9]{3,}', word)]
    for word in sorted(set(words), key=len, reverse=True):
        pattern = build_typo_tolerant_pattern(word)
        if not (pattern.startswith(_BOUNDARY) and pattern.endswith(_BOUNDARY)):
            continue
        body = pattern[len(_BOUNDARY):-len(_BOUNDARY)]
        if body.startswith('(') and body.endswith(')'):
            body = body[1:-1]
        alternatives = body.split('|')
        if all(re.fullmatch(r'[A-Za-z0-9]+', item) for item in alternatives):
            return sorted({item.lower() for item in alternatives})
    return None


def indexed_title_candidates(title: str) -> dict | None:
    terms = title_candidate_terms(title)
    if terms is None:
        return None
    # Missing, invalidated and future-version documents retain legacy behavior.
    return {'$or': [
        {SEARCH_TOKEN_VERSION_FIELD: SEARCH_TOKEN_VERSION,
         SEARCH_TOKEN_FIELD: {'$in': terms}},
        {SEARCH_TOKEN_VERSION_FIELD: {'$ne': SEARCH_TOKEN_VERSION}},
    ]}
