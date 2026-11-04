"""Every type accepted by advanced syntax must reach the same repository enum."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.services.file_access import FileAccessService
from core.utils.file_type import get_file_type_from_string
from repositories.media import FileType


@pytest.mark.parametrize('kind', list(FileType))
def test_all_declared_file_types_roundtrip_from_text(kind):
    assert get_file_type_from_string(kind.value.upper()) is kind


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', list(FileType))
async def test_advanced_type_is_forwarded_without_document_fallback(kind):
    media = SimpleNamespace(search_files=AsyncMock(return_value=([], 0, 0)))
    service = FileAccessService(SimpleNamespace(can_retrieve_file=AsyncMock(return_value=(True, 'ok'))),
        media, SimpleNamespace(), SimpleNamespace(check_rate_limit=AsyncMock(return_value=(True, 0))),
        SimpleNamespace(USE_CAPTION_FILTER=True, FEATURE_ADVANCED_SEARCH=True))
    assert (await service.search_files_with_access_check(42, 'movie type:'+kind.value, 42))[3]
    assert media.search_files.await_args.args[1] is kind
