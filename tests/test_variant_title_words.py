"""Technical noise removal must not erase meaningful words in a title."""
import pytest

from core.utils.feature_search import canonicalize_media_title


@pytest.mark.parametrize('left,right', [
    ('The Proper Job 2025 720p.mkv', 'The Job 2025 1080p.mp4'),
    ('HDR Story 2025 720p.mkv', 'Story 2025 1080p.mp4'),
    ('SDR Story 720p.mkv', 'Story 1080p.mp4'),
    ('A Proper Job', 'A Job'),
    ('The Repack Story', 'The Story'),
])
def test_technical_looking_title_words_do_not_merge_distinct_content(left, right):
    assert canonicalize_media_title(left) != canonicalize_media_title(right)


@pytest.mark.parametrize('left,right', [
    ('Movie 2025 720p PROPER REMUX HDR.mkv', 'Movie 2025 1080p SDR REPACK.mp4'),
    ('Title E25 Proper 720p.mkv', 'Title E25 1080p.mp4'),
])
def test_release_tags_after_metadata_still_group(left, right):
    assert canonicalize_media_title(left) == canonicalize_media_title(right)
