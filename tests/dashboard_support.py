"""Dashboard fixtures without external connections."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.services.features import FeatureService


def dashboard_fixture(rows=(), advanced=True, caption=True):
    repository=SimpleNamespace(
        top_zero_results=AsyncMock(return_value=list(rows)),
        resolve_zero_result=AsyncMock(return_value=True),
        count_documents=AsyncMock(return_value=0),
    )
    media=SimpleNamespace(
        has_matching_file=AsyncMock(return_value=False),
        get_file_stats=AsyncMock(return_value={'total_files':0,'total_size':0,'by_type':{}}),
    )
    history=SimpleNamespace(get_global_top_searches=AsyncMock(return_value=[]))
    config=SimpleNamespace(FEATURE_CONTENT_DASHBOARD=True,FEATURE_ADVANCED_SEARCH=advanced,
                           USE_CAPTION_FILTER=caption)
    return FeatureService(repository,media,history,config),repository,media,history
