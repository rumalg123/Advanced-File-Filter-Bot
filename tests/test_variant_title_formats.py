"""Grouping handles stored normalized extensions without discarding title words."""
from collections import Counter

import pytest

from core.utils.feature_search import canonicalize_media_title, group_media_variants
from test_recommendations_and_similarity import make_file


@pytest.mark.parametrize('left,right', [
    ('Show.S01E01.720p.x264.mkv', 'Show S01E01 1080p x265 mp4'),
    ('Show S01E01 720p x264 mkv', 'Show S01E01 1080p x265 mp4'),
    ('Movie 2025 720p WEB DL mkv', 'Movie 2025 1080p WEB DL webm'),
    ('Movie 2025 720p mp4', 'Movie 2025 1080p avi'),
    ('Song 2025 mp3', 'Song 2025 flac'),
])
def test_known_raw_and_normalized_containers_do_not_split_variants(left, right):
    assert canonicalize_media_title(left) == canonicalize_media_title(right)


@pytest.mark.parametrize('left,right', [
    ('Doctor.No', 'Doctor.Yes'), ('Film.2024', 'Film.2025'),
    ('Show S01E01 720p mkv', 'Show S01E02 1080p mkv'),
    ('Movie 2024 720p mkv', 'Movie 2025 1080p mp4'),
])
def test_real_title_words_years_and_episodes_remain_distinct(left, right):
    assert canonicalize_media_title(left) != canonicalize_media_title(right)


def test_mixed_container_grouping_preserves_every_original_file():
    files = [make_file('a', 'Movie 2025 720p x264 mkv'),
             make_file('b', 'Other 2025 720p mkv'),
             make_file('c', 'Movie 2025 1080p x265 mp4')]
    groups = group_media_variants(files)
    assert len(groups) == 2 and len(groups[0][1]) == 2
    assert Counter(id(file) for _, group in groups for file in group) == Counter(map(id, files))
