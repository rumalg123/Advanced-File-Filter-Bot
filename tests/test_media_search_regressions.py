"""Mongo query regression coverage without a running database or Redis.

The evaluator below implements only the Mongo predicate operators emitted by
the media search compiler. Integration tests with MongoDB remain recommended.
"""
import re

import pytest

from core.utils.helpers import parse_search_query
from repositories.media import FileType, MediaRepository


TARGET = {
    "file_name": "Doctor X Mafia in White S01E03 NF x264 540p mkv",
    "caption": None,
    "season": "01",
    "episode": "03",
    # Video uploads currently prefer dimensions instead of filename quality.
    "resolution": "960x540",
    "file_type": "video",
    "file_size": 346879000,
}

OTHER_EPISODE = {
    **TARGET,
    "file_name": "Doctor X Mafia in White S01E02 NF x265 1080p mkv",
    "episode": "02",
    "resolution": "1920x1080",
}


def matches(predicate, document):
    """Evaluate Mongo operators used by _build_search_filter."""
    for field, expectation in predicate.items():
        if field == "$and":
            if not all(matches(clause, document) for clause in expectation):
                return False
            continue
        if field == "$or":
            if not any(matches(clause, document) for clause in expectation):
                return False
            continue

        actual = document.get(field)
        if isinstance(expectation, dict):
            if "$regex" in expectation:
                if not isinstance(actual, str):
                    return False
                flags = re.IGNORECASE if "i" in expectation.get("$options", "") else 0
                if re.search(expectation["$regex"], actual, flags) is None:
                    return False
            if "$in" in expectation and actual not in expectation["$in"]:
                return False
            if "$gte" in expectation and (actual is None or actual < expectation["$gte"]):
                return False
            if "$lte" in expectation and (actual is None or actual > expectation["$lte"]):
                return False
        elif actual != expectation:
            return False
    return True


def mongo_filter(text, *, use_caption=True, advanced_filters=None, file_type=None):
    repository = object.__new__(MediaRepository)
    # The actual code normalizes text before compiling its Mongo filter.
    from core.utils.validators import normalize_query
    return repository._build_search_filter(
        normalize_query(text), file_type, use_caption, advanced_filters
    )


@pytest.mark.parametrize(
    "text",
    [
        "doctor x mafia",
        "doctor x mafia in white",
        "mafia doctor x white",
        "Doctor X Mafia in White S01E03 NF x264 540p mkv",
        "Doctor.X.Mafia.in.White.S01E03.NF.x264.540p.mkv",
        "doctor x mafia s01e03",
        "doctor x mafia e03 540p",
        "s01e03 540p",
        "S1 E3",
        "season 1 episode 3",
        "540p",
    ],
)
def test_valid_searches_match_video_with_dimension_metadata(text):
    assert matches(mongo_filter(text), TARGET), text


@pytest.mark.parametrize(
    "text",
    [
        "Doctor X Mafia in White S01E03 NF x264 540p mkv",
        "s01e03",
        "e03",
        "540p",
        "doctor x mafia s01e03 540p",
    ],
)
def test_legacy_media_without_metadata_still_searchable(text):
    legacy = {key: value for key, value in TARGET.items()
              if key not in {"season", "episode", "resolution"}}
    assert matches(mongo_filter(text), legacy), text


@pytest.mark.parametrize("text", ["s01e04", "720p", "doctor x mafia e04 540p"])
def test_wrong_episode_and_quality_do_not_match(text):
    assert not matches(mongo_filter(text), TARGET), text


def test_season_episode_pair_does_not_match_two_different_pairs():
    misleading = {
        "file_name": "Doctor X Mafia S01E02 S02E03 540p mkv",
        "file_type": "video",
    }
    assert not matches(mongo_filter("Doctor X Mafia S01E03"), misleading)


def test_advanced_filters_with_legacy_fallback_and_size():
    filters = {
        "season": "01",
        "episode": "03",
        "resolution": "540p",
        "year": 2026,
        "min_size": 200000000,
        "max_size": 400000000,
        "file_type": "video",
    }
    legacy = {
        **TARGET,
        "file_name": "Doctor X Mafia in White S01E03 2026 NF x264 540p mkv",
        "season": None,
        "episode": None,
        "resolution": None,
    }
    predicate = mongo_filter("doctor x mafia", advanced_filters=filters)
    assert matches(predicate, legacy)
    assert not matches(predicate, {**legacy, "file_size": 500000000})
    assert not matches(predicate, {**legacy, "file_type": "document"})
    assert not matches(predicate, {**legacy, "file_name": legacy["file_name"].replace("540p", "720p")})


def test_advanced_season_episode_match_same_pair():
    predicate = mongo_filter("doctor x mafia", advanced_filters={
        "season": "01", "episode": "03"
    })
    assert matches(predicate, TARGET)
    assert not matches(predicate, {
        "file_name": "Doctor X Mafia S01E02 S02E03",
        "file_type": "video",
    })


def test_caption_search_respects_setting():
    caption_only = {
        "file_name": "Unrelated Document mkv",
        "caption": "Doctor X Mafia in White S01E03 540p",
        "file_type": "document",
    }
    assert matches(mongo_filter("doctor x mafia s01e03 540p"), caption_only)
    assert not matches(
        mongo_filter("doctor x mafia s01e03 540p", use_caption=False),
        caption_only,
    )


def test_title_tokens_cannot_be_split_across_name_and_caption():
    split = {
        "file_name": "Doctor X 540p",
        "caption": "Mafia S01E03",
    }
    assert not matches(mongo_filter("doctor x mafia"), split)


def test_type_filter_is_applied_with_parsed_metadata():
    predicate = mongo_filter(
        "doctor x mafia s01e03 540p",
        file_type=FileType.VIDEO,
    )
    assert matches(predicate, TARGET)
    assert not matches(predicate, {**TARGET, "file_type": "document"})


@pytest.mark.parametrize(
    ("text", "title", "season", "episode", "quality"),
    [
        ("s01e03", "", "01", "03", None),
        ("S1 E3", "", "01", "03", None),
        ("S01", "", "01", None, None),
        ("E03", "", None, "03", None),
        ("ep45 s01", "", "01", "45", None),
        ("season 1 episode 3", "", "01", "03", None),
        ("Doctor.X.S01E03.540p.mkv", "Doctor X mkv", "01", "03", "540p"),
        ("Scary Movie 2025", "Scary Movie 2025", None, None, None),
        ("My TV Show", "My TV Show", None, None, None),
        ("doctor x mafia 540p", "doctor x mafia", None, None, "540p"),
    ],
)
def test_query_parser_preserves_titles_and_understands_episode_notation(
    text, title, season, episode, quality
):
    assert parse_search_query(text) == (title, season, episode, quality)


def test_only_existing_database_fields_are_used():
    predicate = mongo_filter("doctor x mafia s01e03 540p", advanced_filters={
        "language": "english", "max_size": 1000000000
    })
    allowed = {
        "$and", "$or", "file_name", "caption", "season", "episode",
        "resolution", "file_type", "file_size",
    }

    def collect_keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if not key.startswith("$"):
                    assert key in allowed
                collect_keys(item)
        elif isinstance(value, list):
            for item in value:
                collect_keys(item)

    collect_keys(predicate)
