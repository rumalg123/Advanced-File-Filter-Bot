"""Schema-compatible MongoDB search predicates for indexed Telegram media.

Searches work against existing media_files documents. No migration, stored
normalized-title field, index, or write is required. A media file may have
missing metadata, or a video resolution stored as dimensions (e.g. 960x540)
instead of the 540p quality tag present in its filename.

For user-supplied text, require all title tokens in the same text field. Parsed
season/episode/quality constraints can be satisfied by metadata OR by the
original filename/caption, which also supports older indexed documents.
"""
import re
from typing import Any, Dict, Optional

from core.utils.helpers import build_typo_tolerant_pattern, parse_search_query


def _text_pattern(text: str) -> str:
    """Match complete query tokens, in any order, in one filename or caption.

    Each token is escaped by build_typo_tolerant_pattern. Unlike a phrase-only
    regex, this survives tokens removed by the metadata parser and filename
    variants with different word order. It also preserves existing common typo
    aliases (e.g. this/thus).
    """
    # Duplicate lookaheads do not enforce token multiplicity; the old
    # matcher only required existence. Removing duplicates preserves those
    # semantics while reducing worst-case regex evaluation work.
    tokens = list(dict.fromkeys(text.split()))
    if len(tokens) == 1:
        return build_typo_tolerant_pattern(tokens[0])
    return (
        r"\A"
        + "".join(
            rf"(?=[\s\S]*{build_typo_tolerant_pattern(token)})"
            for token in tokens
        )
        + r"[\s\S]*"
    )


def _word_pattern(word: str) -> str:
    """A literal word bounded by punctuation, whitespace or string edges.

    Treat underscores as separators too. Escape even validated filter values
    so user input can never become an arbitrary regular expression.
    """
    return rf"(?<![^\W_]){re.escape(word)}(?![^\W_])"


def _sources_match(
    stored_field: Optional[str],
    stored_match: Optional[Any],
    filename_regex: str,
    use_caption: bool,
) -> Dict[str, Any]:
    """Match stored metadata, or source text for missing/legacy metadata."""
    choices = []
    if stored_field is not None:
        choices.append({stored_field: stored_match})

    regex = {"$regex": filename_regex, "$options": "i"}
    choices.append({"file_name": regex})
    if use_caption:
        choices.append({"caption": regex})
    return {"$or": choices}


def _number_metadata_match(
    field: str, value: str, use_caption: bool
) -> Dict[str, Any]:
    number = int(value)
    # Historic data may contain 1, "1" or "01".
    candidates = [str(number), str(number).zfill(2), number]
    if field == "season":
        # Handles S01E03, S01 E03, S1, and "season 1".
        filename_pattern = (
            rf"(?<![^\W_])(?:season[\W_]*|s)0*{number}"
            rf"(?=[\W_]|e\d|$)"
        )
    else:
        # Handles S01E03, E03, EP03 and "episode 3".
        filename_pattern = (
            rf"(?<![^\W_])"
            rf"(?:s\d{{1,2}}[\W_]*e|episode[\W_]*|ep[\W_]*|e)"
            rf"0*{number}(?!\d)"
        )
    return _sources_match(
        field, {"$in": candidates}, filename_pattern, use_caption
    )


def _season_episode_match(
    season: str, episode: str, use_caption: bool
) -> Dict[str, Any]:
    """Keep S01E03 together, avoiding matches from unrelated episode tags."""
    season_number = int(season)
    episode_number = int(episode)
    stored = {
        "$and": [
            {
                "season": {
                    "$in": [str(season_number), str(season_number).zfill(2), season_number]
                }
            },
            {
                "episode": {
                    "$in": [str(episode_number), str(episode_number).zfill(2), episode_number]
                }
            },
        ]
    }
    pattern = (
        rf"(?<![^\W_])(?:season[\W_]*|s)0*{season_number}"
        rf"[\W_]*(?:episode[\W_]*|ep[\W_]*|e)0*{episode_number}(?!\d)"
    )
    return {
        "$or": [
            stored,
            {"file_name": {"$regex": pattern, "$options": "i"}},
            *([{"caption": {"$regex": pattern, "$options": "i"}}] if use_caption else []),
        ]
    }


def _resolution_match(resolution: str, use_caption: bool) -> Dict[str, Any]:
    value = str(resolution).lower()
    matched = _sources_match(
        "resolution",
        {"$regex": rf"^{re.escape(value)}$", "$options": "i"},
        _word_pattern(value),
        use_caption,
    )
    # PH-015: newly indexed media may carry an explicit quality field,
    # while older documents retain label/dimension variants in resolution.
    # Never infer a 540p label merely from 960x540 pixel dimensions.
    if re.fullmatch(r"\d{3,4}p", value):
        matched["$or"].insert(
            0, {"quality": {"$regex": rf"^{re.escape(value)}$", "$options": "i"}}
        )
    return matched


def build_media_search_filter(
    query: str,
    file_type: Optional[Any] = None,
    use_caption: bool = True,
    advanced_filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile user search and explicit advanced filters into Mongo predicates.

    Existing fields only: file_name, caption, season, episode, resolution,
    file_type, file_size. A missing season/episode/resolution never forces
    reindexing as long as the token appears in the filename or caption.
    """
    title, season, episode, resolution = parse_search_query(query)
    clauses = []

    # Do not reinsert the whole query when parsing consumes every token:
    # "S01E03 540p" is a legitimate metadata-only search.
    if title:
        regex = {"$regex": _text_pattern(title), "$options": "i"}
        alternatives = [{"file_name": regex}]
        if use_caption:
            alternatives.append({"caption": regex})
        clauses.append({"$or": alternatives})

    if season is not None and episode is not None:
        clauses.append(_season_episode_match(season, episode, use_caption))
    else:
        if season is not None:
            clauses.append(_number_metadata_match("season", season, use_caption))
        if episode is not None:
            clauses.append(_number_metadata_match("episode", episode, use_caption))
    if resolution is not None:
        clauses.append(_resolution_match(resolution, use_caption))

    advanced = advanced_filters or {}
    if advanced.get("season") is not None and advanced.get("episode") is not None:
        # Both explicit filters must refer to the same season/episode pair.
        if str(advanced["season"]) != season or str(advanced["episode"]) != episode:
            clauses.append(
                _season_episode_match(
                    str(advanced["season"]), str(advanced["episode"]), use_caption
                )
            )
    else:
        if advanced.get("season") is not None and advanced["season"] != season:
            clauses.append(
                _number_metadata_match("season", str(advanced["season"]), use_caption)
            )
        if advanced.get("episode") is not None and advanced["episode"] != episode:
            clauses.append(
                _number_metadata_match("episode", str(advanced["episode"]), use_caption)
            )
    if advanced.get("resolution") and advanced["resolution"] != resolution:
        clauses.append(_resolution_match(str(advanced["resolution"]), use_caption))

    if advanced.get("year") is not None:
        clauses.append(
            _sources_match(
                None, None, _word_pattern(str(advanced["year"])), use_caption
            )
        )
    if advanced.get("language"):
        clauses.append(
            _sources_match(
                None, None, _word_pattern(str(advanced["language"])), use_caption
            )
        )

    size_filter = {}
    if advanced.get("min_size") is not None:
        size_filter["$gte"] = int(advanced["min_size"])
    if advanced.get("max_size") is not None:
        size_filter["$lte"] = int(advanced["max_size"])
    if size_filter:
        clauses.append({"file_size": size_filter})

    selected_file_type = file_type
    if selected_file_type is None and advanced.get("file_type"):
        selected_file_type = advanced["file_type"]
    if selected_file_type is not None:
        type_value = getattr(selected_file_type, "value", selected_file_type)
        clauses.append({"file_type": type_value})

    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}
