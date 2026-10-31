"""Grouping never changes selectable file identity or the owned query context."""
from collections import Counter

import pytest

from core.utils.button_builder import ButtonBuilder
from handlers.callbacks_handlers.file import FileCallbackHandler
from test_recommendations_and_similarity import make_file


@pytest.mark.parametrize('grouped', [True, False])
@pytest.mark.parametrize('private', [True, False])
@pytest.mark.parametrize('reference', [None, '@deadbeef'])
def test_grouped_and_flat_buttons_preserve_every_file_and_context(grouped, private, reference):
    files = [make_file('first', 'Movie S01E01 720p x264 mkv'),
             make_file('other', 'Other S01E01 1080p mkv'),
             make_file('second', 'Movie S01E01 1080p x265 mp4')]
    rows = ButtonBuilder.search_file_buttons(files, user_id=42, is_private=private,
                                             query_reference=reference, group_variants=grouped)
    callbacks = [button.callback_data for row in rows for button in row]
    selected = [FileCallbackHandler.parse_file_callback(data, 42) for data in callbacks if data.startswith('file#')]
    assert Counter(identifier for identifier, _, _ in selected) == Counter(file.file_unique_id for file in files)
    assert all(owner == 42 and origin == reference for _, owner, origin in selected)
    assert all(len(data.encode('utf-8')) <= 64 for data in callbacks)
    assert callbacks.count('noop') == int(grouped)
