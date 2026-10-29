"""PH-015: optional canonical metadata with legacy MongoDB compatibility."""
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymongo import MongoClient

from core.utils.media_factory import MediaFileFactory
from core.utils.media_metadata import (
    effective_quality,
    extract_explicit_quality,
    extract_telegram_dimensions,
    normalize_quality_label,
)
from core.utils.search_matcher import build_media_search_filter
from repositories.media import FileType, MediaRepository
from scripts.profile_media_search import is_local


@pytest.mark.parametrize(
    ("name", "caption", "expected"),
    [
        ("Show.S01E03.540p.mkv", None, "540p"),
        ("Show.S01E03.1080P.mkv", "Show 720p", "1080p"),
        ("Show.mkv", "Release is 2160p", "2160p"),
        ("Show.mkv", None, None),
        ("Show.1920x1080.mkv", None, None),
        ("x264.Show.mkv", None, None),
        ("Not540p.mkv", None, None),
        ("Show.1080p60.mkv", None, None),
        ("Show.540px.mkv", None, None),
    ],
)
def test_quality_tags_are_observed_explicitly(name, caption, expected):
    assert extract_explicit_quality(name, caption) == expected


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (960, 540, (960, 540)),
        (1920, 1080, (1920, 1080)),
        (None, 540, (None, None)),
        (960, None, (None, None)),
        (0, 540, (None, None)),
        (True, 540, (None, None)),
        ("960", 540, (None, None)),
        (960.5, 540, (None, None)),
        (65536, 1080, (None, None)),
    ],
)
def test_physical_dimensions_require_trusted_integer_pair(width, height, expected):
    assert extract_telegram_dimensions(SimpleNamespace(width=width, height=height)) == expected


def _make_media(name, *, width=None, height=None):
    media = SimpleNamespace(
        file_name=name, file_id="test-file-id", file_unique_id="unique-file-id",
        file_size=100, mime_type="video/mp4", width=width, height=height,
    )
    message = SimpleNamespace(caption=None, media=None, reply_to_message=None)
    return MediaFileFactory.from_pyrogram_media(media, message, FileType.VIDEO)


def test_factory_keeps_legacy_resolution_and_new_canonical_fields():
    entity = _make_media("Doctor.X.S01E03.540p.mkv", width=960, height=540)
    assert (entity.resolution, entity.width, entity.height, entity.quality) == (
        "960x540", 960, 540, "540p"
    )
    assert entity.display_quality == "540p"
    repository = object.__new__(MediaRepository)
    data = repository._entity_to_dict(entity)
    assert (data["resolution"], data["width"], data["height"], data["quality"]) == (
        "960x540", 960, 540, "540p"
    )
    assert repository._dict_to_entity(dict(data)).display_quality == "540p"


def test_document_without_dimensions_has_quality_but_no_guessed_width_or_height():
    entity = _make_media("Show.S01E02.540p.mkv")
    assert entity.resolution == "540p"
    assert entity.quality == "540p"
    assert entity.width is None and entity.height is None
    data = object.__new__(MediaRepository)._entity_to_dict(entity)
    assert "width" not in data and "height" not in data


def test_dimensions_alone_never_claim_a_quality_tag():
    entity = _make_media("Show.S01E02.mkv", width=960, height=540)
    assert entity.resolution == "960x540"
    assert entity.quality is None and entity.display_quality is None
    data = object.__new__(MediaRepository)._entity_to_dict(entity)
    assert "quality" not in data


def test_legacy_docs_read_without_migration_and_leave_original_shape_unchanged():
    entity = _make_media("Show.540p.mkv")
    repository = object.__new__(MediaRepository)
    original = repository._entity_to_dict(entity)
    for key in ("quality", "height", "width"):
        original.pop(key, None)
    before = dict(original)
    restored = repository._dict_to_entity(dict(original))
    assert restored.display_quality == "540p"
    assert restored.quality is None
    assert original == before  # no write/patch of original MongoDB fields

    legacy_dimensions = dict(original, file_name="NoQuality.mkv", resolution="960x540")
    assert repository._dict_to_entity(dict(legacy_dimensions)).display_quality is None


def test_explicit_quality_fallback_does_not_infer_from_pixel_height():
    assert effective_quality(None, "960x540", "Show.mkv") is None
    assert effective_quality(None, "960x540", "Show.540p.mkv") == "540p"
    assert effective_quality(None, "540p", "Show.mkv") == "540p"
    assert normalize_quality_label(" 1080P ") == "1080p"
    assert normalize_quality_label("1920x1080") is None


@pytest.mark.integration
def test_mongo_matches_new_and_legacy_quality_metadata_without_a_migration():
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Requires the disposable CI MongoDB service")
    assert is_local(uri), "Never write test fixtures to remote or production MongoDB"
    name = f"ph015_ci_{uuid4().hex}"
    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        collection = client[name]["media_files"]
        try:
            collection.insert_many([
                {"_id": "new", "file_name": "Show.mkv", "quality": "540p",
                 "resolution": "960x540", "width": 960, "height": 540},
                {"_id": "legacy-label", "file_name": "Show.mkv",
                 "resolution": "540p"},
                {"_id": "legacy-filename", "file_name": "Show.540p.mkv",
                 "resolution": "960x540"},
                {"_id": "dimensions-only", "file_name": "Show.mkv",
                 "resolution": "960x540"},
                {"_id": "different-quality", "file_name": "Show.mkv",
                 "quality": "720p", "resolution": "1280x720"},
                {"_id": "caption-only", "file_name": "Show.mkv",
                 "caption": "Show.540p"},
            ])
            before = {doc["_id"]: doc for doc in collection.find({})}
            indexes_before = sorted(collection.index_information())
            query = build_media_search_filter("540p")
            matched = {doc["_id"] for doc in collection.find(query)}
            assert matched == {
                "new", "legacy-label", "legacy-filename", "caption-only"
            }
            excluded_caption = {doc["_id"] for doc in collection.find(
                build_media_search_filter("540p", use_caption=False)
            )}
            assert excluded_caption == {"new", "legacy-label", "legacy-filename"}
            assert sorted(collection.index_information()) == indexes_before
            assert {doc["_id"]: doc for doc in collection.find({})} == before
        finally:
            client.drop_database(name)
